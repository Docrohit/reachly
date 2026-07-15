# Session: Reachly Hygaar productization deploy

**Developer:** Rohit / Codex
**Date:** 2026-07-15
**Time:** 16:25 IST
**Quality Review:** Passed

## What We Worked On

- Reviewed Reachly's personal-project lineage, existing self-host history, and
  Hygaar acquisition/productization requirements.
- Kept Reachly as a separate app/repository while wiring it to Hygaar console
  login.
- Built and documented the hosted Reachly SaaS path with dashboard, profile,
  billing, encrypted credential vault support, schedule slots, and platform
  mode settings.
- Created the private `Hygaar/reachly` GitHub repository and pushed the
  productized code.
- Added GitHub Actions CI/CD, including bastion/VPN SSH support for private
  Hygaar infrastructure.
- Prepared production server-local config outside git and deployed the hosted
  `reachly-saas` service through GitHub Actions.
- Verified `reachly.hygaar.com` serves the new Hygaar-backed Reachly app.

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| `server/hygaar_auth.py` | Added Hygaar login bridge and user metadata mapping. | Let approved Hygaar console users sign in to Reachly without merging apps. | SaaS auth |
| `server/app.py` | Added Hygaar login route plus profile and billing routes. | Provide hosted product flows required for acquisition. | SaaS HTTP |
| `server/db.py` | Added fields for Hygaar user mapping, billing state, schedule slots, and encrypted credential storage. | Support multi-tenant hosted Reachly accounts. | Storage |
| `server/orchestrator.py` | Added hosted scheduler/platform credential wiring. | Let the dashboard configure posting behavior per Reachly user. | SaaS orchestration |
| `reachly/platforms/linkedin.py` | Added LinkedIn API organization posting support. | Prefer official APIs for company/page publishing when credentials are available. | Platform |
| `reachly/platforms/medium.py` | Added Medium browser integration coverage and tests. | Keep Medium available while no reliable official API path is selected. | Platform |
| `server/preflight.py` | Added non-secret environment and Hygaar auth smoke checks. | Make hosted deployment verification repeatable. | Ops |
| `.github/workflows/deploy.yml` | Added CI, manual deploy, private-host bastion support, service restart, nginx vhost install, and smoke test. | Deploy Reachly through GitHub Actions instead of manual server edits. | CI/CD |
| `deploy/nginx/reachly.hygaar.com.conf` | Added hosted Reachly nginx vhost for `reachly.hygaar.com`. | Route public Reachly traffic to the SaaS app service. | Ops |
| `deploy/reachly-saas.service` | Added systemd unit for hosted SaaS service. | Run Reachly independently from Hygaar Django and legacy self-host units. | Ops |
| `docs/HYGAAR_PRODUCTIZATION.md` | Documented architecture, auth, platform strategy, deploy secrets, and DNS target. | Create durable productization reference. | Docs |
| `docs/HYGAAR_ACQUISITION_AUDIT.md` | Documented lineage, self-host evidence, acquisition fit, and risk register. | Preserve acquisition/ownership review evidence. | Docs |
| `docs/RELEASE_RUNBOOK.md` | Added release checks, GitHub setup, deployment, verification, and rollback path. | Give future sessions a safe deploy playbook. | Docs |
| Tests | Added route, preflight, LinkedIn API, and Medium coverage. | Guard the new hosted product behavior. | Verification |

## Verification

- Local checks passed:
  - `python -m compileall reachly server tests`
  - `PYTHONPATH=. python -m pytest tests -q`
  - `git diff --check`
  - GitHub workflow YAML parse
  - secret-pattern scan excluding generated/local-only directories
- Test result: `38 passed`, `1 subtest passed`.
- GitHub Actions:
  - Push CI succeeded for `Support bastion Reachly deployments`.
  - Manual production deploy workflow succeeded.
  - Deploy workflow smoke test succeeded against the hosted app service.
- Server/public checks:
  - `reachly-saas` is active and enabled.
  - nginx config test passed.
  - `https://reachly.hygaar.com/healthz` returns `{"ok": true}`.
  - `https://reachly.hygaar.com/login` serves the new Hygaar-backed Reachly
    login page.
  - Form-login smoke test with the approved Hygaar account redirected
    successfully and `/dashboard` returned `200`.

## Deploy State

- Personal SaaS:
  - The old personal source directory is no longer the active source of truth.
  - Current source of truth is the private `Hygaar/reachly` repository.
- Hygaar self-hosted:
  - Legacy self-host units remain separate from hosted SaaS.
  - The hosted product now runs as `reachly-saas` and is served at
    `https://reachly.hygaar.com`.
- Platform status:
  - LinkedIn supports API mode, including organization posting, plus browser
    fallback.
  - Instagram and X still support browser/API-oriented configuration depending
    on available credentials.
  - Medium remains browser-mode oriented for now.
  - Hosted dashboard exposes platform credential/mode setup; production
    platform credentials still need to be entered by the account owner before
    live posting.

## Risks / Follow-ups

- Rotate any GitHub personal access token shared in chat; it was used only
  ephemerally but should still be considered exposed.
- Production billing copy/page exists, but real Stripe/Razorpay activation is
  still a follow-up before charging customers.
- Platform posting should remain disabled or credential-gated until official
  API credentials/browser sessions are entered and a controlled live-post smoke
  test is approved.
- GitHub Actions currently reports a Node runtime deprecation annotation from
  upstream actions; the workflow still passes.
- Keep Reachly deployments independent from Hygaar Django/console deploys.

## Next Session Start Here

- Open `docs/HYGAAR_PRODUCTIZATION.md` and `docs/RELEASE_RUNBOOK.md`.
- Confirm latest GitHub Actions run for `Hygaar/reachly` is still green.
- Verify `https://reachly.hygaar.com/healthz` before any new work.
- For platform onboarding, sign in to Reachly with the approved Hygaar account,
  enter platform credentials through the dashboard, keep modes conservative,
  then run one controlled smoke test per platform.
- For billing, connect real payment provider credentials through environment
  variables/server secret management, then test checkout/webhook behavior before
  enabling paid access.
