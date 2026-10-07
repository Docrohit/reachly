# Prompt 13: New Company Setup

Use when onboarding a new company to Reachly:

```markdown
Set up Reachly for a new company.

Collect:

- Company name, website, sector
- ICP and business goals
- Brand voice and forbidden claims
- Posting style: `thought_leader` or `brand_promoter`
- Platforms: LinkedIn, Instagram, X, Medium, YouTube
- API mode or browser mode per platform
- Media provider: Gemini images, optional Seedance video, or none
- Schedule and timezone
- Context repo or uploaded docs

Create/update:

- Per-business dashboard goals (keep repo business_goals.md for Reachly itself)
- platform credentials in `.env` or encrypted vault
- `REACHLY_CONTEXT_REPO` if using repo docs
- `POST_TIMES`, `INSTAGRAM_OFFSET_MINUTES`, timezone

Verify:

- preview output is on-brand
- browser/API sessions are primed
- one manual test post or dry-run per platform
- logs and history record outcomes
```
