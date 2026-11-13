# Final Excel Closure — GR-EXCEL-CLOSURE-20261029

**Status: READY FOR ONE LOCAL EXCEL ACCEPTANCE RUN.** Every bug that the supplied
evidence could reproduce is fixed, and tests pass. Unknown facts are handled visibly.
What remains is the owner's single fresh crawl and real-media check.

Branch `fix/gatherradar-source-field-hardening`, Draft PR #11 (base
`feat/data-quality-occurrences`). Per-case results:
[`FINAL_EXCEL_CASE_RESULTS.json`](FINAL_EXCEL_CASE_RESULTS.json).

## Inputs received

All ten package inputs were present and matched the manifest's sizes and SHA-256:

- latest workbook, review JSON and run manifest `ca3548cb…`;
- the Jabama v3 structural report and the timeslot relationship report;
- the historical audit, `unresolved.json`, the field workbook, review JSON and manifest `e3ddedf3…`.

The package contains none of the original media, saved HTML, raw/evidence JSONL,
databases, browser data or fonts.

## Evidence tiers

| Tier | What it is | Used for |
| --- | --- | --- |
| Owner-produced | Relationship report: 88 parents and 295 timeslots, every check passing; v3 shapes | Enabling Jabama timeslots |
| Caption replay | Discovery, normalization and canonicalization rerun on the captions stored in the supplied `review.json`, at the frozen reference (no media; publication time unknown) | F01, F02, F03, F06, F07 |
| Projection replay | The supplied 13 + 11 projection re-exported through current code at `2026-10-29T13:59:38Z`. These are stored facts, not a re-extraction | Workbook, overflow and validator checks |
| Synthetic | Sanitized fixtures and unit tests | Every rule, positive and negative |

The projection replay is kept outside Git, under the scratchpad's `final/qa-final-replay/`. Results:

- Workbook valid: 13 + 11 rows matching the run.
- One overflow value intact; no cell over 32,767 characters.
- Only the header row is frozen; fonts are Vazir and Poppins only.
- The validator reports `CHECK` for F01, F02, F04, F07, J01 and J04. This is correct: those stored facts predate the fixes, which is why the fresh crawl is required.
- Native visual rendering was not possible in Cloud and remains a local check.

## What changed

1. **Jabama timeslots (J01, J02, J05).** `VERIFIED_SESSION_SEMANTICS = {"timeslots"}`, backed by the relationship report.
   - Every timeslot still passes the strict per-record checks.
   - Each child keeps its own start and end; the parent `durationHours` is never reused.
   - The horizon applies per timeslot. The current view lists only in-horizon sessions, while SQLite keeps all of them.
   - A visible page window that contains the timeslots is not emitted as another session.
2. **Sold-out flags and availability (J03).**
   - `soldOut=true` is a booking flag only. It never affects expiry or Schedule Review and never sets the status.
   - A flag contradicted by remaining seats drops the seat count.
   - Gate `"sold_out"` stays unset.
3. **legacy-941 (J04).** A whole-session window that contradicts the stated activity length keeps its dates. It goes to Schedule Review with a Persian reason, and no slots are invented.
4. **Fields (F01–F07).**
   - Presence-verb venue in the dated clause.
   - Prose name of an address building as the venue.
   - No city from a hashtag or handle.
   - A narrative length adjective conflicting with the header length keeps both wordings (`Event.conflicting_values`) and quotes them in Persian.
   - Program sections that are not adjacent to About are joined as separate exact slices.
5. **OCR (O01).**
   - `ocr-quality/1` lets an implausible nonempty reading continue to the next local engine.
   - The cache is keyed by image, slot, and engine/version/config. Newly installed engines can recover old images without rerunning good ones.
   - Selection prefers a usable reading of the same image.
6. **Excel (X03).**
   - Which sheet a row is on reflects temporal relevance.
   - `آمادگی داده` reflects completeness.
   - The capacity column shows booking facts (source wording, session flags, seats), never a guarantee.
   - The guide explains this split.
   - `refresh` reports collection, persistence and each export separately. When the workbook fails, it prints the exact offline recovery command.
7. **Acceptance (R01).**
   - `gatherradar acceptance --run-dir …` validates and writes one bundle.
   - `scripts/final_excel_acceptance.ps1` runs tests, then one crawl, then the bundle.

## Remaining limitations, honestly

