# Hygaar Stabilization Timeline: July 15 to August 14, 2026

> Status: CURRENT operational record.
> Created: 2026-08-14.
> Scope: Hygaar core platform backend, console, dev/QA/prod server split, Harsh-led v2/stage work, production hotfixes, and the QA stabilization decision.
> Security note: this document intentionally avoids private IPs, SSH keys, passwords, tokens, and provider secrets. Use `server_info.md` in the relevant repo/workspace for sensitive server lookup details, and follow `deploy_rules.md` for deploy rules.

## Why This Exists

Between July 15 and August 14, 2026, Hygaar had three streams moving at the same time:

1. Production bug fixing on the existing platform.
2. Harsh's v2 restructuring and worker redesign work.
3. New business-critical product features for Micasa/Libas style workflows.

Those streams overlapped across `prod-env`, `qa-env`, `dev-env`, backend worktrees, console worktrees, and a new dev/QA server split. This created confusion about which code was stable, which code was experimental, and which hotfixes must be replayed when QA is rolled back.

This document is the shared memory for that period. It should be read before:

- changing QA/prod branches;
- changing Celery queues or worker service definitions;
- debugging GPT Image 2.0 modular/image-to-image issues;
- moving Harsh's v2/stage work across environments;
- rebuilding QA from a known-good date;
- explaining July 15 to August 14 decisions to the team.

## Executive Summary

As of August 14, 2026:

- Production should stay on the stable production line and receive only focused production hotfixes.
- QA should be treated as the recovery/stabilization environment: a known-good July 27 style base plus selected stable feature work and production hotfixes.
- Dev should carry Harsh's v2 code, new task/worker redesign, and Stage 3 infrastructure experiments until they are tested and stable.
- Harsh's Stage 1 v2 code restructure is a code organization change inside the same Django app.
- Harsh's Stage 2 task/worker redesign is a larger behavior and operations change and should not be mixed into QA/prod casually.
- Harsh's Stage 3 ECS/Fargate/container infra work should remain isolated until explicitly promoted.
- Several late July features were business-critical and should be preserved on QA: inventory SKU fetch, satellite grouping/assignment, Agent 1/Agent 3C usage of those assets, and Agent 6B marketplace work.
- Production GPT Image 2.0 modular failures were handled as production hotfixes, including moving image generation back to the Images API path where required, hardening reference-image handling, fixing async polling, and avoiding composition-id shadowing.
- Server operations require an OpenVPN check before SSH. If the VPC route is absent, ask the user to connect OpenVPN. Do not edit servers manually.

## Glossary

| Term | Meaning |
|---|---|
| Old monolith | Pre-v2 backend layout where most code lived in large flat files such as `models.py`, `views.py`, `celery_tasks.py`, and many loose root modules under `hdb_app`. |
| V2 / Stage 1 | Harsh-led package-by-layer and package-by-domain restructuring under the same Django app. This moves code into `views/`, `services/`, `models/`, `tasks/`, etc. |
| Stage 2 | Harsh-led task and worker redesign: C2/C3/C4 style task flow, dispatcher/processor/poller changes, Redis/queue/service topology changes. |
| Stage 3 | Infrastructure rejig around containers/ECS/Fargate and related deploy/runtime changes. |
| Production line | `prod-env` and production app server path used for live clients. This should accept focused hotfixes only during stabilization. |
| QA recovery line | The QA branch/environment rebuilt from a known-good July 27/late-July base plus approved hotfixes and selected stable features. |
| Dev v2 line | `dev-env`/backend-v2 line where Stage 1/2/3 work can continue while being tested. |
| Modular GPT Image 2.0 | Image generation flow where prompt plus multiple reference images are sent to GPT Image 2.0 for lifestyle/studio/modular outputs. |
| RCA | Root Cause Analysis: what failed, why it failed, why it escaped earlier, and what fix/prevention is required. |

## Repositories And Copies

