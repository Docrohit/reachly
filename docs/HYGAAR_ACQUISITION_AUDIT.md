# Reachly Hygaar Acquisition Audit

Status: in progress
Last verified: 2026-07-15

## Scope

This document records the current evidence for acquiring Reachly into Hygaar as
a separate product and repository. It is intentionally separate from Hygaar
Django/React docs because Reachly deploys and operates independently.

## Proven Lineage

| Claim | Evidence in this repo | Status |
|---|---|---|
| Reachly started as Rohit's personal project | `sessions/Rohit_2026-06-02_reachly-build-deploy.md` records that Reachly was copied into `hdb_oct17/reachly/` and the duplicate personal copy was removed from `~/Desktop/Personal/reachly`. | Proven by session docs; original local folder is no longer present. |
| Reachly has its own code and docs | `AGENTS.md`, `product_theory.md`, `business_goals.md`, `README.md`, `PROMPTS/`, `sessions/`, `reachly/`, `server/`, and `deploy/`. | Present locally. |
| Reachly was self-hosted on the Hygaar server | June session docs record isolated deploy under `/opt/reachly` with `reachly-agent` and `reachly-dashboard`. | Proven by session docs and deploy units. |
| Reachly later got a dashboard | `reachly/dashboard/`, `deploy/reachly-dashboard.service`, and session docs record the Hygaar dashboard for goals, schedule, strategy preview, and run-now. | Present. |
| Current hosted product is separate from Hygaar Django | `server/` is a FastAPI app; deploy target is `/opt/reachly-saas` with `reachly-saas`. | Implemented locally. |

## Architecture Decision

Reachly remains a standalone app and repository owned by Hygaar:

- It may authenticate against Hygaar via `auth/login/`.
- It may call Hygaar media APIs when configured.
- It does not import or modify Hygaar Django or console code.
- It stores Reachly profile, schedule, platform credentials, billing state, and
  logs in its own database.
- Hosted users are keyed by Hygaar `Account.user_id` in
  `server.db.User.hygaar_user_id`.

## Platform Posting Status

| Platform | API status | Browser status | Dashboard credential support |
|---|---|---|---|
| LinkedIn | Implemented via Posts API. Personal author uses `person_urn` or `/userinfo`; company pages use `organization_id` / `urn:li:organization:*`. | Implemented with feed composer, company page name, and company admin URL fallback. | Access token, person URN, organization ID, company page name, company admin URL, email/password. |
| X / Twitter | Implemented with OAuth2 user token or OAuth1 credentials; v2 media upload is covered by tests. | Implemented with Playwright login/composer; supports checkpoint login identifier. | OAuth2 token, OAuth1 consumer/access credentials, username/password, checkpoint identifier. |
| Instagram | Implemented with Instagram Graph API using access token, IG user id, and public media URL. | Implemented with Playwright create flow. | Access token, IG user id, username/password. |
| Medium | Browser mode implemented for long-form draft/public articles with required 16:9 image. | Implemented with Playwright persistent session. | Email/password, publish status, expected account guard. API mode is intentionally rejected until a reliable supported Medium publishing API path is approved. |

## Productization Work Completed Locally

- Hygaar login bridge: `server/hygaar_auth.py`.
- Hosted login route: `POST /auth/hygaar/login`.
- Hosted pages: `/dashboard`, `/profile`, `/billing`.
- Per-user credential vault for API/browser credentials.
- Per-user schedules for LinkedIn/X, Instagram offset, and Medium slots.
- GitHub Actions CI/CD workflow: `.github/workflows/deploy.yml`.
- Hosted nginx vhost: `deploy/nginx/reachly.hygaar.com.conf`.
- Hosted systemd service: `deploy/reachly-saas.service`.
- Hosted install script: `deploy/install_saas_on_server.sh`.
- Hosted preflight utility: `python -m server.preflight`.
- Acquisition architecture doc: `docs/HYGAAR_PRODUCTIZATION.md`.
- Release runbook: `docs/RELEASE_RUNBOOK.md`.
- GitHub PR template: `.github/pull_request_template.md`.

## Current Verification Commands

Run from the Reachly repo root:

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python -m compileall reachly server tests
git diff --check
ruby -e "require 'yaml'; YAML.load_file('.github/workflows/deploy.yml'); puts 'workflow_yaml_ok'"
bash -n deploy/install_saas_on_server.sh
```

Latest local result:

- 36 tests passed, plus 1 subtest passed.
- Compile passed.
- Whitespace check passed.
- Workflow YAML parse passed.
- Install script syntax check passed.

## Live Deployment Status

Read-only checks on 2026-07-15:

- `https://reachly.hygaar.com/healthz` returns `HTTP 200` and `{"ok":true}`.
- `https://reachly.hygaar.com/` returns a protected sign-in page through nginx.
- The live root still serves the older deployed UI, so local productization
  changes have not yet been deployed.

No manual server edits, SSH deploys, commits, pushes, or Route 53 changes have
been performed for this acquisition work.

## GitHub / CI/CD Status

Local remote still points to the personal repository:

```bash
origin git@github.com:Docrohit/reachly.git
```

The target Hygaar repository is not currently reachable from this machine:

```bash
git ls-remote git@github.com:Hygaar/reachly.git HEAD
# Repository not found / access denied
```

The local GitHub CLI is also not authenticated:

```bash
gh auth status
# not logged into any GitHub hosts
```

The GitHub connector available in Codex can operate on existing repositories,
files, and PRs, but it does not expose repository creation in this environment.

## Required External Setup

1. Create or grant access to `Hygaar/reachly`.
2. Review the local diff for secrets before first commit.
3. Set the repository remote to `git@github.com:Hygaar/reachly.git`.
4. Push the approved initial Hygaar-owned branch.
5. Add GitHub Actions production secrets:
   - `REACHLY_DEPLOY_HOST`
   - `REACHLY_DEPLOY_USER`
   - `REACHLY_DEPLOY_SSH_KEY`
   - optional `REACHLY_DEPLOY_PATH`
6. Ensure server `.env` exists at `/opt/reachly-saas/.env` and contains
   production secrets outside git.
7. Route `reachly.hygaar.com` to the selected ALB/EC2 target.
8. Deploy through a manual GitHub Actions dispatch with `deploy=true`, then verify:
   - `systemctl is-active reachly-saas`
   - `curl -fsS http://127.0.0.1:8050/healthz`
   - `curl -fsS https://reachly.hygaar.com/healthz`
   - browser login with a Hygaar console account.

## Security Notes

- Do not commit `.env`, OAuth tokens, platform passwords, browser sessions,
  deploy keys, or Hygaar account passwords.
- The known Hygaar account password used for manual verification must remain
  outside git and outside docs.
- Browser sessions belong only on the server/local runtime data directory.
- Reachly billing state is separate from Hygaar media-generation credits.
