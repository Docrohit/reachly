# Personal Reachly: correct Council workspace ownership

Date: 2026-10-08 (Asia/Kolkata).

The user signed in and could not see either Council business. Their actual
Chrome session showed Profile user ID 4, free plan, no configured business, and
only Personal workspace in Businesses. The initial deployment had assumed the
pre-existing configured admin account (1) was the user's intended login and
seeded Council workspaces (2, 3) there. This assumption was incorrect.

After a private SQLite backup on the personal host, enabled account 4 with the
pro plan and ran the existing idempotent seed script for owner 4. This created
Council of AI (5) and Council Network (6). Both are active, dry-run on,
schedules off, with no imported provider/platform credentials. Original account
and workspace records were preserved; no data or secrets were transferred.

Verified both Council businesses are visible in the user's real logged-in
browser at /workspaces. Screenshot: /tmp/reachly-council-workspaces.jpg (local,
temporary verification artifact). No app code change/redeploy or provider call
was needed. The deployed app revision remains 5594467. These documentation
changes record a runtime account correction, not a new application release.

Future provisioning must identify the intended owner's authenticated profile
instead of assuming that the first or configured admin account is that owner.
