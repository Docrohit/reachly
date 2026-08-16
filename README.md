# Reachly

**Your AI thought-leadership autopilot.** Reachly studies a business — its vision,
sector, product and brand voice — then **writes and publishes on-brand content every
day** to **LinkedIn, X (Twitter), Instagram, Medium, and YouTube**, complete with AI-generated
images, relevant hashtags, and links back to the business. Short social posts go to
LinkedIn / X / Instagram; long-form **Medium articles** (850–1300 words) run on their
own daily schedule. Reachly can also make narration-led 16:9 videos for
LinkedIn + YouTube.

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
- **Current context**: reads dashboard goals plus current repo docs before each
  generation: `AGENTS.md`, `product_theory.md`, `business_goals.md`,
  `docs/HYGAAR_MOAT_ARCHITECTURE_2026.md`, `docs/DOC_INDEX_CURRENT.md`, and
  `Business_cases*.csv` when present. It also reads `knowledge_bank.md` release
  events and explicit `.md`, `.csv`, `.txt`, or `.docx` docs such as a moat
  document passed through `REACHLY_CONTEXT_DOCS`. This keeps posts and videos
  aligned with updated Hygaar moat/feature/business-case material without a
  service restart.
- **Media**: generates an image per post with **Gemini ("Nano Banana")**, or with
  your **Hygaar** account (image *and* video). Bring your own keys.
- **Long-form**: writes a full **Medium article** (title, subtitle, 850–1300 word
  body, tags) with a **16:9 image**, de-duped against recent article openings.
- **Narration-led video**: creates 60-120s 16:9 videos from the daily post theme
  or a manual topic/title/hook/payoff. It writes the script, generates ElevenLabs
  narration, transcribes with OpenAI, groups the transcript into 4-6 visual cards,
  generates silent Seedance clips, runs Gemini visual QC, retries bad cards up to
  two times, renders the final narration-led video, then posts to LinkedIn + YouTube.
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
python -m reachly.runner seedance-account-check  # minimal ModelArk activation/billing probe
python -m reachly.runner linkedin --media-kind video --video-strategy recap  # LinkedIn-first Seedance video test
python -m reachly.runner longform-video-preflight # check long-form video dependencies
python -m reachly.runner longform-video --theme "Why Hygaar beats in-house AI media"
python -m reachly.runner knowledge-event --kb-title "Prod update" --kb-summary "What changed and why it matters"
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
POST_TIMES="09:00,12:00,15:00,18:00,21:00"
INSTAGRAM_OFFSET_MINUTES="5"
INSTAGRAM_MODE="browser"
ATTACH_IMAGE="yes"
IMAGE_PROVIDER="gemini"
VIDEO_PROVIDER="seedance"
SEEDANCE_API_KEY="..."  # or ARK_API_KEY / MODELARK_API_KEY from the Agent 8 env
SEEDANCE_CLIP_COUNT="0" # auto: 2.5 uses native 30s, 2.0 fallback splits into 15s clips
REACHLY_DAILY_MEDIA_PLAN="image,image,image,video,video"
```

For the narration-led long-form maker, also set:

```env
REACHLY_LONGFORM_VIDEO_ENABLED="yes"
REACHLY_LONGFORM_VIDEO_TIMES="11:30,17:30"
ELEVENLABS_API_KEY="..."
REACHLY_ELEVENLABS_VOICE_ID="..."
OPENAI_API_KEY="..."      # gpt-4o-transcribe, then whisper fallback
GEMINI_API_KEY="..."      # clip hallucination QC
YOUTUBE_MODE="api"
YOUTUBE_REFRESH_TOKEN="..."
YOUTUBE_CLIENT_ID="..."
YOUTUBE_CLIENT_SECRET="..."
```

YouTube uploads require OAuth scope
`https://www.googleapis.com/auth/youtube.upload`; API keys and service accounts
are not enough for uploading to the Hygaar channel.

With the defaults above (Asia/Kolkata):

| Slot | LinkedIn | Instagram | Media |
|------|----------|-----------|-------|
| Morning | 09:00 | 09:05 | Image |
| Noon | 12:00 | 12:05 | Image |
| Afternoon | 15:00 | 15:05 | Image |
| Evening | 18:00 | 18:05 | Video from recent image posts |
| Night | 21:00 | 21:05 | Fresh video ad |

