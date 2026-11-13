# Source-grounded Event recall validation — 2026-10-23

Implementation and frozen replay are complete; full recall acceptance is **not**.
Two inspected media images still contain activity facts lost by stored OCR. They
have not been repaired with invented text or source-specific title overrides.

## Evidence and baseline

Starting branch: `feat/data-quality-occurrences`, with the owner's existing
uncommitted work. Baseline: **1,301 tests passed** before edits. The matching local
run was inspected; no claim is made to have opened the separately named attachment
`GatherRadar(5).xlsx`.

Frozen owner run: `d2f2fa5457574c61b7aa772cc712af30`.
Reference: **2026-10-23T00:39:15.332636+03:30**, Asia/Tehran; horizon 14 days.
The 45 selected RawItems reproduce the original 41 discoveries, 16 title exclusions
and 25 admitted Events exactly. Evidence JSONL has no acquisition timestamp, so
its immutable selected fragments reproduce the baseline but cannot prove the
original acquisition time of every historical OCR variant. No new crawl was used.

The private, ignored `data/recall-validation/SOURCE_AUDIT.md` and
`raw-item-audit.json` cover all 45 items: publisher, URL, publication basis, content
type, captions/website headings, capture limitations, OCR fragments, activity
assessment, candidates, title provenance, date expressions, Occurrences and
dispositions. Original evidence remains unchanged.

## Confirmed causes and changes

- The old title gate diagnosed missing titles after a narrow explicit-name parser;
  it could not recover a named activity across line breaks or a factual description.
  Detection now precedes deterministic title resolution. Explicit source titles,
  display titles, source spans, fragment IDs and review warnings remain distinct.
- Generic series invitations and collection covers produced pseudo-Events; noisy
  Reel variants duplicated one pizza workshop and one historical festival. Bounded
  caption segmentation, contextual detection and corroborated same-activity grouping
  remove those records without merging independent sessions.
- Mana's title stopped at a generic exhibition label; daily closure wording blocked
  its explicit range. The name and range now survive, with an hours warning.
- Barayand's separate date/clock clauses lost the later session. They now produce
  distinct Occurrences, keeping the 1 Aban session at the stored run time.
- The Gregorian festival range was reduced to a month word. Explicit-year English
  ranges now normalize, retain adjacent clocks and diagnose competing calendars.
- Relative announcements lost their publication context. Finite weekday/today-tomorrow
  schedules now require original publication time; no crawl-time or next-week rollover.
- A four-session website description retained only its first date. An explicit finite
  list now preserves all four dates, with a clock only on the supported first session.
- Verified dated sessions were treated as conflicting with even a matching weekly
  rule. Existing sessions can now corroborate that rule; no instances are generated.
  Actual weekday/date disagreements remain in schedule review.

All changes use the existing extraction, normalization, canonicalization and export
boundaries. No paid/remote AI dependency was added. The latest-five Instagram policy,
Carousel capture code, Evenza source and Davvvat Website policy were preserved.

## Audit of the original 16 exclusions

| Source | Original exclusions | Evidence classification |
| --- | ---: | --- |
| Emrooz Instagram | 7 | 5 collection/series segmentation cases; 1 descriptive title; 1 title present in OCR |
| Evenza Instagram | 5 | 1 collection cover; 1 explicit title; 2 repeated historical-recap frames; 1 incomplete OCR case |
| Jabama Instagram | 3 | 1 collection cover; 2 descriptive titles |
| Tehran by Tehran | 1 | 1 explicit name across a line break |

Classification totals: `MULTI_EVENT_SEGMENTATION_FAILURE=7`,
`EXPLICIT_TITLE_MISSED=2`, `DESCRIPTIVE_TITLE_AVAILABLE=3`,
`TITLE_IN_OCR_MISSED=1`, `PAST_EVENT_RECAP=2`,
`MEDIA_EVIDENCE_INCOMPLETE=1`; `NON_EVENT_CONTENT`, `INSUFFICIENT_EVIDENCE`
and `OTHER` each zero within these 16. The seven segmentation cases comprise
three covers that are not individual Events and four ambiguous series invitations;
they do not establish seven new activities.

Six original title exclusions recover defensible titles: one ongoing Event, four
expired Events and one genuine undated activity. Seven umbrella records and two
duplicate historical frames are not restored as individual Events. One original
title failure remains. Ordinary cafe/venue promotions and retrospective-only
announcements elsewhere in the 45-item audit remain outside canonical Events.

## Same-input quantitative comparison

| Metric | Before | After |
| --- | ---: | ---: |
| Raw source observations | 45 | 45 |
| Extracted EventCandidates, before cross-source merging | 43 | 32 |
| Canonicalized discoveries, before admission | 41 | 30 |
| Confirmed non-Event candidate records: collection covers | 3 | 0 |
| Source-attributed explicitly titled Events | 25 | 26 |
| Source-backed descriptive title recoveries | 0 | 3 |
| Title-resolution/admission failures | 16 | 1 |
| Verified redundant pizza/festival candidates | 4 | 0 |
| Eligible canonical Events | 25 | 29 |
| Actionable Events | 12 | 18 |
| Ongoing Event ranges retained | 2 | 4 |
| Future/today Occurrences in actionable output | 26 | 33 |
| All current supported Occurrences, including ongoing ranges | 28 | 37 |
| Correctly expired Events | 1 | 7 |
| Needs schedule review | 12 | 4 |
| Beyond horizon / otherwise excluded | 0 / 0 | 0 / 0 |
| Verified information-loss cases in the bounded audit checklist | 16 | 2 |

