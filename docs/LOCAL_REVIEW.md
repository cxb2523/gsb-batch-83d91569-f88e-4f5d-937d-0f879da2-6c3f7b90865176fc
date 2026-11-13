# Local persistence and review

GatherRadar uses JSONL for source/evidence audit, SQLite for durable canonical and
human review state, and XLSX as the default review interface. CSV and JSON are
portable exports. No Google account, Office installation, server, paid API, or
internet connection is required for persistence and export. Collection still
requires access to the selected public sources; Instagram may require the existing
Chrome login and local Tesseract setup.

## Owner workflow

```bash
python -m gatherradar refresh --all-enabled --days 14
python -m gatherradar refresh --source davvvat_website --limit 2 --days 14
python -m gatherradar refresh --all-enabled --skip-instagram-evidence
```

Open `data/review/GatherRadar.xlsx`. Save and close it before the next refresh.
Refresh imports supported decisions/notes first, collects exact current members,
analyzes them, commits SQLite, and exports a new snapshot. New, Changed, and
Existing-but-observed items all belong to the run; unobserved historical items do not.
Source failures are isolated and produce a partial/failed status with a nonzero exit.

For existing observations without collection, browser, OCR, or network:

```bash
python -m gatherradar refresh --all-enabled --stored --days 14
```

This preserves the existing bounded local selection: website first-seen storage
order and Instagram publication recency. It does not claim fresh listing membership.
`--limit` is 1–30 per source (default 5). `--days` is 1–90 (default 14), inclusive from
run start's `Asia/Tehran` date. `--review-timezone` affects presentation, not eligibility.
The exact stored refresh clock excludes reliably ended Events, including earlier today.
Ongoing ranges overlap the window; an unknown end time is not invented. Inferred dates retain warnings.
Filtered Events remain in SQLite history. Event/source timezones are preserved.

An actual activity must be established before resolving a meaningful display title.
An explicit heading is preferred; a concise factual description supported by this
Event's own source evidence may also pass. Derived titles retain a review warning,
their source span and fragment IDs in hidden technical columns. Blank/generic or
unsupported titles, collection covers and non-Event promotions remain excluded.
The source funnel distinguishes RawItems, candidates, Events and Occurrences.
Raw captions, OCR and provenance remain available for offline reprocessing.

## Paths, recovery, and re-export

Defaults derive from `--data-dir` (default `data`):

| Purpose | Default |
| --- | --- |
| SQLite | `data/state/gatherradar.sqlite3` |
| Human workspace | `data/review/GatherRadar.xlsx` |
| Run metadata | `data/runs/<run_id>.json` |
| CSV/JSON | `data/exports/{latest,runs/<run_id>}/` |
| Gemini bundle | `data/exports/gemini/{latest,runs/<run_id>}/` |

Override with `--db`, `--workbook`, and `--export-dir`. Paths use portable `pathlib`.
Runtime defaults are Git-ignored; keep custom output paths outside tracked source
directories. Initialization is automatic and idempotent.

```bash
python -m gatherradar status
python -m gatherradar review import
python -m gatherradar export --run latest
python -m gatherradar export --run <run_id>
python -m gatherradar export csv --run latest
python -m gatherradar export json --run latest
python -m gatherradar export gemini --run latest
```

`export` reads SQLite without analysis, collection, OCR, or Google. `latest` selects
the newest persisted run. The `latest/` artifact directory holds the most recently
exported selection; exporting a historical run deliberately updates that view.
The per-run directories remain independently addressable. Review decisions are
current SQLite state over historical source facts, not historical human-state backups.
CSV/JSON/Gemini-only commands do not load openpyxl or import XLSX edits.

SQLite commits before export. An export failure leaves canonical state intact and
prints a recovery error. Retry `export` after fixing the path or closing the workbook.
A repeated completed `--run-id` does not collect or insert another run; it retries
exports. Interrupted runs reuse their original reference time and matching options.

## Workbook and human ownership

Permanent sheets are `راهنما`, `تاریخچه اجراها`, `بررسی تکراری‌ها`; `_meta` is hidden.
Run sheets are `رویدادها <Jalali-date> <HHMM>` and, when Places exist,
`مکان‌ها <Jalali-date> <HHMM>`. Same-minute names receive deterministic shortened
suffixes within XLSX's 31-character limit. The index links to each historical sheet.
Historical sheets, including arbitrary visual edits, are not rewritten during export.

