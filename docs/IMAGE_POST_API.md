# Personal Reachly: image-post API

Generate for the selected personal workspace from Postman or curl. No operator service
credential is required. No request publishes a social post.

## Set up

1. Choose the business at `/workspaces`, save its name/website and provider keys in Settings.
   A text-provider key and a Gemini key for images/review are required. Credentials are never
   accepted in the generation payload and never borrowed from another workspace.
2. Open `/api-access` (**Image API**) and create a token. Copy the one-time display into a
   local environment variable or Postman secret. The database stores only its hash. Replacing
   or revoking the token invalidates the old one. Changing the business identity requires a new token.
3. Import `docs/examples/Reachly_Image_Posts.postman_collection.json` or use curl below.
   Set `base_url`, `reachly_token` and a fresh `request_id` UUID. Reuse the UUID and exact
   payload for retries; use a new UUID only for an intentionally new generation.

## Example payload

Save as `request.json` (these are fictional example inputs):

```json
{
  "topic": "Explain our service to a first-time customer",
  "inputs": {
    "audit": {"captured_at": "2026-10-08", "findings": ["Customers need a clearer explanation of the service"]},
    "website": {"sources": ["https://your-business.example"], "facts": ["Replace with verified facts"]},
    "saas2point0": {"audience": "Replace with your target audience", "positioning": "Replace with approved positioning"},
    "post_analytics": {"lesson": "Replace with measured performance, including dates"},
    "other": {"objective": "Explain one concrete benefit without unsupported claims"}
  },
  "visual": {
    "aspect_ratio": "4:5",
    "image_size": "1K",
    "quality_review": "required",
    "layout": {"headline": "Meet your next idea", "cta": "Learn more"}
  },
  "research_requested": false
}
```

```bash
export REACHLY_BASE='https://reachly.nftforger.com'
# Set REACHLY_TOKEN privately; do not put it in Git or shared shell history.
REQUEST_ID=$(uuidgen)
curl --max-time 100 --fail-with-body \
  "$REACHLY_BASE/api/v1/image-posts?wait_seconds=90" \
  -H "Authorization: Bearer $REACHLY_TOKEN" \
  -H "Idempotency-Key: $REQUEST_ID" \
  -H 'Content-Type: application/json' \
  --data-binary @request.json > result.json
```

When completed, the JSON contains `state: "completed"`, `job_id`, and `candidates[0]` with
`post` (hook/body/hashtags/link), `image_base64`, `mime_type`, and a private `image_url`.
Write `image_base64` to a PNG after decoding, or download `image_url` with the same bearer token.

```bash
JOB_ID=$(jq -r '.job_id' result.json)
curl --fail-with-body "$REACHLY_BASE/api/v1/image-posts/$JOB_ID" \
  -H "Authorization: Bearer $REACHLY_TOKEN" > result.json
# Decode only after confirming state is completed:
jq -e '.state == "completed"' result.json >/dev/null && \
  jq -r '.candidates[0].image_base64' result.json | openssl base64 -d -A > post.png
curl --fail-with-body "$REACHLY_BASE/api/v1/image-posts/$JOB_ID/audit" \
  -H "Authorization: Bearer $REACHLY_TOKEN" > generation-audit.json
```

HTTP **202** means queued/running; poll `status_url`. The default wait is 25 seconds, maximum
90. A proxy may time out first; retry with the same UUID/payload or poll the existing job.
Use `include_image=false` to omit base64 from POST/GET responses. A terminal GET returns
HTTP 200 even for a failed job: always check `state` and each candidate's `state`.

`failed` and `needs_attention` do not return publishable images. Inspect the audit. Never
automatically issue a new request after an uncertain paid attempt. There is no auto-retry.
Queued jobs survive restart and resume when polled. A lost running job is held for inspection
when its 30-minute lease expires; it is not replayed. Ten new jobs per workspace per hour.

## Optional inputs

- `business`: override profile fields for this request; `name` and `website` must exactly
  match the selected workspace. Otherwise create/select that business's own workspace.
- `inputs`: up to 60,000 characters of JSON for audit, website facts, SaaS2point0, analytics
  and any other public business context. These are supplied facts, not independently verified
  research. Omit `inputs` to use the saved goals/project/research/performance notes. An explicit
  empty object means no saved notes. The profile itself is always included.
- `brand`: `{colors: ["#112233"], theme: "Natural light", logo_base64: "..."}`. Omit to use
  saved brand data. Logos are composited separately; they are never drawn by the model.
- `research_requested: true`: request additional sourced Gemini search. Adds provider cost;
  failure gives a visible warning and generation continues from supplied inputs.
- `brief`: structured objective/theme/narrative/setting plus topic/instructions. The common
  contract currently uses clinic-oriented enum choices; general business direction can always
  be supplied through `topic`, `inputs`, `business.brand_theme` and `brand.theme`.
- `references`: up to four `{role, label, image_base64}` objects. Roles are `product`, `premises`,
  `person`, `style`. Supply raw base64, not data URLs or remote URLs. Prefer files below 2 MB.
- `visual`: aspect ratio (`1:1`, `4:5`, `3:4`, `4:3`, `9:16`, `16:9`), resolution
  (`1K`, `2K`, `4K`), optional deterministic layout, and review policy. Review defaults to
  required. Explicit `quality_review: "off"` is saved as an opt-out, not a passed review.

Full prompt flow and practical input guidance: [IMAGE_QUALITY.md](IMAGE_QUALITY.md).

## Revise an image

Send a new request ID and this payload, referring to a completed candidate in the same workspace:

```json
{
  "original": {"job_id": "PREVIOUS_JOB_UUID", "candidate_id": "PREVIOUS_CANDIDATE_UUID"},
  "revision_mode": "image",
  "feedback": "Keep the product and camera angle. Make the background pale blue.",
  "visual": {"aspect_ratio": "4:5", "image_size": "1K"}
}
```

`image` preserves caption and sends original pixels to Gemini. `copy` reuses the image;
`both` revises both. Include the desired `inputs`, references, layout and shape again when
revising; they are not silently inferred from a previous request. Every request is saved
separately with its lineage. The API delivers images directly; it does not automatically
create a Studio draft or publish it.

## Status codes and operating notes

401 invalid/revoked token; 404 job/image outside this workspace or unavailable; 409 reused
UUID with changed inputs; 413 payload above 16 MB; 422 invalid input or missing provider keys;
429 more than ten new jobs/hour. Reference pixels are validated before paid calls.

The API requires the personal web app, its normal database/vault, and writable private
`REACHLY_GENERATION_DATA` (default `.reachly_generation`). It runs jobs in web background
threads; the separate service-client CLI worker deliberately does not claim personal jobs.
Do not mount the generation directory as public static files. Back up and manage retention
for the database, prompts, raw images and references. Additive table `imageapikey` is created
by normal app initialization. This API token is for generation only and grants no publishing scope.
