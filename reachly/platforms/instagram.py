"""Instagram posting.

API mode uses the Instagram Graph API (Business/Creator accounts only):
  1) POST /{ig-user-id}/media   with image_url/video_url + caption   -> creation_id
  2) POST /{ig-user-id}/media_publish with creation_id
NOTE: Instagram fetches the media from a PUBLIC url, so API mode requires the
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
        if not post.media or post.media.kind not in ("image", "video"):
            return self._fail("Instagram API mode requires generated image or video media.")

        media_url = post.media.public_url or self._public_url_for(post.media.local_path)
        if not media_url:
            return self._fail(
                "Instagram API needs a PUBLIC media url. Set PUBLIC_MEDIA_BASE_URL "
                "or use INSTAGRAM_MODE=browser."
            )
        try:
            caption = post.for_platform(Platform.instagram)
            create_payload = {"caption": caption, "access_token": self.token}
            if post.media.kind == "video":
                create_payload.update(
                    {"media_type": "REELS", "video_url": media_url, "share_to_feed": "true"}
                )
            else:
                create_payload["image_url"] = media_url
            create = requests.post(
                f"{GRAPH}/{self.user_id}/media",
                data=create_payload,
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
        if not post.media or post.media.kind not in ("image", "video"):
            return self._fail("Instagram browser mode requires generated image or video media.")
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

                if not self._open_create(page, post.media.kind):
                    shot = save_debug_artifact(page, self.data_dir, "instagram", "create_not_found")
                    return self._fail(f"Could not open Instagram create dialog. Debug: {shot}")

                if not self._upload_media(page, media_path):
                    shot = save_debug_artifact(page, self.data_dir, "instagram", "media_upload_failed")
                    return self._fail(f"Could not upload media to Instagram composer. Debug: {shot}")

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

    def _open_create(self, page, media_kind: str = "image") -> bool:
        # Direct create URL often works when logged in.
        for url in self._create_urls(media_kind):
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                if self._composer_ready(page):
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
                    self._click_create_control(loc)
                    page.wait_for_timeout(2000)
                    if self._composer_ready(page):
                        return True
                    if self._click_post_menu_item(page):
                        return True
                    if self._click_post_menu_coordinates(page):
                        return True
            except Exception:  # noqa: BLE001
                continue
        return self._composer_ready(page)

    def _composer_ready(self, page) -> bool:
        if not page.locator("input[type='file']").count():
            return False
        body = ""
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:  # noqa: BLE001
            body = ""
        cues = (
            "Create new post",
            "Drag photos and videos here",
            "Select from computer",
            "Crop",
            "Edit",
            "Write a caption",
            "Share",
        )
        return any(cue in body for cue in cues) or page.get_by_role("dialog").count() > 0

    def _click_create_control(self, loc) -> None:
        try:
            loc.evaluate(
                """el => {
                    const target = el.closest('a,button,div[role="button"]') || el;
                    target.click();
                }"""
            )
        except Exception:  # noqa: BLE001
            loc.click()

    def _click_post_menu_item(self, page) -> bool:
        for selector in (
            "text=Post",
            "div[role='button']:has-text('Post')",
            "button:has-text('Post')",
        ):
            try:
                item = page.locator(selector).first
                if item.count() and item.is_visible():
                    try:
                        item.evaluate(
                            """el => {
                                const target = el.closest('a,button,div[role="button"]')
                                  || el.parentElement
                                  || el;
                                target.click();
                            }"""
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    page.wait_for_timeout(1200)
                    if self._composer_ready(page):
                        return True

                    box = item.bounding_box()
                    if box:
                        for x_offset in (box["width"] / 2, 80, 150):
                            try:
                                page.mouse.click(box["x"] + x_offset, box["y"] + box["height"] / 2)
                                page.wait_for_timeout(1200)
                                if self._composer_ready(page):
                                    return True
                            except Exception:  # noqa: BLE001
                                continue

                    try:
                        item.click(timeout=8000)
                        page.wait_for_timeout(1200)
                        if self._composer_ready(page):
                            return True
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                continue
        return False

    def _click_post_menu_coordinates(self, page) -> bool:
        # Instagram's left-rail Create menu sometimes exposes text nodes that
        # Playwright can see but cannot activate reliably. The viewport is fixed
        # in persistent_page(), so this is a stable last-resort click on Post.
        try:
            page.mouse.click(58, 552)
            page.wait_for_timeout(2000)
            return self._composer_ready(page)
        except Exception:  # noqa: BLE001
            return False

    def _create_urls(self, media_kind: str) -> tuple[str, ...]:
        if media_kind == "video":
            return (
                "https://www.instagram.com/create/select/",
                "https://www.instagram.com/create/style/",
            )
        return (
            "https://www.instagram.com/create/select/",
            "https://www.instagram.com/create/style/",
        )

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

    def _upload_media(self, page, media_path: str) -> bool:
        try:
            file_input = page.locator("input[type='file']").first
            file_input.wait_for(state="attached", timeout=15000)
            file_input.set_input_files(media_path)
            page.wait_for_timeout(5000)
            if not self._select_screen_visible(page):
                return True
        except Exception:  # noqa: BLE001
            pass

        for selector in (
            "text=Select from computer",
            "button:has-text('Select from computer')",
            "div[role='button']:has-text('Select from computer')",
        ):
            try:
                button = page.locator(selector).first
                if not (button.count() and button.is_visible()):
                    continue
                with page.expect_file_chooser(timeout=10000) as chooser_info:
                    button.click(timeout=8000)
                chooser_info.value.set_files(media_path)
                page.wait_for_timeout(5000)
                return not self._select_screen_visible(page)
            except Exception:  # noqa: BLE001
                continue
        return not self._select_screen_visible(page)

    def _select_screen_visible(self, page) -> bool:
        try:
            body = page.locator("body").inner_text(timeout=3000)
        except Exception:  # noqa: BLE001
            return False
        return "Drag photos and videos here" in body and "Select from computer" in body

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
