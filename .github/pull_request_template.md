## Summary

-

## Scope

- [ ] Standalone agent
- [ ] Hosted SaaS
- [ ] Platform posting
- [ ] Deploy/infra
- [ ] Docs only

## Safety Checks

- [ ] No `.env`, browser sessions, tokens, passwords, API keys, or deploy keys committed
- [ ] No Hygaar Django or console code changed unless explicitly approved
- [ ] Platform live-posting behavior was kept in dry-run or explicitly verified
- [ ] Runtime data is preserved by deploy changes (`.env`, `.venv`, `.reachly_data`, `reachly_media`, `*.db`)

## Verification

- [ ] `python -m compileall reachly server tests`
- [ ] `pytest tests -q`
- [ ] `git diff --check`
- [ ] Workflow YAML parses
- [ ] Relevant manual/browser verification completed or documented

## Deploy Notes

- Target service:
- Target domain:
- Required secrets/env changes:
- Rollback notes:
