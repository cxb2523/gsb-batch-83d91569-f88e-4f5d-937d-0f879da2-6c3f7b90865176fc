# Live-Run QA and OCR Fallback (2026-10-29)

Follow-up on branch `fix/gatherradar-source-field-hardening` (draft PR #11, base
`feat/data-quality-occurrences`). Neither PR #11 nor anything else was merged; `main` is
unchanged. Contract details: [data contracts](DATA_CONTRACTS.md#live-run-qa-fixes-2026-10-29).

**Inputs actually available in Cloud:** the owner's live-run `review.json`, workbook
`GatherRadar.xlsx` and manifest for run `e3ddedf31d5248808f78e5586b58d703` (started
2026-10-29T12:54:35Z, 9 sources, 26 canonical Events: 12 actionable, 10 schedule review,
4 expired). The referenced "targeted QA and OCR fallback master prompt" was **not** among
the attachments; this work follows the priorities stated in the owner's message. Raw
JSONL, HTML, media and SQLite from the run were not available; live sources remain
unreachable from Cloud.

## What the live run confirms about PR #11

- Jabama program sections reached `description_text` on five live pages (`89740631`,
  `86400491`, `48751310`, `01519540`, `08945247`): `چه برنامه‌ای داریم؟` and its text are
  present. The other two audit pages were not described this run (see open items).
- Mana's range shows a blank remaining-session count in the live workbook.
- The new session diagnostics fired on **every** Jabama website page
  (`embedded_session_drift_new_properties`), so no embedded sessions were read at all.

## Defects confirmed in this run and fixed

| Live item | Symptom | Cause | Fix | Tests |
| --- | --- | --- | --- | --- |
| Jabama `08945247` | `source_date_text` = `۲ ساعت` | `مدت زمان:` also matched the date label `زمان:` | nested labels belong to the longer label | `test_live_run_temporal.py` |
| Jabama `95037796` | `۸ آبان · ۱۸:۰۰` lost its clock → schedule review | `·` not a date/clock separator | `·`/`•` accepted as separators | same |
| Salovini `De98iwhkf3A` | `جمعه ۸ آبان / ساعت ۵` published as **05:00**, actionable | bare 12-hour clock read as 24-hour; extraction also dropped `عصر/شب` (so `ساعت ۸ شب` became 08:00) | day-part words kept and applied within fixed bounds; bare 1–6 without minutes = `ambiguous_meridiem` → schedule review | same |
| Salovini `De98iwhkf3A` | `جمعه و شنبه ۸ و ۹ آبان` unresolved | weekday-list prefix unsupported | expanded when weekdays match dates in order | same |
| Davvvat `DfCnNueOwV6` | no venue (`در عمارت زیرخاکی` under the title) | generic head without holding wording | standalone line under the title + repeated name | `test_live_run_fields.py` |
| Davvvat `DfCdYpmtECt` | no venue (`ایونت «چیزمیز» در کافه‌کتاب مدیا`) | no prose/address agreement for this form | quoted event name + exact address tail | same |
| All Jabama pages | zero sessions read | strict parser refused any new session property | bounded tolerant mode (below) | `test_jabama_sessions.py`, `test_jabama_program_sessions.py` |

Before/after on identical live wording (PR #11 head `0d4cc39` vs current head):

| Input | Before | After |
| --- | --- | --- |
| Hiilan description `source_date_text` | `۲ ساعت` | none from the duration label |
| `۸ آبان · ۱۸:۰۰` | 30 Oct, no clock, `unparsed_temporal` | 30 Oct 18:00 |
| `جمعه ۸ آبان / ساعت ۵` | 30 Oct **05:00** | 30 Oct, no clock, `ambiguous_meridiem` |
| `جمعه و شنبه ۸ و ۹ آبان` | no session, `ambiguous_date_context` | 30 and 31 Oct |
| venue سکانس چهارم / چیزمیز | null / null | `عمارت زیرخاکی` / `کافه‌کتاب مدیا` |

Policy change to note: a test previously pinned `ساعت ۸ شب` as unreadable. Combined with
extraction dropping `شب`, real 20:00 events became 08:00. `شب` is now applied to 6–11 only;
`ساعت ۲ شب` / `ساعت ۱۲ شب` remain unchosen.

## Jabama sessions with unknown properties

The new property **names** are recorded locally in raw metadata
`source_session_drift_keys` but were not in the uploaded files, so no new shape could be
documented. Bounded tolerant mode: a session whose only drift is extra, safely named
properties keeps its own id, start and duration (`schema_status = unverified_properties`);
price, discount, seats and enabled are not read. Its occurrence is reviewable but never
actionable, unless its date and clock equal exactly one schedule the page states in
visible text (then `embedded_session_corroborated_by_page_text`). Non-empty `timeslots`
and unsafe key names stay refused. Expected effect on the next live run: pottery,
perfume, tour and stand-up pages should show session dates in schedule review instead of
"unreadable"; the Hiilan workshop should stay actionable if its sessions match its visible 15:00 schedule.

## OCR fallback

`FallbackOcrProvider` with engines from `GATHERRADAR_OCR_ENGINES`
(default `tesseract,easyocr,windows`). Unavailable engines are skipped; a later engine runs
only after a failed or empty result; each attempt is stored separately and the chosen one
last. `python -m gatherradar ocr check [--image PATH]` validates engines read-only.

| Engine | Verified in Cloud |
| --- | --- |
| Tesseract 5.3.4 + `fas` | **Real**, through the chain, on a rendered Persian image (`RealTesseractTests`, skipped where Tesseract is absent) |
| EasyOCR 1.7.2 (optional extra) | **Real**, manual run in a scratch venv with Tesseract deliberately broken: read `کارگاه سفال / جمعه ٨ آبان` from a rendered image. Not part of the default suite (torch is large). |
| Windows.Media.Ocr (PowerShell) | **Not run** — Linux Cloud. Behaviour tested with a fake runner only. Persian (`fa`) OCR availability on Windows is not confirmed; if not installed, the engine reports unavailable rather than substituting another script. |

None of this proves OCR quality on the owner's Instagram media; the two OCR audit entries
(Evenza `DewenndDR2X`, Jabama `DewdAUCCnsq`) and this run's 9 `title_resolution_failed`
media candidates still need the original images.

## Open items (evidence needed)

1. **Jabama session key names:** run the snippet below and send the output.
2. **Jabama `69063962`** is now `non_event: retrospective_without_new_attendance` and
   **`legacy-941`** produced no Event (one unclassified item). Both were Events on 2026-10-23.
   The page text may have changed; need their latest raw JSONL lines.
3. **Media title failures:** 9 candidates excluded for missing titles (Jabama Instagram 6,
   Tehran by Tehran 2, Evenza 1); OCR images needed. Try `ocr check --image` on one slide.
4. **City from a hashtag:** `رویداد سکانس چهارم` gets city `تهران` from `#ایونت_تهران`. It is
   true here but not a stated location; not changed.
5. **Possible duplicate:** two Vadoostan `سفالگری با چرخ` pages at 10:00 and 13:00 on 8 Aban
   are suggested for review. They are distinct sessions; the suggestion is never merged.
6. **Venue not read:** `ایونت ویرا در تیدا سنتر` (address holds `مجتمع تجاری تیدا سنتر`).

## Validation

- Full suite: **1,403 tests, OK, 9 skipped** (optional google-sheets extra). The real
  Tesseract test runs where Tesseract is installed.
- New tests: `test_live_run_temporal.py`, `test_live_run_fields.py`, `test_ocr_fallback.py`,
  plus updated session tests.

## Owner local acceptance (Windows PowerShell)

Close the workbook first.

```powershell
git fetch origin
git switch fix/gatherradar-source-field-hardening
git pull --ff-only
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m gatherradar ocr check
```

Optional EasyOCR fallback (large download; models fetched once):

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[ocr-easyocr]"
.\.venv\Scripts\python.exe -m gatherradar ocr check --image "data\media\<one slide>.png"
```

Fresh crawl:

```powershell
$env:GATHERRADAR_TESSERACT_PATH="C:\Program Files\Tesseract-OCR\tesseract.exe"
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --limit 5 --days 14
```

Jabama session property names (names only, no values):

```powershell
@'
import json, pathlib
for path in sorted(pathlib.Path("data/raw/website").glob("jabama_*.jsonl")):
    latest = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        latest[item.get("id")] = item
    for item_id, item in latest.items():
        meta = item.get("raw_metadata") or {}
        if meta.get("source_session_diagnostics"):
            print(item_id, meta.get("source_session_diagnostics"), meta.get("source_session_drift_keys"))
'@ | .\.venv\Scripts\python.exe -
```

## Follow-up: XLSX export failure in run `ca3548cb65534d868277f140cdc92855`

The run persisted 28 canonical Events (13 actionable, 11 schedule review), but XLSX export
stopped with `A review cell exceeds the XLSX text limit`. Cause: the Jabama Event
`تجربه ساخت ماگ شخصی با سفال` (`legacy-941`) now has 50 embedded sessions; its hidden
`occurrences` cell serialized to 56,591 characters (limit 32,767). SQLite, CSV and JSON
were complete.

Fix: oversized snapshot values are stored losslessly in a hidden `_overflow` sheet (chunks
≤ 32,000 characters with SHA-256 and length) and the cell refers to them; see
[the data contracts](DATA_CONTRACTS.md#workbook-schema-version-3). Reviewer-owned values are
never shortened, and remaining failures name sheet, record ID, field and length.

Acceptance on the owner's `review.json` (rebuilt into an isolated SQLite in Cloud): export
succeeds; the reopened workbook has 13 rows in the main sheet and 11 in Schedule Review;
all 50 occurrences reassemble byte-identically from `_overflow` and match SQLite, CSV and
JSON; a decision and note round-trip through import; a same-run re-export adds no sheet or
overflow row. The 4 expired Events are not in `review.json`, so that isolated DB has 24.

The optional Google Sheets adapter sends the same serialized value and has its own
per-cell limit (not changed or validated here).

Offline re-export with your stored state (no crawl; close the workbook first). Replace the
paths with your isolated database and workbook:

```powershell
.\.venv\Scripts\python.exe -m gatherradar export all --run ca3548cb65534d868277f140cdc92855 --db "data\state\gatherradar.sqlite3" --workbook "data\review\GatherRadar.xlsx" --export-dir "data\exports"
```

## Follow-up: Jabama `soldOut` and `timeslots` (evidence boundary)

Confirmed from the owner's local diagnostics: unknown property `soldOut` on Jabama Events
`69063962`, `62170465`, `08945247`, `95037796` and Experiences `48751310`, `01519540`,
`86400491`, `89740631`, `legacy-941`, `88230976`; non-empty `timeslots` on `48751310`,
`01519540`, `86400491` (Experiences); `71461868` empty sessions; `86400491` (Events) generic
envelope drift. The raw store keeps names only, the live pages are unreachable from Cloud,
and no saved HTML was supplied, so **types and meaning are not verified** and no new schema
is supported. See [the contract](DATA_CONTRACTS.md#jabama-session-evidence-boundary-2026-10-29).

Fixed now: an unverified session whose own date has passed is `expired` instead of
schedule review; envelope failures name their stage; new observations keep value-free
shapes; the read-only `diagnose jabama-sessions` report.

Generate the sanitized report (read-only; existing observations show names/diagnostics):

```powershell
.\.venv\Scripts\python.exe -m gatherradar diagnose jabama-sessions --data-dir data --output data\exports\jabama-session-schema.json
```

To include structure without a crawl, save public pages in your browser (Ctrl+S, "Webpage,
HTML only"), e.g. `https://jabama.events/events/48751310` and `.../62170465`, then:

```powershell
.\.venv\Scripts\python.exe -m gatherradar diagnose jabama-sessions --data-dir data --html "$HOME\Downloads\48751310.html" --html "$HOME\Downloads\62170465.html" --output data\exports\jabama-session-schema.json
```

(The next regular refresh also records shapes automatically.) Offline replay and export,
no crawl:

```powershell
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --stored --limit 5 --days 14 --db data\replay\state.sqlite3 --workbook data\replay\GatherRadar.xlsx --export-dir data\replay\exports
.\.venv\Scripts\python.exe -m gatherradar export all --run latest --db data\replay\state.sqlite3 --workbook data\replay\GatherRadar.xlsx --export-dir data\replay\exports
```

## Follow-up: evidence-grounded Jabama timeslots

The owner's v3 structural report (`jabama-session-schema-v3.json`, two saved pages, 81 and
7 sessions) confirmed `soldOut` as a boolean (false in all 88) and the twelve timeslot keys.
It carried no values, so ownership, timestamps and seat relationships remain unverified.
Implemented: typed `soldOut`, strict independent timeslot records with parent and child
identity, a parent-window check, seat-count consistency, duplicate-ID handling and a
publication gate (`VERIFIED_SESSION_SEMANTICS`, empty). Timeslots and `soldOut=true` are held
in Schedule Review; `soldOut=false` sessions with empty timeslots are handled as documented
sessions again. See [the contract](DATA_CONTRACTS.md#jabama-session-evidence-boundary-2026-10-29).

Relationship check of the same browser-saved pages (read-only; writes only the report;
booleans and counts per page position, no file names or values):

```powershell
.\.venv\Scripts\python.exe -m gatherradar diagnose jabama-timeslots --html "$HOME\Downloads\page-81-sessions.html" --html "$HOME\Downloads\page-7-sessions.html" --output data\exports\jabama-timeslot-relationships.json
```

Replace the two paths with the saved files used for the v3 report. Please share the JSON.
The gate is opened only if every `session_id_equals_parent_id` is `true`, `start_before_end`
is all `true`, `timestamp_form` has no `unparseable`, `parent_window` is all `within`, and
`availability` has no `inconsistent`; `sold_out` additionally needs a `soldOut=true` example.

Offline replay into an isolated database (no crawl). Stored observations keep the session
records parsed at collection time: October 29 `soldOut` sessions stay `unverified_properties`
and refused timeslot sessions stay absent. This replay therefore checks compatibility (no
lost Events, identities, decisions or exports), not the new parsing. Both take effect after
the next normal local collection of `jabama_events_website` and `jabama_experiences_website`,
which appends a new revision because the parsed session records changed.

```powershell
.\.venv\Scripts\python.exe -m gatherradar refresh --all-enabled --stored --limit 5 --days 14 --db data\replay-timeslots\state.sqlite3 --workbook data\replay-timeslots\GatherRadar.xlsx --export-dir data\replay-timeslots\exports
```
