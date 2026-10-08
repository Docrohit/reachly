# Council business profiles and brand assets

Date: 2026-10-08 (Asia/Kolkata).

User requested fuller business information, SaaS2point0 context and logos for
both businesses in their personal Reachly. Target: owner 4, Council of AI
workspace 5 and Council Network workspace 6. Both names, domains and ownership
were checked before the update.

Reviewed the personal SaaS2point0 toolkit README and each Council project's
docs/code. Council source was 794ada4; Network source was a78e2c1. No changes were
made to either source project. The toolkit describes structured project context,
not a hosted research API. Older Council planning documents conflict with newer
billing implementation; the imported brief separates current source, configurable
defaults, editorial hypotheses and roadmap. No numerical price is represented
as a verified live offer, and no analytics/adoption evidence was invented.

Reusable profile payloads and source-derived PNG/SVG marks are in
`businesses/council-of-ai/` and `businesses/council-network/`. The marks were
exported from the projects' existing CSS shapes/palettes: Council's sage bars
and Network's violet/cyan/pink conic-gradient orb. No standalone original logo
image files were present in the inspected source trees.

After a private SQLite backup, updated business description, sector, vision,
voice, themes, hashtags and goals; saved SaaS2point0-style project context and
dated source references in the encrypted business vault. Saved separate logos,
palettes, themes and bottom-right logo placement using Reachly's logo validation
and business-owned file paths. Existing vault values, including any provider
keys, were preserved; existing custom notes are preserved by the import logic.
No platform credentials, account data or schedules were copied or changed.

Verification: production read-back confirmed both business profiles, context
lengths (5629 and 5702 characters), palettes and existing logo files. Checked
both businesses' Studio and Settings in the user's authenticated Chrome session:
correct business context, profile content, colours and visual theme were visible.
Current Settings has an upload control but no saved-logo thumbnail; the logo
files and ownership mapping were verified server-side. No model generation,
research-provider call or public posting was run. Application code is unchanged,
so no application redeploy or full test-suite rerun was needed.

Local temporary UI evidence: `/tmp/reachly-council-of-ai-context.jpg` and
`/tmp/reachly-council-network-context.jpg`. Logo assets and editable context are
kept in the repository; runtime account updates are already live.
