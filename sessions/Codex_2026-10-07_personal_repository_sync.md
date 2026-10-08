# Personal Reachly repository connection and snapshot

Date: 2026-10-07

## Repository ownership

- Personal workspace: `/Users/rohitsharma/Desktop/M2026/Personal/reachly`.
- Personal remote: `git@github.com:Docrohit/reachly.git`.
- Hygaar workspace and remote remain separate and unchanged.
- This folder initially had no `.git`. Its Git history was connected to the existing personal `main` at `7a2842917374d447eef43e63409c2c73fe625028` without replacing its source files.
- Work branch: `codex/rohit-personal-reachly-sync-2026-10-07`.

## Snapshot findings

Before this note, all 140 tracked files of Hygaar Reachly revision `e0b7deb` matched this folder exactly. This is an October 5 snapshot, not an independently evolved personal codebase or the October 7 Hygaar release.

Compared with personal `main`, it adds clinic generation, branding, ideas, teleprompter, contributions and performance inputs. It also removes the content-assets page and changes related personal media features. The copied workflow enables deployment on pushes to `main` and contains Hyclinics provisioning. Review those differences before merging; this sync does not merge, deploy, provision accounts or publish social content.

## Validation

- Python 3.12 virtualenv installed locally; excluded from Git.
- `python -m compileall -q reachly server tests`: passed.
- `PYTHONPATH=. python -m pytest tests -q`: 177 passed, 1 subtest passed; 122 deprecation warnings.
- `git diff --check`: passed.
- Credential-pattern scan found no matches; reviewed literal candidates were placeholders, environment references or test fixtures.
- `.env`, virtualenv, runtime databases, browser state, generation state and brand assets remain ignored.

No live posting or production acceptance is claimed by these checks.
