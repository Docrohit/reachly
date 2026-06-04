"""Debug Instagram browser login — submit creds, dump resulting page state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reachly.config import AgentConfig
from reachly.platforms.browser import persistent_page


def main() -> int:
    cfg = AgentConfig.from_env_file(".env")
    from reachly.models import Platform

    ig = cfg.platforms[Platform.instagram]
    out = cfg.data_dir / "ig_debug.png"

    with persistent_page("instagram", cfg.data_dir) as page:
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        page.wait_for_timeout(5000)
        print("home URL:", page.url)
        print("pw fields:", page.locator("input[type='password']").count())

        user = page.locator("input[name='email'], input[name='username']").first
        pw = page.locator("input[name='pass'], input[name='password']").first
        user.fill(ig.username or "")
        pw.fill(ig.password or "")
        print("filled username:", ig.username)

        # Buttons available
        for sel in ("div[role='button']", "button"):
            els = page.locator(sel).all()
            for e in els[:12]:
                t = (e.inner_text() or "").strip()[:30]
                if t:
                    print(f"  {sel}: {t!r} visible={e.is_visible()}")

        pw.press("Enter")
        page.wait_for_timeout(13000)

        print("post-submit URL:", page.url)
        print("title:", page.title())
        body = page.locator("body").inner_text()[:900]
        print("body snippet:", repr(body))
        page.screenshot(path=str(out), full_page=False)
        print("screenshot:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
