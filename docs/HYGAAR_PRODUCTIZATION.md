# Reachly Hygaar Productization

Status: in progress
Owner: Hygaar

See `docs/HYGAAR_ACQUISITION_AUDIT.md` for the evidence log covering personal
project lineage, self-host deployment history, platform status, and remaining
external GitHub/AWS setup.

## Decision

Reachly remains a separate application and repository. Hygaar account login is
used as the identity provider, but Reachly keeps its own database for:

- Reachly profile and business context
- publishing schedules
- encrypted AI/provider keys
- encrypted platform credentials
- posting logs and health state
- Reachly billing/subscription state

The hosted scheduler mirrors the Hygaar self-hosted pilot:

- LinkedIn/X primary slots come from `User.post_times`
- Instagram runs at `post_times + instagram_offset_minutes`
- Medium runs from `User.medium_times`
- Manual dashboard runs still use the all-enabled `run_once` path

Do not move Reachly into `hdb_backend` or the React console repo. It may call
Hygaar APIs, and it may authenticate against Hygaar, but deploys independently.

## Source Lineage

Reachly began as a personal product prototype. The old
`~/Desktop/M2026/Personal/reachly` directory is no longer present locally; the
June 2026 session notes record that it was copied into
`hdb_oct17/reachly/` and the duplicate personal copy was removed.

The self-hosted Hygaar pilot runs separately from Hygaar Django under
`/opt/reachly` with `reachly-agent` and `reachly-dashboard`. The acquired hosted
product target is `/opt/reachly-saas` with `reachly-saas`.

## Authentication

Hosted Reachly uses Hygaar console credentials:

1. User submits email/password on Reachly.
2. Reachly calls Hygaar backend `auth/login/`.
3. Hygaar returns JWTs and user metadata.
4. Reachly maps `Account.user_id` into `User.hygaar_user_id`.
5. Reachly stores its own session and profile data.

Secrets are not committed. Hygaar passwords, platform passwords, API keys, and
browser sessions stay in environment variables, encrypted vault fields, or
server-local data directories.

## Platform Strategy

Preferred mode is official API where available:

| Platform | Preferred | Fallback |
|---|---|---|
| Instagram | Graph API with public media URL | Playwright browser |
| X / Twitter | OAuth API | Playwright browser |
| LinkedIn | API, especially org posting when approved | Playwright browser |
| Medium | Browser today | API only after a reliable supported path exists |

The dashboard exposes mode selection per platform.

## Deployment

GitHub Actions workflow: `.github/workflows/deploy.yml`

Required GitHub repository secrets:

| Secret | Meaning |
|---|---|
| `REACHLY_DEPLOY_HOST` | EC2 host or DNS name reachable over SSH |
| `REACHLY_DEPLOY_USER` | SSH user, defaults to `ubuntu` when blank |
| `REACHLY_DEPLOY_SSH_KEY` | private deploy key with server access |
| `REACHLY_DEPLOY_PATH` | optional target path, defaults to `/opt/reachly-saas` |
| `REACHLY_BASTION_HOST` | optional bastion/VPN host for private deploy hosts |
| `REACHLY_BASTION_USER` | optional bastion SSH user, defaults to `ubuntu` |
| `REACHLY_BASTION_SSH_KEY` | private bastion key, required only with bastion host |

Server `.env` must already exist at the deploy path and must contain production
secrets such as:

- `REACHLY_ENVIRONMENT=production`
- `REACHLY_SESSION_SECRET`
- `REACHLY_VAULT_KEY`
- `REACHLY_DATABASE_URL`
- `REACHLY_PUBLIC_BASE_URL=https://reachly.hygaar.com`
- `REACHLY_HYGAAR_API_BASE_URL=https://genai.hygaar.com` or the chosen env
- `REACHLY_HYGAAR_PRO_EMAILS` for manually approved Hygaar accounts while
  Stripe/Razorpay billing is not connected

DNS/Route 53:

- Target subdomain: `reachly.hygaar.com`
- Point it at the selected ALB/EC2 routing layer.
- The nginx vhost is `deploy/nginx/reachly.hygaar.com.conf`.

## GitHub Repo Setup

Create or transfer the repository under the Hygaar GitHub organization:

```bash
gh repo create Hygaar/reachly --private --source=. --remote=origin
git push -u origin main
```

If the repo already exists, change the local remote:

```bash
git remote set-url origin git@github.com:Hygaar/reachly.git
git push -u origin main
```

Do not push until the working tree has been reviewed for secrets and the owner
has approved the first Hygaar-owned commit.