- **Source ambiguity:**
  - the meaning of `soldOut=true` (no example);
  - exact attendance times for legacy-941;
  - the Simorgh and Rokhdad conflicts;
  - recall for multi-activity collections (Emrooz).
- **Real-media checks** (O02, O03, D01):
  - original images were not supplied;
  - the nine title exclusions in `ca3548cb…` are not nine known Events;
  - nothing is claimed from synthetic posters;
  - OCR recovery needs a second local engine (EasyOCR or Windows OCR) to be installed.
- **Old observations** keep the session records parsed when they were collected. Only the fresh crawl applies the new parsing; the revisions it appends are expected.
- **CSV:** a cell can exceed common reader limits (Python needs `csv.field_size_limit`). Use the XLSX or JSON for those values.

## Tests and checks (Cloud, Python 3.13)

- `python -m unittest discover -s tests`: **1,482 run, OK, 9 skipped, 0 failed.** All 9 skips are the optional `google-sheets` extra.
- `compileall`, `pip check` and `git diff --check`: clean.
- The acceptance script ran end-to-end in Cloud with PowerShell 7.6 in `-OfflineReplay` mode (parse errors 0, exit 0, bundle created).
- Windows PowerShell 5.1 and the live crawl are the owner's local run.

## The one local acceptance run (Windows)

```powershell
cd C:\path\to\GatherRadar
git fetch origin fix/gatherradar-source-field-hardening
git checkout fix/gatherradar-source-field-hardening
git pull origin fix/gatherradar-source-field-hardening
.\.venv\Scripts\python.exe -m pip install -e .
powershell -ExecutionPolicy Bypass -File scripts\final_excel_acceptance.ps1
```

What the script does:

1. Runs the tests and stops on any failure.
2. Performs exactly one `refresh --all-enabled --limit 5 --days 14` into `data\qa-final-<timestamp>\`, with its own SQLite, workbook and exports. It reuses the existing GatherRadar Chrome profile.
3. Validates the workbook.
4. Writes `data\qa-final-<timestamp>\GatherRadar-review-bundle.zip`.

Add `-IncludeMedia` to put a bounded selection of stored public media for the tracked OCR cases into the bundle. Nothing is uploaded automatically.

Raw and evidence stores under `data\` are shared append-only history, not isolated per run.

**Return only `GatherRadar-review-bundle.zip`.** It contains:

- the workbook;
- the run manifest and `review.json`;
- the test summary, OCR check and refresh output;
- `acceptance-report.json`, with workbook checks, per-case outcomes and the OCR evidence index.

It excludes the database, cookies, browser profile, `.env`, raw stores, local paths and signed media URLs.

## Owner acceptance run `3e9237b1…` (2026-10-29)

Commit `0318b82`: 16 actionable Events, 4 Schedule Review, 6 expired, valid workbook,
10 missing-title exclusions. Every image in the returned bundle (40) and every stored
OCR reading was inspected; captions were not in that bundle. Per-item findings are in
`FINAL_EXCEL_CASE_RESULTS.json` (`acceptance_run_3e9237b1`):

- **Evenza `DfCIk4Njdij` (3 exclusions):**
  - The carousel holds nine genuine single activities, several still upcoming at the run (۸ آبان).
  - They were missed because both local engines misread the stylized date headers and Persian titles.
  - Even exact text would require choosing the title among same-shaped lines, i.e. encoding one publisher's template. Not changed.
- **Jabama `DfC8atTke1c` (4 exclusions):**
  - A one-day itinerary whose clocks are suggested slots.
  - Two stops have their own dates, but their stored OCR is garbled.
  - Using itinerary clocks would fabricate schedules. Not changed.
- **Tehran by Tehran:**
  - `DfE3vanOLGI` is a mood Reel; its concrete show is already an Event from the Jabama website.
  - `DfC2146NWtl` had no bundled frames.
- **Davvvat `DfFPSscke1e`** was untracked, so no evidence was bundled.

The bundle tooling now:
- indexes captions and every title- or evidence-excluded item;
- shares the image budget round-robin;
- writes the zip itself, so entry names are portable (Windows PowerShell 5.1 `Compress-Archive` had stored `media\…`).

The dependency probe no longer nests quotes. No further live crawl is required for closure. Recovering the poster-only activities needs better local OCR of stylized Persian type or the publishers' caption text, not a rule change.
