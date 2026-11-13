# Carousel, run-time relevance and Evenza validation

Validated locally on 2026-10-23 (Asia/Tehran), on `feat/data-quality-occurrences`.
This work extends the owner's uncommitted title-admission, Occurrence, SQLite and
XLSX changes. It does not replace that work with GitHub main.

## Baseline and repository safety

- `.venv/Scripts/python.exe -m unittest discover -s tests`: **1,269 tests passed**
  before implementation. The first invocation through global Python failed on
  missing project dependencies (85 errors); the existing project venv was used
  thereafter, with no dependency changes.
- No reset, stash, discard, commit, push, merge or history rewrite.
- Live raw/evidence additions and acceptance artifacts remain under ignored `data/`.
- Validation refreshes used a SQLite backup and separate XLSX/export paths under
  `data/reliability-validation/`. The owner's original database and workbook were
  not refreshed or overwritten. All **92 historical Event snapshots** and **59
  Event review records** also survived unchanged in the validation database.

## Reproduced root cause and fix

The failing operation was `page.wait_for_function` inside `_largest_visible`,
called with `article img, main img`. At slide index **1** (zero based), both
`DejjUQ_CiVD` and `DeZxZnVijWb` displayed a loaded **VIDEO** (`readyState=4`),
while the previous image was clipped outside the carousel. The image-only wait
could not succeed. One earlier attempt returned before the transition ended,
showing why a delay increase alone would also risk a wrong slide mapping.

The driver now waits for loaded image/video media with almost its full horizontal
width visible, then stable geometry. An element handle prevents a changing `nth`
locator from silently targeting a different DOM node. Navigation requires changed
element/source identity. Bounds, source and visibility are checked again after
capture; changed captures are discarded. Video slides use one paused frame at
time zero, reusing the existing bounded video-seek logic.

There are at most **three capture attempts on the same slide**. Persistent,
duplicate, navigation or slide-limit failures are reported with source ID, RawItem
ID, slide index, category and retry count. Capture stops that post when position
is unconfirmed and retains earlier successes. No click is retried ambiguously.
The evidence summary exposes failed/unconfirmed positions separately from OCR.
Content-addressed storage and duplicate detection prevent duplicate artifacts.
Session, login, public-profile and checkpoint boundaries remain in force.

Live evidence command on the original latest-five stored sample:

```text
Raw items: 5
Carousel slides: 4
Reel frames: 17
OCR succeeded: 20
OCR empty: 1
OCR failed: 0
Capture failures: 0
```

The repeated two-post Carousel check confirmed `(0, IMG), (1, VIDEO)` for each
post, four distinct artifacts, no failure, and **zero new PNG files**. The Reel
sampler deduplicates identical frames; 17 retained frames does not assert 18
distinct frames. Video-slide capture is a frame sample, not complete video OCR.

## Collection recency and Evenza

The existing profile candidate bound remains `limit + 3`, with the buffered pool
capped at 12 items (eight candidates for `--limit 5`). Publication timestamps determine order;
three old pinned posts cannot displace five newer candidates. Unknown timestamps
sort last and emit `publication_recency_unverified`, including unknown candidates
outside the final five. No capture timestamp is substituted for publication time.
No historical crawling or extra pagination was added.

`evenza_platform_instagram` is enabled, publisher `evenza_platform`, username
`evenza.platform`, canonical URL `https://www.instagram.com/evenza.platform/`,
without `stkn`. Registry selection, generic collection, clean content URLs and
publisher coverage are tested. Owner-authenticated live collection returned
**5 observations, 5 new, 0 failures**. A later full live refresh collected five
observations each from Evenza and Jabama and completed their evidence/discovery
pipeline with no source failure.

## Schedule semantics and frozen comparisons

