"""Headless-browser helper built on Playwright.

Each platform gets a persistent context directory so a login survives between
daily runs (cookies/localStorage are kept on disk). This keeps the agent from
re-logging-in (and tripping 2FA) every day.

Browser mode is best-effort: social sites change their DOM frequently, so the
selectors here are written defensively and every adapter degrades to a clear
error rather than crashing the whole run.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("reachly.browser")


@contextmanager
def persistent_page(profile_name: str, data_dir: Path, *, headless: bool = True):
    """Yield a Playwright Page backed by a persistent context on disk."""
    from playwright.sync_api import sync_playwright

    session_dir = Path(data_dir) / "browser_sessions" / profile_name
    session_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(session_dir),
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1366, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            yield page
        finally:
            context.close()


def save_debug_artifact(page, data_dir: Path, platform: str, label: str) -> str:
    """Persist a screenshot and tiny metadata file for browser-mode failures."""
    debug_dir = Path(data_dir) / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{platform}_{label}_{int(time.time())}"
    shot = debug_dir / f"{stem}.png"
    meta = debug_dir / f"{stem}.txt"
    try:
        page.screenshot(path=str(shot), full_page=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not save %s screenshot: %s", platform, e)
    try:
        body = ""
        try:
            body = page.locator("body").inner_text(timeout=3000)[:2000]
        except Exception:  # noqa: BLE001
            body = ""
        meta.write_text(
            f"url={page.url}\ntitle={page.title()}\n\n{body}\n",
            encoding="utf-8",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not save %s debug metadata: %s", platform, e)
    return str(shot)
