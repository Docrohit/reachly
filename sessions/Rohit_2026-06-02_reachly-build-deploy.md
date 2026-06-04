# Session: Build & deploy Reachly — AI thought-leadership autopilot for Hygaar

**Developer:** Rohit (+ AI pair session)
**Date:** 2026-06-02
**Time:** ~07:30–19:30 IST (multi-hour session)
**Quality Review:** ⚠️ Issues found and fixed during session (LinkedIn selectors, scheduler closure, Playwright user cache); broad `except` blocks retained intentionally with logging in agent/platforms

---

## What We Worked On

- Designed and built **Reachly** — LLM + harness that generates and posts daily thought-leadership content to LinkedIn / X / Instagram
- Productized for two modes: **standalone `.env` agent** and **multi-tenant SaaS** (`server/` with Telegram OTP)
- Integrated **Gemini** (text + Nano Banana images) and optional **Hygaar media API** (read-only consumer; no hdb_backend changes)
- Deployed isolated install on Hygaar app server: `/opt/reachly`, systemd `reachly-agent` + `reachly-dashboard`
- LinkedIn **browser mode**: primed session via mobile app approval; successful **live personal-profile post**
- Added **strategy context**: dashboard goals → fallback `AGENTS.md` + `product_theory.md` from client repo
- Added **Hygaar dashboard** (goals, schedule, posting style, run-now, strategy preview)
- Set **3× daily schedule**: 09:00, 13:30, 21:00 Asia/Kolkata (LinkedIn)
- Added **staggered Instagram**: 5 min after each LinkedIn slot — reuses caption, Gemini image from text prompt, 3× daily to `@hygaar.studios`
- Enabled **Instagram browser mode** with updated create-flow selectors (`/create/select/`)
- Added **nginx** reverse proxy config for `reach.hygaar.com` → dashboard port 8765
- Authored Reachly **`AGENTS.md`** and **`product_theory.md`**

---

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| `reachly/` (new product) | Agent core: config, LLM, content, media, platforms, agent, scheduler, runner | Standalone deployable harness | Agent / Service |
| `reachly/platforms/*.py` | LinkedIn/X/Instagram API + Playwright browser posters | API approval hard; browser for fast start | Platform adapters |
| `reachly/media.py` | Gemini image + Hygaar `X-API-Key` client | Pluggable media; Hygaar as plugin only | Media |
| `reachly/context.py` | Load goals.md + repo AGENTS.md + product_theory.md | Ground LLM in business strategy | Content / Strategy |
| `reachly/settings_store.py` | Dashboard JSON + goals.md persistence | Editable without .env restarts | Config |
| `reachly/dashboard/` | FastAPI Hygaar control panel | Goals, schedule, run-now, logs | Controller |
| `reachly/scheduler.py` | Staggered LinkedIn + Instagram cron jobs | 3× LI + 3× IG per day | Scheduler |
| `reachly/agent.py` | `run_linkedin_slot` / `run_instagram_slot`, pending post queue | LinkedIn first, IG + image later | Agent |
| `reachly/platforms/instagram.py` | Browser create flow (`/create/select/`, fallback selectors) | Instagram web UI changed | Platform |
| `server/` | SaaS: Telegram OTP, vault, billing stubs, orchestrator | Future multi-customer product | SaaS |
| `deploy/install_on_server.sh` | Bootstrap `/opt/reachly` + systemd | Server install | Deploy |
| `deploy/nginx/reach.hygaar.com.conf` | Proxy to :8765 | Public dashboard URL | Infra |
| `reachly/AGENTS.md` | Project constitution for Reachly | Onboard devs + AI sessions | Docs |
| `reachly/product_theory.md` | Why / how Reachly works | Strategy + boundaries | Docs |
| Server `/opt/reachly/.env` | Hygaar creds, schedule, context repo, dashboard token | Runtime config (not in git) | Config |

---

## Architecture Notes

### Isolation from Hygaar backend
Reachly is a **separate Python product** under `hdb_oct17/reachly/`. It does not import Django or share CodeDeploy with `hdb_backend`. Server install uses dedicated user `reachly`, paths `/opt/reachly`, and units `reachly-agent` / `reachly-dashboard`. This was an **owner-approved exception** to hdb `AGENTS.md` Rule #1 (no direct server edits) documented in `DEPLOY_SESSION.md`.

### Strategy context priority
```
goals.md (dashboard)  →  AGENTS.md + product_theory.md (REACHLY_CONTEXT_REPO)
                      →  .env BUSINESS_* baseline
```
Posting styles: `thought_leader` vs `brand_promoter` (Hygaar currently set to promoter on server).

### Staggered LinkedIn → Instagram
```
LinkedIn  09:00 / 13:30 / 21:00  →  generate + post text + save pending_instagram_post.json
Instagram 09:05 / 13:35 / 21:05  →  load pending + Gemini image from image_prompt + post
```
Instagram images are generated at the Instagram slot, not at LinkedIn time.

### Platform posting
- **LinkedIn browser:** persistent Playwright session; login required device approval once
- **Company page posting:** attempted via composer “Post as” switcher — **not reliable** in headless UI; deferred; personal profile works
- **Image attach on LinkedIn browser:** often fails; posts succeed text-only

