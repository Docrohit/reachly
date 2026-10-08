# Session: Nano Banana Image Default

**Developer:** Codex
**Date:** 2026-09-30
**Time:** 15:15
**Quality Review:** Passed

## What We Worked On
- Removed Reachly's Gemini 2.5 image-generation default.
- Set standalone and business-generation examples to Nano Banana 2 (`gemini-3.1-flash-image`).
- Added regression coverage so image defaults do not silently drift back.

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| `reachly/agent.py` | Updated `AgentSettings.gemini_image_model` default to `gemini-3.1-flash-image`. | Standalone Reachly agent should use the approved Gemini 3.1 image model by default. | Agent configuration |
| `reachly/config.py` | Updated `GEMINI_IMAGE_MODEL` fallback to `gemini-3.1-flash-image`. | `.env`-based runs without an override must not fall back to Gemini 2.5 image generation. | Configuration |
| `reachly/media.py` | Updated `generate_image_gemini` default model to `gemini-3.1-flash-image`. | Direct image-generation calls should use Nano Banana 2 unless an approved provider config overrides it. | Media |
| `docs/business-generation-api.md` | Updated example provider config image models to `gemini-3.1-flash-image`. | Hyclinics/Reachly operators should see the correct approved image-model example. | Documentation |
| `tests/test_media_branding.py` | Added regression assertions for AgentSettings, AgentConfig, and direct Gemini image defaults. | Prevents accidental reintroduction of Gemini 2.5 image defaults. | Tests |

## Verification
- `/Users/rohitsharma/Desktop/M2026/Main_products/hdb_oct17/reachly/.venv/bin/python -m pytest tests/test_media_branding.py -q`
- `/Users/rohitsharma/Desktop/M2026/Main_products/hdb_oct17/reachly/.venv/bin/python -m pytest tests -q`
- `/Users/rohitsharma/Desktop/M2026/Main_products/hdb_oct17/reachly/.venv/bin/python -m compileall reachly server tests`
- `git diff --check`

## Deploy State
- Personal SaaS: Not deployed in this session.
- Hygaar self-hosted: Not deployed in this session.
- Platform status: Source-only change pending PR review/merge.

## Risks / Follow-ups
- Production `REACHLY_GENERATION_CONFIG` can still explicitly set any approved image model. After merge, verify the protected provider JSON for `hyclinics_owned` uses `gemini-3.1-flash-image`.
- Previously generated images are unchanged; regenerate affected clinic content after deploying this source change.

## Next Session Start Here
- Merge and deploy this PR through the Reachly workflow.
- Confirm live provider config image model for `hyclinics_owned`.
- Generate a fresh two-image pair for New Clinic and verify no logo placeholder appears when no logo is supplied.
