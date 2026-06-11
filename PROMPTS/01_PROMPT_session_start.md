# Prompt 1: Reachly Session Start

Copy-paste into an AI coding agent at the start of every Reachly session:

```markdown
We are working on Reachly.

Before doing anything:

1. Read `AGENTS.md`.
2. Read `product_theory.md`.
3. Read `business_goals.md`.
4. Read the latest file in `sessions/`.
5. Check `git status --short`.
6. Summarize:
   - current product goal
   - current deploy locations
   - platform status for LinkedIn, Instagram, X
   - what is safe to change
   - what must not be changed

Rules:

- Do not commit secrets or `.env`.
- Do not modify Hygaar Django code unless explicitly requested.
- Keep Reachly deploys isolated to Reachly paths/services.
- For browser posting changes, verify with real page state or debug artifacts.
- If posting live content, confirm platform/account first.
- **Always create a branch from the latest deploy branch** (e.g., `main` or `dev-env`). NEVER branch from another feature branch — it drags in unmerged commits from other work and causes spurious conflicts. Push your branch + raise a PR; never push directly to shared env branches.
```