### Productization path
| Today (Hygaar) | Future (any company) |
|---|---|
| Single `.env` + dashboard | SaaS `server/` per-tenant DB |
| `REACHLY_CONTEXT_REPO` → their repo | Same + auto-discovery of docs |
| `goals.md` on disk | Goals field in SaaS dashboard |

---

## Tests Added / Updated

| Test | What it covers |
|---|---|
| None committed | Manual: `preview`, `once`, login prime, dashboard context load (`goals+repo` verified on server) |
| Smoke scripts (deploy/) | `li_debug.py`, `li_login_test.py`, `prime_linkedin.py` — operational, not unit tests |

---

## Deploy / Server State (end of session)

| Item | Status |
|---|---|
| Code path | `/opt/reachly` |
| Agent service | `reachly-agent` **active** — 6 jobs: LI 09:00/13:30/21:00, IG 09:05/13:35/21:05 IST |
| Instagram | **browser mode enabled**; image from Gemini prompt; session priming pending |
| Dashboard service | `reachly-dashboard` **active** — port 8765 |
| LinkedIn session | Primed (device approval completed) |
| Live post | ✅ At least one successful personal LinkedIn post |
| nginx | `reach.hygaar.com.conf` installed, nginx reloaded |
| Dashboard auth | Token in server `.env` as `REACHLY_DASHBOARD_TOKEN` (not in git) |

### Access dashboard
1. **Preferred (after DNS/ALB):** `https://reach.hygaar.com/?token=<REACHLY_DASHBOARD_TOKEN>`
2. **Until DNS routes:** SSH tunnel `ssh -L 8765:127.0.0.1:8765 ubuntu@<bastion/app>` then `http://localhost:8765/?token=...`

Token value: retrieve on server with `grep REACHLY_DASHBOARD_TOKEN /opt/reachly/.env` (do not commit).

---

## Risks / Follow-ups

- [ ] **Instagram session** — run `runner instagram`, approve login on phone; confirm live post
- [ ] **DNS / ALB:** Add `reach.hygaar.com` route to app server port 80 (same as other Hygaar subdomains)
- [ ] **LinkedIn company page** — fix “Post as Hygaar” in browser composer or use LinkedIn API with `w_organization_social`
- [ ] **X / Twitter** — off; API is pay-per-use in 2026
- [ ] **Image attach** on LinkedIn browser — investigate file upload selectors
- [ ] **Session expiry** — LinkedIn may require re-approval; re-run `deploy/prime_linkedin.py`
- [ ] **Security:** Rotate dashboard token if ever exposed in chat logs; restrict `reach.hygaar.com` by VPN/IP if needed
- [ ] **Commit reachly/** into git when ready (currently untracked under `hdb_oct17`)
- [ ] Wire SaaS dashboard to same context/goals model as standalone dashboard

---

## Environment

- **Branch:** Reachly not committed; lives at `hdb_oct17/reachly/` (untracked in parent repo)
- **hdb_backend branch:** `dev-env` (unchanged — no Reachly code in hdb_backend)
- **Reachly runtime:** Hygaar app server, isolated `/opt/reachly`
- **Context repo on server:** `/var/www/html/dev-env/hdb_backend` (Hygaar AGENTS.md + product_theory.md)
- **Reachly docs:** `/opt/reachly/AGENTS.md` + `/opt/reachly/product_theory.md` (for Reachly itself)

---

## Session Timeline (abbreviated)

1. Built Reachly product from scratch (agent, platforms, media, SaaS skeleton)
2. Copied to `hdb_oct17/reachly/`; removed duplicate from `~/Desktop/Personal/reachly`
3. Deployed to server via `install_on_server.sh` + Playwright for `reachly` user
4. LinkedIn login blocked → device approval flow → user tapped Yes → session saved
5. First live post succeeded (personal profile; company page selector failed)
6. Added context loader, dashboard, 3× schedule, nginx, governance docs
7. Added staggered Instagram (5 min offset), `run_instagram_slot`, `runner instagram` CLI
8. Updated Instagram browser selectors; deployed to server; 6 scheduler jobs confirmed active

---

## Continuation (2026-06-03)

- **Requirement:** Text prompt generates images; Instagram posts **3× daily**, **5 minutes after** each LinkedIn slot
- **Implemented:** `INSTAGRAM_OFFSET_MINUTES`, `pending_instagram_post.json`, separate scheduler jobs
- **Test result:** Content + Gemini image generation ✅; Instagram browser post blocked until session primed
- **Docs updated:** README, AGENTS.md, product_theory.md, DEPLOY_SESSION.md

**Next session:** Start with `PROMPTS/01_PROMPT_session_start.md`, read `reachly/AGENTS.md` + `reachly/product_theory.md`, prime Instagram session, verify `reach.hygaar.com` DNS.

---

## Handoff Checklist

- [x] Quality review completed; LinkedIn login/selectors fixed iteratively
- [x] Session doc created (this file)
- [x] No secrets in this doc (token/passwords referenced only by env var name)
- [ ] Automated tests — not added
- [ ] Git commit — not done (user did not request)
- [x] Post-deploy monitoring: `journalctl -u reachly-agent -f`, `journalctl -u reachly-dashboard -f`, nginx `/var/log/nginx/reachly-*.log`
- [ ] Instagram browser session primed and live post confirmed
