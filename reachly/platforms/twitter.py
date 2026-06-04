"""Twitter / X posting.

API mode uses X API v2 with an OAuth2 user-context bearer token
(scopes: tweet.write, media.write, users.read). Media upload follows the v2
chunked INIT/APPEND/FINALIZE flow.

Browser mode logs in headlessly and composes a tweet via the web app.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import requests

from ..models import GeneratedPost, Platform, PlatformCredentials, PostResult
from .base import Poster
from .browser import persistent_page, save_debug_artifact

logger = logging.getLogger("reachly.twitter")

API = "https://api.x.com/2"
MEDIA_UPLOAD = f"{API}/media/upload"
TWEETS = f"{API}/tweets"


class TwitterApiPoster(Poster):
    platform = Platform.twitter

    def __init__(self, creds: PlatformCredentials):
        super().__init__(creds)
        self.token = creds.api_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def post(self, post: GeneratedPost) -> PostResult:
        if not self.token:
            return self._fail("Missing TWITTER_OAUTH2_TOKEN for API mode.")
        try:
            media_ids = []
            if post.media and post.media.kind == "image":
                media_ids.append(self._upload_image(post.media.local_path))

            payload: dict = {"text": post.for_platform(Platform.twitter)}
            if media_ids:
                payload["media"] = {"media_ids": media_ids}

            r = requests.post(TWEETS, json=payload, headers=self._headers(), timeout=30)
            if r.status_code >= 300:
                return self._fail(f"X tweet failed {r.status_code}: {r.text[:300]}")
            data = r.json().get("data", {})
            tid = data.get("id")
            return self._ok(permalink=f"https://x.com/i/web/status/{tid}" if tid else None)
        except Exception as e:  # noqa: BLE001
            return self._fail(f"X API error: {e}")

    def _upload_image(self, path: str) -> str:
        size = os.path.getsize(path)
        init = requests.post(
            f"{MEDIA_UPLOAD}/initialize",
            json={
                "media_type": "image/png",
                "total_bytes": size,
                "media_category": "tweet_image",
            },
            headers=self._headers(),
            timeout=30,
        )
        init.raise_for_status()
        media_id = init.json()["data"]["id"]

        with open(path, "rb") as f:
            requests.post(
                f"{MEDIA_UPLOAD}/{media_id}/append",
                data={"segment_index": 0},
                files={"media": f},
                headers=self._headers(),
                timeout=60,
            ).raise_for_status()

        finalize = requests.post(
            f"{MEDIA_UPLOAD}/{media_id}/finalize",
            headers=self._headers(),
            timeout=30,
        )
        finalize.raise_for_status()
        processing = finalize.json().get("data", {}).get("processing_info") or {}
        self._await_media(media_id, processing)
        return media_id

    def _await_media(self, media_id: str, processing: dict, max_wait: int = 120) -> None:
        state = processing.get("state")
        if not state or state == "succeeded":
            return
        deadline = time.time() + max_wait
        wait = int(processing.get("check_after_secs") or 2)
        while time.time() < deadline:
            time.sleep(max(1, wait))
            status = requests.get(
                MEDIA_UPLOAD,
                params={"command": "STATUS", "media_id": media_id},
                headers=self._headers(),
                timeout=30,
            )
            status.raise_for_status()
            processing = status.json().get("data", {}).get("processing_info") or {}
            state = processing.get("state")
            if state == "succeeded":
                return
            if state == "failed":
                raise RuntimeError(f"X media processing failed: {processing}")
            wait = int(processing.get("check_after_secs") or 2)


class TwitterBrowserPoster(Poster):
    platform = Platform.twitter

    def __init__(self, creds: PlatformCredentials, *, data_dir: Path):
        super().__init__(creds)
        self.data_dir = Path(data_dir)

    def post(self, post: GeneratedPost) -> PostResult:
        text = post.for_platform(Platform.twitter)
        try:
            with persistent_page("twitter", self.data_dir) as page:
                page.goto("https://x.com/home", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                if self._needs_login(page):
                    if not self._login(page):
                        shot = save_debug_artifact(page, self.data_dir, "twitter", "login_failed")
                        return self._fail(f"X login failed (check credentials / 2FA). Debug: {shot}")
                    page.goto("https://x.com/home", wait_until="domcontentloaded")

                page.goto("https://x.com/compose/post", wait_until="domcontentloaded")
                box = page.locator("div[data-testid='tweetTextarea_0']").first
                try:
                    box.wait_for(state="visible", timeout=15000)
                except Exception:
                    shot = save_debug_artifact(page, self.data_dir, "twitter", "composer_not_found")
                    return self._fail(f"X composer not found. Debug: {shot}")
                box.click()
                page.keyboard.type(text, delay=10)

                if post.media and post.media.kind == "image":
                    file_input = page.locator("input[type='file']").first
                    file_input.set_input_files(post.media.local_path)
                    page.wait_for_timeout(4000)

                page.locator("button[data-testid='tweetButton']").first.click()
                page.wait_for_timeout(4000)
                return self._ok()
        except Exception as e:  # noqa: BLE001
            return self._fail(f"X browser error: {e}")

    def _needs_login(self, page) -> bool:
        if "/login" in page.url or "/i/flow/login" in page.url:
            return True
        if page.locator("input[name='password']").count():
            return True
        body = page.locator("body").inner_text(timeout=5000)
        return "Sign in to X" in body or "Log in to X" in body or "Sign in with" in body

    def _login(self, page) -> bool:
        if not (self.creds.username and self.creds.password):
            return False
        page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        user = page.locator("input[name='text']").first
        user.wait_for(timeout=15000)
        user.fill(self.creds.username)
        self._click_next(page)
        page.wait_for_timeout(2000)

        if not page.locator("input[name='password']").count():
            challenge = page.locator("input[name='text']").first
            if challenge.count():
                login_identifier = (
                    self.creds.extra.get("login_identifier")
                    or self.creds.username
                    or ""
                )
                challenge.fill(login_identifier)
                self._click_next(page)
                page.wait_for_timeout(2000)

        pw = page.locator("input[name='password']").first
        pw.wait_for(timeout=15000)
        pw.fill(self.creds.password)
        page.get_by_role("button", name="Log in").click()
        page.wait_for_timeout(4000)
        return "/login" not in page.url

    def _click_next(self, page) -> None:
        for name in ("Next", "Continue"):
            button = page.get_by_role("button", name=name)
            if button.count():
                button.first.click()
                return
        page.keyboard.press("Enter")
