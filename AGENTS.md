# AGENTS.md — Reachly Project Constitution

> Single source of truth for AI tools and developers working on **Reachly** —
> an AI thought-leadership autopilot for LinkedIn, X, and Instagram.
> Read at the start of every session.

---

## Identity

Reachly generates on-brand social posts daily for a business, optionally with
AI images/video, and publishes via official APIs or headless browser (Playwright).

**Stack:** Python 3.12 / FastAPI (SaaS + dashboard) / APScheduler / Playwright /
Gemini (text + image) / optional Hygaar media API

**Product shapes:**
1. **Standalone agent** — `.env` + `python -m reachly.runner run`
2. **Single-tenant dashboard** — `python -m reachly.dashboard` (Hygaar today)
3. **Multi-tenant SaaS** — `server/` with Telegram OTP (future customers)

Reachly is **separate from hdb_backend**. It may *call* Hygaar APIs; it must
**never modify** Hygaar backend code or deploy pipeline.

---

## Core Rules

| # | Rule |
|---|---|
| 1 | **Never modify hdb_backend** unless explicitly asked. Reachly consumes Hygaar APIs read-only. |
| 2 | **Never commit secrets** — `.env`, passwords, OAuth tokens, dashboard tokens. |
| 3 | **Reachly server deploy is isolated** — `/opt/reachly`, own systemd units (`reachly-agent`, `reachly-dashboard`). Do not mix with CodeDeploy hdb services. |
| 4 | **Understand before editing** — read `product_theory.md` and trace agent → content → platform flow. |
| 5 | **Browser mode is best-effort** — social UIs change; fail with clear errors, never crash silently. |
| 6 | **Strategy context priority:** dashboard `goals.md` → repo `AGENTS.md` + `product_theory.md`. |

---

## Architecture: Layer Map

| Layer | Location | Responsibility |
|---|---|---|
| **CLI / scheduler** | `reachly/runner.py`, `reachly/scheduler.py` | Entrypoints, cron times |
| **Agent harness** | `reachly/agent.py` | Orchestrate generate → media → post → log |
| **Content** | `reachly/content.py` | LLM prompts, theme rotation |
| **Strategy context** | `reachly/context.py`, `reachly/settings_store.py` | Goals + repo docs |
| **LLM** | `reachly/llm.py` | Gemini / OpenAI / Anthropic |
| **Media** | `reachly/media.py` | Gemini image, Hygaar client |
| **Platforms** | `reachly/platforms/` | LinkedIn, X, Instagram (api + browser) |
| **Storage** | `reachly/storage.py` | SQLite post history |
| **Dashboard** | `reachly/dashboard/` | Hygaar control panel |
| **SaaS** | `server/` | Multi-tenant product (Telegram OTP, billing) |

### Request / run lifecycle

**Staggered schedule (Hygaar default):**

```
LinkedIn slots:  POST_TIMES           → 09:00, 13:30, 21:00 (Asia/Kolkata)
Instagram slots: POST_TIMES + offset → 09:05, 13:35, 21:05 (INSTAGRAM_OFFSET_MINUTES=5)
```

**Each LinkedIn slot:**

```
1. Scheduler fires at POST_TIMES (local TZ)
2. Agent loads BusinessProfile + StrategyContext (goals + docs)
3. LLM generates hook + body + hashtags + image_prompt
4. Content saved to pending_instagram_post.json
5. Post to LinkedIn (text; image attach best-effort in browser mode)
6. History recorded in SQLite
```

**Each Instagram slot (N minutes later):**

```
1. Scheduler fires at offset time
2. Load pending post from pending_instagram_post.json (or generate fresh if missing)
3. Gemini generates image from image_prompt (ATTACH_IMAGE=yes)
4. Post image + caption to Instagram (browser or Graph API)
5. History recorded in SQLite
```

**One-shot (`runner once`):** generates content, attaches image if Instagram enabled, posts all enabled platforms in one run.

---

## Conventions

### Naming
- Python: `snake_case` files and functions
- Env vars: `SCREAMING_SNAKE` (Reachly-specific: `REACHLY_*` prefix)
- Dashboard data: `.reachly_data/goals.md`, `dashboard_settings.json`

### Configuration
- Standalone: `.env` at install root (`/opt/reachly/.env` on server)
- Never log credential values
- `DRY_RUN=yes` until user confirms live posting

### Posting modes
- `thought_leader` — insights first, soft brand tie-in
- `brand_promoter` — educate market on product capabilities

### Platform modes
- `api` — official APIs (preferred on servers when tokens available)
- `browser` — Playwright persistent session in `.reachly_data/browser_sessions/`
- `off` — skip platform

---

## Hygaar-specific defaults

| Setting | Value |
|---|---|
| Context repo | `/var/www/html/dev-env/hdb_backend` |
| Post times (LinkedIn) | 09:00, 13:30, 21:00 Asia/Kolkata |
| Instagram offset | 5 min → 09:05, 13:35, 21:05 |
| LinkedIn | browser mode, personal profile (company page TBD) |
| Instagram | browser mode, `@hygaar.studios` — image from Gemini prompt |
| Image gen | Gemini (`ATTACH_IMAGE=yes`; images generated at Instagram slot) |
| Posting style | `brand_promoter` |

---

## Forbidden Patterns

| Pattern | Why | Instead |
|---|---|---|
| Editing hdb_backend for Reachly features | Breaks deploy rules | Call Hygaar API or extend Reachly only |
| Storing passwords in git | Security | `.env` + encrypted vault (SaaS) |
| Silent `except: pass` on post failures | Ops blindness | Log + record in history.db |
| Hardcoded LinkedIn `#username` selector only | UI changed | Multiple selectors + visible-field check |
| Assuming free X API tier | Deprecated 2026 | Document pay-per-use or browser mode |

---

## Key Files

| File | Role |
|---|---|
| `reachly/agent.py` | Main harness (`run_linkedin_slot`, `run_instagram_slot`) |
| `reachly/context.py` | Load goals + AGENTS.md + product_theory |
| `reachly/scheduler.py` | Staggered LinkedIn + Instagram cron jobs |
| `reachly/platforms/linkedin.py` | API + browser posting |
| `reachly/platforms/instagram.py` | API + browser posting (create flow selectors) |
| `reachly/dashboard/app.py` | Hygaar dashboard |
| `deploy/install_on_server.sh` | Server bootstrap |
| `deploy/nginx/reach.hygaar.com.conf` | Public dashboard proxy |

---

## Decision Checklist (before every edit)

```
□ Does this touch hdb_backend? (should be NO)
□ Are secrets out of git and session docs?
□ Does browser code degrade gracefully on UI changes?
□ Is strategy context (goals → docs) still correct priority?
□ Did I test preview / once / instagram on server before enabling live schedule?
```
