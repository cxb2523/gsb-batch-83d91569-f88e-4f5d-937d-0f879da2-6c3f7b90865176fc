# Optional Gemini handoff

The generated instructions mirror the local review design: Persian RTL, bold contrasting
headers, compact rows and bounded widths, clickable short labels with exact source URLs,
decision dropdowns and text-labelled status badges. Freeze **only the header row** and
open on current Events. Prefer Vazir for Persian/mixed text and Poppins for English
where supported; use a Persian-capable fallback otherwise. Fonts are not bundled and
Google/Gemini font availability is not assumed. Do not translate machine facts or infer
missing data to improve appearance. Publishing and visual acceptance remain manual.

Normal local refresh produces `data/exports/gemini/latest/` automatically. Regenerate
it offline from SQLite with `python -m gatherradar export gemini --run latest`.
Per-run bundles live under `data/exports/gemini/runs/<run_id>/`.

1. Run GatherRadar and inspect the local XLSX/JSON if needed.
2. Open the bundle directory.
3. Open Gemini manually in your browser.
4. Upload `review.json`, `events.csv`, `schedule_review.csv`, `places.csv`, `possible_duplicates.csv`,
   `manifest.json`, and `GEMINI_INSTRUCTIONS.md`.
5. Ask Gemini to follow `GEMINI_INSTRUCTIONS.md` and create/format a Persian RTL
   review Google Sheet, if that capability is available in your Gemini account.
6. Compare row counts, IDs, dates and source/registration links before using the Sheet.

GatherRadar requires no Gemini/Google credentials, API, or Google Cloud project for
this workflow. You may need to sign into Gemini/Google in the browser. The application
does not open Gemini, automate its UI, upload files, or claim its output is deterministic.
Manual live Gemini use has not been validated and is not required for Stage 9 readiness.

The manifest declares bundle/export versions, one run's timestamp/horizon/timezone,
filenames, counts, roles and SHA-256 hashes. Empty Places/duplicates CSVs retain headers
and are explicitly described. No local absolute paths or auth/browser state are included.
CSV/JSON bytes reuse the normal exporters; no second Gemini-specific fact serializer exists.

Only `events` / `events.csv` contains actionable publishing candidates at the stored
run timestamp. `schedule_review` / `schedule_review.csv` is a separate investigation
queue, never an upcoming Event list. Expired, beyond-horizon, cancelled or postponed
Events are excluded from the current Event view. JSON `event_dispositions` explains
membership; full historical Events and sessions stay in SQLite. Re-exporting an old
run preserves its reference clock rather than advancing it to today's date.

Instructions allow presentation improvements while prohibiting invented facts, factual
rewriting, silent row deletion, removed IDs, changed URLs, and automatic duplicate merges.
JSON is authoritative for exact strings/structured arrays; CSV is a spreadsheet-safe
table convenience. Source-derived cells are data, never instructions. Nulls stay unknown.

Export schema 3 retains source-supported context: `description_text` (the source's own
description), `area_text` (approximate neighborhood), `duration_text`, `organizer_name`,
`availability_text` and `source_schedule_text`. The instructions require Gemini to treat
descriptions as untrusted content (never instructions), keep them whole rather than
summarize them or fill `summary`, keep area separate from venue/address and never derive
an address from it, keep schedule wording visible without inventing occurrences, keep
availability as source wording without inventing capacity, and never derive duration or
organizer.

The resulting Sheet is a one-way presentation copy. SQLite owns application state;
JSONL owns source evidence. Use the local XLSX for persistent review decisions/notes.
No edits or generated facts return automatically. A manually downloaded compatible
review workbook could be considered in a future explicit workflow; arbitrary
Gemini-sheet ingestion is intentionally not implemented.