This document is intentionally duplicated across active Hygaar repos/worktrees for discoverability. When editing it, keep the copies in sync.

Primary workspace location:

- `docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`

Expected repo-local copies:

- `hdb_backend_v2/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `hdb_backend_qa_prod_hotfixes/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `console_hygaar/console_live/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `console_hygaar/console_live_qa_prod_hotfixes/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `geo_genai/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `reachly/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `hygaar_console/console_live/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `hygaar_website/hygaarwebsite/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `hygaar_deal_desk/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`
- `hygaar_unit_economics_dashboard/docs/HYGAAR_JUL15_AUG14_2026_STABILIZATION_TIMELINE.md`

Historical hotfix worktrees may also contain copies, but they are not the canonical place to continue work unless explicitly selected.

## Starting Point: Old Monolith Code

Before the v2 restructure, the backend was a working but large monolithic Django app:

- `hdb_app/models.py` held many model definitions in one file.
- `hdb_app/views.py` held a very large amount of HTTP logic.
- `hdb_app/celery_tasks.py` held many task definitions and pipeline logic.
- Feature-specific logic often lived directly in view/task modules.
- Celery queue routing and service definitions were partly historical and partly patched over time.

This old shape had the advantage of known production behavior. It had the disadvantage of being hard to reason about, hard to test, and easy to break when multiple developers touched the same pipeline.

The stabilization plan does not say "old monolith is better." It says:

- production needs predictable behavior now;
- QA should recover from a known-good state;
- v2/stage work should continue on dev until it is proven end-to-end.

## Harsh's Three Stages

### Stage 1: V2 Code Restructure

Commit evidence starts around July 23-27, 2026.

Main intent:

- restructure `hdb_app` from flat monolith into package-by-layer and package-by-domain structure;
- keep the same Django app and avoid unnecessary migration churn;
- create clearer homes for views, services, tasks, models, middleware, admin, and tests;
- reduce future collisions in giant files.

Observed structure in v2 docs/AGENTS:

- `hdb_app/views/<domain>/`
- `hdb_app/services/<domain>/`
- `hdb_app/models/<domain>.py`
- `hdb_app/tasks/<domain>.py`
- `hdb_app/urls/routes.py`
- `hdb_app/middleware/`
- `hdb_app/agents/`
- `hdb_app/admin/`
- `hdb_app/tests/`

Important note:

- Stage 1 is mostly code organization, but because it moves many call sites, it can still create regressions through imports, path changes, route differences, and incomplete ports.

### Stage 2: Task And Worker Redesign

Commit evidence starts around July 27-30 and gets merged into dev around August 1-2, 2026.

Main intent:

- redesign agent task processing;
- introduce C2/C3/C4 style architecture;
- split or consolidate dispatchers, processors, and pollers;
- change queue routing and worker service topology;
- support larger, more reliable multi-agent workloads.

Why it is risky:

- Celery topology changes are runtime behavior changes, not just code cleanup.
- Small queue routing mistakes can strand tasks, send work to the wrong worker, or overload the wrong queue.
- The frontend can look correct while backend tasks are silently stuck.
- Redis DB, worker process count, systemd service names, and code-level `queue=` choices must all agree.

Operational decision:

- Stage 2 remains on dev/v2 until tested.
- Do not replay Stage 2 into QA/prod during stabilization unless explicitly approved and tested.

### Stage 3: Infra Rejig With Containers/ECS/Fargate

Commit evidence appears around August 5-7, 2026.

Main intent:

- containerize or prepare backend-v2 for ECS/Fargate style deployment;
- update Dockerfiles, task definitions, ALB/health check behavior, static files, build cache, and environment routing;
- isolate v2 deployment experiments from current production behavior.

Operational decision:

- Stage 3 is a separate infra track.
- It should not be mixed into QA/prod recovery unless the team explicitly decides to promote it.

## Server Split And Environment Policy

