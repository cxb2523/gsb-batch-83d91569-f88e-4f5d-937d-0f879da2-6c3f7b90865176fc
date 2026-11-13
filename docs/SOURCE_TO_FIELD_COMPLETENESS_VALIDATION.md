# Source-to-field completeness validation

## Scope and repository baseline

Owner run `ffb29b26622c445988b3e647ecf2d514`; stored reference
`2026-10-23T19:59:11.168836+00:00` = `2026-10-23T23:29:11.168836+03:30`.
Starting branch: `feat/data-quality-occurrences`; HEAD:
`efc5d8321aad9ae4f42cea534320a3fc14829d27`. The tree already contained extensive
uncommitted occurrence, title, capture, source and review changes. They were preserved.
Baseline: **1,328 offline tests passed**, using `.venv/Scripts/python.exe`.

The frozen selection reproduces 45 observations across nine sources and six publishers,
32 discoveries, one unresolved-title exclusion and 31 canonical Events. Replay uses
the stored run time and original source publication timestamps, not today's clock.
Raw observations are selected by manifest membership and observation cutoff.
Evidence JSONL lacks acquisition timestamps: exact historical media-variant membership
cannot be independently proved, although the replay reproduces the reported baseline.

## Confirmed causes and implemented corrections

- **Location extraction:** pin parsing considered the first location component only,
  missed a city separated by `|`, and included partial parenthetical directions in
  venue names. Compound area/building/gallery lines now retain each component;
  explicit name/branch pins retain venue and neighborhood. Sponsor/office pins are
  rejected. No city or street address is inferred from neighborhood knowledge.
- **Field contract:** nullable `location_context` carries explicit building wording
  through discovery facts, candidates, canonical resolution and field provenance,
  SQLite JSON payloads, CSV/JSON/Gemini and XLSX. Older records default to null.
- **Other text facts:** the explicit `مدت زمان اجرا` duration label and bounded
  event-is-held-by organizer prose are recognized. Authors, performers, sponsors and
  publishers are not automatically organizers.
- **Time loss:** time signal selection dropped dotted English AM/PM suffixes. The
  excluded Evenza candidate's `4:30 P.M` became `04:30`. Selection now preserves the
  suffix and normalization yields `16:30`; midnight/noon are deterministic. This
  correction does not establish a missing date or admit a titleless candidate.
- **Next-session presentation:** current exports expose the next supported future
  session date, clocks and count within the run horizon. Sessions sort by aware
  instant; date-only sessions retain unknown clocks. Already-started sessions and
  ongoing date ranges are not called future sessions. Parent dates and historical
  occurrences are unchanged. Ten of eleven actionable records have this presentation.
- **XLSX:** known canonical categories are translated on both actionable and schedule
  review sheets. New columns use the existing RTL design. The factual projection
  fingerprint now includes all canonical fields, so description/price/duration-only
  corrections cannot silently leave an old sheet stale. Old projections are retained;
  unchanged repeat export does not create another tab. Human edits are excluded from
  this fingerprint.
- **Media diagnostics:** refresh previously reduced acquisition details to
  `media_evidence_partial`. Future manifests preserve source/RawItem, failure category,
  slide/frame position and retry count; OCR/malformed-record counts are separate.
  Video inspection, missing duration, frame capture, page and checkpoint failures
  receive distinct categories. Raw exception bodies are not copied to the manifest.

Primary implementation files: `extraction/{fields,rules,models,rule_based,service,validation}.py`,
`domain/{event,event_candidate}.py`, `deduplication/resolution.py`,
`normalization/times.py`, `review/relevance.py`, `exports/{excel,excel_design,portable}.py`,
`collectors/instagram_evidence.py`, `orchestration/{evidence_run,refresh}.py`.
No new package, remote AI dependency or replacement extraction system was introduced.

## Frozen before/after results

| Metric | Before | After |
|---|---:|---:|
| Raw observations | 45 | 45 |
| Discoveries | 32 | 32 |
| Unresolved-title exclusions | 1 | 1 |
| Canonical Events | 31 | 31 |
| Actionable | 11 | 11 |
| Expired | 14 | 14 |
| Schedule review | 6 | 6 |
| Beyond horizon | 0 | 0 |
| Canonical IDs changed | — | 0 |
| Corrected canonical field values | — | 9 |
| Corrected excluded-candidate clock values | — | 1 |
| Actionable records showing next session | 0 | 10 |

The owner-only ledger covers **32 records × 21 fields = 672 field rows**, with raw IDs,
candidate IDs, fragment IDs, source spans where available, provenance, before/after
values, dispositions and diagnosed gaps. It does **not** establish semantic correctness
of every populated field or absence of every blank. Unknown evidence is explicitly
unverified, not reported as `SOURCE_NOT_PROVIDED`.

The following correctness denominator contains **43 explicitly checked source facts**,
including the excluded candidate's clock. It is not a whole-dataset completeness rate.
Other descriptions, occurrences, categories, availability and registration measurements
remain unverified in `metrics.json`; there is no claim of 100% completeness.

