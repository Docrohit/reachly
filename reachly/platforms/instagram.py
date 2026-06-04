"""Instagram posting.

API mode uses the Instagram Graph API (Business/Creator accounts only):
  1) POST /{ig-user-id}/media   with image_url + caption   -> creation_id
  2) POST /{ig-user-id}/media_publish with creation_id
NOTE: Instagram fetches the image from a PUBLIC url, so API mode requires the
media to be reachable on the internet (the SaaS server hosts it; self-hosters
set PUBLIC_MEDIA_BASE_URL or use browser mode).

Browser mode logs in headlessly and uses the web "Create" composer.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

import requests

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster
from .browser import persistent_page, save_debug_artifact

logger = logging.getLogger("reachly.instagram")

GRAPH = "https://graph.facebook.com/v21.0"


class InstagramApiPoster(Poster):
    platform = Platform.instagram

    def __init__(self, creds: PlatformCredentials, *, public_media_base_url: Optional[str] = None):
        super().__init__(creds)
        self.token = creds.api_token
        self.user_id = (creds.extra or {}).get("user_id")
        self.public_media_base_url = public_media_base_url

    def post(self, post: GeneratedPost) -> PostResult:
        if not (self.token and self.user_id):
            return self._fail("Missing INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_USER_ID.")
        if not post.media or post.media.kind != "image":
            return self._fail("Instagram API mode requires an image. Enable ATTACH_IMAGE.")

        image_url = post.media.public_url or self._public_url_for(post.media.local_path)
        if not image_url:
            return self._fail(
                "Instagram API needs a PUBLIC image url. Set PUBLIC_MEDIA_BASE_URL "
                "or use INSTAGRAM_MODE=browser."
            )
        try:
            caption = post.for_platform(Platform.instagram)
            create = requests.post(
                f"{GRAPH}/{self.user_id}/media",
                data={"image_url": image_url, "caption": caption, "access_token": self.token},
                timeout=60,
            )
            if create.status_code >= 300:
                return self._fail(f"IG container failed {create.status_code}: {create.text[:300]}")
            creation_id = create.json()["id"]

            self._await_container(creation_id)

            publish = requests.post(
                f"{GRAPH}/{self.user_id}/media_publish",
                data={"creation_id": creation_id, "access_token": self.token},
                timeout=60,
            )
            if publish.status_code >= 300:
                return self._fail(f"IG publish failed {publish.status_code}: {publish.text[:300]}")
            return self._ok()
        except Exception as e:  # noqa: BLE001
            return self._fail(f"Instagram API error: {e}")

    def _await_container(self, creation_id: str, max_wait: int = 120) -> None:
        deadline = time.time() + max_wait
        while time.time() < deadline:
            r = requests.get(
                f"{GRAPH}/{creation_id}",
                params={"fields": "status_code", "access_token": self.token},
                timeout=30,
            )
            if r.ok and r.json().get("status_code") == "FINISHED":
                return
            time.sleep(3)
        # Images are usually instant; don't hard-fail if status endpoint lags.

    def _public_url_for(self, local_path: str) -> Optional[str]:
        if not self.public_media_base_url:
            return None
        name = Path(local_path).name
        return f"{self.public_media_base_url.rstrip('/')}/{name}"


class InstagramBrowserPoster(Poster):
    platform = Platform.instagram

    def __init__(self, creds: PlatformCredentials, *, data_dir: Path):
        super().__init__(creds)
        self.data_dir = Path(data_dir)

    def post(self, post: GeneratedPost) -> PostResult:
        if not post.media or post.media.kind != "image":
            return self._fail("Instagram browser mode requires an image. Enable ATTACH_IMAGE.")
        caption = post.for_platform(Platform.instagram)
        media_path = str(Path(post.media.local_path).resolve())
        try:
            with persistent_page("instagram", self.data_dir) as page:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                if self._needs_login(page):
                    if not self._login(page):
                        return self._fail("Instagram login failed (check credentials / 2FA).")
                    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                    page.wait_for_timeout(4000)

                if not self._open_create(page):
                    shot = save_debug_artifact(page, self.data_dir, "instagram", "create_not_found")
                    return self._fail(f"Could not open Instagram create dialog. Debug: {shot}")

                file_input = page.locator("input[type='file']").first
                file_input.wait_for(state="attached", timeout=15000)
                file_input.set_input_files(media_path)
                page.wait_for_timeout(3500)

                cap = None
                for _ in range(4):
                    cap = self._caption_box(page)
                    if cap.count():
                        break
                    next_button = page.get_by_role("button", name="Next")
                    if next_button.count():
                        next_button.first.click(timeout=12000)
                        page.wait_for_timeout(2500)
                        continue
                    break

                cap = self._caption_box(page).first
                try:
                    cap.wait_for(state="visible", timeout=15000)
                except Exception:
                    shot = save_debug_artifact(page, self.data_dir, "instagram", "caption_not_found")
                    return self._fail(f"Could not find Instagram caption box. Debug: {shot}")
                cap.click()
                page.keyboard.type(caption, delay=3)

                page.get_by_role("button", name="Share", exact=True).first.click(timeout=12000)
                page.wait_for_timeout(6000)
                return self._ok()
        except Exception as e:  # noqa: BLE001
            return self._fail(f"Instagram browser error: {e}")

    def _needs_login(self, page) -> bool:
        url = page.url
        if "/accounts/login" in url or "/challenge" in url:
            return True
        if page.locator("input[name='username'], input[name='email']").count() > 0:
            return True
        # Instagram home when logged out shows inline login (no name=username).
        body = page.locator("body").inner_text(timeout=5000)
        if "Log into Instagram" in body or "Log in to Instagram" in body:
            return True
        if page.get_by_role("button", name="Log in").count() and page.locator(
            "input[type='password']"
        ).count():
            return True
        return False

    def _open_create(self, page) -> bool:
        # Direct create URL often works when logged in.
        for url in ("https://www.instagram.com/create/select/", "https://www.instagram.com/create/style/"):
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                if page.locator("input[type='file']").count():
                    return True
            except Exception:  # noqa: BLE001
                continue

        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        for sel in (
            'a[href="#"]:has-text("Create")',
            'svg[aria-label="New post"]',
            'svg[aria-label="Create"]',
            '[aria-label="New post"]',
            '[aria-label="Create"]',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click()
                    page.wait_for_timeout(2000)
                    if page.locator("input[type='file']").count():
                        return True
            except Exception:  # noqa: BLE001
                continue
        return page.locator("input[type='file']").count() > 0

    def _caption_box(self, page):
        return page.locator(
            "textarea[aria-label*='caption'], "
            "textarea[aria-label*='Caption'], "
            "textarea[placeholder*='caption'], "
            "textarea[placeholder*='Caption'], "
            "div[aria-label*='caption'][contenteditable='true'], "
            "div[aria-label*='Caption'][contenteditable='true'], "
            "div[contenteditable='true'][role='textbox'], "
            "[role='textbox'][contenteditable='true']"
        )

    def _login(self, page) -> bool:
        if not (self.creds.username and self.creds.password):
            return False
        # Use current page if it already shows the login form; else dedicated login URL.
        if not page.locator("input[type='password']").count():
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

        user = page.locator(
            "input[name='email'], input[name='username'], input[autocomplete='username']"
        ).first
        pw = page.locator("input[name='pass'], input[name='password'], input[type='password']").first
        user.wait_for(state="visible", timeout=20000)
        user.click()
        user.fill(self.creds.username)
        pw.click()
        pw.fill(self.creds.password)
        # The form's <input type=submit> is hidden; the visible "Log in" control is a
        # styled div/button. Pressing Enter in the password field submits reliably.
        clicked = False
        for sel in ("div[role='button']:has-text('Log in')", "button:has-text('Log in')"):
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=5000)
                    clicked = True
                    break
            except Exception:  # noqa: BLE001
                continue
        if not clicked:
            pw.press("Enter")
        page.wait_for_timeout(10000)

        if "/challenge" in page.url or "challenge" in page.url:
            logger.warning(
                "Instagram checkpoint — open Instagram on your phone and tap Approve/Yes."
            )
            for _ in range(24):  # up to ~2 min
                page.wait_for_timeout(5000)
                if not self._needs_login(page) and "/challenge" not in page.url:
                    return True
            return False

        page.wait_for_timeout(3000)
        return not self._needs_login(page)
