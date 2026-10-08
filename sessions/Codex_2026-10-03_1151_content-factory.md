# Session: Content Factory v2 Briefs and Ideas

Date: 2026-10-03. Branch: `codex/content-factory-upgrade`, based on `619a34b`.
Local changes only; no commit, push, PR or deployment.

The generation contract now accepts version-two creative briefs and a three-idea
operation. Ideas return editable scripts and validated public-fact source fields
without generating images. Creative direction reaches planning, copy and image
prompts. Version-one serialization/digests are preserved for in-flight retries.
Provider ownership, tenant isolation and publishing separation are unchanged.

Changed: `reachly/generation_contract.py`, `reachly/generation_worker.py`,
`reachly/content_ideas.py`, `server/generation_api.py`,
`tests/test_content_ideas.py`, `docs/business-generation-api.md`.

Validation: package regression tests under `tests/`, including existing generation
API compatibility, branding and provider routing. All provider outputs were mocked.
An initial root test discovery included the existing deployment LinkedIn login
script and failed because its bundled browser binary was absent; subsequent
regression runs explicitly used `pytest tests -q`. No login/post was performed.

The companion Hyclinics worktree implements private contributions, manual video
and image proposals, prompted recording and exact-version review. Its browser
test used synthetic camera/audio, protected upload/playback, edited MP4 reupload
and a clinic variation request through v2 approval. That is not AI video editing.

Still unimplemented: structured evidence weighting/deeper research, automatic
document extraction, real-footage transcription/editing, AI carousel generation,
per-slide retries, new publishing adapters and richer production-cost metering.
Real-provider quality and physical-device testing remain acceptance gates.
