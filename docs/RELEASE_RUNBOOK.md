# Reachly Release Runbook

Status: draft for Hygaar-owned repository

## Release Rule

Reachly deploys independently from Hygaar Django and the React console. Do not
modify CodeDeploy, hdb backend services, or console build/deploy paths for a
Reachly release.

## Pre-Release Checks

Run from the Reachly repo root:

```bash
python -m compileall reachly server tests
PYTHONPATH=. python -m pytest tests -q
git diff --check
ruby -e "require 'yaml'; YAML.load_file('.github/workflows/deploy.yml'); puts 'workflow_yaml_ok'"
bash -n deploy/install_saas_on_server.sh
```

For hosted production environment checks, run:

```bash
python -m server.preflight
```

To verify the live Hygaar auth bridge without printing tokens or passwords, set
credentials in the shell environment and run:

```bash
REACHLY_PREFLIGHT_HYGAAR_EMAIL="..." \
REACHLY_PREFLIGHT_HYGAAR_PASSWORD="..." \
python -m server.preflight --hygaar-auth
```

Run a secret-oriented scan before the first Hygaar-owned push:

```bash
rg -n "AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|EC|DSA) PRIVATE KEY|xox[baprs]-|ghp_[A-Za-z0-9_]{30,}|AIza[0-9A-Za-z_-]{35}" . \
  --glob '!*.pyc' \
  --glob '!__pycache__/**' \
  --glob '!.venv/**' \
  --glob '!*.png'
```

Also inspect staged files manually for:

- Hygaar account passwords
- platform passwords
- OAuth tokens
- `REACHLY_VAULT_KEY`
- `REACHLY_SESSION_SECRET`
- browser session state
- SQLite databases

## First Hygaar Repository Setup

After `Hygaar/reachly` exists and access is granted:

```bash
git remote set-url origin git@github.com:Hygaar/reachly.git
git push -u origin main
```

Required GitHub Actions production secrets:

| Secret | Required | Meaning |
|---|---|---|
| `REACHLY_DEPLOY_HOST` | yes | EC2 host or DNS name reachable over SSH |
| `REACHLY_DEPLOY_USER` | yes | SSH user; workflow defaults empty value to `ubuntu` |
| `REACHLY_DEPLOY_SSH_KEY` | yes | Private deploy key with server access |
| `REACHLY_DEPLOY_PATH` | no | Defaults to `/opt/reachly-saas` |

## Server Prerequisites

The production server must have a Reachly `.env` outside git at:

```text
/opt/reachly-saas/.env
```

Minimum required production values:

```env
REACHLY_ENVIRONMENT=production
REACHLY_FREE_MODE=false
REACHLY_SESSION_SECRET=...
REACHLY_VAULT_KEY=...
REACHLY_DATABASE_URL=...
REACHLY_PUBLIC_BASE_URL=https://reachly.hygaar.com
REACHLY_HYGAAR_API_BASE_URL=https://genai.hygaar.com
REACHLY_HYGAAR_LOGIN_PATH=/auth/login/
REACHLY_TELEGRAM_LOGIN_ENABLED=false
```

Use `REACHLY_HYGAAR_PRO_EMAILS` only as a temporary manual activation path
until billing is fully connected.

## Deploy

Deployment should happen through GitHub Actions after production secrets exist:

1. Push to `main` after review approval.
2. Confirm the push-triggered `test` job passes.
3. Run the `Reachly CI/CD` workflow manually with `deploy=true`.
4. Confirm the `deploy` job restarts `reachly-saas`.
5. Confirm the workflow smoke test passes.

Do not manually edit files on the server. If emergency rollback is required,
deploy the last known good commit through the same workflow.

## Post-Deploy Verification

Read-only checks:

```bash
curl -fsS https://reachly.hygaar.com/healthz
curl -fsS http://127.0.0.1:8050/healthz
```

Hosted app preflight:

```bash
python -m server.preflight
```

Server checks through the deploy channel:

```bash
systemctl is-active reachly-saas
journalctl -u reachly-saas -n 100 --no-pager
```

Browser checks:

1. Open `https://reachly.hygaar.com/login`.
2. Sign in with an approved Hygaar console account.
3. Verify `/dashboard` renders schedule and platform credential sections.
4. Verify `/profile` shows the Hygaar email/account mapping.
5. Verify `/billing` renders Reachly Pro billing copy.
6. Save one platform in `off` mode to verify encrypted vault writes without
   live posting.

## Rollback

Preferred rollback:

1. Revert or select the last known good commit.
2. Push to `main`.
3. Let GitHub Actions redeploy.
4. Re-run post-deploy checks.

Manual server mutation is not part of the normal rollback path.
