# Personal Reachly Release Runbook

Repository: `Docrohit/reachly`. Current CI runs tests only, with no deployment job.
Verified personal target: `reachly.nftforger.com`, `/opt/reachly-saas`,
`reachly-saas` on the personal VPS. Secrets remain outside Git.

## Before release

Read `AGENTS.md` and `docs/PERSONAL_REACHLY_STATUS.md`. Check independent hosted login, personal branding, workspace isolation, and
deployment defaults.
Review the copied snapshot against personal main, including removed features.

Run from the repo root:

```bash
.venv/bin/python -m compileall -q reachly server tests
PYTHONPATH=. .venv/bin/python -m pytest tests -q
git diff --check
```

Inspect staged files for credentials, browser sessions, runtime databases, and
accidental environment files. Never print secret values in review output.

## Personal deployment plan

Choose and verify a personal host, domain, install directory, service names,
secret storage, data directories, backup, and rollback revision. Active install scripts target the personal domain. Archived proxy files are
historical; never use them for a personal release.
Neither historical service names nor a health response from an old domain prove
that the new personal release is running there.

Use `python -m server.preflight` only with the intended personal environment.
Configure production session and vault secrets, database, personal public URL,
authentication and billing explicitly. Keep platform modes off and dry-run on
until live posting is authorized for the selected account.

Use a reviewed release archive of the tested Git revision, a private code/config
backup, and a SQLite backup before changing this personal installation. Preserve
the service environment and all runtime directories. Write the commit SHA into
`REVISION`; `/healthz` reports it. Verify it after restart.

Implement a deployment workflow for the personal target before enabling
automatic releases from CI. A push to main currently runs tests only. Do not copy old
remote-switching commands, account provisioning, nginx reloads, or server targets.

## Release and acceptance

With authorization for the concrete deployment, release the tested revision and
preserve `.env`, data, credentials, browser state, generated media, and databases.
Verify the served revision, service logs, health response, personal sign-in,
dashboard, and credential save/load. Record each check separately.

If needed, roll back to the documented good revision using the same personal
deployment path and repeat acceptance checks. Record the outcome in `sessions/`.
