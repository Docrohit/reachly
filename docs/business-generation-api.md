# Business generation API — 29 September 2026

Reachly generates strategy, copy, image prompts and PNG images. The caller owns
approval and publishing. These endpoints never invoke the standalone posting loop.

## Contract

- `POST /api/v1/generation-jobs`: `X-Reachly-Client`, Bearer token and UUID
  `Idempotency-Key` required. Replays return the same job; changed input conflicts.
- `GET /api/v1/generation-jobs/{job_id}`: scoped status, candidates, warnings,
  source version, model names and evidence provenance.
- `GET /api/v1/generation-jobs/{job_id}/assets/{candidate_id}`: authenticated PNG.
  Hyclinics verifies the SHA-256 before importing an immutable version.

Inputs: schema version 1, permanent `business_id`, `source_version`, BusinessProfile,
`public_facts`, `brand` (hex colours, visual theme, optional PNG/JPEG base64 logo),
count 1–5 and recent hooks. No server file paths or model secrets in requests.

`clinic_basic` includes only public business inputs. `clinic_enhanced` can add
scoped GEO and research evidence. Each evidence object carries `business_id`,
`captured_at`, source URLs and findings. GEO must match the business website.
Evidence older than 30 days or without timezone/source information is rejected.
Hyclinics omits unusable audits; Reachly then records a missing-audit warning.

Enhanced requests can request online research. One grounded search call per
uncached job, capped at 3,000 output tokens; successful research is cached for
24 hours by client, business and brief hash. No sources means unavailable research,
with a warning. Research never invents an unavailable audit. No clinical claims
are treated as authorised merely because a research source mentions them.

Revisions use `count: 1`, `revision_mode: copy|image|both`, feedback, and
`original: {job_id, candidate_id}`. The original must be complete and owned by
the same client/business. Copy-only preserves its image; image-only preserves
the current copy supplied by Hyclinics. Hyclinics checks the expected revision
again before import and resets both approvals after a successful revision.

## Content Factory v2 (local implementation, 3 October 2026)

The same endpoints accept `schema_version: 2` with `operation: "posts" | "ideas"`.
Version-one requests retain their previous serialization and idempotency digest.
No new provider or publishing credentials are accepted from callers.

For posts, optional `brief` supplies `objective`, `theme`, `narrative`, `setting`,
`format`, `topic` and `instructions`. These fields reach planning, copy and image
prompts and are validated against the contract choices. `format` is currently
restricted to `image`; automated carousel and recorded-video operations are not
implemented. Patient journeys and treatment scenes are illustrative, not claims
about actual patients or premises. This constraint still requires human review.

For ideas, pass `count: 3`, no original asset and `creative_mode: "distinct_posts"`.
The result has three `ideas` containing `title`, `reason`, editable `script` and
`sources` (public-fact field identifiers). Unknown sources and duplicate titles
fail validation. Scripts request 130-180 words for a 60-90 second target; speaking
duration and factual quality require real-provider review. Ideas do not invoke
image generation. Enhanced research may still incur its normal cached search call.
Hyclinics caches the suggestions, queues refreshes explicitly and caps them at two
per clinic per hour. Opening a page does not generate a new paid request.

This increment does not extract uploaded documents, transcribe real recordings,
rank GEO findings, change the research algorithm, or publish new media formats.
Uploaded material remains within Hyclinics's manual production workflow.

## Credential ownership and activation

Set `REACHLY_GENERATION_CONFIG` to a protected JSON file outside the checkout:

```json
{
  "clients": {
    "hyclinics": {
      "token_env": "HYCLINICS_REACHLY_SERVICE_TOKEN",
      "business_ids": ["HYC-REPLACE_WITH_REAL_CLINIC_ID"],
      "provider": "hyclinics_owned",
      "max_hourly_jobs": 20
    }
  },
  "providers": {
    "hyclinics_owned": {
      "llm_provider": "gemini",
      "llm_model": "gemini-2.5-flash",
      "image_model": "gemini-3.1-flash-image",
      "gemini_api_key_env": "HYCLINICS_GEMINI_API_KEY"
    },
    "reachly_owned": {
      "llm_provider": "openai",
      "llm_model": "gpt-4o-mini",
      "image_model": "gemini-3.1-flash-image",
      "openai_api_key_env": "REACHLY_OPENAI_API_KEY",
      "gemini_api_key_env": "REACHLY_GEMINI_API_KEY"
    }
  }
}
```

