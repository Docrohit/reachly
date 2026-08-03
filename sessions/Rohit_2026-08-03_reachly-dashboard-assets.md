# Session: Reachly dashboard asset library

**Date:** 2026-08-03
**Commit:** `2ce29e3` (`Add Reachly dashboard asset library`)

## What Changed

- Added a single-tenant dashboard Creative assets panel for recent image/video assets.
- Added 24h/48h filters, individual media preview/download routes, and a ZIP download route.
- Stored the exact platform-rendered post text in `history.db` as `post_text` for copy reuse.
- Kept cleanup-compatible behavior: if a media file has already been removed, the dashboard keeps text visible and disables local download.

## Verification

- Local:
  - `.venv/bin/python -m pytest tests -q` -> 67 passed, 1 subtest passed.
  - `.venv/bin/python -m py_compile reachly/storage.py reachly/agent.py reachly/dashboard/app.py`.
  - `git diff --check`.
- Server:
  - Deployed to isolated self-host target `/opt/reachly`.
  - Restarted only `reachly-agent.service` and `reachly-dashboard.service`.
  - `http://127.0.0.1:8765/healthz` returned 200.
  - Authenticated dashboard render for `/?assets=24` returned 200.
  - 24h live asset library showed 6 assets: 4 images, 2 videos, all with files available.
  - Individual media route and 24h ZIP route both returned 200.

## Access Note

The single-tenant dashboard is running on port 8765 but is not publicly routed through DNS right now. A local SSH tunnel was started on this Mac for immediate access at `http://127.0.0.1:8765/?assets=24`. Use the existing `REACHLY_DASHBOARD_TOKEN` to sign in; do not paste it into chat or commit it.
