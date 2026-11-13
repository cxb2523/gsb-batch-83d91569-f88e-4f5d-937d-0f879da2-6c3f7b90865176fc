# Stage 7 validation — 2026-09-24

## Starting state and environment

- Branch: `feat/normalization`; clean tracked/untracked working tree.
- HEAD, local `main`, and `origin/main`: `d387d8eb189f4eaf51fbe2bd51f48c290aca170e`.
- This is the README commit after Stage 6 PR #5's merge
  `716e166461c8fd8fbf4ce21da2f48ce2197abb87`; the GitHub connector confirmed PR #5 merged.
- System Python 3.13.15 initially reported 588 tests with one import error because that
  interpreter lacked Playwright. The existing project `.venv` passed all **659 baseline
  tests** without repository changes. All subsequent checks use that environment.
- Public PyPI JSON metadata verified `persiantools` 6.2.0, Python >=3.9, and the Windows
  `tzdata` dependency before editing packaging. Editable installation succeeded with
  persiantools 6.2.0 and tzdata 2026.4. Python 3.13.15 imported both the calendar library
  and `ZoneInfo('Asia/Tehran')` successfully. No unrelated dependency was added.

## Method

Read existing local stores only; no recollection. Website runs used `--limit 5` in stored
first-seen order. Instagram runs used five latest stored observations, with `--evidence`
for Davvvat and Vadoostan and caption-only discovery for Jabama and Emrooz. This is 35 raw
items, not 35 normalized candidates. Classification/grouping remained unchanged.

The final programmatic review blocked socket connections and subprocess creation,
normalized each outcome twice with exact equality, and compared SHA-256 hashes of all
nine existing raw/evidence JSONL files before and after: unchanged. CLI review was also
run for these modes. Tests separately verify byte-identical default output as the prefix
of opt-in output, forbid acquisition/writes, and compare temporary runtime trees.

The table uses candidate order within each bounded run. It intentionally omits raw
captions, names, handles and contact details. All listed timestamps use configured
`Asia/Tehran` (+03:30). Website references use capture timestamps; Instagram references
use publication timestamps.

## Observed results

| Source / candidate samples | Wording category | Final interpretation and review outcome |
| --- | --- | --- |
| Davvvat website #1 | Yearless date + hours | 2026-09-25, 11:00–21:00; aware same-day timestamps; inferred year, missing price |
| Davvvat website #2 | Yearless bounded date range + daily hours; explicit free | 2026-09-23 through 2026-09-25, 10:00–21:00 clocks; **no continuous timestamps**; zero price, unspecified currency; inferred year and multi-day-hours review |
| Davvvat website #3 | Yearless date + time | 2026-10-01 19:00 aware start; inferred year, missing price |
| Davvvat website #4 | Yearless date + hours; amount embedded in prose | 2026-09-24 17:00–19:30 aware timestamps; price unresolved because the full field contains additional prose; no invented multiplier |
| Davvvat website #5 | Yearless date + hours | 2026-09-25 08:00–11:30 aware timestamps; inferred year, missing price |
| Vadoostan website #1 | Four discrete sessions | Date/time unresolved; `multiple_dates`; missing price |
| Vadoostan website #2–4 | Yearless dates + times | 2026-09-25 at 10:00, 11:00, 11:00 respectively; inferred year, missing price |
| Vadoostan website fifth raw item | Other | No candidate, no normalization |
| Jabama website #1 | Discrete dates; minimum price | No single date/price; `multiple_dates`, `ambiguous_price` |
| Jabama website #2 | Date only; minimum price | 2026-10-01 inferred date; no clock or timestamp; price unresolved |
| Jabama website #3 and #5 | Weekday only; minimum price | No date/time/price invented; unresolved temporal wording and price |
| Jabama website #4 | Yearless date with truncated clock wording; minimum price | 2026-09-30 inferred date only; no repaired clock; price unresolved |
| Davvvat Instagram #1 | Date bounds + weekly recurring hours | 2026-09-18 through 2026-11-06; no timestamp interval; recurrence/unparsed schedule and inferred-year diagnostics |
| Davvvat Instagram #2 | Weekdays and hours, no calendar date | Unresolved; no arbitrary weekday date |
| Davvvat Instagram #3 | Yearless date range + hours | 2026-09-16 through 2026-09-18; clocks 14:00–22:00; no continuous timestamps; inferred year, missing price |
| Vadoostan Instagram | Five raw items; ten Other units | No Event/Place candidates to normalize; no new interpretation |
| Jabama Instagram #1 | Explicit Persian year/date + hours | 2026-09-24 10:00–19:00 aware timestamps, `exact`; missing price |
| Jabama Instagram #2 | Discrete dates | Unresolved; no continuous interval |
| Jabama Instagram #3 | End-only wording (“until”) | Unresolved; did not turn an end bound into a start date |
| Jabama Instagram #4 | Broad relative week | Unresolved; no arbitrary day |
| Emrooz Instagram #1, #2, #4, #5 | Broad weekend wording | Unresolved; no assumed weekend calendar |
| Emrooz Instagram #3 | Discovery selected “today” from a publisher name | Raw evidence inspection disproved temporal context. Final result is unresolved with `ambiguous_relative_context`, not a publication-day event |

Final totals: **26 Event candidates**, **13 partially normalized**, **13 unresolved**,
no invalid results in this bounded sample, no Place candidates. No remaining invented
date, clock, price, or continuous interval was identified in this review. Inferred years
remain explicit review assumptions, not verified facts. Existing discovery also contains
imperfect unrelated fields (for example event-format classification); Stage 7 preserves
them and does not claim to fix discovery accuracy.

Available real samples covered explicit Persian date/time, yearless dates, bounded ranges,
date-only results, missing prices, unconditional free, minimum/prose prices, recurrence,
discrete dates and broad relative wording. **No safe real “today/tomorrow” temporal example,
simple nonzero amount-only price, or Place candidate was present in this bounded selection.**
Those paths are validated with synthetic offline tests. The one apparent real “today”
example was rejected after source inspection; it is not reported as a successful relative
date normalization.

## Verification

Final checks in the project `.venv`:

- `python -m unittest discover -s tests`: **750 passed**, including **91 new** normalization
  tests covering digits, text preservation, calendar boundaries, year inference bounds,
  relative evidence context, weekdays, date/time ranges, DST, prices, failure isolation,
  determinism and offline/read-only CLI compatibility.
- `python -m compileall src`: passed.
- `python -m pip check`: no broken requirements.
- `git diff --check`: passed (Git reports existing LF/CRLF conversion notices only).

## Known limitations

This is not a recall benchmark. Unrecognized grammar, ambiguous numeric calendars,
cross-Nowruz yearless ranges, DST folds/gaps, reversed clocks, recurring schedules,
multiple sessions, tiered/conditional prices and long prose remain unresolved/partial.
Normalization cannot restore facts omitted by discovery, repair OCR, prove source truth,
or guarantee that a configured timezone describes every event. No recurrence engine,
occurrence expansion, persistence, export, scheduling or deduplication was implemented.

Review retains original source wording and IDs. No runtime/private data, credentials,
raw captions, or store files are included in the change. No commit, push or merge was made.
