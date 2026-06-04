# Prompt 13: New Company Setup

Use when onboarding a new company to Reachly:

```markdown
Set up Reachly for a new company.

Collect:

- Company name, website, sector
- ICP and business goals
- Brand voice and forbidden claims
- Posting style: `thought_leader` or `brand_promoter`
- Platforms: LinkedIn, Instagram, X
- API mode or browser mode per platform
- Media provider: Gemini, Hygaar, none
- Schedule and timezone
- Context repo or uploaded docs

Create/update:

- `business_goals.md` or dashboard goals
- platform credentials in `.env` or encrypted vault
- `REACHLY_CONTEXT_REPO` if using repo docs
- `POST_TIMES`, `INSTAGRAM_OFFSET_MINUTES`, timezone

Verify:

- preview output is on-brand
- browser/API sessions are primed
- one manual test post or dry-run per platform
- logs and history record outcomes
```
