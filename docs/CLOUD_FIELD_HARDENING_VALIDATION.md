# Cloud Field Hardening Validation (2026-10-29)

Engineering report for branch `fix/gatherradar-source-field-hardening`, started from
`origin/feat/data-quality-occurrences` at `1ea8ecf`. `main` was not changed. Contract
changes are summarized in [the data contracts](DATA_CONTRACTS.md#cloud-field-hardening-2026-10-29);
the per-entry machine-readable ledger is [CLOUD_FIELD_HARDENING_LEDGER.json](CLOUD_FIELD_HARDENING_LEDGER.json).

**Scope of evidence.** A passing unit suite does not prove live OCR completeness or current
event availability. Everything below was verified offline on sanitized fixtures or on the
exact source wording carried by the owner's frozen workbook and `unresolved.json`.

## Inputs actually available in Cloud

| Input | Available | Use |
| --- | --- | --- |
| `SOURCE_TO_FIELD_AUDIT.md`, `unresolved.json` | yes (owner attachments, not committed) | defect list, quoted wording |
| `GatherRadar-Fields.xlsx` (frozen workbook) | yes (attachment, not committed) | unchanged captions/descriptions, header/schedule wording, diagnostics |
| `field-ledger.json`, `before.json`, `after.json`, `ocr/results.json` | no | — |
| Original carousel images / reel frames | no | OCR entries are blocked |
| Raw JSONL, evidence store, SQLite of the frozen run | no | stored replay is an owner step |
| Live `jabama.events` / `vadoostan.ir` pages | no — Cloud egress policy refuses these hosts | no live inspection was attempted further |

## Baseline

`python -m unittest discover -s tests` on `1ea8ecf` (Python 3.13, fresh `.venv`):
**1,338 tests, OK, 9 skipped** (all nine skips need the optional `.[google-sheets]` extra).
The owner-reported 1,338 is confirmed.

## Ledger (19 entries = 15 Event IDs + 1 unassigned media item)

| # | Source | Field | Status | Cause → fix | Tests |
| --- | --- | --- | --- | --- | --- |
| 1 | Evenza `DewenndDR2X` slide 4 | title/date/venue | BLOCKED | image/OCR passes not accessible | — |
| 2 | Jabama `DewdAUCCnsq` slide 1 | title/date/time/description | BLOCKED | image/OCR passes not accessible | — |
| 3–5 | Jabama `DeoiH5qRkBU` (×3 IDs) | duplicate identity | PARTIAL | caption corroboration rejected corrupt OCR clocks and the `ت→ع` substitution → tolerated only for frames whose weekday/clock wording is proven corrupt (`c6f9fac`, `b11d432`) | `test_same_post_ocr_grouping.py` |
| 6 | Evenza `DehBOzsNFs9` Oktober | venue/city/duration | FIXED | no trailing-head venue, foreign-city or `سه‌روزه` grammar → added (`96fcc59`) | `test_location_grammars.py` |
| 7 | Davvvat `DexCzYgxZ9H` | venue | FIXED | prose + address agreement unsupported → `در جریان/برگزار` predicate + exact address tail (`96fcc59`) | `test_location_grammars.py` |
| 8 | Jabama `legacy-941` | area | FIXED | `لوکیشن حدودی …` grammar → `area_text` only (`96fcc59`) | `test_location_grammars.py` |
| 9–15 | Jabama ×7 pages | description | PARTIAL | adapter read only About → About + adjacent program sections (`b893eec`); real HTML not accessible | `test_jabama_program_sessions.py` |
| 16 | Vadoostan Simorgh | start_time/occurrences | FIXED | list not expanded, clock line not in schedule → 4 date-only sessions + `schedule_clock_conflict` (`ade069c`) | `test_schedule_conflicts.py` |
| 17 | Vadoostan Rokhdad | duration/end_time/occurrences | FIXED | month-per-day list + shared clock unsupported; header length kept despite contradiction → 4 sessions 19:00–20:30, length conflict (`ade069c`) | `test_schedule_conflicts.py` |
| 18–19 | Jabama `48751310`, `01519540` | occurrences | BLOCKED | unknown session shape; diagnostics now name the cause and unexpected key names (`b893eec`) | `test_jabama_program_sessions.py` |

Totals: **FIXED 5, PARTIAL 10, BLOCKED 4, UNSOLVED 0** entries. "FIXED" means verified on
the frozen source wording; for #8 the page-level position of the sentence is confirmed by
the owner's next crawl.

## Before/after on identical inputs

The same script ran against a worktree of `1ea8ecf` and against the branch head, with
identical inputs: the frozen caption/description wording from the workbook, the quoted
`unresolved.json` sentence, a reconstruction of the pizza Reel and the sanitized Jabama
program fixture. These are not frozen-run statistics; no 31-Event metric is claimed.

| Case | Before (`1ea8ecf`) | After |
| --- | --- | --- |
| Oktober venue / city / duration / disposition | null / null / null / expired | `کوچوک‌چیفتلیک پارک` / `استانبول` / `سه‌روزه` / expired |
| عمارت عقاب venue | null | `عمارت عقاب` |
| `legacy-941` area sentence | null | `ستارخانه` |
| Simorgh sessions | 1 (5 Aban 06:00, `unresolved_schedule`) | 4 date-only, `schedule_clock_conflict`, schedule review |
| Rokhdad sessions / duration | 1 (5 Aban 19:00) / `۲ ساعت` | 4 × 19:00–20:30 / null + `duration_conflict` |
| Pizza reconstruction | 3 Events (`ورکشاپ ساخت پیتزا`, `ورکشاپ پیعزاء`, `ورکشاپ پیتزاء`) | 1 Event, caption title, expired |
| Jabama program fixture description | About only (2 lines) | About + program (7 lines) |

The baseline output reproduces the audit's three pizza titles and the single-session
Simorgh/Rokhdad rows exactly, which supports the root-cause attribution.

## Changes by workstream

- **Descriptions (P0).** `JabamaAdapter._description`: About body plus directly adjacent
  sections headed `چه برنامه‌ای داریم؟` / `برنامه …`, headings kept, one exact retained slice.
  Organizer biography, related events, booking aside and navigation stay out. Detached,
  renamed or empty program sections keep the About-only value.
- **Sessions (P0).** Specific value-free drift codes; unexpected session property names in
  `source_session_drift_keys`; readiness `source_sessions_unreadable`. No new shape was
  accepted because none could be inspected.
- **OCR (P0).** No change. Both entries need the original images.
- **Grouping (P1).** One-letter substitution and clock disagreement are tolerated only when
  every frame in the media group shows corrupt mixed-script weekday/clock wording. Clean
  frames, other weekdays, calendar dates and other activities stay separate. The surviving
  Event keeps the caption's `primary` identity slot.
- **Locations (P1).** Prose/address venue agreement; trailing-head venue; explicit event
  city; unlabelled `N‌روزه/N‌ساعته`; approximate area. Mana's area/building/venue split is
  pinned by a regression test.
- **Contradictions (P1).** Explicit date lists with a shared clock; header/list clock conflict
  keeps dates date-only; header/narrative length conflict leaves `duration_text` null.
  Alternative wording stays visible in `source_schedule_text`.
- **Review exports.** `remaining_session_count` is null (blank) for range-only Events (the
  frozen Mana row showed `0`); the `جلسه‌ها` cell is chronological (the frozen Ala row listed
  ۱۳، ۸، ۱۵، ۶، ۷، ۱۴ آبان). Schedule-review category labels were already Persian on the base
  branch. Workbook layout, tabs and decisions are otherwise unchanged.

## Identity and history

No DDL, records-schema or workbook-schema change. Only the pizza fix can change which Event
IDs a new run emits: the caption Event (`primary` slot) remains; the two former frame-slot
Event IDs are no longer produced. Their SQLite history and any owner decisions stay intact;
no alias is created, in line with the existing "no automatic split/merge resolution" policy.
Jabama observations whose description now includes the program get one new raw revision
(the structural field joins the content hash); this is the intended observation-revision
behavior.

## Validation

- Full suite on branch head: **1,373 tests, OK, 9 skipped** (35 new tests in five files).
- `python -m compileall src tests`, `pip check`, `git diff --check`: clean.
- Offline end-to-end QA (temporary directory; Rokhdad or Simorgh plus Oktober, عمارت عقاب and
  the pizza reconstruction canonicalized together): two syncs of identical input, export,
  owner decision written in XLSX, import (1 imported, 0 malformed, 0 conflicts), re-export:
  decision preserved; actionable Event IDs identical across XLSX/CSV/JSON/SQLite; CSV/JSON
  parity for duration, venue, city, remaining-session count and description; Gemini bundle
  complete; `PRAGMA integrity_check` = ok; `PRAGMA foreign_key_check` = empty.
- QA found one regression introduced during this work (merged pizza Event routed to schedule
  review instead of expired); fixed in `b11d432` and covered by a test.

## Remaining issues and minimum evidence

1. **OCR (#1, #2).** Need slide-4 / slide-1 PNGs (or crops) and their stored OCR fragments.
2. **Jabama program HTML (#9–15).** The fix assumes the program section is a sibling section
   directly after About, as the audit describes. If a page places another section between
   them, the description stays About-only (never wrong, possibly incomplete). Confirm on a
   fresh crawl.
3. **Jabama sessions (#18–19).** Need the new diagnostics/key names from a fresh crawl, or a
   sanitized HTML snippet of the embedded session object, before any new shape is supported.
4. **Pizza (#3–5).** Confirm on the stored frozen evidence with a replay (below); the Cloud
   test is a reconstruction.
5. **Timezone of non-Tehran Events.** Oktober (Istanbul) still carries the source timezone
   `Asia/Tehran`; it is date-only and expired, so no instant is wrong, but per-Event timezone
   inference from an explicit foreign city is not implemented.
6. **Tehran by Tehran `media_evidence_partial`.** No new evidence in Cloud; no historical
   root cause is claimed. Future manifests already retain bounded failure categories.

## Owner local acceptance

Close the review workbook first. From the repository root (Windows PowerShell):

```powershell
git fetch origin
git switch --track origin/fix/gatherradar-source-field-hardening
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

Optional stored replay of the frozen observations into a *separate* state/workbook (no
browser, no OCR, no collection; the run time is the replay time, so dispositions are not
comparable to 2026-10-23, but grouping and fields are):

```powershell
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --stored --limit 5 --days 14 --db data\replay\state.sqlite3 --workbook data\replay\GatherRadar.xlsx --export-dir data\replay\exports
```

Then the fresh bounded crawl (all enabled sources; `davvvat_website` stays disabled):

```powershell
$env:GATHERRADAR_TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --limit 5 --days 14
```

Upload for QA: terminal output, the regenerated workbook, the new run manifest under
`data\runs\`, and for Jabama `48751310` / `01519540` the `source_session_diagnostics` and
`source_session_drift_keys` values from `data\raw\website\jabama_*.jsonl` (names only).
Check in the workbook: the seven Jabama descriptions contain `چه برنامه‌ای داریم؟`; one pizza
Event; Simorgh in schedule review with four dates; Rokhdad with four 19:00–20:30 sessions.
