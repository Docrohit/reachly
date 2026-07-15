"""Medium browser posting.

Medium's public API is not reliable for new integrations, so Reachly uses a
persistent Playwright browser session. The adapter fails if Medium cannot save
the draft; this avoids treating a clicked Publish button as success.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster
from .browser import persistent_page, save_debug_artifact

logger = logging.getLogger("reachly.medium")


class MediumBrowserPoster(Poster):
    platform = Platform.medium

    def __init__(self, creds: PlatformCredentials, *, data_dir: Path):
        super().__init__(creds)
        self.data_dir = Path(data_dir)
        self.publish_status = (creds.extra or {}).get("publish_status", "draft").lower()
        self.expected_account = (creds.extra or {}).get("expected_account", "").strip()

    def post(self, post: GeneratedPost) -> PostResult:
        if not post.media or post.media.kind != "image":
            return self._fail("Medium browser mode requires a 16:9 image.")
        try:
            with persistent_page("medium", self.data_dir) as page:
                page.goto("https://medium.com/new-story", wait_until="domcontentloaded")
                page.wait_for_timeout(3500)
                if self._needs_login(page):
                    return self._fail("Medium login required. Prime the browser session first.")
                if self.expected_account and self.expected_account.lower() not in self._account_text(page).lower():
                    return self._fail(
                        f"Medium account mismatch. Expected '{self.expected_account}'."
                    )

                editor = self._editor(page)
                if editor is None:
                    shot = save_debug_artifact(page, self.data_dir, "medium", "editor_not_found")
                    return self._fail(f"Medium editor not found. Debug: {shot}")

                self._write_article(page, post)
                if not self._attach_image(page, post.media.local_path):
                    shot = save_debug_artifact(page, self.data_dir, "medium", "image_attach_failed")
                    return self._fail(f"Medium image upload failed. Debug: {shot}")

                if not self._wait_for_saved(page):
                    shot = save_debug_artifact(page, self.data_dir, "medium", "save_failed")
                    return self._fail(
                        "Medium could not save the story; not publishing. "
                        f"Debug: {shot}"
                    )

                if self.publish_status != "public":
                    return self._ok(permalink=page.url)

                if not self._publish(page, post.hashtags):
                    shot = save_debug_artifact(page, self.data_dir, "medium", "publish_failed")
                    return self._fail(f"Medium publish failed. Debug: {shot}")
                if not self._wait_for_published(page):
                    shot = save_debug_artifact(page, self.data_dir, "medium", "publish_unverified")
                    return self._fail(f"Medium publish could not be verified. Debug: {shot}")
                return self._ok(permalink=page.url)
        except Exception as e:  # noqa: BLE001
            return self._fail(f"Medium browser error: {e}")

    def _needs_login(self, page) -> bool:
        url = page.url
        if "/m/signin" in url or "/signin" in url:
            return True
        body = _body_text(page)
        return "Sign in to Medium" in body or "Create an account" in body

    def _account_text(self, page) -> str:
        parts = []
        for selector in ("button[aria-label*='user' i]", "[aria-label*='profile' i]", "button"):
            try:
                for loc in page.locator(selector).all()[:8]:
                    text = (loc.inner_text(timeout=1000) or "").strip()
                    if text:
                        parts.append(text)
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(parts + [_body_text(page)[:500]])

    def _editor(self, page):
        selectors = [
            "article div[contenteditable='true']",
            "section div[contenteditable='true']",
            "div[role='textbox'][contenteditable='true']",
            "div[contenteditable='true']",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="visible", timeout=6000)
                return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    def _write_article(self, page, post: GeneratedPost) -> None:
        title, paragraphs = _article_parts(post)
        title_editor = self._title_editor(page)
        editor = title_editor or self._editor(page)
        if editor is None:
            raise RuntimeError("Medium editor disappeared before writing.")
        editor.click()
        page.keyboard.insert_text(title)
        page.keyboard.press("Enter")
        for paragraph in paragraphs:
            page.keyboard.insert_text(paragraph)
            page.keyboard.press("Enter")
            page.keyboard.press("Enter")

    def _title_editor(self, page):
        selectors = [
            "[contenteditable='true'][data-default-value='Title']",
            "[contenteditable='true'][aria-label='Title']",
            "[role='textbox'][aria-label='Title']",
            "h1[contenteditable='true']",
            "h2[contenteditable='true']",
            "h3[contenteditable='true']",
        ]
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                loc.wait_for(state="visible", timeout=2500)
                return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    def _attach_image(self, page, image_path: str) -> bool:
        try:
            page.keyboard.press("Home")
            page.wait_for_timeout(300)
        except Exception:  # noqa: BLE001
            pass

        resolved_path = str(Path(image_path).resolve())
        if self._set_first_file_input(page, resolved_path):
            return True

        add_entry_points = [
            lambda: page.get_by_role(
                "button",
                name=re.compile(r"add an image, video, embed, or new part", re.I),
            ).first,
            lambda: page.get_by_role("button", name=re.compile(r"add an image", re.I)).first,
            lambda: page.locator("button[aria-label*='image' i]").first,
        ]
        for build in add_entry_points:
            try:
                loc = build()
                if not loc.count():
                    continue
                if loc.is_visible():
                    loc.click(timeout=8000, force=True)
                    page.wait_for_timeout(800)
                    if self._set_first_file_input(page, resolved_path):
                        return True
                    if _click_first(page, [
                        lambda: page.get_by_role("button", name=re.compile(r"^add an image$", re.I)).last,
                        lambda: page.locator("button:has-text('Add an image')").last,
                    ]):
                        page.wait_for_timeout(800)
                        if self._set_first_file_input(page, resolved_path):
                            return True
            except Exception:  # noqa: BLE001
                continue
        return False

    def _set_first_file_input(self, page, image_path: str) -> bool:
        try:
            file_input = page.locator("input[type='file']").first
            if file_input.count():
                file_input.set_input_files(image_path, timeout=15000)
                page.wait_for_timeout(5000)
                return True
        except Exception:  # noqa: BLE001
            return False
        return False

    def _wait_for_saved(self, page, timeout_ms: int = 30000) -> bool:
        deadline = page.evaluate("Date.now()") + timeout_ms
        while page.evaluate("Date.now()") < deadline:
            body = _body_text(page)
            if "Something is wrong and we cannot save your story" in body:
                return False
            if re.search(r"\bSaved\b|\bDraft\b", body, re.I):
                return True
            page.wait_for_timeout(1500)
        return "Something is wrong and we cannot save your story" not in _body_text(page)

    def _publish(self, page, tags: list[str]) -> bool:
        if not _click_first(page, [
            lambda: page.get_by_role("button", name=re.compile(r"^publish$", re.I)).first,
            lambda: page.locator("button:has-text('Publish')").first,
        ]):
            return False
        page.wait_for_timeout(2500)

        for tag in tags[:5]:
            try:
                box = page.locator("input[placeholder*='tag' i], input[type='text']").last
                if box.count() and box.is_visible():
                    box.fill(tag)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(300)
            except Exception:  # noqa: BLE001
                continue

        return _click_first(page, [
            lambda: page.get_by_role("button", name=re.compile(r"publish now|publish", re.I)).last,
            lambda: page.locator("button:has-text('Publish now')").last,
            lambda: page.locator("button:has-text('Publish')").last,
        ])

    def _wait_for_published(self, page, timeout_ms: int = 45000) -> bool:
        deadline = page.evaluate("Date.now()") + timeout_ms
        while page.evaluate("Date.now()") < deadline:
            body = _body_text(page)
            if "Something is wrong" in body:
                return False
            if "/p/" in page.url or "Your story is published" in body:
                return True
            page.wait_for_timeout(2000)
        return False


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _article_parts(post: GeneratedPost) -> tuple[str, list[str]]:
    title = post.hook.strip()
    paragraphs = _paragraphs(post.body)
    return title, paragraphs


def _body_text(page) -> str:
    try:
        return page.locator("body").inner_text(timeout=3000)
    except Exception:  # noqa: BLE001
        return ""


def _click_first(page, builders) -> bool:
    for build in builders:
        try:
            loc = build()
            if loc.count() and loc.is_visible() and loc.is_enabled():
                loc.click(timeout=10000, force=True)
                return True
        except Exception:  # noqa: BLE001
            continue
    return False