Names above are examples; operators select available approved models and provision
keys through the normal secret-management process. A remote Reachly process cannot
read Hyclinics's environment: provision the selected credential in the worker's
environment. Sharing a credential profile never shares logos, facts or history.
Without organisation provisioning, provision each allowed clinic ID explicitly.
For the Hyclinics integration use the organisation API described below instead.
Do not use wildcard business scopes.

API and generation worker share `REACHLY_GENERATION_DATA`, a private persistent
directory. Run `python -m reachly.generation_worker`; `--once` claims at most one
job for diagnostics. The supplied systemd service uses a restrictive umask.
The existing deployment workflow installs/enables it only when the config path is
set in the server environment file. This change does not dispatch a deployment.
The durable SQLite ledger is designed for one host, not a shared network filesystem.

Jobs persist before paid calls. Atomic claims prevent simultaneous execution;
results checkpoint after each candidate. A 30-minute stale lease becomes
`needs_attention` and is never automatically paid for again. Provider exceptions
with uncertain outcomes also need inspection; known validation failures are
explicitly retryable. Retrying known failed candidates creates a new request,
preserving successful candidates. Keep the ledger, assets and research cache in
backups; deployment rsync excludes this directory and business-logo storage.

## Branding in existing Reachly interfaces

Hosted and standalone dashboards accept a business-owned logo, colours and visual
theme. The shared post/article/image prompts use the business sector. Missing logo
means no logo. The hosted dashboard no longer accepts arbitrary server logo paths.

The generic mode does not discover product repositories. Hosted businesses get
separate context/history directories. Global Hygaar knowledge requires both an
eligible Hygaar identity and the explicit Hygaar business preset. Existing Hygaar
operators must select that preset deliberately; old environment-logo inheritance
is removed. For standalone environment branding, `BRAND_OWNER` must match
`BUSINESS_NAME`. Use a separate `DATA_DIR` and social-account configuration per
standalone business; changing brand identity does not rebind publishing accounts.

## Validation / limits

### Daily alternatives (29 September refinement)

`creative_mode: "daily_alternatives"` supports one daily post with one or two
alternatives. Pass `content_type` (for example `awareness`) and an optional `topic`.
A supplied topic bypasses the planning call; otherwise Reachly plans one shared
topic. Both candidates retain that topic while varying copy openings and visual
composition. The ordinary `distinct_posts` default remains backward compatible.
Requests for more than two daily alternatives are rejected. Hyclinics owns the
clinic-local daily initial allowance, explicit extra regeneration tracking, version
history and selection/approval. This per-request bound is not a ban on extra
Ops-requested regeneration. No publishing happens in the generation API.

The daily planner requests exactly one short topic. If a model returns extra
topics, the worker logs the count and uses the first topic for both alternatives,
without a second planning call or additional images. An invalid first topic still
fails validation. Distinct-post batches still require the exact requested topic
count. Terminal planning failures retain `failed_stage` for diagnosis without
logging business briefs or model responses.

Tests exercise fake provider PNG bytes through real API, worker, overlay and asset
retrieval code. They cover ownership, no-logo behaviour, sector/context separation,
three inputs, missing research/audit, partial failure, duplicate requests and leases.
These tests are not live model or social-platform acceptance. Real-provider output,
deployed worker health and an explicitly authorised destination post remain release
acceptance steps. Browser publishing is unchanged and separately approved.

## Organisation provisioning from Hyclinics

`POST /api/v1/generation-jobs/organisations` accepts only:

```json
{"organisation_id": "ORG-0000000000000001"}
```

It uses the same server-to-server `X-Reachly-Client` and Bearer credential as
content generation. In addition, the configured client must have the boolean
`organisation_provisioning: true`. This capability defaults to disabled. It is
not a browser API and accepts no provider credentials, pack, organisation name,
URLs or arbitrary configuration. IDs must match the permanent Hyclinics format.
The bounded request is idempotent and returns the ID and `state: registered`.
Registration itself creates no generation job or provider call.

