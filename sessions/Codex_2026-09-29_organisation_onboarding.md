# Session: Organisation registration for Hyclinics clinic onboarding

**Developer:** Codex
**Date:** 2026-09-29
**Time:** 16:00
**Quality Review:** Passed

## What We Worked On
- User requested a secret-protected organisation registration API instead of
  per-clinic allowlist maintenance, with normal Ops console clinic creation.

## What Changed

| File / area | Change | Why | Layer |
|---|---|---|---|
| server/generation_api.py | Bounded idempotent registration; explicit client capability; organisation-aware scope | Trusted Hyclinics backend can onboard groups | API |
| reachly/generation_contract.py | Optional organisation ID | Additive generation contract |
| reachly/generation_store.py | Persistent client/org grants and immutable clinic/org bindings | Atomic registration with job acceptance and client isolation | Storage |
| deploy/enable_organisation_provisioning.py | Private backup and atomic capability enablement | One-time rollout through reviewed deployment |
| .github/workflows/deploy.yml | Explicit SaaS-only activation input | No manual per-clinic server operations |
| tests | Auth, membership, legacy idempotency, deployment helper | Prevent scope and deployment regressions |

## Verification
- 134 tests plus one subtest passed; compileall passed.
- Workflow YAML parsed; activation helper tested for preservation, idempotency,
  missing-config rejection and private backup permissions.
- Real local HTTP bridge with Hyclinics and an empty clinic allowlist: automatic
  organisation registration, two distinct mocked images, selected customer
  approval, zero duplicate imports and zero publications.
- Reviewed actual diff; no provider prompt, public posting, unrelated scheduler,
  secret value or production organisation identifier changes.

## Deploy State
- Personal SaaS: new code not deployed. Existing runtime still uses static scope.
- Hygaar self-hosted: unchanged.
- Platform status: no social publishing performed.

## Risks / Follow-ups
- Merge and deploy Reachly with the explicit activation input before the Hyclinics
  consumer deploys. Real provider image acceptance remains pending.
- The service credential holder is trusted to attest clinic membership from its
  database. Browser callers never receive that credential.
- Clinic transfer between organisations is deliberately rejected once bound;
  an explicit transfer/reconciliation flow is outside this change.
- Additional ledger tables preserve existing data. Rolling back disables new
  onboarding but does not remove existing stored jobs.

## Next Session Start Here
- Follow docs/business-generation-api.md rollout order, then verify a real clinic
  request. Do not equate synthetic images or green CI with real-provider success.
