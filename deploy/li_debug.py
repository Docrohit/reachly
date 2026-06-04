"""Diagnostic: what does the server's headless browser see at LinkedIn login?"""
import sys
from pathlib import Path

sys.path.insert(0, "/opt/reachly")
from reachly.platforms.browser import persistent_page  # noqa: E402

data_dir = Path("/opt/reachly/.reachly_data")
shot = data_dir / "li_debug.png"

with persistent_page("linkedin", data_dir, headless=True) as page:
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    page.screenshot(path=str(shot), full_page=False)
    has_user = page.locator("#username").count()
    body = (page.content() or "").lower()
    flags = [w for w in ("checkpoint", "verify", "unusual", "captcha", "puzzle",
                          "let's do a quick", "security check", "try again")
             if w in body]
    print("URL:", page.url)
    print("TITLE:", page.title())
    print("#username present:", bool(has_user))
    print("input count:", page.locator("input").count())
    print("flags:", flags)
    print("screenshot:", shot)
