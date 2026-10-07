# Personal Reachly restart and combined product

Date: 2026-10-07 (Asia/Kolkata).

## User direction

Continue the original personal Reachly with the later generation upgrades, under
Docrohit/reachly. Reachly itself owns generation, publishing and performance
feedback for any project/business/service. Initial requested business workspaces
are Council of AI and Council Network. The owner will add provider and platform
credentials. Deploy the personal site at reachly.nftforger.com.

## Completed implementation

- Replaced active identity, agent instructions, goals, prompts and release docs
  with personal Reachly context. Historical operational docs/configs archived.
- Retained copied generation APIs, ideas, teleprompter, research, contributions,
  branding and performance capabilities. Restored personal content-assets UI.
- Personal Telegram login and business workspace switching. Each workspace owns
  its profile, inputs, keys, platform connections, drafts, history and schedule.
- Studio: save project/SaaS2point0 text, sourced research, measured performance;
  research through the business's Gemini key; generate drafts; explicitly publish
  via connected adapters. Claims publishing once and preserves uncertain outcomes.
- Analytics UI records measured post metrics for future generation feedback.
  Automatic platform analytics retrieval is not implemented.
- Standalone repo context is opt-in and bounded to the selected repo. Hosted
  businesses cannot inherit work-server credentials or unrelated context.
- Legacy identity bridge is disabled by default. Internal compatibility names
  and schema remain; no external identity API is required for personal operation.
- Scheduling defaults off; dry-run defaults on. Identity changes disable platform
  modes and scheduling. Work-specific deploy/provisioning removed from GitHub CI.
- Added an idempotent seed script for the two Council profiles, based on their
  inspected READMEs, without invented prices/results or copying credentials.
- Added Personal/AGENTS.md outside this repository to override stale portfolio
  routing for future personal sessions.

## Validation before release

- 184 tests passed, 1 subtest passed; existing deprecation warnings remain.
- Python compilation, shell syntax checks, git diff --check passed.
- Browser-rendered workspace and studio flows checked at desktop/mobile widths;
  no mobile horizontal overflow in the business switcher.
- Active core docs, prompts, env example and product UI have no work-brand names.
- Real research, generation, Telegram delivery, social posting and analytics
  retrieval were not exercised; no personal provider/platform keys are configured.

## Personal target observed before deploy

reachly.nftforger.com serves the personal VPS installation at /opt/reachly-saas,
service reachly-saas. It had one active Telegram account, no profiles or platform
connections, and no live-posting accounts. Its bot is reachlypersonalbot.

Deployment revision, backup and post-release verification will be recorded after
release. A GitHub push alone is not deployment evidence.