During this period, the team split server responsibilities:

- Production stayed on its own production app server.
- Dev and QA moved to a new shared dev/QA app server.
- Worker and queue definitions differed across prod, QA, dev, and v2 at different moments.

Rules going forward:

1. Production is for live client work and focused hotfixes.
2. QA is for stable release testing and recovery, not untested Stage 2/Stage 3 work.
3. Dev is where v2/stage work continues until verified.
4. Do not SSH-edit or SCP code onto any server.
5. Use CodeDeploy/GitHub Actions according to `deploy_rules.md`.
6. Before SSH/log inspection, verify OpenVPN is connected. If not connected, ask the user to connect it.
7. Keep server addresses and credentials in `server_info.md` or approved secret stores only, not in this timeline.

## Final Stabilization Decision

The operational decision from the August 13-14 discussion:

| Environment | Intended state |
|---|---|
| Prod | Keep working production. Apply only focused production bug fixes. Treat the modular GPT Image 2.0 issue as a direct production fix. |
| QA | Revert/rebuild to the known-good July 27/late-July line, then replay only approved production hotfixes and selected stable feature work. |
| Dev | Keep Harsh's v2 code, Stage 2 task/worker redesign, and Stage 3 infra work here until tested. |

The reason:

- QA and dev had become hard to reason about after Stage 1/2 merges and multiple fixes.
- Production also had bugs, but production bugs were isolated enough to fix directly.
- Micasa/Libas style customer work needs a stable operational environment now.
- Harsh's work is valuable but needs a separate stabilization lane.

## Features That Must Not Be Lost In QA Recovery

These were added in the July 28-August 2 window and are business-critical:

| Feature | Backend commits/examples | Console commits/examples | Keep on QA? |
|---|---|---|---|
| Inventory SKU fetch | `b7d20360`, `1ecaeaf9`, `eed1edc9`, `7b0a2ecf` | `65d52ca`, `5bb47b6`, `ca8f59a`, `e8b0dd4` | Yes |
| Satellite grouping | `2e6d19c1`, `fe625072`, `ad48a8cb`, `cc02a9f0`, `5aba1353`, `6d42e53a` | `9e4c3fd`, `880f4d2`, `21d268b`, `2ea04d0`, `7343a4a`, `930567d` | Yes |
| Satellite assignment controls | `c8b098d4`, `0dee494a` | `b122269` | Yes |
| Agent 1/Agent 2 satellite assignment parsing/use | `0e8aedde`, `5741a33b` family in dev; confirm exact port before promotion | Console assignment UI above | Yes, after verification |
| Smart 3C targeted editor | `248a82f1`, `96b276c4` | `a88299a`, `199b59c` | Yes |
| Agent 6B marketplace/direct upload | Deepak July 29-31 chain, plus QA metadata port `3cc8ffc1` | Deepak July 29-August 1 Agent 6B UI chain | Yes, if tested |

## Production Hotfixes To Preserve

These fixes are part of the recovery baseline and should be present wherever QA is meant to mirror production behavior:

