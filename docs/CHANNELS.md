# Channels: connect, publish and 24-hour autopilot

Date: 2026-10-17. Personal Reachly only. Never reuse Hygaar/Hyclinics apps, IDs or secrets.

`/channels` lists every project (business workspace) under the signed-in owner. Each project can:

- **Connect Facebook**: Facebook Login on the personal Meta app. You pick a Page; an Instagram
  professional account linked to that Page connects at the same time (Page token, Graph v25).
- **Connect X**: OAuth 2.0 with PKCE on the personal X app. Tokens refresh automatically before
  they expire (X rotates refresh tokens, so refreshes are serialized and re-read).
- **Publish** a draft to any connected channels. Each draft/channel pair gets one attempt. Only a
  definite platform refusal (HTTP 4xx) may be retried; timeouts and unknown outcomes show
  "check platform" and are never retried automatically. X sends also go through the shared
  account ledger (duplicates blocked, 20 sends per UTC day).
- **Autopilot** (per project, off by default): every 10 minutes the scheduler checks each enabled
  project. When Live publishing is on and no post has gone out for 24 hours, it publishes the
  oldest waiting draft from the last 14 days (never attempted by Channels), or generates a new image
  post when none is waiting, then publishes to the chosen autopilot channels. After an attempt it
  waits 3 hours before trying again. "Publish next post now" runs the same steps immediately; a
  topic always generates a new post. "Discard" removes a draft from the queue.

Tokens are encrypted in `PlatformCredRow.vault` and never reach the browser. Connecting replaces the
channel's previous credentials (old OAuth 1.0a X keys are dropped). New tables (`channeloauthstate`,
`channelpublication`, `autopilotsetting`) are created by normal app startup.

## Server environment (`/opt/reachly-saas/.env` on the personal VPS)

| Variable | Value |
|---|---|
| `REACHLY_X_CLIENT_ID`, `REACHLY_X_CLIENT_SECRET` | OAuth 2.0 client of X app **Reachly Personal Channels** (ID 33544892) in the personal "Council of AI \|\| Council Network" developer account |
| `REACHLY_META_APP_ID`, `REACHLY_META_APP_SECRET` | Personal Meta app (Facebook Login), owned by the Council Facebook account, not the Hygaar portfolio |
| `REACHLY_META_LOGIN_CONFIG_ID` | `3224979434360539` (Facebook Login for Business configuration; when empty, classic scopes are requested) |
| `REACHLY_META_GRAPH_VERSION` | Optional, default `v25.0` |
| `REACHLY_AUTOPILOT_ENABLED` | Optional, default `true`; `false` stops the scheduler job |
| `REACHLY_PUBLIC_BASE_URL` | `https://reachly.nftforger.com` (callbacks and Instagram image URLs) |

Type secrets at a hidden prompt on the server; never paste them into chat, commands or Git.

## App setup

**X** (done 2026-10-17): app permissions Read and write; type Web App (confidential client);
callback `https://reachly.nftforger.com/channels/oauth/x/callback`; website
`https://reachly.nftforger.com`. The developer account is Pay Per Use and had $0.00 credits:
posting fails with "Add X API credits" until credits are bought.

**Meta** (done 2026-10-17): app **Reachly Personal Channels**, App ID `1747562673749332`, created in
the personal developer account (Rohit Sharma profile, contact councilnetwork.agents@gmail.com), with
**no business portfolio** (never the Hygaar portfolio). Use cases: "Manage everything on your Page"
(added `pages_manage_posts`, `pages_read_engagement`) and Instagram API "setup with Facebook login"
(content permissions). Facebook Login for Business: valid OAuth redirect URI
`https://reachly.nftforger.com/channels/oauth/meta/callback`; configuration **Reachly channel
publishing**, ID `3224979434360539` (user access token; `business_management`, `instagram_basic`,
`instagram_content_publish`, `pages_manage_posts`, `pages_read_engagement`, `pages_show_list`).
App domain `reachly.nftforger.com`. The app is unpublished (Development): only people with a role on
the app can connect, which covers the owner's own Pages. Instagram must be a professional account
linked to the Page.

## Acceptance still needed

Source and tests only (2026-10-17). Real acceptance needs: personal Meta app created, both apps'
keys on the server, deployment, connecting Council's Page/Instagram/X, X credits, and one reviewed
live post per channel with its permalink checked.

## Email-code sign-in and client access (2026-10-19)

- **Owner**: while signed in (Telegram), open **Channels → Sign-in email**, enter an email and confirm
  the 6-digit code. Afterwards `/login` → "Email me a code" signs in to the same account.
- **Clients**: on a project card, **Client access → Invite client** stores the email for that one
  project and emails an invitation. The client signs in at `/login` with that email and lands on
  `/client`: their project only, where they connect their own Facebook/Instagram/X and approve posts
  or ask for changes. Drafts with changes requested are held back from autopilot. Owner pages
  (`/channels`, `/studio`, settings) return 401 for clients. **Remove** revokes access immediately.
- Codes: six digits, HMAC-hashed, single use, 10 minutes, 5 attempts, 5 codes per email per hour. No
  passwords are stored. `/auth/email/start` replies the same whether or not the email has access.
- An email belongs to one sign-in (owner or one client project).
- Meta app is unpublished: a client can connect Facebook only if their Facebook user has a role on the
  app (App roles → add as Tester) or if they make the owner's profile a Page admin and the owner
  connects. Self-serve for anyone needs App Review. X works for any account.

| Variable | Value |
|---|---|
| `REACHLY_SMTP_HOST` / `REACHLY_SMTP_PORT` | e.g. `smtp.gmail.com` / `587` (STARTTLS; `465` uses SSL) |
| `REACHLY_SMTP_USER` / `REACHLY_SMTP_PASSWORD` | Council Gmail address and its app password (copy from Council's env yourself) |
| `REACHLY_SMTP_FROM` | e.g. `Reachly <councilnetwork.agents@gmail.com>` |
