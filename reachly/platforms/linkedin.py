"""LinkedIn posting.

API mode uses the modern Posts API (/rest/posts) with the w_member_social scope.
Images are registered via /rest/images?action=initializeUpload, the binary is PUT
to the returned uploadUrl, and the resulting image URN is attached to the post.

Browser mode logs in headlessly and publishes via the web composer.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster
from .browser import persistent_page, save_debug_artifact

logger = logging.getLogger("reachly.linkedin")

REST = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202505"  # YYYYMM; bump periodically


class LinkedInApiPoster(Poster):
    platform = Platform.linkedin

    def __init__(self, creds: PlatformCredentials):
        super().__init__(creds)
        self.token = creds.api_token
        self.person_urn = (creds.extra or {}).get("person_urn") or None

    def _headers(self, extra: dict | None = None) -> dict:
        h = {
            "Authorization": f"Bearer {self.token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": LINKEDIN_VERSION,
            "Content-Type": "application/json",
        }
        if extra:
            h.update(extra)
        return h

    def _resolve_author(self) -> str:
        if self.person_urn:
            return self.person_urn
        # /userinfo (OpenID) returns "sub" = the member id.
        r = requests.get(
            "https://api.linkedin.com/v2/userinfo",
            headers={"Authorization": f"Bearer {self.token}"},
            timeout=20,
        )
        r.raise_for_status()
        sub = r.json()["sub"]
        self.person_urn = f"urn:li:person:{sub}"
        return self.person_urn

    def post(self, post: GeneratedPost) -> PostResult:
        if not self.token:
            return self._fail("Missing LINKEDIN_ACCESS_TOKEN for API mode.")
        try:
            author = self._resolve_author()
            content = None
            if post.media and post.media.kind == "image":
                image_urn = self._upload_image(author, post.media.local_path)
                content = {"media": {"id": image_urn}}

            body = {
                "author": author,
                "commentary": post.for_platform(Platform.linkedin),
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            }
            if content:
                body["content"] = content

            r = requests.post(f"{REST}/posts", json=body, headers=self._headers(), timeout=30)
            if r.status_code >= 300:
                return self._fail(f"LinkedIn post failed {r.status_code}: {r.text[:300]}")
            post_id = r.headers.get("x-restli-id") or r.headers.get("x-linkedin-id")
            permalink = (
                f"https://www.linkedin.com/feed/update/{post_id}/" if post_id else None
            )
            return self._ok(permalink=permalink)
        except Exception as e:  # noqa: BLE001
            return self._fail(f"LinkedIn API error: {e}")

    def _upload_image(self, author: str, path: str) -> str:
        init = requests.post(
            f"{REST}/images?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": author}},
            headers=self._headers(),
            timeout=30,
        )
        init.raise_for_status()
        value = init.json()["value"]
        upload_url = value["uploadUrl"]
        image_urn = value["image"]
        with open(path, "rb") as f:
            up = requests.put(
                upload_url,
                data=f.read(),
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=120,
            )
            up.raise_for_status()
        return image_urn


class LinkedInBrowserPoster(Poster):
    platform = Platform.linkedin

    def __init__(self, creds: PlatformCredentials, *, data_dir: Path):
        super().__init__(creds)
        self.data_dir = Path(data_dir)

    def post(self, post: GeneratedPost) -> PostResult:
        text = post.for_platform(Platform.linkedin)
        post_as = (self.creds.extra or {}).get("post_as", "").strip()
        try:
            with persistent_page("linkedin", self.data_dir) as page:
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                if "/login" in page.url or "/checkpoint" in page.url or "authwall" in page.url:
                    if not self._login(page):
                        return self._fail("LinkedIn login failed (check credentials / 2FA).")
                    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")

                if not self._open_composer(page):
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "composer_not_found")
                    return self._fail(f"LinkedIn composer button not found. Debug: {shot}")
                page.wait_for_timeout(1500)

                # Optionally switch the author to a Company Page before typing.
                if post_as:
                    if not self._select_post_as(page, post_as):
                        return self._fail(
                            f"Could not select Company Page '{post_as}' in the composer "
                            f"(are you an admin? is the name exact?). Nothing was posted."
                        )

                editor = self._find_editor(page)
                if editor is None:
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "editor_not_found")
                    return self._fail(f"LinkedIn composer editor not found. Debug: {shot}")
                editor.click()
                page.keyboard.type(text, delay=5)

                if post.media and post.media.kind == "image":
                    try:
                        page.get_by_role("button", name="Add a photo").click()
                        page.locator("input[type='file']").first.set_input_files(
                            post.media.local_path
                        )
                        page.wait_for_timeout(3000)
                        page.get_by_role("button", name="Next").click()
                        page.wait_for_timeout(1500)
                    except Exception:  # noqa: BLE001
                        logger.warning("LinkedIn image attach failed; posting text only.")

                if not self._click_post(page):
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "post_button_not_found")
                    return self._fail(f"LinkedIn Post button not found. Debug: {shot}")
                page.wait_for_timeout(4000)
                return self._ok()
        except Exception as e:  # noqa: BLE001
            return self._fail(f"LinkedIn browser error: {e}")

    def _open_composer(self, page) -> bool:
        for url in (
            "https://www.linkedin.com/feed/?shareActive=true",
            "https://www.linkedin.com/feed/",
        ):
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                if self._find_editor(page) is not None:
                    return True
            except Exception:  # noqa: BLE001
                continue

        candidates = [
            lambda: page.get_by_role("button", name=re.compile(r"start a post", re.I)).first,
            lambda: page.get_by_text(re.compile(r"start a post", re.I)).first,
            lambda: page.locator("button:has-text('Start a post')").first,
            lambda: page.locator("div[role='button']:has-text('Start a post')").first,
            lambda: page.locator("button.share-box-feed-entry__trigger").first,
            lambda: page.locator(".share-box-feed-entry__top-bar button").first,
            lambda: page.locator("[data-control-name='share.sharebox_focus']").first,
        ]
        for build in candidates:
            try:
                loc = build()
                if loc.count() and loc.is_visible():
                    try:
                        loc.click(timeout=8000, force=True)
                    except Exception:  # noqa: BLE001
                        loc.evaluate("el => el.click()")
                    page.wait_for_timeout(2500)
                    if self._find_editor(page) is not None:
                        return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _find_editor(self, page):
        selectors = [
            "div.ql-editor[contenteditable='true']",
            "div[role='textbox'][contenteditable='true']",
            "div[contenteditable='true'][aria-label*='Create a post' i]",
            "div[contenteditable='true']",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                loc.wait_for(state="visible", timeout=5000)
                return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    def _click_post(self, page) -> bool:
        candidates = [
            lambda: page.get_by_role("button", name=re.compile(r"^post$", re.I)).last,
            lambda: page.locator("button:has-text('Post')").last,
            lambda: page.locator("button.share-actions__primary-action").last,
        ]
        for build in candidates:
            try:
                loc = build()
                if loc.count() and loc.is_visible():
                    loc.click(timeout=10000)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _select_post_as(self, page, name: str) -> bool:
        """In the open share composer, switch the author to a Company Page by name.

        Best-effort across LinkedIn UI variants: open the actor/identity switcher,
        then click the entry matching the page name.
        """
        toggle = None
        candidates = [
            "button.share-actor-toggle-button",
            "button[aria-label*='Post as' i]",
            "button[aria-label*='posting as' i]",
            ".share-box-feed-entry__top-bar button",
            ".share-creation-state__top-bar button",
        ]
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    toggle = loc
                    break
            except Exception:  # noqa: BLE001
                continue
        if toggle is None:
            try:
                toggle = page.get_by_role(
                    "button", name=re.compile(r"post(ing)? as", re.I)
                ).first
                toggle.wait_for(timeout=3000)
            except Exception:  # noqa: BLE001
                logger.warning("LinkedIn: could not find the 'Post as' switcher.")
                return False

        try:
            toggle.click()
            page.wait_for_timeout(1200)
            option = page.get_by_text(name, exact=False).first
            option.wait_for(timeout=5000)
            option.click()
            page.wait_for_timeout(800)
            # Some variants require confirming the selection.
            for label in ("Done", "Save", "Select"):
                btn = page.get_by_role("button", name=label).first
                try:
                    if btn.count() and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(600)
                        break
                except Exception:  # noqa: BLE001
                    continue
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("LinkedIn: selecting page '%s' failed: %s", name, e)
            return False

    def _login(self, page, *, wait_for_approval: int = 0) -> bool:
        """Log in. If LinkedIn issues a device-approval checkpoint and
        wait_for_approval > 0, poll that many seconds for the user to tap
        "Yes" in their LinkedIn app (used by the one-time priming command)."""
        if not (self.creds.username and self.creds.password):
            return False
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        email = self._first_visible(
            page, ["input[type='email']", "input[autocomplete^='username']",
                   "#username", "#session_key"]
        )
        pw = self._first_visible(
            page, ["input[type='password']", "input[autocomplete='current-password']",
                   "#password", "#session_password"]
        )
        if not email or not pw:
            logger.warning("LinkedIn: login fields not found.")
            return False

        email.click()
        email.fill(self.creds.username)
        pw.click()
        pw.fill(self.creds.password)
        pw.press("Enter")
        page.wait_for_timeout(6000)

        if self._is_logged_in(page):
            return True

        url = page.url
        if "/checkpoint" in url or "/challenge" in url:
            if wait_for_approval <= 0:
                logger.warning("LinkedIn: verification checkpoint (approve in app). url=%s", url)
                return False
            logger.info("LinkedIn: waiting up to %ss for app approval...", wait_for_approval)
            waited = 0
            while waited < wait_for_approval:
                page.wait_for_timeout(5000)
                waited += 5
                if self._is_logged_in(page):
                    logger.info("LinkedIn: approved + logged in.")
                    return True
            logger.warning("LinkedIn: approval not completed within %ss.", wait_for_approval)
            return False
        return self._is_logged_in(page)

    @staticmethod
    def _is_logged_in(page) -> bool:
        try:
            page.wait_for_timeout(500)
            url = page.url
            return ("/feed" in url) or ("linkedin.com/in/" in url) or (
                page.locator("button:has-text('Start a post')").count() > 0
            )
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _first_visible(page, selectors: list[str]):
        for sel in selectors:
            try:
                for loc in page.locator(sel).all():
                    if loc.is_visible():
                        return loc
            except Exception:  # noqa: BLE001
                continue
        return None
