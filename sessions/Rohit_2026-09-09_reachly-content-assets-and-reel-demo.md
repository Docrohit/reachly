# Session: Reachly content assets and Hyclinic demo reels

**Date:** 2026-09-09
**Scope:** Reachly SaaS dashboard content visibility, Hyclinic demo asset generation, and short-video audio handling.

## What Changed

- Added the hosted dashboard Content page at `/dashboard/assets`.
- Added media preview/download routes for generated image/video assets.
- Added a ZIP download route for recent generated assets.
- Added Content navigation from the main dashboard shell.
- Opened per-user history databases in immutable read-only mode for Content pages, so
  root-owned demo history files cannot trigger SQLite write/checkpoint errors
  during asset browsing.
- Updated dry-run publishing so generated image/video media and post copy are recorded in `history.db`; dry-run dashboard generations now appear in Content.
- Updated fresh short-video reference image prompts to be business-generic and people-free for clinic/service demos.
- Changed short-video voiceover default to off. Seedance clips now stay silent unless `REACHLY_VIDEO_VOICEOVER=yes` is explicitly configured.
- Preserved long-form narration behavior separately; this change is for short/fresh Seedance videos.

## Server Notes

- Emergency server hotpatches were made to `/opt/reachly-saas` during demo recovery.
- Local repo files and server files were reconciled afterward for:
  - `reachly/agent.py`
  - `reachly/config.py`
  - `server/app.py`
  - `server/templates/base.html`
  - `server/templates/dashboard.html`
  - `server/templates/assets.html`
- `reachly-saas` was restarted and returned `active`.

## Demo Assets

Local demo download folder:

- `/Users/rohitsharma/Desktop/Hyclinic_Demo_Assets/`

Downloaded/generated files:

- `bs_post_1_dental_checkup.png`
- `bs_post_2_whitening_myths.png`
- `bs_post_3_kids_dentistry.png`
- `bs_still_1_clinic.png`
- `bs_still_2_services.png`
- `bs_still_3_closing.png`
- `bs_reel_clip1_voiced.mp4`
- `bs_reel_clip1_MUTED.mp4`
- `bs_reel_clip2_voiced.mp4`
- `bs_reel_clip2_MUTED.mp4`

The muted reel files were verified with `ffprobe`: both are 30.04s vertical MP4 files with zero audio streams.

## Verification

- `.venv/bin/python -m compileall reachly server tests` passed.
- `PYTHONPATH=. .venv/bin/python -m pytest tests/test_video_voiceover.py tests/test_dashboard_assets.py tests/test_server_productization.py -q` passed: 25 passed.
- `git diff --check` passed.
- Server-side asset query over `/opt/reachly-saas/agents/user_*/history.db` showed:
  - `rohitsharma@hygaar.com`: existing Content assets present.
  - `ritikayadav@hygaar.com`: one dry-run image asset present.
  - `gurmeet.bindra@hygaar.com`: one dry-run image asset present.
  - `rohit.sharma@hygaar.com`: one dry-run image asset present.

## Operational Notes

- Use the muted reel exports for external sharing. The voiced exports contain the old ecommerce-oriented narration and should not be sent for the clinic demo.
- Reachly remains a separate app from Hygaar Django/console. Do not move these changes into `hdb_backend`.
- The configured `Hygaar/reachly` remote was not reachable from this machine during the session; `Docrohit/reachly` was reachable.
