# Session: Clinic contributions in business generation

**Developer:** Claude Code (with Rohit)
**Date:** 2026-10-05
**Quality Review:** Passed

## What We Worked On
- Optional `contributions` input: text-only material a business shared itself (awards, events, talks, news).
- A `focus` item turns a post request into a post about that material.

## What Changed

| File / area | Change | Layer |
|---|---|---|
| reachly/generation_contract.py | `Contribution` model (≤10, bounded, extra fields rejected, http/https links only); one focus, posts only; omitted when absent | Contract |
| reachly/generation_worker.py | `clinic_contributions` + fixed guidance in context; planner focus directive; `contributions_used`; prompt v4 | Worker |
| reachly/content_ideas.py, reachly/teleprompter.py | Ideas and scripts may cite `clinic_contributions` only when supplied | Worker |
| tests/test_content_ideas.py | Focus reaches planner and copy; provenance; bounds and digest stability | Tests |
| docs/business-generation-api.md | Contributions section | Docs |

## Verification
- `pytest tests -q`: 177 passed, 1 subtest. Provider calls mocked; no posting.

## Deploy State
- Merge and deploy before Hyclinics `codex/material-driven-generation`, which starts sending `contributions`.

## Risks / Follow-ups
- Real-provider review of how often contributions appear in daily posts.
