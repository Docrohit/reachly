# Session: Email-code sign-in and client access

**Developer:** Claude
**Date:** 2026-10-19
**Quality Review:** Issues fixed

## What We Worked On

Email-code sign-in for the owner (linked to the existing Telegram account) and invited clients who
see only their own project. Channels connection routes now accept either the owner or that project's
client; OAuth state is bound to whoever started the flow.

## What Changed

| Area | Change | Layer |
| --- | --- | --- |
| Sign-in | `/auth/email/start` and `/auth/email/verify`; codes HMAC-hashed, 10 minutes, 5 attempts, 5/hour | `server/accounts.py` |
| Owner email | `/account/email` link and confirm with a code | `server/accounts.py` |
| Clients | Invite/remove per project, `/client` portal, approve or ask for changes; changes hold drafts back from autopilot | `server/accounts.py`, `server/channels.py` |
| Channels | Connect/callback/pick/disconnect use an owner-or-client actor; project cards show reviews and clients | `server/channels.py`, templates |
| Config | `REACHLY_SMTP_*` | `server/settings.py`, `docs/CHANNELS.md` |

## Verification

- Full suite 233 passed (7 new in `tests/test_accounts.py`); compileall; `git diff --check`.
- Login and client portal rendered with sample data. Email sending mocked; no real email sent.

## Deploy Notes

New tables are created at startup. Set `REACHLY_SMTP_*` from the Council Gmail app password. Deploy
with the release archive as before. Meta app is unpublished: clients need a Tester role (or make the
owner a Page admin) before they can connect Facebook.
