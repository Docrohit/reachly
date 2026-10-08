"""Operator-assisted login for one isolated clinic browser connection.

Usage: python -m reachly.clinic_session <connection-uuid>
Run in an interactive environment using the same protected clinic session volume
as the approved-publishing worker. Complete login/2FA yourself in the browser.
"""
import json
import os
import sys
from pathlib import Path
from uuid import UUID
from .approved_publish import profile_lock
from .platforms.browser import persistent_page


def main():
    connection_id = str(UUID(sys.argv[1]))
    bindings = json.loads(Path(os.environ["REACHLY_CLINIC_BINDINGS"]).read_text())
    binding = bindings[connection_id]
    platform = binding["platform"]
    if platform not in {"instagram", "facebook"}:
        raise ValueError("Unsupported clinic browser platform")
    root = Path(os.environ["REACHLY_CLINIC_DATA"]) / connection_id
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with profile_lock(root / "publish.lock"):
        with persistent_page(platform, root, headless=False) as page:
            page.goto("https://www.instagram.com/" if platform == "instagram" else "https://www.facebook.com/", wait_until="domcontentloaded")
            input("Complete login and select the intended clinic identity in the browser. Press Enter to close the session. ")


if __name__ == "__main__":
    main()