**Per slot:**

1. **LinkedIn image slots** — LLM generates hook, body, hashtags, and media prompt → posts text + image to LinkedIn → records the image for future video references.
2. **LinkedIn video slots** — first daily video uses the last image-post references and prior copy; second daily video generates fresh storyboard images and script direction. Seedance 2.5 gets one native 30s multi-scene prompt; 2.0 fallback is split into 15s clips.
3. **Instagram (+N min)** — loads pending content → reuses the LinkedIn video or generates an image from the text prompt → posts media + caption via browser or Graph API.

Instagram requires generated media. If no pending post exists (e.g. LinkedIn slot failed), Instagram generates fresh content instead.

Before the first live video run, use `seedance-account-check`. It creates minimal
4-second ModelArk probe tasks and reports provider-side blockers such as
`ModelNotOpen` for Seedance 2.5 activation or `AccountOverdueError` for billing.

### Knowledge bank from product updates

Reachly keeps an append-only `knowledge_bank.md` in its data directory. Future
posts, articles, and long-form videos read it before generation. Use this for
dated product facts from merged branches or production releases:

```bash
python -m reachly.runner knowledge-event \
  --kb-title "Seedance 2.5 long-form videos shipped" \
  --kb-summary "Reachly can now make 60-120 second narration-led 16:9 videos with ElevenLabs voiceover, transcript cards, Seedance clips, Gemini QC, and LinkedIn/YouTube publishing." \
  --kb-source "github_actions" \
  --kb-environment "prod" \
  --kb-commit "$GITHUB_SHA"
```

Hosted Reachly also exposes `POST /internal/knowledge-events` when
`REACHLY_KNOWLEDGE_EVENT_SECRET` is set. A deploy workflow can call it after
prod is updated:

```bash
curl -X POST "https://reachly.hygaar.com/internal/knowledge-events" \
  -H "Content-Type: application/json" \
  -H "X-Reachly-Knowledge-Secret: $REACHLY_KNOWLEDGE_EVENT_SECRET" \
  -d '{"source":"github_actions","environment":"prod","title":"Prod update","summary":"Summarize the user-visible features and moat impact here.","commit_sha":"'"$GITHUB_SHA"'"}'
```

The event text is treated as factual context only, not as instructions.

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
| **Instagram** | Business account, Graph API token + IG user id, and a **public** image/video URL (the hosted server provides one). | username + password; generated image posts or video/Reels uploads |
| **Medium** | Public API not reliable for new integrations — **browser mode only**. | email + password; **16:9 image required**; `MEDIUM_PUBLISH_STATUS` = `draft` or `public`; optional `MEDIUM_EXPECTED_ACCOUNT` guard |
| **YouTube** | OAuth refresh token/client for scope `https://www.googleapis.com/auth/youtube.upload`; uploads use resumable `videos.insert`. | Not supported |

Because API approval can take weeks (and X now charges), **browser mode** lets users
start posting immediately; they can upgrade to API mode later.

**Instagram browser tips:** Prime the session once (login + phone approval if prompted).
Video posts prefer `/reels/create/` and fall back through the standard create
flow. Test with `python -m reachly.runner instagram` before enabling the live
schedule.

---

## 🧱 Architecture

```
reachly/            # the agent core — no server dependency
  config.py         # .env  -> typed config (standalone)
  models.py         # BusinessProfile, PlatformCredentials, GeneratedPost ...
  llm.py            # Gemini / OpenAI / Anthropic text generation
  content.py        # theme rotation + post generation
  media.py          # Gemini image gen, Seedance, ElevenLabs, Hygaar client
  longform_video.py # 90s narration-led video pipeline + QC retries
  platforms/        # twitter / linkedin / instagram / medium / youtube
  agent.py          # harness: run_linkedin_slot / run_instagram_slot / run_medium_slot / run_longform_video_slot
  scheduler.py      # APScheduler: LinkedIn, IG offset, Medium, long-form video
  runner.py         # CLI: preview | once | run | instagram | longform-video
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