The exact stored `run.started_at` is converted to `Asia/Tehran`; every stage and
re-export shares that reference. The horizon includes today through today +
`--days`. Event IANA timezones are preserved. Supported dated occurrences take
precedence; only relevant occurrences enter current publishing exports. Explicit
ranges retain ongoing Events even beyond the horizon. Daily opening hours never
become a continuous interval; final-day closing time can prove expiry. Date-only
Events and start-only Events today remain eligible without an invented end time.
Unknown/conflicting dates and recurrence without dated instances stay in schedule
review. Cancellation/postponement excludes actionability; sold-out/capacity stays
separate. Raw evidence, full SQLite facts and reviewer decisions are retained.

| Same frozen input | Previous Event view | Actionable | Expired | Beyond horizon | Schedule review | Otherwise excluded |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 13 synthetic Events, 30 Mehr 1405 at 15:30 Tehran | 11 | 7 | 2 | 1 | 2 | 1 |
| 22 eligible Events from stored run `005a5510b7d9481c808f3869f85c463e` | 19 | 11 | 2 | 0 | 9 | 0 |

The stored run reference is `2026-10-20T13:26:53.342007+00:00` (16:56:53 Tehran).
Each eligible Event has one disposition and reason, with per-session outcomes.
The counts sum to eligible canonical membership without double counting.

## End-to-end outputs

- Stored refresh of all nine enabled channels, five observations each:
  **34 discoveries → 18 title exclusions → 16 canonical Events → 1 actionable,
  4 expired, 11 schedule review**. Six publishers represented. Reference:
  `2026-10-22T20:49:31.665967+00:00` (October 23, 00:19 Tehran).
- Fresh live refresh of Jabama and Evenza, five observations each:
  **11 discoveries → 6 title exclusions → 5 canonical Events → 0 actionable,
  5 schedule review**. Both publishers represented. Reference:
  `2026-10-22T20:50:19.381653+00:00` (October 23, 00:20 Tehran).
- SQLite visible membership, run manifests, XLSX Event rows, CSV IDs, structured
  JSON and Gemini bytes/counts were reconciled for both runs. Investigation rows
  agree separately. SQLite integrity and foreign-key checks passed.
- Re-export is idempotent and uses the stored reference; historical workbook
  snapshots and review decisions survive projection changes. Full session history
  remains available through `load(include_filtered=True)`.
- Validation artifacts: `data/reliability-validation/CurrentRefresh.xlsx`,
  `LiveRefresh.xlsx`, `historical-exports/`, `current-exports/`, `live-exports/`,
  `historical-comparison.json`, `carousel-verification.json`, `acceptance.json`.

## Regression coverage and limits

Deterministic mocked Playwright coverage includes transient recovery, persistent
failure, image replacement during capture, duplicate visuals, partial recovery,
mixed video slides, navigation identity and slide bounds. Frozen schedule tests
cover yesterday, clock boundaries today, ongoing/final-day ranges, ranges extending
beyond the horizon, future dates, mixed sessions, weekly recurrence, unknown dates
and ends, cancellation/postponement, date-only values, Nowruz/leap-day boundaries,
exact time-zone conversion, export parity, history and title-admission guards.

The live sources still have extraction limitations: six of eleven live discoveries
lacked admissible titles; all five remaining Events had unresolved schedules.
They were kept out of the actionable view rather than filled with inferred facts.
No broader extraction-accuracy claim, Google upload or Telegram integration is made.
The validated Jabama timeouts did not recur after the fix; other layouts and network
conditions can still produce explicit bounded failures.

Final verification used the project venv:

- `python -m unittest discover -s tests`: **1,301 tests passed** (35.363 seconds).
- `python -m compileall src`: passed.
- `python -m pip check`: no broken requirements.
- `git diff --check`: passed.
- `git status`: same branch, changes unstaged, no commit/push/merge.

The newly added regression cases total 32; existing tests were adjusted only where
the requested schedule-review separation, export table count, stop-on-failure
behavior, or enabled-source count changes their expected contract.
