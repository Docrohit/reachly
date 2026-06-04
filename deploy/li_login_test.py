"""Validate LinkedIn login + 'post as Hygaar Page' WITHOUT publishing."""
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
post_as = (creds.extra or {}).get("post_as", "")

shot = Path(cfg.data_dir) / "li_login_test.png"

with persistent_page("linkedin", cfg.data_dir, headless=True) as page:
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    logged_in = "/feed" in page.url
    if not logged_in:
        logged_in = poster._login(page)
        page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        logged_in = "/feed" in page.url

    print("LOGGED_IN:", logged_in, "url:", page.url)
    page_ok = None
    if logged_in:
        start = page.get_by_role("button", name="Start a post")
        start.wait_for(timeout=15000)
        start.click()
        page.wait_for_timeout(1500)
        if post_as:
            page_ok = poster._select_post_as(page, post_as)
        page.screenshot(path=str(shot))
        print("POST_AS:", post_as, "SELECTED_OK:", page_ok)
    print("screenshot:", shot)
print("DONE (nothing was published)")
