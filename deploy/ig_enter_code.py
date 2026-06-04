"""Complete Instagram email-code checkpoint for Reachly's browser session."""
from __future__ import annotations

import sys

from reachly.config import AgentConfig
from reachly.models import Platform
from reachly.platforms.browser import persistent_page


def main() -> int:
    code = sys.stdin.read().strip()
    if not code:
        print("missing code", file=sys.stderr)
        return 2

    cfg = AgentConfig.from_env_file("/opt/reachly/.env")
    creds = cfg.platforms[Platform.instagram]

    with persistent_page("instagram", cfg.data_dir, headless=True) as page:
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        body = page.locator("body").inner_text(timeout=10000)
        if "Check your email" not in body and "/auth_platform/codeentry" not in page.url:
            page.goto(
                "https://www.instagram.com/accounts/login/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            page.wait_for_timeout(3000)
            user = page.locator(
                "input[name='email'], input[name='username'], input[autocomplete='username']"
            ).first
            pw = page.locator(
                "input[name='pass'], input[name='password'], input[type='password']"
            ).first
            user.wait_for(state="visible", timeout=30000)
            user.fill(creds.username or "")
            pw.fill(creds.password or "")
            clicked = False
            for sel in ("div[role='button']:has-text('Log in')", "button:has-text('Log in')"):
                try:
                    btn = page.locator(sel).first
                    if btn.count() and btn.is_visible():
                        btn.click(timeout=5000)
                        clicked = True
                        break
                except Exception:
                    continue
            if not clicked:
                pw.press("Enter")
            page.wait_for_timeout(10000)

        code_input = page.locator(
            "input[name='verificationCode'], "
            "input[autocomplete='one-time-code'], "
            "input[aria-label*='Code'], "
            "input[type='text']"
        ).first
        code_input.wait_for(state="visible", timeout=30000)
        code_input.fill(code)

        clicked = False
        for sel in ("button:has-text('Continue')", "div[role='button']:has-text('Continue')"):
            try:
                btn = page.locator(sel).first
                if btn.count() and btn.is_visible():
                    btn.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            code_input.press("Enter")

        page.wait_for_timeout(12000)
        body = page.locator("body").inner_text(timeout=10000)[:500]
        print({"url": page.url, "title": page.title(), "body": body})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