| Area | Commit examples | Why it matters |
|---|---|---|
| GPT Image 2.0 Images API routing | `6e98f171`, `4d7b8001`, `d24d958`, `31d8ccfc` | GPT Image 2.0 generation must use the correct OpenAI image path where the Responses API is not suitable for image creation. |
| GPT Image 2.0 model key/payload mapping | `9f5e6c3d`, `d24d958`, `31d8ccfc` | Prevents frontend/backend mismatch around labels such as GPT Image 2.0, GPT 1.5, internal model ids, and payload shape. |
| Modular GPT Image 2.0 hardening | `69f13f45`, `5fd82c51`, `31d8ccfc` | Handles multiple references, worker execution, and composition-id scoping issues. |
| Async GPT image polling in console | `110d7c5` | Prevents UI from showing failure before async backend completion has been polled correctly. |
| JWT/user_id fallback | `3cfafdca`, `f2fe3bc`, `3d2ce6ab` | Prevents production endpoints from failing when frontend payload is missing `user_id` but JWT has it. |
| Vertex/BYOK empty API key bypass | `d879e674`, `3d2ce6ab` | Allows Vertex mode to bypass empty customer API key validation. |
| AI Studio 500/429 error UX | `6f06a4a7`, `29d905fe`, `3d2ce6ab` | Converts provider failures into actionable user-facing errors. |
| Duplicate generation session prevention | `253a88fe` | Avoids duplicate generation sessions for the same batch. |
| CodeDeploy staging cleanup | `68edef67`, `3d2ce6ab` | Prevents stale files from previous deployments from surviving into a new release. |
| Admin static CSS/Whitenoise for QA | `821d97ab`, `6a781733` | Restores Django admin styling when Nginx/static proxy behavior is inconsistent. |
| Marketplace SKU metadata mapping | `3cc8ffc1` | Preserves real SKU/marketplace metadata through Agent 6B marketplace push. |

## GPT Image 2.0 Modular Incident Notes

### What users saw

Around August 12-13, production users saw "Image Failed" in modular/lifestyle image generation, including tests with 6-7 reference images. There was also discussion of flows with up to 14 or 16 images.

### Important distinction

There may have been more than one issue:

- a backend/provider/API issue around GPT Image 2.0 routing and async completion;
- a worker/task execution issue;
- a payload/classification issue where images that should be marked as fine detail or other reference roles were being marked as `original`;
- an operational usage issue where modular prompts were designed for specific labels such as front/back/model/fine-detail/satellite references, not arbitrary unlabeled image packs.

### Working policy after hotfix discussion

- GPT Image 2.0 should support up to 14 reference images in the modular path after the hardening work.
- Seedream 5.0 Pro had a 10 reference image limit in the v2/dev line.
- Nano Banana had been discussed as tolerating 16 references, but provider-specific limits must be enforced by the model adapter.
- Do not silently mark all inputs as `original` if prompt construction expects fine detail/reference roles.
- If a user sends 7 images and it fails, debug the actual backend error first; do not assume it is only image-count related.
- If a user sends 14+ images, enforce model-specific caps before dispatch and return a useful validation message instead of a late worker failure.

### Hotfix implementation areas

The production and QA hotfixes touched:

- backend OpenAI/GPT image generation routing;
- backend modular virtual try-on/generation services;
- backend worker task path for image generation;
- frontend OpenAI image payload mapping;
- frontend async polling for GPT image generation;
- composition id handling to avoid shadowing the real composition being updated.

## Agent 2 Stuck/Empty SKU Incident Notes

The reported production logs for batch `BATCH-51A04DCA` showed:

- Agent 2 campaign orchestrator started.
- Progress initialized with `total_skus: 1`, `total_tasks: 1`.
- Grouping attempted.
- Query returned no SKUs for the batch.
- Fallback to individual processing scheduled 0 tasks.

Related user/team context:

- Agent 1 was reported successful for the batch and returned a SKU id.
- The failure appeared when Agent 2 looked for SKUs and got none.

Working interpretation:

- Treat this as a scope/data linkage issue unless reproduced as a code regression.
- The likely area to inspect is batch id + SKUData lookup + workspace/default-workspace scope consistency.
- Do not assume it is the same root cause as GPT Image 2.0 modular image failure.

Prevention:

- Agent 2 should fail clearly when Agent 1 has results but Agent 2 finds zero rows.
- Logs should include batch id, effective workspace id, owner admin id, project id, and SKUData count without exposing secrets.
- UI/admin bug reports must include Agent 1 status, Agent 2 status, batch id, workspace/project/user context, input CSV/assets, and exact timestamp.

## Worker And Queue Stabilization Checklist

When rebuilding QA or comparing prod/QA/dev, verify code-level queue routing and systemd worker definitions together.

