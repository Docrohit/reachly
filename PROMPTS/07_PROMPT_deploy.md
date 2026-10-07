# Prompt 7: Personal Reachly Deploy

```markdown
Prepare a release of personal Reachly.

1. Read AGENTS.md, docs/PERSONAL_REACHLY_STATUS.md, and docs/RELEASE_RUNBOOK.md.
2. Verify the personal remote, source revision, Git status, and relevant tests.
3. Resolve the documented login, branding, and deployment separation gaps.
4. Establish the personal host, domain, install path, service names, runtime
   data locations, credentials, and rollback revision. Old scripts are templates,
   not evidence of the correct target.
5. Make the proposed deployment concrete and reviewable. Deploy only with user
   authorization for that personal target; do not reuse other accounts/services.
6. Preserve runtime data and restart only the selected personal services.
7. Verify deployed revision, service state, logs, health endpoint, and actual
   onboarding flow. Publishing acceptance is a separate authorized check.
8. Record evidence, skipped checks, and rollback details in sessions/.

The current GitHub workflow runs tests only; it does not deploy.
```