Re-exporting a legacy run applies current title admission to every new output.
If the existing Event tab contains excluded IDs, XLSX adds a filtered projection
for that same run and updates the index to it. The original tab remains intact
as history. `_meta` marks that superseded tab; later review imports use its
replacement, avoiding duplicate or stale review decisions. Save and import any
edits first (the `export` CLI does this automatically). Repeating the export does
not add another projection. Historical SQLite facts and decisions are retained.

The optional Sheets adapter similarly appends a deterministic `_eligible_…` run
projection when a legacy snapshot's counts differ, preserving its prior tabs and
human review. Repeated publishing reuses that projection. No Google connection is
required to regenerate the local workspace.

The primary Event columns follow the Persian contract in
[DATA_CONTRACTS.md](DATA_CONTRACTS.md#local-review-and-persistence-stage-9):
decision, title, category, lifecycle status, Jalali dates/weekday/times, the announced
schedule, venue / area / city / address, duration, price, availability, format, the
source description, organizer, action and source links, source count, data quality and
your note. Column meanings:

| Column | Meaning |
| --- | --- |
| `مکان` | Named venue |
| `منطقه / محله` | Approximate area/neighborhood the source states; never a precise address |
| `آدرس` | Precise address, only when the source gives one |
| `زمان‌بندی اعلام‌شده` | Exact source schedule wording: always shown for multiple sessions, weekly recurrence or daily windows; otherwise shown only when the normalized date is missing, inferred or diagnosed |
| `مدت` | Stated length, never computed from times |
| `ظرفیت / وضعیت ثبت‌نام` | Booking status, separate from date relevance: the source's own availability wording (badge; `تکمیل ظرفیت` also sets lifecycle status), else per-session source facts in plain Persian (a session sellout flag, a flag contradicted by seat counts, or the first listed session's remaining seats), never a booking guarantee |
| `توضیحات / معرفی` | The source's own description — not an AI or generated summary |
| `برگزارکننده` | Explicitly labelled organizer/host only |
| `آمادگی داده` | `آماده بررسی`, `نیاز به تکمیل`, `نیاز به بررسی زمان‌بندی`, or `منبع در دسترس نیست`; filter within the existing snapshot |
| `دلیل بررسی` | Readable reason for the assessment, separate from human notes |
| `جلسه‌ها` | Each supported occurrence's own date/time, price wording and availability; no arbitrary primary date |

Three separate questions: the sheet (current Events vs Schedule Review) answers
"is it temporally relevant now"; `آمادگی داده` answers "are the details complete and
consistent"; the capacity column and `وضعیت رویداد` answer "what does the source say
about booking". When the source states two different values for one field (for
example length «۲ ساعت» and «سه‌ساعته»), the field stays empty and `دلیل بررسی`
quotes both values verbatim.

Readiness does not assert publication approval or complete collection. A missing
optional price, location or description is not a defect without evidence that a
supported fact was lost. Inferred years, schedule conflicts and recurring rules
need schedule review; known extraction failures, absent titles and partial OCR
need enrichment. Raw observations remain available; only admitted Events enter
new canonical history. The review horizon
checks actual dated sessions individually, never an invented first-to-last interval.
Unresolved/conflicting schedules appear in a separate `زمان‌بندی` worksheet and
`schedule_review.csv` / JSON `schedule_review` array. They are not actionable upcoming
Events. The current Event view contains only relevant supported occurrences; the full
session history remains in SQLite. Cancellation/postponement excludes publishing;
sold-out/availability facts remain separate. Re-export always uses the stored run clock.

An ongoing exhibition with a supported date range belongs in the Event view even
when its visiting-hours exceptions need checking. The warning remains visible in
`دلیل بررسی`; it does not turn known relevance into an unknown date. Relative dates
require the original publication timestamp. A bounded date list preserves all
listed sessions without assigning the first session's clock to later dates.

`disposition_counts` partitions eligible canonical Events into `actionable`, `expired`,
`beyond_horizon`, `needs_schedule_review`, and `otherwise_excluded`, without overlap.
JSON `event_dispositions` gives each Event's reason and individual session dispositions.
`filtered` includes every non-actionable disposition; `undated` is the schedule-review
count, including ambiguous dated schedules. Historical workbook sheets remain intact;
a changed projection gets a new sheet and preserves the old one.