Expected queue families from current ops docs:

- `default`
- `csv_pipeline`
- `csv_bulk`
- `agent2`
- `image_gen`
- `reformer`
- `qc_analysis`
- `qc_regen`
- `delivery_pipeline`
- `video_tasks`
- `tech_agent`

Checks:

1. Every `.delay()`/`.apply_async()` for heavy agent work must route to the intended queue.
2. Worker service files must actually consume those queues.
3. `after_install.sh` must restart the same service names that exist in `deploy/systemd/*`.
4. QA rollback should not accidentally keep Stage 2 dispatcher/processor/poller service definitions if the code was reverted to an older task shape.
5. Redis DB isolation must match environment expectations so dev/v2 workers do not steal QA/prod tasks.
6. Image generation and GPT Image 2.0 modular paths must use the correct worker queue, not `default`.
7. `DJANGO_ALLOW_ASYNC_UNSAFE` must not be used as a shortcut for ORM/thread issues.
8. Log inspection should always identify which service/process handled the task.

## Timeline

### July 15, 2026

- GPT image generation had several quick changes around DALL-E 2 fallback, old model mapping, GPT 5.6 Responses API experiments, and multimodal input formatting.
- This period created important context: GPT Image 2.0 and OpenAI image generation cannot be treated as a generic text Responses API problem.
- Console and backend QA/dev merges continued.

### July 16, 2026

- Optional satellite picker work landed through the `feature/rohit-new-work-20260716` branch.
- Production-style hotfixes addressed project `None` handling in `gemini_virtual_tryon_generate`.
- Agent 3 image encoding was hardened for production image inputs.

### July 17, 2026

- New dev/QA server deployment work happened.
- Multiple CodeDeploy retries fixed environment/setup issues such as virtualenv, `libgl1`, DB env, and DB restore details.
- This is the start of the practical server split period: production separate, dev/QA on new infrastructure.

### July 18-22, 2026

- Worker/autoscale/CORS cleanup happened.
- CSV encoding and Pixx parsing fixes landed.
- Agent 3 GPT Image 2.0 timeout/resolution/refusal/JSON truncation issues were addressed.
- Console Agent UI standardization continued.

### July 23, 2026

- Harsh's Stage 1 v2 restructuring began landing in git history.
- Major commit: domain-driven layered architecture restructuring.
- Related work added v2 deployment scripts, systemd service files, dependency fixes, architecture README docs, v2 CORS origins, and Redis DB isolation for v2 workers.

### July 24-25, 2026

- Video CSV drive link columns were extended with `images` and `assets`.
- Console and backend v2 UI/agent layout work continued.
- Satellite list field length validation was added.

### July 27, 2026

- Backend-v2 merged dev-env and resolved restructure conflicts.
- Context docs were regenerated for the v2 split.
- This became the rough "last known stable-ish QA base" discussed later, though some of Rohit's four upgrades were not all landed yet.

Important nuance:

- July 27 was already in/around v2 Stage 1 territory. It was not purely old monolith.
- The rollback goal is therefore not "go to ancient monolith." The goal is "go to the last QA line that led toward working prod, then replay selected stable work and prod hotfixes."

### July 28, 2026

- Inventory SKU fetch backend and console work landed:
  - exact Micasa ID matching;
  - status access fixes;
  - numeric old ID fallback;
  - workspace sharing/scope;
  - console page for ops to launch Pixx Drive jobs;
  - pagination/lazy thumbnails/resume improvements.
- Satellite grouping schema and APIs started landing.

### July 29, 2026

- Satellite grouping matured:
  - Pixx group previews;
  - shared user saves;
  - allow required satellite folders;
  - queue large satellite CSV parsing;
  - workspace satellite group browser API/UI.
- Deepak's Agent 6B/direct marketplace upload chain started:
  - direct marketplace upload APIs/tasks;
  - Shopify support;
  - numeric product ID handling;
  - console marketplace UI.

