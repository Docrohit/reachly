# Prompt 7: Reachly Deploy

Use before deploying Reachly to a server:

```markdown
Deploy Reachly safely.

1. Read `AGENTS.md`, `product_theory.md`, `business_goals.md`.
2. Check `git status --short`.
3. Run relevant local tests.
4. Identify target:
   - Personal SaaS: `/opt/reachly-saas`, service `reachly-saas`
   - Hygaar self-hosted: `/opt/reachly`, services `reachly-agent`, `reachly-dashboard`
5. Deploy only Reachly files. Do not touch Hygaar Django services.
6. Restart only the relevant Reachly service(s).
7. Verify:
   - service active
   - web endpoint responds for SaaS/dashboard
   - `journalctl` has no immediate errors
8. Write deploy result into `sessions/`.
```
