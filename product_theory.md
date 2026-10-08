# Reachly — Product Theory

## Purpose

Reachly is Rohit's independent AI content and publishing product. It helps
founders, creators, and businesses turn their own expertise, product facts,
and goals into useful posts, articles, and videos, with less manual work.

The selected user's brand is the subject of the content. No outside company,
vertical, social account, or identity provider defines Reachly's identity.

## Product flow

1. Collect a business profile, audience, goals, brand voice, and approved facts.
2. Generate content ideas and drafts grounded in those facts.
3. Generate images or narration-led videos when requested and configured.
4. Review voice, claims, account targeting, and media before enabling publishing.
5. Publish through the configured platform adapter and record the outcome.

The copied source includes LinkedIn, X, Instagram, Medium, YouTube, and Facebook
adapters, generation jobs, ideas, teleprompter scripts, contributions, and
performance inputs. Their presence does not prove that a personal account is
connected or that an independent hosted product is ready.

## Product forms

| Form | Purpose |
|---|---|
| Standalone agent | User-owned configuration, data, and social accounts |
| Single-user dashboard | Goals, schedule, preview, and publishing controls |
| Hosted SaaS | Independent onboarding, credential vault, billing, and scheduling |

These share agent code. Hosted sign-in uses a personal Telegram bot. One owner
can create separate business workspaces with isolated settings and credentials.

## Content context

Dashboard goals set direction. Dated knowledge-bank entries and selected product
documents supply facts. A business profile sets the baseline voice and themes.
No content may invent capabilities, customer results, or release status.

The context loader reads the selected repo only, with explicit extra documents
supported through `REACHLY_CONTEXT_DOCS`. Historical handoffs and archived
integration docs are not active strategy. Hosted workspaces use saved project notes, research, and performance feedback.
Standalone use can explicitly select repo documents.

- `thought_leader`: useful insight with a light connection to the user's brand.
- `brand_promoter`: useful explanation of that business's real capabilities.

## Media and publishing

Direct provider integrations include Gemini images and optional Seedance video,
ElevenLabs narration, and OpenAI transcription. Use the user's configured keys.
Older provider integrations are compatibility code, not default dependencies.

Scheduling is configurable per user. LinkedIn and Instagram can be staggered;
Medium articles and long-form video have separate scheduling paths. Examples
are not promises of a running schedule. Start with dry-run and platforms off.

Prefer official APIs where supported. Browser publishing requires maintained
selectors and an authenticated session and can fail on account checkpoints.
Record failures clearly. Verify actual publication, not only a button click.

## Boundaries and success

Reachly is a standalone personal product, not a module of another application.
Separate account data, brand assets, strategy, history, and credentials. Reuse
copied features only when they serve this product's users.

Success means useful on-brand drafts, straightforward onboarding, trustworthy
account targeting, auditable publishing, and a clear account of provider costs.
No personal production or platform success is claimed yet; current evidence
and launch gaps live in `docs/PERSONAL_REACHLY_STATUS.md`.
