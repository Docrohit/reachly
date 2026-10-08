# Session: Visual quality and personal image-post API

**Developer:** Codex
**Date:** 2026-10-08
**Time:** 22:30 IST
**Quality Review:** Issues fixed

## What We Worked On

Implemented the requested image-quality upgrades in personal Reachly, with a separately
ported work-service branch. Started from latest personal main after confirming PR #2 merged.
No work credentials, account data or deployment configuration were copied.

## What Changed

| Area | Change | Why | Layer |
| --- | --- | --- | --- |
| Visual pipeline | Structured planning, actual reference pixels, shape/resolution, original-image edits, deterministic text/logo composition and vision review | More relevant, controllable images and visible quality failures | Generation |
| Audit records | Exact text/final image/review prompts, models/settings, reference copies/hashes, raw/final images, revision feedback and linkage | Inspect and reproduce decisions without keys | Private storage |
| Personal API | Workspace token creation/rotation/revocation, bounded payloads, atomic/idempotent jobs, synchronous wait with polling fallback, image/base64 and audit replies | curl/Postman access using each workspace's own provider keys | SaaS |
| Studio | Reference uploads, shape/resolution/headline/CTA controls, completed-draft audit link | Expose visual controls in personal Reachly | UI |
| Documentation | IMAGE_QUALITY.md, IMAGE_POST_API.md, Postman collection | Save the input-quality recommendations and usage examples | Docs |

## Verification

- Full suite: 214 passed and one subtest; compilation and diff checks passed.
- Includes provider-payload pixels/config, 4K portrait dimensions, review failure/uncertainty,
  original-image edits preserving copy, token rotation/revocation/scope, UUID replay, input
  validation before provider use, hourly limits and competing atomic claims.
- Paid providers mocked. No social publishing, scheduling or live paid generation performed.
- The selected SDK supports ImageConfig; declared google-genai >=2.28 to preserve that capability.

## Deploy State

This branch is for PR review, not deployed. Existing personal production is unchanged.
The API and controls become available after deployment; do not describe them as live yet.
The new additive imageapikey table is initialized by normal app startup. Private generation
records need writable storage and operator-managed retention. API request envelopes require
at least 16 MB proxy headroom. Provider keys still require actual workspace configuration.

## Risks / Follow-ups

Planning and mandatory review add provider calls and cost. Review is a conservative assistance
gate, not proof of visual or clinical accuracy. No automatic paid repair loops. API callers may
explicitly disable review; that is recorded as disabled, not passed. Real generation/edit
acceptance still needs the personal workspace's own keys. Unicode deterministic text requires
an installed font via REACHLY_LAYOUT_FONT. API output is not automatically imported to Studio.
Legacy article/video and external media paths are not fully migrated to the new planner.

## Next Session Start Here

Review the PR and its CI, then use the personal release runbook if deploying. Check /api-access
and one scoped curl request. Verify an actual generated image and image-only revision using
personal keys, including failed-review behavior and saved audit. Keep platform schedules unchanged.
