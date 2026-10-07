# Session: Performance signals in business generation

**Developer:** Claude Code (with Rohit)
**Date:** 2026-10-04
**Time:** 18:42
**Quality Review:** Passed

## What We Worked On
- Optional `performance` input so Hyclinics can share each clinic's measured post results.
- Use of those results in planning, copy, ideas and teleprompter-script context.

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| reachly/generation_contract.py | Bounded `Performance` model (extra fields rejected, ≤30k chars); omitted from serialization when absent | Typed contract; legacy digests/in-flight replays unchanged | Contract |
| reachly/generation_worker.py | `performance_signals` + fixed guidance in context; planner directive; `performance_used` in result; prompt version v3 | Favour what works, keep exploration, never justify claims | Worker |
| tests/test_content_ideas.py | Signals reach planner/copy/ideas; bounds; digest stability | Regression coverage | Tests |
| docs/business-generation-api.md | Performance section | Consumer handoff | Docs |

## Verification
- `python -m compileall -q reachly server tests` passed.
- `pytest tests -q`: 174 passed, 1 subtest. Provider calls mocked; no posting.

## Deploy State
- Personal SaaS / generation service: deploys via main CI/CD after merge; merge before Hyclinics `codex/official-social-publishing`.
- Hygaar self-hosted: unchanged.
- Platform status: unchanged; no posts sent.

## Risks / Follow-ups
- Signal quality depends on clinics publishing via official APIs; nothing is sent until 3 measured posts exist.
- Real-provider output review still required for healthcare copy.

## Next Session Start Here
- Merge this PR, confirm CI/CD deploy, then merge the Hyclinics companion.
