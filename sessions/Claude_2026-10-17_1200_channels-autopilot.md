# Session: Channels dashboard, Meta/X connections and 24-hour autopilot

**Developer:** Claude
**Date:** 2026-10-17
**Quality Review:** Issues fixed

## What We Worked On

Added `/channels` (Hyclinics-inspired, personal only): each project connects its Facebook Page,
linked Instagram professional account and X account through the owner's OAuth consent, publishes
drafts to several channels, and can run a 24-hour autopilot. Created the personal Meta and X apps.
No work (Hygaar/Hyclinics) apps, IDs, secrets or accounts were used or copied.

## What Changed

| Area | Change | Layer |
| --- | --- | --- |
| Connections | Facebook Login for Business (Page token, linked Instagram), Page picker, X OAuth 2.0 PKCE with locked refresh-token rotation; single-use 15-minute owner-bound state | `server/channels.py` |
| Publishing | One attempt per draft and channel; only definite 4xx refusals retryable; X through the shared ledger; results recorded in history and PostLogRow | `server/channels.py` |
| Autopilot | Every 10 minutes; when Live is on and 24 hours passed without a post, publish the oldest waiting draft (14 days, never attempted) or generate an image post; 3-hour backoff; manual "Publish next post now" | `server/channels.py`, `server/orchestrator.py` |
| Platforms | `FacebookApiPoster` (Page photos/feed, appsecret_proof); Instagram poster adds appsecret_proof, permalink, rejection marker, Graph v25 | `reachly/platforms/` |
| UI | Project cards, channel tiles, drafts with receipts, autopilot panel, add-project form with optional AI-key copy | `server/templates/channels*.html` |
| Docs | Setup, env vars, app IDs | `docs/CHANNELS.md` |

## Verification

- `python -m compileall -q reachly server tests`, full suite 226 passed (11 new channel tests), `git diff --check`.
- Page rendered with sample data in a throwaway DB. Providers mocked; no live connection, generation or post.

## Deploy Notes

- Target: `reachly.nftforger.com`, `/opt/reachly-saas`, `reachly-saas`. Not deployed.
- New env: `REACHLY_META_APP_ID`, `REACHLY_META_APP_SECRET`, `REACHLY_META_LOGIN_CONFIG_ID`,
  `REACHLY_X_CLIENT_ID`, `REACHLY_X_CLIENT_SECRET` (secrets typed by Rohit at a hidden prompt).
- New tables are created at startup; no destructive migration. Rollback: previous revision; the new
  tables are unused by older code.
- Rohit asked for no code changes over ssh/scp; deployment needs his upload or a CI deploy job.

## Next Session Start Here

Instagram professional + linked to the Council Page; buy X credits; deploy; set env; create the
TravelSolo project; connect Council channels; enable Live; send one reviewed post per channel and
check permalinks before turning autopilot on.
