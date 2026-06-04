"""One-time LinkedIn session priming.

Submits the login (which sends a device-approval notification to the user's
LinkedIn app), then waits for them to tap "Yes". On success the cookies persist
in the on-disk browser session so future headless daily runs need no login.
"""
import sys
from pathlib import Path

sys.path.insert(0, "/opt/reachly")
from reachly.config import AgentConfig  # noqa: E402
from reachly.models import Platform  # noqa: E402
from reachly.platforms.browser import persistent_page  # noqa: E402
from reachly.platforms.linkedin import LinkedInBrowserPoster  # noqa: E402

cfg = AgentConfig.from_env_file("/opt/reachly/.env")
creds = cfg.platforms[Platform.linkedin]
poster = LinkedInBrowserPoster(creds, data_dir=cfg.data_dir)

with persistent_page("linkedin", cfg.data_dir, headless=True) as page:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    if poster._is_logged_in(page):
        print("ALREADY_LOGGED_IN")
    else:
        ok = poster._login(page, wait_for_approval=200)
        print("LOGIN_OK:", ok, "url:", page.url)
        if ok:
            # land on feed to solidify the session
            page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            print("FEED_OK:", "/feed" in page.url)
