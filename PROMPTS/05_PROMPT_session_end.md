# Prompt 5: Reachly Session End

Copy-paste into an AI coding agent before closing a Reachly session:

```markdown
We are ending this Reachly session. Do these steps in order.

## 1. Quality Review

Review every changed file from `git diff`.

Check:

- No secrets, passwords, tokens, IPs, or private server details were committed.
- Browser-mode failures log clear errors and create debug artifacts.
- No broad exception silently hides platform failure.
- Scheduler changes do not duplicate posts unexpectedly.
- Platform changes do not affect unrelated platforms.
- Dashboard/SaaS changes keep Telegram OTP and credential vault behavior intact.

Fix issues before documenting.

## 2. Verification

Run relevant checks:

- `python -m compileall reachly server tests`
- targeted unit tests if touched
- if deployed, check service status and recent logs
- if posting, verify actual platform page/date, not only internal "ok"

## 3. Session Note

Create `sessions/[Name]_[YYYY-MM-DD]_[HHMM]_[brief-title].md`.

Use this template:

# Session: [brief title]

**Developer:** [name]
**Date:** [YYYY-MM-DD]
**Time:** [HH:MM]
**Quality Review:** Passed / Issues fixed

## What We Worked On
- ...

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|

## Verification
- ...

## Deploy State
- Personal SaaS:
- Hygaar self-hosted:
- Platform status:

## Risks / Follow-ups
- ...

## Next Session Start Here
- ...

## 4. Git

If changes should be preserved:

- `git status --short`
- `git add ...`
- `git commit -m "..."`
- `git push`

## 5. Handoff

Tell the user:

- what was completed
- what is deployed where
- what failed or is blocked
- what to monitor next
```
