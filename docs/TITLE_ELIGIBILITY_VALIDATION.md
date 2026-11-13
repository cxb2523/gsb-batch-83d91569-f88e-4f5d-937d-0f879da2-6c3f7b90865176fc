# Event title admission validation — 2026-10-20

Historical validation: the owner clarified this policy on 2026-10-23. A positively
identified Event may use a concise, evidence-grounded descriptive display title;
an explicit source heading is not mandatory. See
[Event recall validation](EVENT_RECALL_VALIDATION.md) and the current
[admission contract](DATA_CONTRACTS.md#event-admission). The measurements below
describe the earlier implementation, not the clarified discovery policy.

## Root cause and enforcement

`missing_source_title` / `missing_title` diagnosed incomplete extraction but did
not prevent canonical persistence. Readiness classified these rows as needing
enrichment, and exports displayed them. Excel also reused a completed run's tab,
so filtering only a newly loaded document would not fix an existing workbook.

`review/eligibility.py` now centralizes admission. A nonblank, non-placeholder
title must have field provenance pointing to the Event's own source candidates,
source IDs and a canonical source URL. This checks attribution, not model
confidence, and never manufactures or rewrites a title.

Admission follows extraction and available evidence enrichment. SQLite `sync`
enforces it before inserting Event facts, snapshots, identity mappings or review
rows. The review window only counts eligible Events. SQLite `load` filters legacy
payloads before deserialization, without changing saved data. Every local export
boundary and optional Sheets snapshot creation also applies the policy.
Same-run XLSX re-export adds an eligible projection when membership changes,
keeps the original tab intact, and imports subsequent decisions from the replacement.

## Frozen owner-run results

The input is the same 40 RawItems across eight sources used for the preceding
data-quality acceptance run. No new collection, OCR call or discovery-threshold
change was performed.

| Count | Before | After |
| --- | ---: | ---: |
| Deduplicated candidates before admission | 32 | 32 |
| Excluded before new canonical persistence | 0 | 10 |
| Canonical Event membership for the run | 32 | 22 |
| Date-window filtered | 7 | 3 |
| Displayed Events | 25 | 19 |

The confirmed six displayed titleless Events all came from
`emrooz_events_instagram`, across five distinct posts. Full-run inspection found
four additional titleless records that the date window had already hidden.

| Source | Excluded from full canonical run | Removed from displayed view |
| --- | ---: | ---: |
| `emrooz_events_instagram` | 7 | 6 |
| `jabama_events_instagram` | 3 | 0 |
| All other sources | 0 | 0 |

All ten exclusions were missing titles, not placeholders or unsupported-title
attribution. Counts reconcile: **32 = 10 + 22** and **22 = 3 + 19**.
The existing stored run also re-exports to 19 Events, without deleting any of
its original 32 snapshots.

## Verification and artifacts

Validation used isolated copies of the prior 25-Event workbook and SQLite file.
The original owner files remain untouched. Ignored local artifacts:

- `data/stage9-validation/title-eligibility-20261020/acceptance-01/GatherRadar.xlsx`
- The same directory's `gatherradar.sqlite3` and `exports/` (CSV, JSON, Gemini).
- `data/stage9-validation/title-eligibility-20261020/summary.json`
- `data/stage9-validation/title-eligibility-20261020/events.png` (rendered preview).
- `data/stage9-validation/title-eligibility-20261020/verify.py` (offline acceptance script).

The regenerated workbook was reopened and its current tab's 19 Event IDs were
compared with both CSVs, both JSONs and the Gemini manifest. Membership mismatches:
zero. Occurrence payloads matched across formats; Gemini file hashes passed.
The current Event tab was rendered and visually inspected.

Preservation checks verified:

- 102 historical Event snapshots and four historical run records unchanged.
- Four historical workbook snapshot sheets unchanged.
- All 57 existing review records unchanged.
- All 14 original raw/evidence file hashes unchanged.
- Stable Event IDs retained; repeat export adds no new projection.
- Migration called twice without data changes; SQLite `integrity_check = ok`;
  `foreign_key_check` returned no violations.

`python -m unittest discover -s tests`: **1,269 passed**, zero failures or skips.
The 12 added tests cover real titles, whitespace, invisible/symbol-only titles,
decorated placeholders, missing attribution, dates/venues without titles,
trusted OCR, multiple Events in one post, run-manifest diagnostics, legacy
re-export, historical decisions, migration and cross-format membership.
Optional Sheets admission and legacy projection were verified with the offline
client fake. `compileall`, `pip check`, and `git diff --check` passed.

## Compatibility and limitations

SQLite DDL remains version 1; portable records and XLSX remain version 3. No new
dependency, discovery threshold or extraction rule was introduced. Prior extraction,
occurrence, schedule, persistence and workbook improvements remain in place.

Source attribution relies on the existing extraction/provenance contract; this
gate is not an independent semantic fact-checker. Missing source titles remain
unrecovered until better evidence is available. Historical tabs intentionally
retain the original titleless rows, while current projections omit them.
Live Google Sheets publishing was not exercised. Offline results do not claim
fresh source availability or solve the pre-existing partial media evidence.

No commit, push or merge was performed.
