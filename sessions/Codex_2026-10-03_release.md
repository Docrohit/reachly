# Session: Content Factory PR Release Preparation

Date: 2026-10-03. Developer: Codex.

User approval now covers committing and pushing the implemented upgrades and
creating a PR for manual merge into main. This supersedes the publication hold
recorded in earlier session notes. The branch matches freshly fetched main at
its base; no unrelated checkout was changed.

Merge this Reachly PR before its Hyclinics companion. Main CI/CD deploys the SaaS
service after tests and restarts the generation worker when its existing runtime
configuration is present. Do not invoke an agent-target deploy for this change.
Verify CI/CD completion before merging Hyclinics, whose new static briefs send
schema-version-two requests. V1 compatibility is retained for existing callers.

No automatic merge, direct server edit, runtime secret change, provider call or
social publication was performed as part of PR preparation. A successful PR
check is not a deployed-revision or live-output claim.

The release preparation reruns compileall and the offline tests directory. The
full Content Factory roadmap is not included: automatic footage editing, AI
carousels, deeper research/GEO weighting and new publishing adapters remain
separate work. The companion Hyclinics contribution flag stays off by default
outside DEBUG pending its documented media safety gates.
