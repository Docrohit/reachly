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

## First release compatibility check

The original personal database kept telegram_chat_id NOT NULL. The first
workspace provisioning attempt failed on that historical constraint and the
release restored the previous code/configuration and SQLite backup automatically.
The old public site remained healthy. Workspaces now receive unique namespaced
non-Telegram identifiers; they still use the owner's login and cannot sign in
independently. A regression test covers the original NOT NULL schema.

GitHub branch push succeeded. PR creation was refused by the current CLI account
and the connected integration (permissions); no PR or GitHub CI pass is claimed
for the initial push. The test workflow now also runs on codex task branches.

## Final release and end-session checks

- Release code: b379b607669e92a6d066094d57586e28597952cb.
- 185 tests and one subtest passed locally and in the staged personal-server
  release. The original production SQLite backup was also migrated and seeded
  twice in isolation; the second pass created no duplicate businesses.
- GitHub CI succeeded: https://github.com/Docrohit/reachly/actions/runs/37663145785.
- Personal deployment succeeded after a private code/configuration and SQLite
  backup. Service reachly-saas is active; public HTTPS health reports the release
  revision. No work-product installation was changed.
- Council of AI (workspace 2) and Council Network (workspace 3) are under the
  existing personal owner login. Both have source-grounded profiles and initial
  project notes, dry-run enabled, schedules disabled, and no platform credentials.
- Public personal login page displays reachlypersonalbot. Authenticated route
  checks were performed with an internal owner test session; no OTP message,
  paid model generation, or social publication was triggered.
- GitHub code is pushed to codex/rohit-personal-reachly-sync-2026-10-07. Main has
  not been changed. PR creation was denied by current API permissions; the owner
  can open the comparison while signed into the personal GitHub account.
- End-session prompt executed: reviewed changes, checked secret patterns,
  compilation/tests/shell syntax/diff, live service and served behavior, and
  recorded this handoff. The final documentation commit follows the tested code
  release; its source snapshot will be synchronized without changing runtime code.

## Next session

Use personal Reachly's AGENTS.md and start prompt. Log in at the personal site,
open Businesses, then choose Council of AI or Council Network. Add each project's
AI keys and X/Instagram accounts in Settings. Review the initial facts/goals,
generate a draft in Studio, and enable Live mode only when ready to publish.
Automatic social metrics sync and direct SaaS2point0 API integration remain
future work; pasted input and measured analytics entry are available now.
