# Reachly

**Your AI thought-leadership autopilot.** Reachly studies a business — its vision,
sector, product and brand voice — then **writes and publishes on-brand content every
day** to **LinkedIn, X (Twitter), Instagram, and Medium**, complete with AI-generated
images, relevant hashtags, and links back to the business. Short social posts go to
LinkedIn / X / Instagram; long-form **Medium articles** (850–1300 words) run on their
own daily schedule.

It ships in two shapes from one codebase:

| | What it is | Who runs it |
|---|---|---|
| **Standalone agent** | A single `.py` agent driven by a `.env` file | The customer, on their own server |
| **Hosted SaaS** | Multi-tenant web app with Hygaar console login, a credential vault, billing, and a per-user scheduler | You |

## Hygaar Product

Reachly is being productized as a Hygaar-owned app, but it remains a separate
repo and deployment from `hdb_backend` and `console_live`.

- Hosted URL target: `https://reachly.hygaar.com`
- App service target: `/opt/reachly-saas`, systemd `reachly-saas`
- Login: Hygaar console email/password through the Hygaar backend auth API
- Local app data: Reachly SQLModel DB keyed by Hygaar `Account.user_id`
- Platform setup: API-first credentials per platform, with Playwright browser
  fallback where official APIs are unavailable or not approved

See [`docs/HYGAAR_PRODUCTIZATION.md`](docs/HYGAAR_PRODUCTIZATION.md) for the
current acquisition architecture and CI/CD setup, and
[`docs/HYGAAR_ACQUISITION_AUDIT.md`](docs/HYGAAR_ACQUISITION_AUDIT.md) for the
lineage/deployment evidence log. Release steps live in
[`docs/RELEASE_RUNBOOK.md`](docs/RELEASE_RUNBOOK.md).

---

## ✨ What it does

- **Content**: rotates through your content themes daily, asks an LLM for a
  thought-leadership post (hook + body + hashtags + image prompt), and de-dupes
  against recent posts so it never repeats itself.
- **Media**: generates an image per post with **Gemini ("Nano Banana")**, or with
  your **Hygaar** account (image *and* video). Bring your own keys.
- **Long-form**: writes a full **Medium article** (title, subtitle, 850–1300 word
  body, tags) with a **16:9 image**, de-duped against recent article openings.
- **Publishing**: posts via the **official APIs** *or* a **headless browser**
  (Playwright) when you don't have API access — chosen **per platform**. Medium
  publishes via browser (persistent session), as a **draft** or **public** article.
- **Scheduling**: posts **multiple times per day** at configurable local times.
  LinkedIn and Instagram can run on a **staggered schedule** — e.g. Instagram
  **5 minutes after each LinkedIn slot**, reusing the same caption and generating
  an image from the LLM's text prompt. **Medium runs on its own independent slots**
  (`MEDIUM_TIMES`, default two per day), separate from the social stagger.
- **Safety**: starts in **dry-run** so you can preview before going live.

## 🔌 Media generation is pluggable (3 ways to integrate Hygaar)

1. **Independent (default)** — each user brings their **own** Gemini / OpenAI /
   Anthropic keys. Zero Hygaar dependency.
2. **Hygaar as a plugin** — set `IMAGE_PROVIDER=hygaar` (and/or
   `VIDEO_PROVIDER=hygaar`) and give Reachly a Hygaar `X-API-Key`. Reachly calls
   Hygaar's `/api/batch/generate-images/` → polls `/api/batch/generation-status/`.
3. **Reachly inside Hygaar** — the agent core (`reachly.agent.Agent`) is a plain
   library, so Hygaar can import it and drive posting directly.

> Reachly never modifies Hygaar. It only **calls Hygaar's public APIs**.

---

## 🚀 Quick start — standalone agent

```bash
git clone <this-repo> reachly && cd reachly
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium        # only if you use browser mode

cp .env.example .env                          # then edit .env
python -m reachly.runner preview              # generate a post & print it (never posts)
```

When happy, set `DRY_RUN="no"` in `.env` and run it forever:

```bash
python -m reachly.runner run                  # scheduler: LinkedIn + Instagram + Medium slots
python -m reachly.runner once                 # all enabled platforms, one shot
python -m reachly.runner instagram            # test Instagram slot (image + post)
python -m reachly.runner medium               # test Medium article slot (16:9 image + article)
```

Keep it alive with the provided `deploy/reachly-agent.service` (systemd) or Docker.

### The `.env` in one glance
You describe your business, pick an LLM + image provider, and enable each platform
with a `mode` of `api`, `browser`, or `off`. See [`.env.example`](.env.example) for
every field with inline docs.

### Staggered LinkedIn → Instagram schedule

Set multiple LinkedIn times and an Instagram offset (minutes):

```env
POST_TIMES="09:00,13:30,21:00"
INSTAGRAM_OFFSET_MINUTES="5"
INSTAGRAM_MODE="browser"
ATTACH_IMAGE="yes"
IMAGE_PROVIDER="gemini"
```

With the defaults above (Asia/Kolkata):

