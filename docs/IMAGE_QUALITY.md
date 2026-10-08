# Business image quality and generation records

This is the implementation and operating guide for the October 8, 2026 visual upgrades.
Generation and review use the selected business's providers. Generation never proves
publication. The personal and work repositories retain separate credentials and releases.

## Give the system good inputs

There are no numeric input weights or guaranteed quality scores in the context assembly.
The visual planner explicitly uses this order of responsibility:

| Input | What it should do | What to supply |
| --- | --- | --- |
| Objective/theme/creative brief | Direct this specific post | One audience, one point, one action; choose a setting and composition when important |
| Business profile | Constrain identity and factual claims | Accurate services, product capabilities, location, audience, brand voice, palette, logo |
| Audit | Identify a business opportunity | Dated findings with evidence; distinguish observed facts from recommendations |
| Online research | Add current, sourced context | Sources and dates; never let a web page override supplied business identity |
| Past-post feedback | Inform topic and visual choices | Measured impressions/clicks/engagement plus human image feedback, not invented success claims |
| SaaS2point0/project information | Explain positioning and the product | Audience pains, differentiation, approved features and limitations; import as source data |
| Reference images | Establish visual identity | Clean product, premises or approved person photos; style references only guide aesthetics |

For clinics: supply real approved business assets if a real room or staff likeness matters.
Without references, scenes must be illustrative. No invented patient stories, treatment
outcomes or before/after implications. Human review is still required before publication.
For other businesses the same principle applies to product features, awards and testimonials.

Use a short headline and CTA. Put long explanations in the caption. Select the intended
shape before generation: square, portrait feed, story or landscape. Higher resolution does
not fix weak positioning or inaccurate source material.

## Implemented flow

1. Validate business scope and bounded context/references. The API job ledger claims each
   request once and stores its source snapshot.
2. Optional sourced research; topic planning when necessary; generate grounded caption.
3. A dedicated text-model call produces a structured visual plan: subject, composition,
   lighting, palette, reference usage and things to avoid.
4. Send that plan, business/brief context, actual reference pixels and revision feedback
   to Gemini. Shape and resolution are provider configuration fields, not only prompt text.
5. Save the raw image. Compose optional headline/CTA and the supplied logo deterministically.
   Text gets a footer so it does not collide with the subject. No generated logo or typography.
6. Review the finished image with a vision model. It scores relevance, brand,
   reference fidelity, visual integrity and claim safety from 0–5. Every score must be at
   least 3. A failed or unavailable review holds the candidate; there is no automatic paid retry.
7. Save final image, exact prompts, selected models/settings, references and hashes,
   original-candidate linkage, feedback, layout and review results. Deliver completed candidates.

The rubric is a gate, not an objective measurement or promise of correctness. The default
reviewer is `gemini-2.5-flash`; service provider profiles can set `review_model` and
`research_model`. The image model remains the configured model. Planning and review add
provider calls and cost. `visual.quality_review="off"` is an explicit caller opt-out and is
recorded as disabled, never passed.

## Revisions and compatibility

- An image-only revision preserves copy and passes both the selected original image and
  the feedback. Prefer the saved raw image so old text/logo overlays are not generated again.
- A copy-only revision reuses the finished image and records lineage. It does not pay for
  another image or image review.
- Existing v1–v3 service payloads still work and now receive visual planning/review by default.
  Omitted new fields remain omitted when serializing, preserving existing request digests.
- v4 adds `references` and `visual`. See `IMAGE_POST_API.md` in personal Reachly or the
  existing generation API contract in the work repository.
- New Gemini `Agent.build_post` image drafts also use the pipeline. The personal Studio
  exposes references, shape, resolution and optional headline/CTA.
- Legacy article/video and optional external media-provider routes are retained; they do
  not gain this full visual planner/reviewer. The shared Gemini media helper does now use
  explicit shape configuration. No social publishing behavior is expanded by this change.

## Storage and inspection

Service jobs: `REACHLY_GENERATION_DATA/<job_uuid>/`, private from the public media mount.
Each candidate has `<candidate_uuid>.audit.json`, `.raw.png`, `.png` and reference copies.
`text-prompts.json` records exact topic, copy and visual-planning calls before provider use.
The job result preserves sourced research/evidence; `research.audit.json` records the search
prompt, model, tool settings and whether evidence came from cache. The image audit preserves review prompts.
No provider keys or API tokens are written to these records. Inputs are customer data, so
protect backups and restrict file access. Records currently require operator-managed retention;
no automatic deletion or regeneration occurs.

Authenticated service clients use `GET /api/v1/generation-jobs/{job_id}/audit`.
Personal API callers use `GET /api/v1/image-posts/{job_id}/audit`.
Personal Studio completed drafts offer **View prompts and image review**. Standalone drafts
save records under the selected business data directory's `generations/<generation_uuid>`.
Failed Studio calls keep their private disk records for operator inspection.

## Model and layout limits

- Up to four references, each a base64 PNG/JPEG/WebP under about 2 MB; decoded references
  are checked and stripped of metadata. No arbitrary URL downloads or local-path payloads.
- Image sizes: 1K, 2K, 4K. Legacy Gemini 2.5 image supports its native 1K only; larger
  requests fail explicitly instead of silently downgrading.
- Delivery remains bounded by the product image-size limit. Proxy request limits must allow
  the complete JSON/base64 envelope (at least 16 MB for reference-bearing API requests).
- Default deterministic text uses the bundled Pillow font and accepts ASCII. For other
  languages, configure `REACHLY_LAYOUT_FONT` with an installed font covering the script;
  verify rendered glyphs before publication. There is no silent text truncation.
- Gemini request format follows the [official image-generation guide](https://ai.google.dev/gemini-api/docs/generate-content/image-generation).

## Release acceptance

Local tests mock paid providers. Verify one real business generation and one image edit
with that environment's own provider key before claiming live visual acceptance. Check
actual pixels, references, typography, audit records and the final review. Neither GitHub
CI nor a health response proves visual quality. Existing clinic approval and publishing flows
remain the caller's responsibility. New reference/layout controls in a Hyclinics UI are a
separate caller integration; the work service's v4 API already accepts them.

## Prompt source map

- `reachly/content.py`: copy system/user templates and business image constraints.
- `reachly/generation_worker.py`: topic planning, research prompt and context assembly.
- `reachly/visual.py`: visual director and image-review system prompts, final image brief assembly.
- `reachly/media.py`: final image-provider suffix and explicit provider configuration.
- Per-job `text-prompts.json` and audit JSON contain the exact assembled calls for that job.
