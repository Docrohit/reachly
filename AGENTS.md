# AGENTS.md — Personal Reachly

## Identity and ownership

Reachly is Rohit's independently owned personal product: an AI content and
publishing assistant for founders, creators, and businesses. Build it around
users' own profiles, goals, brand voice, accounts, and provider credentials.

- Canonical checkout: `/Users/rohitsharma/Desktop/M2026/Personal/reachly`.
- Personal remote: `git@github.com:Docrohit/reachly.git`.
- This repo's identity overrides older portfolio summaries and copied history.
- Do not switch to another company's repository, branding, accounts, or servers.
- Copied integrations are implementation history, not product requirements.

## Start every session

Run `PROMPTS/01_PROMPT_session_start.md`: read this file, `product_theory.md`,
`business_goals.md`, `docs/PERSONAL_REACHLY_STATUS.md`, and the latest dated
personal session note. Inspect Git status and remotes before editing.

`docs/archive/` and older `sessions/` are historical evidence only. Do not use
them to choose current ownership, deployment targets, credentials, or strategy.

## Core rules

1. Keep work within the personal Reachly repo unless the user expands scope.
2. Preserve existing changes and the copied snapshot. Continue the current task
   branch when appropriate; create new task branches from current personal main
   only after checking the diff. Never reset, pull over, or discard local work.
3. Never commit `.env`, credentials, tokens, browser sessions, or runtime data.
4. Keep `DRY_RUN=yes` and platforms off until the user authorizes live posting
   for the specific account. Generation previews can still incur provider costs.
5. Deploy only to a verified personal target with authorization. CI is test-only;
   inherited install scripts and nginx files need review before reuse.
6. Do not claim source support, passing tests, deployment, and successful public
   posting as equivalent. Report each separately.
7. Fail with useful errors and audit records. A click or internal success flag
   alone is not evidence that a platform published the post.
8. Keep content factual and business-neutral by default. Strategy files must
   belong to the selected business; never auto-discover unrelated workspace docs.

## Architecture

Python 3.12, FastAPI, APScheduler, Playwright, SQLModel/SQLite, and provider APIs.

| Layer | Location | Responsibility |
|---|---|---|
| CLI and schedule | `reachly/runner.py`, `reachly/scheduler.py` | Commands and posting slots |
| Agent | `reachly/agent.py` | Generate, attach media, publish, record outcome |
| Content and context | `reachly/content.py`, `reachly/context.py`, `reachly/knowledge_bank.py` | Prompts and business facts |
| Configuration | `reachly/config.py`, `reachly/settings_store.py` | Environment and dashboard settings |
| Media | `reachly/media.py`, `reachly/longform_video.py` | Images and narration-led video |
| Platforms | `reachly/platforms/` | Platform-specific API/browser adapters |
| Single-user dashboard | `reachly/dashboard/` | Local controls and selected business context |
| Hosted app | `server/` | Accounts, credential vault, schedules and billing |
| Generation API | `server/generation_api.py`, `reachly/generation_worker.py` | Business generation jobs and assets |

## Context and conventions

Dashboard goals and dated knowledge-bank facts guide content. Explicitly chosen
repo docs add product facts. `REACHLY_CONTEXT_REPO` names exactly one repo;
additional documents must be selected explicitly through `REACHLY_CONTEXT_DOCS`.
Standalone context is explicitly enabled for the selected repo. Hosted workspaces
use their own saved inputs and cannot select arbitrary server files.

Use snake_case Python names and REACHLY_* for new product-specific settings.
Keep posting logic in the agent/platform layers, not HTTP handlers. Standalone
configuration lives in `.env`; SaaS maps database settings into agent inputs.

## Validation and handoff

Run relevant tests for behavior changes, `git diff --check`, and compilation when
Python changes. Use `.venv/bin/python` for this checkout. Do not run live social
commands, provider probes, deploy scripts, or migrations as session-start checks.
Record what changed, what was verified, and outstanding work in `sessions/`.
Use `docs/RELEASE_RUNBOOK.md` for release planning.