| Field | Checked facts | Correct before | Correct after | Remaining in checked subset |
|---|---:|---:|---:|---:|
| Title | 1 | 1 | 1 | 0 |
| Start date | 2 | 2 | 2 | 0 |
| End date | 2 | 2 | 2 | 0 |
| Start clock | 2 | 1 | 2 | 0 |
| End clock | 1 | 1 | 1 | 0 |
| Venue | 8 | 2 | 6 | 2 |
| Area | 3 | 1 | 3 | 0 |
| Building context | 1 | 0 | 1 | 0 |
| City | 2 | 1 | 1 | 1 |
| Address | 1 | 1 | 1 | 0 |
| Duration | 5 | 4 | 5 | 0 |
| Price text | 7 | 7 | 7 | 0 |
| Organizer | 8 | 7 | 8 | 0 |

Mana now retains its named gallery, area and building independently. Its explicit
24 Mehr–15 Aban range, 13:00–21:00 visiting hours and Saturday-closure wording survive
SQLite and Excel. It remains actionable; no continuous multi-day attendance interval
or city/address was fabricated. Source prices and descriptions were checked for
downstream parity, separately from whether upstream extraction was complete.

## OCR and live media findings

Both named original images were visually inspected. Twenty bounded local Tesseract
experiments compared original, enlarged, grayscale, top-crop and bottom-crop images
under PSM 6 and 11, using installed Persian/English language data. Original image and
OCR files were not modified. Windows image processing generated isolated derivatives;
no imaging dependency was installed into the project environment.

- **Evenza `DewenndDR2X`, slide index 4:** PSM 11 recovers workshop wording and
  `Four Gardens`; the tiny date header and building label remain inconsistent.
- **Jabama `DewdAUCCnsq`, slide index 1:** enlarged grayscale PSM 6 recovers
  `پنجشنبه ۳۰ مهر`, but still corrupts other activity/clock wording. Other variants
  worsen recognition. Results are experimental evidence, not automatically merged
  authoritative facts. Reliable unattended recognition remains unresolved.
- **Tehran by Tehran:** retained raw/evidence stores have no malformed rows or failed
  OCR fragments. The historical manifest lacks operation-level acquisition details,
  so its original cause is **unverified**. A bounded live check using the existing
  owner-authenticated profile processed the same five stored posts and captured
  **30 frames with zero failures**. No recrawl, login bypass or unrestricted browsing
  was performed. This is a non-reproduction, not proof that the historical defect is fixed.

## Tests and isolated acceptance

New sanitized regressions exercise compound/pinned location, office/sponsor negatives,
explicit organizer and duration, dotted AM/PM, end-to-end ranged exhibition fields,
next-session clocks and parent/history preservation, description-only re-projection,
and manifest diagnostic retention. Existing title admission, occurrence, media,
source registry and runtime tests remain part of the full offline suite.

Acceptance artifacts verify 31 stable owner Event IDs and canonical SQLite fact records,
17 current XLSX rows (11 actionable + six schedule review), CSV/JSON/Gemini field parity,
SQLite integrity and foreign keys, and idempotent repeat export. They preserve all
**148 original snapshots, 85 review rows, six runs and eight historical workbook sheets**.
Original database dump, workbook, raw/evidence JSONL and manifests were checked for
changes. No production workbook or snapshot was overwritten. XLSX reopened with
openpyxl and RTL/frozen panes/cell values were checked; no native Excel visual-render
certification is claimed.

Final full suite: **1,338 tests passed in 49.563 seconds**. Compile, `pip check`,
`git diff --check`, SQLite integrity and foreign keys passed. Repeat exports and
cross-format field/identity checks passed. The previously observed date-only projection
test failure during development was corrected before this final full-suite run.

## Remaining defects and limits

`unresolved.json` contains 19 Event-associated issue entries with exact Event IDs,
source URLs, evidence, earliest stage, blocker and proposed next action. It covers:

- the two OCR cases above (Jabama's missed activity has no canonical Event ID);
- three pizza candidates with differing OCR spellings from repeated Reel frames;
- bilingual Istanbul venue/city/duration extraction gaps;
- Davvvat Huner venue prose/address agreement and the mug workshop's colloquial area;
- Jabama descriptions restricted to the about section, omitting retained program text;
- Vadoostan conflicting header/narrative clocks or durations and incomplete multi-date parsing;
- two pottery sources with embedded-session schema drift and no captured dated sessions.

These remain explicit defects; filled cells, unchanged counts and passing tests do not
resolve them. The full semantic/visual audit requested across every source fact is not
complete. Non-Event false-positive rates and every possible duplicate are not certified.

## Local artifacts and safety

Everything containing owner source text or runtime data remains under ignored
`data/field-completeness-validation/`: `SOURCE_TO_FIELD_AUDIT.md`, `field-ledger.json`
and `.csv`, `verified-facts.json`, `metrics.json`, `field-changes.json`, `unresolved.json`,
`source-funnel.json`, `before.json`, `after.json`, `ocr/results.json`, `live-media.json`,
`acceptance.json`, `field-parity.json`, `GatherRadar-Fields.xlsx`, isolated SQLite and exports.
No commits, pushes, merges, resets, stashes, history rewriting or runtime deletion.
Davvvat collection policy, source registration, latest-five collection and carousel
capture boundaries were preserved.

**NOT READY — VERIFIED SOURCE-TO-FIELD LOSSES REMAIN**