### July 30, 2026

- Satellite assignment controls were added in backend and console.
- GPT 2.0 image generation resolution enforcement fixes landed.
- Agent 6B implementation/fixes continued.
- Harsh's Stage 2 worker/task redesign commits appeared:
  - Agent 2 C2/C3/C4 modular architecture;
  - Agents 4-8 C2/C3/C4 Celery pipeline;
  - dispatcher/processor and C3 poller architecture;
  - worker architecture docs.

### July 31, 2026

- Smart 3C targeted Seedream editing landed in backend and console.
- Pixx Drive jobs were explicitly routed to CSV queue.
- Agent 6B/marketplace fixes continued:
  - migrations;
  - primary key fixes;
  - SKU dot preservation;
  - marketplace IDs in metadata;
  - white background/main image fixes;
  - legacy GenAI/simple padding restoration;
  - redis progress updates;
  - workspace fallback handling.

### August 1, 2026

- Backend-v2 architecture was merged into dev-env.
- Dev worker/service deployment scripts and Redis DB routing were updated.
- GPT model mapping fixes occurred, including hardcoded fallback correction.
- Seedream 5.0 Pro reference limit was enforced at 10 in the v2/dev line.
- OpenAI Responses API instructions were added in docs/code paths, but later production debugging showed GPT Image 2.0 generation needed the Images API route where applicable.

### August 2, 2026

- Rohit fixed OpenAI GPT image API routing.
- Console OpenAI GPT image payload fixes landed.
- This is the period the team later associated with Stage 2 worker redesign making QA/dev unstable.

### August 3, 2026

- Production GPT image routing hotfix was merged.
- CodeDeploy staging cleanup was added to prevent lingering files.
- QA/dev continued receiving branch merges and fixes.

### August 4, 2026

- Vertex mode empty API key validation bypass was fixed.
- Duplicate generation session prevention was added.
- QA systemd services were synced with the new dev architecture, adding C3 poller/dispatcher-processor style services and removing older dedicated workers.
- This is important because it may have mixed Stage 2 worker assumptions into QA.
- Console `Profilesetting.jsx` was restored from prod after it was found empty.

### August 5, 2026

- BYOK/AI Studio 500/429 provider error UX improved.
- API route trailing slash and `api/v2` compatibility aliases were patched.
- Harsh's Stage 3 container/ECS/Fargate related work started appearing:
  - DB SSL mode;
  - Whitenoise/static behavior;
  - Dockerfile entrypoints;
  - build caching;
  - ALB health check host handling;
  - ECS task definition sizing.

### August 6, 2026

- Satellite assignment CSV parsing landed so Agent 1/Agent 2 assigned mode could resolve satellites.
- SmartResizeEngine/recommended size support was added for resizing endpoints.
- Stage 3 ECS task definition work continued.

### August 7, 2026

- Backend-v2 was configured for isolated prod ECS deployment experiments.
- Many production/dev bug fixes landed:
  - model casting generation;
  - swap model CSV shot count;
  - Agent 8 video merge missing segments;
  - guideline sharing visibility;
  - stylised studio all-angles and custom angle issues;
  - ghost PDP and satellite inclusion;
  - top/bottom focus and pose diversity.

### August 8-10, 2026

- Multiple bug-fix loops continued around:
  - Aditya admin access;
  - model swap Agent 2 failure;
  - hardcoded use_case override removal;
  - ffprobe path/duration fixes;
  - image guideline sharing;
  - Agent 2 `str` object crash;
  - workspace invite URL;
  - raw instructions/shot count handling;
  - Agent 8 merge freeze fixes;
  - swap_model enforcement;
  - UI dropdown use case propagation;
  - deployment indentation/signature fixes;
  - Fast Path regressions around templates/satellites/Ghost PDP/Crop/model face index.

This is the period where the team felt the new code paths were creating broad instability.

