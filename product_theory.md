# Reachly — Product Theory

> **Purpose:** Why Reachly exists and how it should behave. Read before changing
> content strategy, posting logic, or product boundaries.

---

## What Does This Product Do?

Reachly is an **AI thought-leadership autopilot**. Given a business profile,
strategy goals, and optional product documentation, it:

1. **Writes** original posts (hook, body, hashtags, link) rotated across themes
2. **Generates** optional images/video (Gemini, Hygaar, or bring-your-own keys)
3. **Publishes** to LinkedIn, X, and Instagram on a schedule (API or browser)
4. **Logs** everything for audit and de-duplication

**Primary user today:** Hygaar (founder/brand team posting as thought leader +
light product promotion)

**Future users:** Any company via SaaS signup or self-hosted `.env` install

---

## Why This Exists

| Problem | Reachly's answer |
|---|---|
| Founders don't post consistently | Daily scheduler at configurable times |
| Generic AI posts sound hollow | Business profile + goals + repo docs ground the LLM |
| API access is hard (LinkedIn approval, X fees) | Browser mode with persistent sessions |
| Media creation is separate from posting | Pluggable Gemini / Hygaar media in same run |
| Multi-channel is tedious | One agent, per-platform rendering (length limits, etc.) |

---

## Strategy Context — How the Agent "Knows" the Business

Priority order (highest wins for *direction*, lower layers add *accuracy*):

```
1. goals.md          — written in dashboard: quarterly focus, ICP, campaigns
2. AGENTS.md         — product constitution: what we are / are not
3. product_theory.md — why the product exists, architecture, forbidden patterns
4. .env BUSINESS_*   — name, vision, sector, themes, hashtags (baseline)
```

For **Hygaar**, repo docs live in `hdb_backend/` on the server. For other
clients, set `REACHLY_CONTEXT_REPO` to their product repo (auto-finds the two
markdown files).

### Posting styles

| Style | When to use | Tone |
|---|---|---|
| `thought_leader` | Personal founder brand, industry credibility | Insight → soft Hygaar mention |
| `brand_promoter` | Company page, product launches, market education | What Hygaar does + why it matters |

Both must stay **useful and non-spammy**. Never invent features not in docs.

---

## Why Two Deployment Modes?

| Mode | Who | Why |
|---|---|---|
| **Hosted dashboard + agent on server** | Hygaar ops | Always-on, LinkedIn session on box, no laptop needed |
| **SaaS (`server/`)** | Paying customers | Telegram OTP, credential vault, billing, no server admin |
| **Self-host (`runner`)** | Enterprise / paid download | Data stays on customer infra, `.env` only |

Same `Agent` class powers all three — only config source differs.

---

## Why Browser Mode?

Social platforms in 2026:

- **X:** no free API tier (pay-per-post)
- **LinkedIn:** API needs partner-approved app + org scopes for company pages
- **Instagram:** Graph API needs Business account + public media URLs

Browser mode lets admins post **immediately** with credentials they already have.
Trade-offs:

- LinkedIn may require **one-time device approval** (phone tap Yes)
- Datacenter IPs trigger checkpoints more than home IPs
- DOM selectors need maintenance when UIs change

**Mitigation:** persistent Playwright profile on disk; prime session once; prefer
API mode when tokens are available.

---

## Media Generation Strategy

Pluggable providers — customer chooses:

| Provider | Use case |
|---|---|
| `gemini` | Fast Nano Banana images; customer's Gemini key |
| `hygaar` | Premium pipeline; customer's Hygaar `X-API-Key` |
| `none` | Text-only posts |

With the **staggered schedule**, images are generated at the **Instagram slot**
(from the LLM's `image_prompt`), not when LinkedIn posts. LinkedIn browser mode
may still attempt image attach separately (best-effort).

Reachly **never modifies** Hygaar backend — only calls public APIs.

---

## Scheduling Philosophy

- Multiple slots per day (`POST_TIMES`) beat one mega-post — different audience windows
- **Hygaar default:** LinkedIn at 09:00, 13:30, 21:00 (Asia/Kolkata)
- **Instagram stagger:** `INSTAGRAM_OFFSET_MINUTES` after each LinkedIn slot (default **5** → 09:05, 13:35, 21:05)
- LinkedIn and Instagram are **separate scheduler jobs**, not one combined run
- LinkedIn slot saves caption + metadata to `pending_instagram_post.json`; Instagram slot reuses it and generates the image then
- Images are generated **at the Instagram slot** from the LLM's `image_prompt` (not at LinkedIn time)
- Theme rotation prevents repetition; recent hooks fed back to LLM as negative examples
- Start in `DRY_RUN` until human approves voice

---

## Product Boundaries (What Reachly Is NOT)

- Not a social inbox / comment replier (post-only v1)
- Not a Hygaar feature inside Django admin (separate service)
- Not a replacement for paid social ads or analytics suites
- Not guaranteed to bypass platform ToS — customers responsible for compliance

---

## Layer Philosophy

When adding features:

1. **Config / dashboard change?** → `settings_store.py` or dashboard templates
2. **Smarter posts?** → `content.py` + `context.py` (prompts only)
3. **New platform?** → `platforms/newplatform.py` + factory in `__init__.py`
4. **New media backend?** → `media.py` provider function
5. **Multi-tenant?** → `server/orchestrator.py` maps DB → Agent

Do not put posting logic in the dashboard — dashboard triggers Agent only.

---

## Roadmap (Known Gaps)

| Item | Status |
|---|---|
| LinkedIn company page posting (browser) | `LINKEDIN_POST_AS="HyGaar"` configured; verify after every UI change |
| Instagram live posting | **Enabled** (browser mode); session must be primed once; selectors updated for `/create/select/` |
| Staggered LinkedIn → Instagram (3× daily) | **Live** — 6 scheduler jobs on server |
| X / Twitter | Browser mode implemented; blocked by X temporary login limits/checkpoint until session is primed |
| Read Reachly's own AGENTS.md in context | Available at `/opt/reachly/` |
| nginx public URL `reach.hygaar.com` | Config added; DNS/ALB route may be needed |
| Automated tests | Minimal — manual `preview` / `once` / `instagram` on server |

---

## Success Metrics (Hygaar pilot)

- 3 posts/day on LinkedIn without manual writing
- 3 posts/day on Instagram (image + caption), 5 min after each LinkedIn slot
- X posts automatically once the server browser session is successfully primed
- Posts reflect current product positioning (from docs)
- < 5 min human time per week (goals update + occasional approve)
- Session survives ≥30 days without re-login (target)