The information-loss checklist covers Mana, Barayand, Oktober, pizza, two relative
announcements, Rollen, the band performance, the quoted autumn title, the specific
film discussion, game/discussion, the dated psychological-discussion slide, the
four-date workshop, matching weekly sessions, and the two remaining OCR cases.
Other ambiguous media activities remain **unverified**, not counted as successes.
Baseline explicit-title origin fields did not exist; its 25 count means titled
source-attributed Events under the old policy, including the generic Mana title.

The four removed redundant candidates are two pizza OCR variants and two festival
frames, not all possible duplicates in the corpus. Two possible duplicate pairs
remain reviewable, including the autumn arts-event descriptions with differing
title/address wording. They are not silently merged or claimed to be distinct.

The final partition reconciles: **29 = 18 actionable + 7 expired + 0 beyond horizon
+ 4 schedule review + 0 otherwise excluded**. All 29 admitted Event IDs retain
their original identity anchors. The source funnel explicitly distinguishes
RawItems, fragments, candidates, canonical Events and Occurrences; shared-source
counts must not be summed as unique global Events.

Newly actionable source records:

- [Mana](https://www.instagram.com/p/Detok4qqQVa/): named ongoing range.
- [Barayand](https://www.instagram.com/p/DeykDRGRMfj/): retained future session.
- [Sale gathering](https://www.instagram.com/p/DezcgXAxAAC/): finite publication-relative dates.
- [Autumn arts announcement](https://www.instagram.com/p/DexCzYgxZ9H/): finite publication-relative dates.
- [Quoted autumn arts name](https://www.instagram.com/p/Dew4h70NcxN/): explicit title and ongoing range; possible duplicate of the preceding record.
- [Puppet-show sessions](https://jabama.events/events/58845694): verified sessions match the weekly rule.

## Remaining defects and review cases

- [Evenza weekly Carousel](https://www.instagram.com/p/DewenndDR2X/), slide index 4:
  the inspected image names a perfume workshop and 1 Aban 16:30; stored OCR loses
  key words. An alternate Tesseract pass improved the activity text but still did
  not reliably recover the date. It was not substituted into historical evidence.
- [Jabama weekly Carousel](https://www.instagram.com/p/DewdAUCCnsq/), slide index 1:
  the inspected image names an experience and date; OCR corruption still prevents
  reliable automatic extraction. OCR execution success does not resolve this defect.
- Vadoostan's multi-activity promotions contain names but incomplete attributable
  schedules in sampled evidence. Recall remains unverified for
  [this collection](https://www.instagram.com/p/DeuIWbHDn91/) and
  [these groups](https://www.instagram.com/p/DeJ8d71jhiq/).
- Four admitted Events appropriately remain in schedule review:
  [conflicting stand-up dates](https://jabama.events/events/69866216),
  [weekday/session disagreement](https://jabama.events/events/69063962),
  [unbounded nightly performance](https://www.instagram.com/p/DepUZ7ERNwj/), and
  [undated film discussion](https://www.instagram.com/p/DdrlYE2PEMe/).
- Reel sampling and full Carousel extent cannot establish complete semantic coverage.
  The frozen Tehran collection report contains a capture failure flag. No new live
  accessibility or capture success is claimed in this offline workstream.

## Verification and safety

Final suite: **1,328 tests passed** in the existing virtual environment.
Compile, dependency and diff checks passed. Tests cover title provenance/forgery,
caption/OCR recovery, segmentation, duplicates, bilingual and relative schedules,
finite lists, recurrence corroboration, persistence and cross-format projections,
alongside the existing Carousel/source/title/Occurrence regressions.

The regenerated `data/recall-validation/GatherRadar-Recall.xlsx` opens on the final
replay, with 18 actionable rows and four separate schedule-review rows. SQLite,
XLSX, CSV, JSON and Gemini agree on IDs, titles, Occurrences and review fields.
Repeated export is idempotent; Gemini manifest hashes match. RTL, freeze panes,
filters, hidden provenance and absence of formula/error cells were checked.
A native visual render was unavailable: neither LibreOffice nor the spreadsheet
artifact runtime is installed. No native Excel visual inspection is claimed.

Validation wrote only to an ignored copy. All **117 original Event snapshots,
74 review records, five historical runs and six historical workbook sheets** were
preserved. Original raw/evidence/manifests, database contents and workbook hashes
remain unchanged. Both databases pass SQLite integrity and foreign-key checks.
No reset, stash, discard, commit, push or merge was performed.

**NOT READY — VERIFIED EVENT RECALL DEFECTS REMAIN**
