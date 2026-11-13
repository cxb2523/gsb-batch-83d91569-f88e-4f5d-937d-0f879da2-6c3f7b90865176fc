# Data-quality hardening validation — 2026-10-20

## A. Repository starting state

- Clean checkout on `fix/instagram-evidence-hardening`.
- HEAD `efc5d8321aad9ae4f42cea534320a3fc14829d27`; main/base
  `67fb44f12b6cd6b24e26a80b6b26cab03af1ce21`.
- GitHub public API verified PR [#10](https://github.com/MohebaliDesign/GatherRadar/pull/10)
  is open and its head exactly matches the checkout. No merge or history rewrite.
- Work branch: `feat/data-quality-occurrences`, created from that head.
- Baseline: **1,154 tests passed, 0 failed, 0 skipped** (27.647 seconds).
- Inspected README, PROJECT_CONTEXT, DATA_CONTRACTS, STAGE9_VALIDATION,
  SOURCE_FIELD_COVERAGE, LOCAL_REVIEW and PUBLISHER_RECOVERY, and the collection,
  acquisition, evidence/grouping, extraction, normalization, deduplication,
  persistence, review/export and orchestration boundaries.

The owner's local raw/evidence stores, SQLite, XLSX, run manifest and portable
exports were available. Run `32ce8008399143b4887ec85c0ade1f1b` was frozen into an
ignored acceptance directory. Archived baseline code replayed its exact 40
observed item IDs from eight sources at the original reference time and reproduced
**35 canonical / 28 displayed / 7 filtered / 17 undated / 1 possible duplicate**.
Historical source captures were not modified.

Evidence has no capture timestamps or complete per-run media manifest. The replay
uses frozen latest-known evidence slots, not an invented historical media snapshot.
Its output matched the owner's persisted baseline exactly on the reported metrics.

## B. Confirmed root causes

| Source-supported fact | Actual loss / earliest point | Repair |
| --- | --- | --- |
| `پنجشنبه ۳۰ مهر - ساعت ۱۹` and equivalent prose | Calendar date survived; the separator remained before strict clock parsing | Remove a date-to-labelled-clock separator only after a supported date; negative/invalid clocks still fail |
| Weekly/nightly source clocks | Recurrence or extra schedule wording erased a known clock | Preserve clocks and supported recurrence rules without generating dates; retain competing diagnostics |
| Explicit distinct dates and same-day sessions | Only one parent temporal record existed | Separate deterministic occurrences, with no arbitrary parent date |
| Theatrical credits, quoted project titles, dated performance headline | Title rules required narrow conventional keywords | Evidence-gated structural title rules, meaningful digits and explicit abstention diagnostics |
| Instagram descriptions | No source caption segment mapped to description | Verbatim caption only for a defensible single-Event unit; ambiguous attribution stays diagnosed |
| Named branches and pinned venues/localities | Label-only or same-clause rules discarded source wording | Conservative natural/structural extraction; venue, area, city and street address remain distinct |
| Barista `Dd9K9nYxACp` | Split `۳` / `am` frame residual escaped the PR10 noise guard | One Event; requested title, `۹ و ۱۰ مهرماه`, branch venue and collapsed frame provenance retained |
| Pizza `DeoiH5qRkBU` | Caption plus two noisy titled frames produced three candidates | Exact repeated frame anchors collapse; an independent exact date and repeated multiword subtitle bridge uniquely joins the caption |
| `DecI6GCxI98` | OCR venue headed by `کارگاه` became a second Event | Explicit caption venue plus distinct title and no independent media occurrence collapses the venue fragment |
| Jabama public sessions | Adapter discarded all embedded script data | Bounded JSON-only parsing of the verified indexed public loader envelope; no JavaScript execution or API calls |
| Visible two-date schedule plus one native session | Naive union duplicated the overlapping date | Enrich only the compatible matching occurrence; keep the other date without borrowed price, ID or availability |

## C. Extraction and normalization

Source wording, digits and provenance remain intact. Supported temporal shapes
include Persian/ASCII digits, ordinals, month suffixes, explicit/inferred years,
single dates/clocks, dash/pipe separators, same-month day lists, clear date ranges,
explicit same-day sessions and supported weekly/daily recurrence wording.
Recurring rules do not instantiate future dates; ranges with daily hours do not
become a continuous multi-day timestamp. Missing clock never becomes midnight.

Source titles can use the existing Event vocabulary, exact quoted/credit
structure, a corroborated project heading, or a dated/ticketed performance
announcement. A bare group name, promotional sentence or first line alone is
insufficient. Unknown and ambiguous titles remain null with diagnostics.

Descriptions are original source text. Online booking never establishes online
attendance. Unspecified price stays null; publisher identity never becomes an
organizer without evidence.

## D. Evidence grouping and duplicates

The separate 11-item frozen Instagram regression sample includes the requested
older barista item and inspected target-run defects:

| Metric | Baseline | Fixed |
| --- | ---: | ---: |
| Candidates | 19 | 15 |
| Missing titles | 11 | 7 |
| Caption descriptions | 0 | 11 |
| Venue facts | 1 | 6 |

Barista 2→1, pizza 3→1, false venue Event 2→1. Real multi-event media, different
dates/titles and unsupported relationships remain separate. The pizza bridge
requires an exact source date, repeated multiword subtitle, one unique named
group and no contradictory date. It is not title similarity or shared URL matching.
Corrupted OCR remains provenance and a review diagnostic, not authoritative time.

## E. Event and occurrence model

`EventOccurrence` contains a deterministic identity, local date/time components,
aware timestamps where supported, timezone, precision, source schedule, native
session ID/origin/locator, raw/candidate/fragment/URL provenance and optional
session price/availability fields. Event identity remains separate and stable.

Explicit sessions retain their own numeric price keys and discount modifiers.
Unknown currency is not guessed. Conflicting base prices or unresolved discounts
do not produce a payable amount. Technical source keys are structured fields,
not fabricated source price wording in the primary workbook.

The actual saved Jabama page produces two occurrences: 23 September 2026 at 20:30
from visible wording, and 24 September at 20:30–22:30 with native session identity
and 45 remaining seats. The first date does not inherit the second session's ID,
end time or availability. These are **saved-page findings, not fresh availability**.

Conservative Stage 8 matching remains. Session keys include source origin; mutable
price/availability and later corroboration do not change occurrence identity.
Same-session temporal conflicts retain competing interpretations for review.

## F. SQLite and export compatibility

- SQLite DDL remains schema **1**. Existing versioned JSON payloads need no new
  relational tables or destructive recreation.
- Records/portable schema **3** adds typed occurrences, schedule kind/rule and
  derived readiness. Legacy records gain empty/unknown defaults **on read**.
  Historical payload bytes remain unchanged; sessions are never invented.
- XLSX remains schema **3**, accepting schema 2 through the existing upgrade path.
  New columns use header-based imports. Human decisions/notes remain separate.
- CSV, JSON and Gemini retain identical occurrence/readiness semantics. Gemini
  instructions prohibit recurrence expansion and source-fact invention.
- Event review remains keyed by stable Event ID. Removed false candidate identities
  stay in historical snapshots; no speculative review alias is introduced.

Acceptance used SQLite's backup API and a workbook copy. It preserved **70
historical fact snapshots, 3 historical workbook sheets and 57 review records**.
Integrity check returned `ok`; foreign-key check returned zero violations.
All 14 original raw/evidence file hashes remained unchanged.

## G. Excel review workspace

New snapshot columns: `آمادگی داده`, `دلیل بررسی`, `جلسه‌ها`, with hidden structured
occurrences, assessment keys and reasons. The owner filters the existing snapshot
instead of maintaining duplicate editable copies across additional tabs.

The four assessments are ready for review, needs enrichment, needs schedule review
and source unavailable. They do not overwrite decisions, lifecycle status,
availability or source health. Optional blanks are not automatically defects.
Known extraction loss, conflicting/noisy evidence and incomplete OCR remain visible.

Persian RTL, Vazir/Poppins, bounded widths/heights, wrapped descriptions, dropdowns,
source hyperlinks, frozen row 1, history and duplicate queue are preserved. The
acceptance XLSX reopened with openpyxl and its changed ranges were rendered and
visually inspected. Native Excel/Numbers rendering was not tested.

## H. Source field coverage

Same frozen owner-run input; denominator changes because three false/duplicate
candidates collapse, not because incomplete discoveries were discarded.

| Metric | Before | After |
| --- | ---: | ---: |
| Canonical Events | 35 | 32 |
| Displayed Events | 28 | 25 |
| Filtered Events | 7 | 7 |
| Undated displayed Events | 17 | 14 |
| Missing displayed titles | 8 | 6 |
| Displayed structured dates | 11 | 11 |
| Displayed clocks | 9 | 13 |
| Displayed venues | 11 | 13 |
| Displayed descriptions | 15 | 23 |
| Verified false/duplicate candidates in this run | 3 | 0 |
| Possible duplicate pairs | 1 | 0 |
| Ready for Review¹ | 0 | 0 |
| Needs Enrichment¹ | 10 | 8 |
| Needs Schedule Review¹ | 18 | 17 |
| Audited source-supported facts lost² | 25 | 0 |

¹ New readiness rules applied to both fact sets for comparison; not historical
readiness fields. All fixed displayed records still require review because of
inferred years, unresolved schedules, missing titles or incomplete media evidence.
Engineering readiness is not publication approval.

² Targeted audit of **34 explicit assertions**: 25 recoveries (3 titles,
6 venues, 12 descriptions, 4 clocks) and 9 golden-reference facts. Before:
21 extraction losses, 4 normalization losses, 9 matched. After: 34 matched.
Missing audited source-supported clocks: 4→0; venues: 6→0. The sole explicit
golden-reference date assertion was matched in both versions. There is **no
exhaustive count of source-supported dates among every undated discovery**; zero
observed defects in this assertion set must not be generalized to the corpus.

The golden `بازی D&D هالووین: ناقوس سیزدهم 🎃` retains 29 Mehr / 21 October 2026,
18:00, ایرانشهر - سمیه, four-hour duration, 500,000 toman, original description,
explicit organizer and source URL. Its inferred year still requires confirmation.

`review.coverage.audit_field` uses explicit source assertions and ordered retention
checks to identify the earliest verified loss. Unknown prior stages prevent a
false earliest-stage claim. Missing output alone cannot prove `SOURCE_MISSING`.
Reports group by publisher, source, channel, field, evidence type and readiness.
Statuses include MATCHED, SOURCE_MISSING, EXTRACTION_BUG, AMBIGUOUS,
ACCESS_RESTRICTED, INTENTIONALLY_UNSUPPORTED and CONFLICT.

## I. Testing and reproducibility

| Check | Result |
| --- | --- |
| Baseline suite | 1,154 passed |
| Final suite | **1,257 passed, 0 failed, 0 skipped** (33.184 seconds) |
| Added tests | 103 |
| `python -m compileall src` | Passed |
| `python -m pip check` | No broken requirements |
| `git diff --check` | Passed |
| Old payload migration / repeat reads | Idempotent; historical payloads unchanged |
| Review/import/locked workbook recovery | Existing and added regressions passed |
| SQLite integrity / foreign keys | `ok` / 0 violations |
| XLSX / CSV / JSON / Gemini comparison | 0 mismatches |
| Original raw/evidence hashes | 14/14 unchanged |

Commands were run through the repository-required RTK wrapper and local `.venv`.
No paid services, authenticated scraping, new dependencies, live collection or
restriction bypass was used. Offline test cases block external access.

Private reproducibility artifacts (intentionally Git-ignored) are under
`data/stage9-validation/data-quality-20261020/`: archived baseline code, frozen
JSONL, manifest, before/after snapshots, field audit JSON/CSV, acceptance summary,
read-only replay scripts and rendered previews. Final owner review copy:
`acceptance-03/GatherRadar.xlsx`; corresponding copied SQLite and portable/Gemini
exports are in the same acceptance directory. The owner workspace was not replaced.
Sanitized regression fixtures and tests are the committed-code-ready reproduction.

## J. Remaining limitations

**Source/access limits:** Davvvat Website remains disabled by policy. The target
run's Jabama media evidence was partial; offline replay does not repair missing
captures. Some roundup posts publish no defensible title or concrete date.

**Intentionally unresolved:** open-ended recurrence, multi-month prose outside
the supported grammar, uncertain dates/years, ambiguous captions and pricing
semantics remain reviewable. Source currency and session discount meaning are not
guessed. The parser supports the verified Jabama envelope, not arbitrary script
formats; schema drift is diagnosed.

**Validation limits:** no fresh collection in this pass; saved public HTML and
frozen runtime evidence were used. Older raw captures lack session metadata that
the old collector discarded; future permitted collection can populate it.
Evidence storage still lacks complete capture manifests/removed-slot tombstones.
The targeted fact audit is not an exhaustive semantic audit of all source text.

**Still-open verified critical defects in the fixed assertion set:** none.
Unknown facts and uninspected source interpretations remain unresolved rather than
being declared correct. Broader OCR semantics and taxonomy expansion remain future work.

## K. Repository safety

No commit, push, merge, force operation or original runtime-data replacement.
PR #10 remains open and untouched. All source/test/document changes are an
inspectable local diff on `feat/data-quality-occurrences`. No runtime/private
artifacts, cookies, tokens, browser profiles or databases are tracked.

## L. Final readiness

**GATHERRADAR DATA QUALITY HARDENING READY FOR OWNER REVIEW**