The former `خلاصه` column was always empty and is no longer shown; `summary` stays a
reserved machine field. Descriptions are complete in the cell but rows stay at most 60
points; open or expand the cell to read it. Only a description longer than Excel's
32,767-character cell limit is cut, with a visible marker; JSON/CSV keep all of it. Any
value over that limit (for example the session list of an Event with dozens of sessions)
is also kept whole, in order, in the hidden `_overflow` sheet; the cell refers to it.
Additional supporting-source columns appear only for multiple source URLs, so each
has its own clickable hyperlink. Original URLs remain in hidden `evidence_urls` and
portable exports. Labels are compact publisher names; hyperlink targets remain exact.
No macros or formulas are required. Technical IDs, ISO dates, provenance, diagnostic
codes, and an opaque review baseline token are hidden. Hidden columns are not security
controls. Every user-facing sheet is RTL with selected wrapped text, bounded widths, frozen header row only (`A2`),
filters, and review dropdowns. Explicit Jalali dates/weekday do not depend on locale.

Workbook schema **3** opens on the newest Event snapshot. Latest Events/Places come
first, then history and duplicate review, older snapshots newest first, guide and hidden
metadata. History has date/time, status, horizon, attempted source count, canonical/shown
Event counts, Places, duplicates, safe source failures and snapshot links.

`exports/excel_design.py` owns the consistent dark header, calm banded body, light
separators, text-labelled decision/status/quality badges, dropdown conditional formatting,
semantic width bounds and 24–60 point body rows (30-point headers). Long descriptive
text is capped visually; expand rows manually to read it all. Dates/times stay compact.
Only supported category keys receive Persian display labels; machine values remain hidden
and unchanged in CSV/JSON. Normal AutoFilter ranges are retained; Table objects add no
needed behavior to immutable snapshots and would add history naming/import complexity.

Best appearance requires **Vazir + Poppins** installed. Persian/mixed cells reference
Vazir; English-only values, technical IDs and URLs reference Poppins. Fonts are not
bundled or detected at runtime; fallback depends on the spreadsheet client.

A schema-2 workbook from earlier Stage 9 runs is accepted: its snapshots are read by
header name, left untouched, and the next export upgrades the workbook to schema 3.
Schema-1 prerelease and newer-than-3 workbooks are detected and refused without
overwrite or import. Keep the old workbook and use a separate `--workbook` path to
regenerate schema 3 from SQLite. Already-imported review state survives in SQLite; unimported schema-1 edits
must be retained for manual reconciliation. There is no automatic schema-1 migration.

Event decisions: `بررسی نشده`, `علاقه‌مندم`, `می‌خوام برم`, `رفتم`, `رد شد`.
Duplicate decisions: `بررسی نشده`, `یکی هستند`, `جدا هستند`.
Only decisions and notes import. Title/date/price/location/area/description/duration/
organizer/availability/schedule/URL edits remain visual changes to that snapshot; they
never become canonical facts or extraction input.
Duplicate decisions never merge Events or change Stage 8 matching.

Event review carries across runs only by exact Stage 8 Event ID. Only the newest
workbook snapshot containing an Event is eligible for import; tab/row order does not
change precedence. Place review is deliberately scoped to `(run_id, candidate_id)`;
Place cross-source deduplication and cross-run review carry-forward are not implemented.
The permanent duplicate queue retains previously seen pairs even if absent this run;
portable exports contain only the selected run's pairs.

Import validates schema, IDs, row membership, allowed values and baseline tokens.
Unknown/changed IDs, duplicate identities, formulas in human fields and malformed rows
are isolated and counted. Tokens bind the exported kind/ID/run to its original human
state. A stale edit that conflicts with newer SQLite review state is reported, never
silently accepted. Unchanged historical/default cells do not undo newer decisions.
Repeated explicit edits to a previously imported snapshot can therefore conflict;
create a new snapshot or a separate recovery workbook from SQLite before further edits.

`review import` prints imported/skipped/malformed/conflict counts and exits nonzero for
malformed/conflicting rows. Automatic refresh can persist useful new source data, but
holds the existing XLSX untouched if any such rows need resolution; CSV/JSON/Gemini
exports still complete. Restore the affected values/IDs locally, or export to a separate
`--workbook` path to recover current SQLite review state. Corrupt/incompatible workbooks
stop automatic import before collection; they are never silently replaced.

