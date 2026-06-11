"""LinkedIn posting.

API mode uses the modern Posts API (/rest/posts) with the w_member_social scope.
Images are registered via /rest/images?action=initializeUpload, the binary is PUT
to the returned uploadUrl, and the resulting image URN is attached to the post.

Browser mode logs in headlessly and publishes via the web composer.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote

import requests

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster
from .browser import persistent_page, save_debug_artifact

logger = logging.getLogger("reachly.linkedin")

REST = "https://api.linkedin.com/rest"
LINKEDIN_VERSION = "202505"  # YYYYMM; bump periodically


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _text_probe(text: str) -> str:
    normalized = _normalize_text(text)
    return normalized[:80]


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
        company_admin_url = (self.creds.extra or {}).get("company_admin_url", "").strip()
        try:
            with persistent_page("linkedin", self.data_dir) as page:
                page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                if "/login" in page.url or "/checkpoint" in page.url or "authwall" in page.url:
                    if not self._login(page):
                        return self._fail("LinkedIn login failed (check credentials / 2FA).")
                    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")

                if company_admin_url:
                    if not self._open_company_admin_composer(page, company_admin_url):
                        shot = save_debug_artifact(
                            page, self.data_dir, "linkedin", "company_composer_not_found"
                        )
                        return self._fail(
                            "LinkedIn company admin composer not found. "
                            f"Check admin access and LINKEDIN_COMPANY_ADMIN_URL. Debug: {shot}"
                        )
                elif not self._open_composer(page):
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "composer_not_found")
                    return self._fail(f"LinkedIn composer button not found. Debug: {shot}")
                page.wait_for_timeout(1500)

                # Optionally switch the author to a Company Page before typing.
                if post_as and not company_admin_url:
                    if not self._select_post_as(page, post_as):
                        return self._fail(
                            f"Could not select Company Page '{post_as}' in the composer "
                            f"(are you an admin? is the name exact?). Nothing was posted."
                        )

                editor = self._find_editor(page)
                if editor is None:
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "editor_not_found")
                    return self._fail(f"LinkedIn composer editor not found. Debug: {shot}")

                if post.media and post.media.kind == "image":
                    if not self._attach_image(page, post.media.local_path):
                        shot = save_debug_artifact(
                            page, self.data_dir, "linkedin", "image_attach_failed"
                        )
                        logger.warning(
                            "LinkedIn image attach failed; posting text only. Debug: %s",
                            shot,
                        )

                editor = self._find_editor(page)
                if editor is None:
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "editor_after_media_not_found")
                    return self._fail(f"LinkedIn composer editor not found after media. Debug: {shot}")
                self._replace_editor_text(page, editor, text)

                if not self._ensure_text_present(page, text):
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "text_missing")
                    return self._fail(
                        "LinkedIn composer text was missing after media attachment. "
                        f"Nothing was posted. Debug: {shot}"
                    )

                if not self._click_post(page):
                    shot = save_debug_artifact(page, self.data_dir, "linkedin", "post_button_not_found")
                    return self._fail(f"LinkedIn Post button not found. Debug: {shot}")
                page.wait_for_timeout(4000)
                return self._ok()
        except Exception as e:  # noqa: BLE001
            return self._fail(f"LinkedIn browser error: {e}")

    def _attach_image(self, page, image_path: str) -> bool:
        """Attach an image in LinkedIn's feed or company-page composer."""
        root = self._composer_root(page)
        candidates = [
            lambda: root.get_by_role("button", name=re.compile(r"add media", re.I)).first,
            lambda: root.locator("button[aria-label*='Add media' i]").first,
            lambda: root.get_by_role("button", name=re.compile(r"add (a )?photo", re.I)).first,
            lambda: root.get_by_role("button", name=re.compile(r"photo|image|media", re.I)).first,
            lambda: root.locator("button[aria-label*='Add a photo' i]").first,
            lambda: root.locator("button[aria-label*='media' i]").first,
            lambda: root.locator("button:has-text('Add a photo')").first,
            lambda: root.locator("button:has-text('Photo')").first,
            lambda: root.locator("button:has-text('Media')").first,
        ]
        for build in candidates:
            try:
                btn = build()
                if btn.count() and btn.is_visible():
                    btn.click(timeout=8000, force=True)
                    page.wait_for_timeout(1000)
                    break
            except Exception:  # noqa: BLE001
                continue

        photo_options = [
            lambda: root.get_by_role("button", name=re.compile(r"photo", re.I)).first,
            lambda: root.locator("button[aria-label*='photo' i]").first,
            lambda: root.locator("button:has-text('Photo')").first,
            lambda: page.get_by_role("button", name=re.compile(r"^photo$", re.I)).last,
        ]
        for build in photo_options:
            try:
                option = build()
                if option.count() and option.is_visible():
                    option.click(timeout=8000, force=True)
                    page.wait_for_timeout(1000)
                    break
            except Exception:  # noqa: BLE001
                continue

        try:
            file_input = root.locator("input[type='file']").first
            if not file_input.count():
                file_input = page.locator("input[type='file']").last
            file_input.set_input_files(image_path, timeout=10000)
            page.wait_for_timeout(5000)
        except Exception as e:  # noqa: BLE001
            logger.warning("LinkedIn file input upload failed: %s", e)
            return False

        next_candidates = [
            lambda: page.get_by_role("button", name=re.compile(r"^next$", re.I)).first,
            lambda: page.locator("button:has-text('Next')").first,
            lambda: page.get_by_role("button", name=re.compile(r"done", re.I)).first,
        ]
        for build in next_candidates:
            try:
                btn = build()
                if btn.count() and btn.is_visible() and btn.is_enabled():
                    btn.click(timeout=8000, force=True)
                    page.wait_for_timeout(1500)
                    return True
            except Exception:  # noqa: BLE001
                continue
        return True

    def _composer_root(self, page):
        """Return the active share composer scope to avoid clicking feed controls."""
        selectors = [
            "div[role='dialog']",
            "div[aria-modal='true']",
            ".share-box",
            ".share-creation-state",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).last
                if loc.count() and loc.is_visible():
                    return loc
            except Exception:  # noqa: BLE001
                continue
        return page

    def engage_with_hashtags(
        self,
        hashtags: list[str],
        *,
        make_comment: Callable[[str, str], str],
        max_comments: int = 3,
    ) -> int:
        clean_tags = []
        for tag in hashtags:
            clean = tag.strip().lstrip("#")
            if clean and clean.lower() not in {t.lower() for t in clean_tags}:
                clean_tags.append(clean)
        if not clean_tags:
            logger.info("LinkedIn engagement skipped: no hashtags.")
            return 0

        comments_done = 0
        with persistent_page("linkedin", self.data_dir) as page:
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            if "/login" in page.url or "/checkpoint" in page.url or "authwall" in page.url:
                if not self._login(page):
                    logger.warning("LinkedIn engagement skipped: login failed.")
                    return 0

            for tag in clean_tags:
                if comments_done >= max_comments:
                    break
                url = f"https://www.linkedin.com/feed/hashtag/{quote(tag)}/"
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                updates = self._visible_updates(page)
                for update in updates:
                    if comments_done >= max_comments:
                        break
                    try:
                        source_text = update.inner_text(timeout=3000).strip()
                    except Exception:  # noqa: BLE001
                        continue
                    if len(source_text) < 80:
                        continue
                    comment = make_comment(f"#{tag}", source_text)
                    if not comment:
                        continue
                    if self._comment_on_update(page, update, comment):
                        comments_done += 1
                        logger.info("Commented on LinkedIn hashtag #%s.", tag)
                        page.wait_for_timeout(2500)
        return comments_done

    def _visible_updates(self, page):
        selectors = [
            "div.feed-shared-update-v2",
            "article",
            "div[data-urn*='activity']",
        ]
        seen = set()
        updates = []
        for sel in selectors:
            try:
                for loc in page.locator(sel).all()[:8]:
                    try:
                        if not loc.is_visible():
                            continue
                        text = loc.inner_text(timeout=1500).strip()
                        key = text[:120]
                        if len(text) > 80 and key not in seen:
                            seen.add(key)
                            updates.append(loc)
                    except Exception:  # noqa: BLE001
                        continue
            except Exception:  # noqa: BLE001
                continue
        return updates[:5]

    def _comment_on_update(self, page, update, comment: str) -> bool:
        try:
            buttons = [
                lambda: update.get_by_role("button", name=re.compile(r"comment", re.I)).first,
                lambda: update.locator("button:has-text('Comment')").first,
            ]
            for build in buttons:
                try:
                    btn = build()
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=8000)
                        break
                except Exception:  # noqa: BLE001
                    continue
            page.wait_for_timeout(1200)
            editor = None
            for sel in (
                "div.ql-editor[contenteditable='true']",
                "div[role='textbox'][contenteditable='true']",
                "div[contenteditable='true']",
            ):
                try:
                    loc = update.locator(sel).last
                    if loc.count() and loc.is_visible():
                        editor = loc
                        break
                except Exception:  # noqa: BLE001
                    continue
            if editor is None:
                return False
            editor.click()
            editor.type(comment, delay=5)
            page.wait_for_timeout(500)
            for candidate in (
                lambda: update.get_by_role("button", name=re.compile(r"^post$", re.I)).last,
                lambda: update.locator("button:has-text('Post')").last,
                lambda: page.get_by_role("button", name=re.compile(r"^post$", re.I)).last,
            ):
                try:
                    btn = candidate()
                    if btn.count() and btn.is_visible() and btn.is_enabled():
                        btn.click(timeout=8000)
                        return True
                except Exception:  # noqa: BLE001
                    continue
        except Exception as e:  # noqa: BLE001
            logger.warning("LinkedIn comment attempt failed: %s", e)
        return False

    def _open_company_admin_composer(self, page, admin_url: str) -> bool:
        """Open the Company Page admin surface and start a post from there."""
        self._goto_company_admin(page, admin_url)
        page.wait_for_timeout(3500)
        if "/login" in page.url or "/checkpoint" in page.url or "authwall" in page.url:
            return False

        if self._find_editor(page) is not None:
            return True

        try:
            if self._click_start_post_menu_item(page):
                page.wait_for_timeout(2500)
                if self._find_editor(page) is not None:
                    return True
        except Exception:  # noqa: BLE001
            pass

        candidates = [
            lambda: page.get_by_role("button", name=re.compile(r"create", re.I)).first,
            lambda: page.get_by_role("button", name=re.compile(r"create.*post", re.I)).first,
            lambda: page.get_by_role("link", name=re.compile(r"create.*post", re.I)).first,
            lambda: page.get_by_role("button", name=re.compile(r"start a post", re.I)).first,
            lambda: page.get_by_text(re.compile(r"start a post", re.I)).first,
            lambda: page.locator("button:has-text('Create')").first,
            lambda: page.locator("button:has-text('Start a post')").first,
            lambda: page.locator("a:has-text('Create a post')").first,
            lambda: page.locator("[data-control-name*='create' i]").first,
        ]
        for build in candidates:
            try:
                loc = build()
                if loc.count() and loc.is_visible():
                    try:
                        loc.click(timeout=10000, force=True)
                    except Exception:  # noqa: BLE001
                        loc.evaluate("el => el.click()")
                    page.wait_for_timeout(2500)
                    if self._find_editor(page) is not None:
                        return True
                    # Some admin variants open a small menu after Create.
                    if self._click_start_post_menu_item(page):
                        page.wait_for_timeout(2500)
                        if self._find_editor(page) is not None:
                            return True
                    menu_items = [
                        lambda: page.get_by_role("menuitem", name=re.compile(r"start a post", re.I)).first,
                        lambda: page.get_by_text(re.compile(r"^start a post$", re.I)).first,
                        lambda: page.get_by_role("menuitem", name=re.compile(r"post", re.I)).first,
                        lambda: page.get_by_role("button", name=re.compile(r"post", re.I)).first,
                        lambda: page.get_by_text(re.compile(r"^post$", re.I)).first,
                        lambda: page.get_by_text(re.compile(r"create a post", re.I)).first,
                    ]
                    for item_builder in menu_items:
                        try:
                            post_item = item_builder()
                            if post_item.count() and post_item.is_visible():
                                post_item.click(timeout=5000, force=True)
                                page.wait_for_timeout(2500)
                                if self._find_editor(page) is not None:
                                    return True
                        except Exception:  # noqa: BLE001
                            continue
            except Exception:  # noqa: BLE001
                continue
        return False

    def _goto_company_admin(self, page, admin_url: str) -> None:
        try:
            page.goto(admin_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as first_error:  # noqa: BLE001
            logger.warning("LinkedIn company admin load timed out, retrying: %s", first_error)
            page.goto(admin_url, wait_until="commit", timeout=60000)

    def _click_start_post_menu_item(self, page) -> bool:
        """Click LinkedIn admin's Create > Start a post row, not only its text node."""
        selectors = [
            "div[role='dialog'] :text('Start a post')",
            "div[aria-modal='true'] :text('Start a post')",
            ":text('Start a post')",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if not (loc.count() and loc.is_visible()):
                    continue
                loc.scroll_into_view_if_needed(timeout=5000)
                loc.evaluate(
                    """el => {
                        const clickable = el.closest(
                            'button,a,[role="button"],[role="menuitem"],li,div'
                        );
                        clickable.click();
                    }"""
                )
                return True
            except Exception:  # noqa: BLE001
                continue
        return False

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

    def _replace_editor_text(self, page, editor, text: str) -> None:
        editor.click()
        try:
            page.keyboard.press("ControlOrMeta+A")
            page.keyboard.type(text, delay=5)
        except Exception:  # noqa: BLE001
            editor.click()
            page.keyboard.type(text, delay=5)
        page.wait_for_timeout(500)

    def _ensure_text_present(self, page, text: str) -> bool:
        """Verify LinkedIn kept the post text after image upload."""
        expected = _text_probe(text)
        for attempt in range(2):
            editor = self._find_editor(page)
            if editor is None:
                return False
            try:
                current = editor.inner_text(timeout=3000)
            except Exception:  # noqa: BLE001
                current = ""
            if expected and expected in _normalize_text(current):
                return True
            logger.warning(
                "LinkedIn composer text missing after media attach; retyping (attempt %s).",
                attempt + 1,
            )
            self._replace_editor_text(page, editor, text)
        try:
            current = self._find_editor(page).inner_text(timeout=3000)
        except Exception:  # noqa: BLE001
            current = ""
        return bool(expected and expected in _normalize_text(current))

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
