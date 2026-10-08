> Historical copied documentation. Not an active personal Reachly plan,
> deployment runbook, or authorization. See ../PERSONAL_REACHLY_STATUS.md.

# Approved clinic browser publishing

Source implementation, 28 September 2026. Browser selectors are not live-verified
for a clinic account. Facebook is newly implemented; it was not supported in the
inspected Reachly checkout. Do not describe it as already working in production.

This bridge does not use the standalone agent, cron-generated content, default
Hygaar sessions, or API tokens. Hyclinics owns generation, immutable approved
snapshots, approvals, scheduling, and the publication ledger. Reachly only posts
the supplied caption and media through a bound browser session.

## Deployment contract

- Deploy this Reachly feature through its normal pipeline, separately from
  Hyclinics. No changes to Hygaar backend are required.
- The Hyclinics social worker invokes the Reachly Python runtime with
  `python -m reachly.approved_publish`. Both installations must be reachable by
  that worker, with the same protected media and session volumes. This is a
  subprocess bridge, not a network partner API. Separate hosts need a deliberate
  worker placement/shared-volume design before activation.
- Set `REACHLY_CLINIC_BINDINGS` to an operator-owned JSON file readable only by
  the worker/operator; `REACHLY_CLINIC_DATA` to a protected persistent directory;
  `REACHLY_CLINIC_MEDIA` to the Hyclinics social media directory.
- JSON mapping shape: each key is the connection UUID shown in Hyclinics. Its
  value contains `clinic_id`, `platform` (`instagram` or `facebook`), `account`
  (exact IG handle without @ or exact Facebook Page name), and `page_url` for FB
  (`https://www.facebook.com/<page>`). Never put passwords or cookies in the JSON.
- For each connection use `python -m reachly.clinic_session <connection-uuid>`
  in an approved interactive environment on the same protected session volume.
  The operator completes login/2FA and, for Facebook, selects the Page identity.
  The command never logs in automatically, posts, or changes permissions.
- Enable the registered connection in Hyclinics only after this setup. Each
  publish still checks identity and requires platform confirmation.

## Delivery and recovery

The JSON payload includes request UUID, connection UUID, clinic ID, platform,
account, exact caption, relative PNG name, and media SHA-256. Media paths must
remain under the configured root. The binding must match clinic/platform/account.
A per-connection OS lock prevents concurrent browser use. A SQLite receipt is
committed before any browser action. Repeating a request returns the existing
receipt; changed payloads with the same ID are rejected.

Only a platform confirmation marks a browser attempt published. A timeout, process
crash, missing identity, expired session, checkpoint, or ambiguous outcome requires
Ops attention. No automatic retries. Hyclinics provides an Ops reconciliation
control: record the verified platform post URL, or inspect the bound account,
confirm absence, and request a new attempt with a distinct request ID. Previous
attempt receipts remain intact. Never infer a successful post from a dry run.

Instagram requires the own-profile link to match the bound handle and a shared
confirmation. Facebook requires the composer to expose the exact Page actor and
publication confirmation. UI/language changes can cause a safe failure. Validate
these selectors with the intended accounts before declaring live acceptance.

## Validation

13 targeted tests passed: exact caption, account and clinic binding, media hash,
path escape, duplicate requests, process-crash recovery, Facebook actor validation,
missing confirmation, Instagram account mismatch, and existing IG API tests.
The full suite also passed on the final main-based branch: 105 tests and 1 subtest.
No real account was logged into and no public social post was sent in this session.