Writes use a sibling temporary XLSX, reopen and compare every cell, then atomically
replace the destination. A locked file preserves its old bytes. Owner structural edits
to required headers, metadata, run index or snapshot deletions require repair or a
separate recovery workbook. Unsupported spreadsheet features may not survive openpyxl
rewriting; this is a standard GatherRadar review workbook, not a general Office editor.

## SQLite policy

Standard-library `sqlite3`, no ORM/server. `CanonicalRepository` is the durable seam;
`SqliteCanonicalRepository` isolates SQL. Schema version 1 uses `PRAGMA user_version`.
Empty databases initialize transactionally; current versions are no-ops; newer versions
and unversioned databases with existing tables fail without destructive replacement.

Foreign keys are enabled on each connection, busy timeout is 5 seconds, WAL is enabled,
and `synchronous=FULL` favors local durability. Every canonical run uses `BEGIN IMMEDIATE`
with commit/rollback. Unique IDs and foreign keys protect run/snapshot/pair membership.
Review imports use short independent transactions to isolate malformed rows.

Keep the database local, with one active owner workflow. Do not use simultaneous
multi-writer access through cloud-synced/network folders. Export files may live in a
synced folder, but close them before refresh and avoid concurrent editing. A local
exclusive `.sqlite3.lock` coordinates refresh/export/import; it is not a distributed
lock. After a crash, remove it only after verifying no GatherRadar process is active.
Back up the DB while GatherRadar is closed, including any outstanding SQLite sidecars,
or use SQLite's backup API; do not copy a live WAL database file in isolation.

## Portable formats

JSON/CSV records schema version 3: `schema_version`, `run`, `events`, `places`,
`possible_duplicates`. UTF-8, deterministic sorted JSON keys; arrays stay arrays,
nulls stay null, dates/times are ISO, Decimal is exact text, enums use stable keys.
Canonical field provenance and diagnostic codes remain structured. Source date and
price wording remain present. Raw contexts, OCR and credentials are excluded.
An unchanged source caption can be `description_text` when attributed to one
defensible Event; it is never summarized. Occurrences retain their own provenance
and price/availability, with null parent dates for distinct sessions. Readiness
reasons and quality indicators use stable English keys.

CSV uses standard-library `csv`, stable English field names, UTF-8 with BOM, null as
empty, and compact JSON for nested arrays/objects. Formula-risk values beginning with
`=`, `+`, `-`, `@` (including whitespace-concealed prefixes) receive an apostrophe;
leading tab/newline also gets a prefix. JSON preserves the original string. XLSX writes
source/review strings as explicit literal cells. Text exceeding XLSX's 32,767-character
cell limit is never silently truncated: snapshot values go losslessly to hidden `_overflow`;
an over-limit reviewer note or any unfitted cell fails export with its sheet, record ID,
field and length. Empty CSV tables retain headers.
CSV is an interchange format; it carries no badge/font/color styling. Serialized
session lists can exceed common CSV reader limits (an Event with hundreds of
timeslots holds well over 131,072 characters in `occurrences`): Python readers must
raise `csv.field_size_limit`, and spreadsheet programs opening the CSV directly may
cut cells at 32,767 characters. Use the XLSX (lossless `_overflow`) or JSON for such
values; the CSV cell itself is complete. JSON/CSV and
SQLite DDL remains version 1. Record migration is additive on read: legacy records
get empty occurrences and unknown schedule kind, never fabricated sessions. Stored
historical payloads, reviews, duplicate state and tokens are not rewritten. XLSX
remains version 3 with header-based imports and additional new-snapshot columns.

## Portability and optional publishing

Persistence/export uses no COM, Office, VBA, AppleScript, or required LibreOffice.
`openpyxl>=3.1.5,<3.2` generates standard OOXML. The selected release declares Python
>=3.8 and is tested here on Python 3.13; this does not claim a macOS/Linux or
Excel/Numbers/LibreOffice visual test. See [package metadata](https://pypi.org/project/openpyxl/).
Client rendering and validation behavior can differ; CSV/JSON are fallback formats.

The [Gemini handoff](GEMINI_HANDOFF.md) is manual and one-way. The
[Google Sheets API adapter](GOOGLE_SHEETS_SETUP.md) is separately optional and still
awaits live OAuth/Sheets validation. Neither is a local Stage 9 readiness prerequisite.