| Slot | LinkedIn | Instagram |
|------|----------|-----------|
| Morning | 09:00 | 09:05 |
| Afternoon | 13:30 | 13:35 |
| Evening | 21:00 | 21:05 |

**Per slot:**

1. **LinkedIn** — LLM generates hook, body, hashtags, and `image_prompt` → posts text to LinkedIn → saves content to `pending_instagram_post.json`.
2. **Instagram (+N min)** — loads pending content → **Gemini generates an image from the text prompt** → posts image + caption via browser or Graph API.

Instagram requires an image (`ATTACH_IMAGE=yes`). If no pending post exists (e.g. LinkedIn slot failed), Instagram generates fresh content instead.

---

## 🏢 Quick start — hosted SaaS

```bash
pip install -r requirements.txt
export REACHLY_VAULT_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())")
export REACHLY_SESSION_SECRET="a-long-random-string"
export REACHLY_TELEGRAM_BOT_TOKEN="123:abc"      # from @BotFather
export REACHLY_TELEGRAM_BOT_USERNAME="YourReachlyBot"
export REACHLY_PUBLIC_BASE_URL="https://your-domain.com"
uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Before deploying hosted production settings, run:

```bash
python -m server.preflight
```

Then open the site:

1. **Landing page** → *Get started*.
2. **Hygaar login**: the user signs in with their Hygaar console email/password.
   Legacy Telegram OTP can be enabled for old self-host/SaaS experiments.
3. **Dashboard**: they fill in their business, paste their **own** AI keys, connect
   each platform (API or browser), pick a daily time, and toggle dry-run → live.
4. **Run now** to test instantly, or let the per-minute scheduler post at their time.

### Productisation
- **Billing**: set `REACHLY_STRIPE_*` to gate activation behind a subscription
  (`/billing` → Stripe Checkout → webhook flips `is_active`). With
  `REACHLY_FREE_MODE=true` (default) accounts are active immediately for dev.
- **Self-host upsell**: paid users get `/install` with a **license key** and copy-paste
  instructions to run the standalone agent on their own box.
- **Credential vault**: all secrets are encrypted at rest with `REACHLY_VAULT_KEY`
  (Fernet) and only decrypted in memory at posting time.

Docker: `cd deploy && docker compose up --build`.

---

## 🔑 Getting platform access

| Platform | API mode needs | Browser mode needs |
|---|---|---|
| **X / Twitter** | OAuth2 user token (`tweet.write`, `media.write`). Note: X has no free tier in 2026 (pay-per-use ~$0.01/post). | username + password; optional login email/phone for X checkpoints |
| **LinkedIn** | `w_member_social` access token for personal posts; `w_organization_social` + organization id for company pages. Partner verification required. | email + password; optional company page name or admin URL |
| **Instagram** | Business account, Graph API token + IG user id, and a **public** image URL (the hosted server provides one). | username + password; **image required** (generated from LLM prompt) |
| **Medium** | Public API not reliable for new integrations — **browser mode only**. | email + password; **16:9 image required**; `MEDIUM_PUBLISH_STATUS` = `draft` or `public`; optional `MEDIUM_EXPECTED_ACCOUNT` guard |

Because API approval can take weeks (and X now charges), **browser mode** lets users
start posting immediately; they can upgrade to API mode later.

**Instagram browser tips:** Prime the session once (login + phone approval if prompted).
The create flow uses `/create/select/` with fallback selectors. Test with
`python -m reachly.runner instagram` before enabling the live schedule.

---

## 🧱 Architecture

```
reachly/            # the agent core — no server dependency
  config.py         # .env  -> typed config (standalone)
  models.py         # BusinessProfile, PlatformCredentials, GeneratedPost ...
  llm.py            # Gemini / OpenAI / Anthropic text generation
  content.py        # theme rotation + post generation
  media.py          # Gemini image gen + Hygaar client (X-API-Key)
  platforms/        # twitter / linkedin / instagram / medium  (api + browser)
  agent.py          # harness: run_linkedin_slot / run_instagram_slot / run_medium_slot
  scheduler.py      # APScheduler: LinkedIn at POST_TIMES, IG at offset, Medium at MEDIUM_TIMES
  runner.py         # CLI: preview | once | run | instagram
  storage.py        # sqlite post history (dedupe + audit)

server/             # the multi-tenant SaaS
  app.py            # FastAPI: auth, dashboard, billing, media hosting
  telegram_bot.py   # legacy /start + OTP login (long-polling, optional)
  db.py             # SQLModel tables
  crypto.py         # Fernet credential vault
  orchestrator.py   # DB rows -> Agent, per-minute scheduler
  templates/        # landing, login, dashboard, billing, install

deploy/             # Dockerfile, compose, systemd unit
```

The same `Agent` runs in both modes — the server just builds its inputs from the
database instead of from `.env`.

---

## ⚠️ Notes & responsible use
- Respect each platform's automation rules and rate limits. Browser automation can
  trip 2FA / bot checks; the persistent session keeps logins between runs to minimise this.
- Keep `DRY_RUN` on until you've reviewed a few generated posts.
- Never commit your `.env` or `REACHLY_VAULT_KEY`.