The grant is persisted in the existing private generation ledger under the
service client and organisation. Generation requests can include the optional
`organisation_id`; its registration is checked before accepting a clinic. The
first job atomically binds that clinic to the organisation. Moving an existing
binding to another organisation is rejected. Jobs, history and assets remain
scoped by client and clinic. An unrelated service client cannot register an
organisation without the capability, or read another client's jobs/assets.
Disabling the capability revokes access through these dynamic organisation grants.

The trusted Hyclinics backend must resolve organisation and clinic from its own
registry and require Ops before calling these APIs. Reachly trusts that service's
attestation of membership; knowledge of an ID is not sufficient without the
server credential. Do not expose that credential to organisation/clinic users.
All clinic packs support social generation; pack-specific prompts remain the
responsibility of Hyclinics.

### Rollout order

1. Merge and deploy Reachly first. In the existing `deploy.yml` manual workflow,
   use `deploy=true`, `target=saas`, `enable_organisation_provisioning=true`.
   The reviewed helper enables only the existing `hyclinics` client, verifies its
   configured credential/provider, backs up the configuration privately, and
   preserves file ownership and permissions. It creates no new credentials and
   changes no standalone-agent configuration. Subsequent deployments can omit
   this one-time input; the protected runtime configuration is retained.
2. Merge/deploy the Hyclinics integration. Before submitting a new generation
   job, its worker idempotently registers the saved organisation, using only the
   saved clinic's organisation ID. Temporary network/5xx errors retry the same
   durable request; no paid generation starts before registration succeeds.
3. Ops adds an organisation/clinic and chooses a pack in the normal console.
   The first Generate action handles registration automatically. Existing clinics
   also work through a new request or explicit retry; no per-clinic server edit.

Legacy clients can continue to use static `business_ids` without an organisation
field. The API omits an absent organisation from encoded legacy payloads so
in-flight idempotency digests remain compatible. No database reset is required;
the ledger creates its additional tables without modifying old job rows.

## Performance signals (4 October 2026)

Requests may include an optional `performance` object computed by the caller from
the business's own published posts: `window_days`, `measured_posts`, `metric`,
`top`/`bottom` (up to 10 posts each: topic, hook, content type, objective, narrative,
setting, weekday, hour, score) and averages `by_content_type`, `by_narrative`,
`by_weekday`, `by_platform`. Unknown fields are rejected; the object is capped at
30,000 characters. It is omitted from serialization when absent, so earlier request
digests and in-flight replays are unchanged.

When present it is added to planning, copy, idea and script context as
`performance_signals` with fixed guidance: favour patterns of higher-engagement posts,
avoid patterns shared by the lowest performers, keep roughly one angle in three
exploratory, never reuse past hooks and never treat results as evidence for a claim.
Results report `performance_used` (measured post count). Hyclinics sends only
aggregate counters and public post copy; comment text and audience data are excluded.

## Clinic contributions (5 October 2026)

Requests may include an optional `contributions` list (at most 10) of material the
business shared itself, such as awards, events, talks or news. Each item has `id`,
`title`, `note` (≤2,000 characters), `speaker`, `event_date` (`YYYY-MM-DD` or empty),
`source_url` (public http/https link, never fetched), `shared_at` and `focus`. Only
text is sent; uploaded files never reach Reachly through this field. Unknown fields
are rejected and the list is omitted from serialization when absent, so earlier
request digests and in-flight replays are unchanged.

The worker adds the list to planning, copy, idea and script context as
`clinic_contributions` with fixed guidance: use the items where relevant so they
appear from time to time, keep each item's own date, never imply a past event is
recent and never add details the item does not state. Ideas and scripts may cite
`clinic_contributions` as a source only when the list is present.

At most one item may be marked `focus`, and only for a `posts` operation. A focused
item is the subject the business explicitly requested: the planner must keep every
topic about it. Results report `contributions_used` (number of items supplied).
