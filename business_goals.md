# Reachly Business Goals

> Source of truth for what Reachly is trying to become. Read this with
> `AGENTS.md` and `product_theory.md` before planning or coding.

---

## North Star

Reachly should be a productized social posting autopilot any company can set up
without engineering help: connect Telegram login, define business goals, add
platform credentials or API keys, and receive scheduled posts across LinkedIn,
Instagram, and X.

## Primary Outcomes

1. **Reliable daily publishing**
   - Generate and publish 3 useful, on-brand posts per day for Hygaar.
   - Keep LinkedIn and Instagram live; bring X online after server session priming.
   - Every post attempt must be auditable in `history.db` and server logs.

2. **Company-agnostic setup**
   - A new company should provide business profile, goals, docs, and credentials.
   - Reachly should not depend on Hygaar-specific code paths except optional Hygaar media APIs.
   - Context should come from `business_goals.md`, dashboard goals, `AGENTS.md`, and `product_theory.md`.

3. **Hosted SaaS**
   - Public product runs at `reachly.nftforger.com`.
   - Telegram OTP login is the default auth path.
   - Accounts can manage credentials, schedule, goals, and posting style from the dashboard.

4. **Self-hosted / single-tenant installs**
   - Hygaar install lives in `/opt/reachly` with isolated systemd units.
   - Personal SaaS install lives in `/opt/reachly-saas`.
   - No Reachly change should require modifying Hygaar Django code.

5. **Media generation**
   - Text generation must be grounded in goals and product docs.
   - Instagram must receive generated image assets.
   - Future video support should plug into the media provider layer, not platform adapters.

## Current Hygaar Pilot Goals

| Area | Goal | Current state |
|---|---|---|
| Instagram | 3 posts/day on `@hygaar.studios` | Live; verified 3 posts on 2026-06-04 |
| LinkedIn | 3 posts/day on HyGaar company page | Browser mode live; company-page targeting configured and needs monitoring |
| X | 3 posts/day on `@hygaarstudios` | Browser mode implemented; blocked by X login limit/checkpoint |
| Product SaaS | usable by any company | Live basics; continue hardening onboarding and billing |
| Context | easy future setup | `AGENTS.md`, `product_theory.md`, `business_goals.md`, `PROMPTS/`, `sessions/` |

## Operating Principles

- Prefer official APIs when available and approved.
- Browser mode is allowed, but must fail loudly with screenshots/debug text.
- Do not silently treat “clicked Share/Post” as success when the platform may block publication.
- Keep secrets in `.env` or encrypted vault only.
- Make every session resumable through `sessions/` handoff notes.

## Near-Term Backlog

- Add stronger post-publication verification for Instagram and LinkedIn browser mode.
- Prime X server session after X temporary login limit clears.
- Confirm LinkedIn company-page posting on the next scheduled run.
- Add dashboard surfaces for recent post audit and platform health.
- Add a guided setup checklist for new companies.
