# Session: Human teleprompter script API

**Developer:** Codex
**Date:** 2026-10-03
**Quality Review:** Passed local review; live provider acceptance pending

## What We Worked On
- Added a text-only 60/75/90-second doctor/clinic-owner script operation.
- Reused business grounding and timing concepts without invoking long-form media.

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| generation_contract.py | v3 script_options; legacy serializer compatibility | Typed backward-compatible API | Contract |
| teleprompter.py | Structured cues, pauses, sources and duration checks | Human speaking copy | Content |
| generation_worker.py | Text-only dispatch and script prompt version | Existing durable queue | Worker |
| test_teleprompter.py | Contract, bounds, provenance, no-media and replay tests | Regression protection | Tests |

## Verification
- 155 tests in tests/ pass; one additional subtest passes.
- Root pytest collection also selects an unrelated deploy LinkedIn login script
  requiring bundled Chromium; it failed before login because Chromium was absent.
  The intended tests/ suite passed without installing packages or logging in.
- Hyclinics local browser QA exercised this API and worker using a fake LLM only.
- No real provider, ElevenLabs, publishing or remote deployment action performed.

## Deploy State
- SaaS/generation: branch prepared for PR; deploy before Hyclinics consumer.
- Self-hosted: unchanged.
- Platforms: unchanged; no posts sent.

## Risks / Follow-ups
- Estimates assume approximately 126 words/minute; actual delivery varies.
- Generated healthcare copy needs doctor review and real-provider quality checks.
- Rotate previously exposed credentials before live acceptance.
- See docs/TELEPROMPTER_API.md; merge through normal main deployment workflow.

## Next Session Start Here
- Verify both PR CI results and merge Reachly first.
- Verify actual deployed revision and run one approved synthetic script request.
