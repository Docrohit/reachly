# Session: Medium deploy for Hygaar Reachly

Date: 2026-07-08

## Scope

- Deployed Reachly source to the isolated Hygaar self-hosted install at `/opt/reachly`.
- Preserved server `.env`, `.reachly_data`, browser sessions, and virtualenv.
- Restarted only `reachly-agent`; `reachly-dashboard` was left running.

## Medium Configuration

- `MEDIUM_MODE=browser`
- `MEDIUM_EMAIL=rohitsharma@hygaar.com`
- `MEDIUM_TIMES=09:30,14:30,19:30`
- `MEDIUM_PUBLISH_STATUS=public`
- `MEDIUM_EXPECTED_ACCOUNT=Rohit Sharma`
- `MEDIUM_IMAGE_ASPECT_RATIO=16:9`

## Verification

- Local checks passed:
  - `python3 -m compileall reachly server tests`
  - `python3 -m pytest tests -q`
- Server checks:
  - `reachly-agent` active after restart.
  - `reachly-dashboard` active.
  - Scheduler log confirmed Medium jobs at `09:30,14:30,19:30` Asia/Kolkata.
  - Server compile check passed with the deployed venv.

## Open Runtime Blocker

The server Playwright Medium session is not logged in yet. A non-publishing smoke
check returned:

- `medium_enabled=True`
- `medium_mode=browser`
- `needs_login=True`
- `account_match=False`
- `title_editor=False`

Scheduled Medium jobs are registered, but the first Medium publish will fail
with login required until the server browser session is primed for the expected
Medium account.

## Notes

- No Hygaar Django services or CodeDeploy paths were touched.
- No credentials or tokens were added to git.