### August 11, 2026

- JWT fallback/user_id validation fixes landed.
- GPT Image 2.0 endpoint was fixed to extract user id from JWT when missing in payload.

### August 12, 2026

- Harsh landed fixes around modular image and wrong queue in Pixx, optional satellite 3-shot limits, hidden queue setting, and satellite CSV upload enforcement.
- Rohit landed production GPT Image 2.0 modular hardening.
- Production discussion focused on whether modular GPT Image 2.0 could handle 7, 14, or 16 references and whether image labels were correct.

### August 13, 2026

- Rohit fixed composition id shadowing in the GPT Image worker.
- Production GPT Image 2.0 modular hardening was merged.
- Console async GPT image polling was merged and ported to QA.
- QA received hotfix ports:
  - prod image hotfixes;
  - remaining prod hotfixes;
  - marketplace SKU metadata mapping.
- QA admin static CSS was fixed with collectstatic/Whitenoise changes.
- Agent 2 stuck/empty SKU issue was investigated from production logs and treated separately from GPT image failure.
- Team decision solidified:
  - prod: stabilize with focused fixes;
  - QA: rollback/rebuild from known-good late-July state plus selected fixes;
  - dev: keep v2/stage worker/infrastructure work.

### August 14, 2026

- This cross-repo stabilization document was created.
- `AGENTS.md` files were updated to point future agents/developers to this timeline before touching QA/prod/stage work.

## Branch And Commit Evidence

### Backend

Representative backend branches/worktrees:

- `hdb_backend_v2` on `codex/gpt-image2-modular-hardening` / v2-related history.
- `hdb_backend_qa_prod_hotfixes` on `codex/qa-prod-hotfixes-rollback-base-20260813`.
- `origin/prod-env` included GPT Image 2.0 modular production hardening by August 13.
- `origin/qa-env` in the QA hotfix worktree was rebuilt to the QA recovery line by August 13.

Representative backend commit groups:

- Stage 1 v2 restructure: `49d2c886`, `8e432777`, `76428fb3`, `1ce4c48a`, `36467670`.
- Stage 2 task/worker redesign: `96a975c2`, `2f371734`, `ca8d11f4`, `a68bfb6d`, `e58b6c02`, `544fbaf1`, `d993fdc8`, `ea8a6fe9`, `487ad6d3`.
- Stage 3 infra/ECS: `bd1a29c3`, `fc0fa21f`, `caf2d1d1`, `14369804`, `05fd54b1`, `6925db4d`, `379df17a`, `fc1ccfff`, `217895e8`, `96bd1f4a`, `15bc8ea3`, `5bc70c01`, `27b4b02`, `f3d1f157`.
- Rohit's inventory/satellite/Smart3C feature chain: `b7d20360`, `1ecaeaf9`, `eed1edc9`, `7b0a2ecf`, `2e6d19c1`, `fe625072`, `ad48a8cb`, `cc02a9f0`, `5aba1353`, `6d42e53a`, `c8b098d4`, `0dee494a`, `248a82f1`, `96b276c4`.
- Deepak's Agent 6B/marketplace chain: July 29-31 feature/fix commits, plus `3cc8ffc1` QA metadata mapping port.
- Production GPT Image 2.0 hotfixes: `6e98f171`, `69f13f45`, `5fd82c51`, QA ports `31d8ccfc`, `3d2ce6ab`.

### Console

Representative console branches/worktrees:

- `console_hygaar/console_live` on `dev-env`.
- `console_hygaar/console_live_qa_prod_hotfixes` on `codex/qa-prod-hotfixes-20260813`.
- `origin/prod-env` included async GPT image polling by August 13.
- `origin/qa-env` included the same async polling hotfix by August 13.

Representative console commit groups:

