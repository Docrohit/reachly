"""Facebook Page publishing.

API mode posts with a Page access token obtained through the owner's Facebook
Login (Channels page). Browser mode requires a pre-authenticated Page session:
do not switch identities automatically, and fail closed if the composer cannot
prove which Page is posting.
"""
import hashlib
import hmac
import logging
from pathlib import Path

import requests

from .base import Poster
from .browser import persistent_page
from ..models import Platform

logger = logging.getLogger(__name__)

GRAPH = "https://graph.facebook.com"
# Prefix for a definite provider rejection: nothing was posted, a retry is safe.
REJECTED = "rejected: "


def appsecret_proof(token: str, app_secret: str) -> dict:
    """Meta's proof that a call comes from the app that owns the token."""
    if not app_secret:
        return {}
    return {"appsecret_proof": hmac.new(app_secret.encode(), token.encode(), hashlib.sha256).hexdigest()}


class FacebookApiPoster(Poster):
    platform = Platform.facebook

    def __init__(self, creds):
        super().__init__(creds)
        extra = creds.extra or {}
        self.token = creds.api_token or ""
        self.page_id = str(extra.get("page_id") or "")
        self.app_secret = extra.get("app_secret") or ""
        self.version = extra.get("graph_version") or "v25.0"

    def post(self, post):
        if not (self.token and self.page_id.isdigit()):
            return self._fail("Connect the Facebook Page on the Channels page first.")
        params = {"access_token": self.token, **appsecret_proof(self.token, self.app_secret)}
        caption = post.for_platform(Platform.facebook)
        try:
            if post.media and post.media.kind == "image" and Path(post.media.local_path).is_file():
                with open(post.media.local_path, "rb") as fh:
                    response = requests.post(f"{GRAPH}/{self.version}/{self.page_id}/photos", params=params,
                                             data={"caption": caption}, files={"source": fh}, timeout=90)
            else:
                response = requests.post(f"{GRAPH}/{self.version}/{self.page_id}/feed", params=params,
                                         data={"message": caption}, timeout=60)
        except requests.RequestException:
            return self._fail("Facebook did not confirm the post. Check the Page before retrying.")
        if 400 <= response.status_code < 500:
            return self._fail(REJECTED + f"Facebook refused the post (HTTP {response.status_code}). Reconnect the Page if this repeats.")
        if not response.ok:
            return self._fail(f"Facebook returned HTTP {response.status_code}. Check the Page before retrying.")
        try:
            data = response.json()
        except ValueError:
            return self._fail("Facebook returned an unreadable reply. Check the Page before retrying.")
        post_id = str(data.get("post_id") or data.get("id") or "")
        if not post_id:
            return self._fail("Facebook did not return a post ID. Check the Page before retrying.")
        return self._ok(f"https://www.facebook.com/{post_id}")


class FacebookBrowserPoster(Poster):
    platform = Platform.facebook

    def __init__(self, creds, *, data_dir):
        super().__init__(creds)
        self.data_dir = Path(data_dir)

    def post(self, post):
        from urllib.parse import urlparse
        target = self.creds.extra.get("page_url", "")
        expected = self.creds.extra.get("expected_account", "")
        parsed = urlparse(target)
        if parsed.scheme != "https" or parsed.netloc != "www.facebook.com" or not expected:
            return self._fail("A verified Facebook Page binding is required.")
        try:
            with persistent_page("facebook", self.data_dir) as page:
                page.goto(target, wait_until="domcontentloaded")
                if page.locator('input[type="password"]').count():
                    return self._fail("Reconnect the Facebook Page browser session.")
                page.get_by_role("button", name="Create post", exact=True).click(timeout=15000)
                dialog = page.get_by_role("dialog").filter(has_text="Create post").last
                # The composer actor, not the Page heading, proves posting identity.
                actor = dialog.get_by_role("button", name=f"Posting as {expected}", exact=True)
                if not actor.count():
                    return self._fail("Cannot verify the Facebook composer Page identity.")
                dialog.get_by_role("textbox").first.fill(post.for_platform(Platform.facebook))
                if post.media:
                    dialog.locator('input[type="file"]').first.set_input_files(post.media.local_path)
                dialog.get_by_role("button", name="Post", exact=True).click(timeout=30000)
                page.get_by_text("Your post is now published", exact=False).first.wait_for(
                    state="visible", timeout=45000
                )
                return self._ok()
        except Exception as exc:
            # A timeout after Post is ambiguous. Never automatically retry it.
            logger.warning("Facebook browser outcome unconfirmed: %s", type(exc).__name__)
            return self._fail("Facebook result needs review in the bound Page; do not retry automatically.")
