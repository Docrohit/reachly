"""Facebook Page browser publishing. Requires a pre-authenticated Page session.

Do not switch identities automatically. Fail closed if the composer cannot prove
which Page is posting. Selectors require a live acceptance test on the bound Page.
"""
import logging
from pathlib import Path
from .base import Poster
from .browser import persistent_page
from ..models import Platform

logger = logging.getLogger(__name__)


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