- Inventory SKU fetch UI: `65d52ca`, `5bb47b6`, `ca8f59a`, `e8b0dd4`.
- Satellite grouping UI: `9e4c3fd`, `880f4d2`, `21d268b`, `2ea04d0`, `7343a4a`, `930567d`, `b122269`.
- Smart 3C UI: `a88299a`, `199b59c`.
- Agent 6B/marketplace UI: July 29-August 1 Deepak commits around direct upload, Shopify, mapping, batch selection, detailed errors, and metadata.
- GPT image payload and polling: `d24d958`, `110d7c5`.

## Verification Already Done During Stabilization

Recorded verification from the August 13 QA hotfix work:

- Changed backend Python files compiled successfully.
- `git diff --check` was clean.
- `python manage.py check` passed locally with a local-only `SECRET_KEY`.
- Full Django tests did not run locally because DB `NAME` was unset in the local environment.
- AWS deploy status could not be checked locally because AWS credentials were invalid (`InvalidClientTokenId`).

Any future promotion should still run environment-specific checks and at least one end-to-end generation flow.

## Operational Bug Report Protocol

For generation failures, every report should include:

- environment: prod, QA, dev, or v2;
- exact timestamp with timezone;
- user id / workspace id / project id where relevant;
- batch id and composition id;
- selected model label and internal model id if visible;
- use case and product type;
- all input assets or a Drive folder;
- prompt/guideline text;
- number of reference images;
- reference labels such as original, fine detail, model, satellite, fabric, front, back;
- frontend screenshot and backend/admin link;
- whether Agent 1 passed;
- whether Agent 2 produced shot plans;
- worker/service log lines around the failure.

Without those details, the team cannot reliably distinguish provider failure, prompt/payload issue, queue routing, workspace scope, and operational misuse.

## Promotion Rules From Here

1. Do not merge dev/v2 into QA wholesale during stabilization.
2. Do not merge Stage 2 worker redesign into QA/prod without a worker topology review.
3. Do not mix Stage 3 ECS/container work with the current prod server line.
4. Use feature branches for fixes, even if the target is production.
5. Keep prod hotfixes small and replayable.
6. After a production hotfix, record:
   - branch;
   - commit;
   - files touched;
   - reason;
   - QA replay status.
7. Before changing image generation, inspect:
   - frontend model catalog/payload mapping;
   - backend model adapter;
   - provider API path;
   - reference image cap;
   - async status/polling path;
   - Celery queue.
8. Before changing Agent 2 or satellite flows, inspect:
   - Agent 1 output;
   - SKUData rows;
   - batch id;
   - workspace/default workspace scope;
   - project filtering;
   - satellite assignment mode.

## Open Questions To Keep Visible

- Which exact July 27 commit is the canonical "QA that made prod" baseline? The current working assumption is late-July v2 Stage 1 plus selected stable features, not pre-v2 monolith.
- Which of the August 7-10 bug-fix chain should be promoted to QA after the immediate recovery? Some may be valuable, but they need a controlled pass.
- Should QA worker topology use the old dedicated services or the newer dispatcher/processor/poller services after rollback? The answer must match the code branch selected.
- Are reference image labels correct in the current modular UI for non-fashion/furniture workflows?
- Should model-specific image reference limits be centrally declared in one backend + frontend catalog to prevent future mismatch?

## Short Policy For Future Agents

If you are an AI agent or developer reading this:

1. Read `AGENTS.md`, `deploy_rules.md`, this document, and the relevant repo's `docs/DOC_INDEX_CURRENT.md`.
2. Do not assume `dev-env`, `qa-env`, and `prod-env` are on the same architecture generation.
3. Do not treat Harsh Stage 1, Stage 2, and Stage 3 as one thing.
4. Do not restore old code blindly; preserve the selected late-July features and production hotfixes.
5. Do not edit servers manually.
6. If SSH/logs are required, verify OpenVPN first.
7. For any GPT Image 2.0 or modular image issue, check payload labels, image count, Images API route, async polling, and worker queue before changing prompts.

