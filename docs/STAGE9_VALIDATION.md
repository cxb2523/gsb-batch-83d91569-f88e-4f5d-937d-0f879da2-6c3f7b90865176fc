# Stage 9 — acceptance evidence

## Data-quality and occurrence hardening (2026-10-20)

The current implementation and actual frozen owner-run comparison are recorded in
[DATA_QUALITY_VALIDATION.md](DATA_QUALITY_VALIDATION.md). Baseline 1,154 tests;
final 1,257 passed, no failures/skips. The same 40 observations yield 32 canonical /
25 displayed Events after three false/duplicate candidates collapse. A targeted
34-assertion audit verifies 25 recovered facts and nine preserved golden-reference
facts; it is not an exhaustive claim about every blank field. Historical snapshots
and reviews survived isolated acceptance; original runtime data was not modified.
Sections below are historical validation evidence.

## Instagram evidence hardening (current)

Branch `fix/instagram-evidence-hardening`, base `67fb44f`. Baseline: 1,108 tests
(9 skipped) passed. Final: 1,154 passed (9 skipped); `compileall`, `pip check` and
`git diff --check` clean.

**Regression target.** The reviewed public Davvvat Reel `instagram:davvvat:Dd9K9nYxACp`
produced a caption Event `رویداد باریستا تویی` with no date or venue, plus a second Event
with the same title and `source_date_text` ≈ `3 am` from a noisy Reel frame. Raw captures
are not committed; `tests/fixtures/evidence_grouping/persian_reel_repeated_anchor.json` is
a sanitized synthetic model of that shape (caption + six noisy frames).

**Loss points.**

| Fact | Lost at | Cause | Fix |
| --- | --- | --- | --- |
| `۹ و ۱۰ مهرماه` | signals | attached `مهرماه` was not a date term, so no temporal fragment existed | month + `ماه` forms are date terms for all months |
| leading days | fields | Arabic comma and ordinal days were not leading days; a year after the month was dropped | grammar extended; ordinal guard for `هفته اول مهر` |
| `شعبه‌ی لواسان کافه رئیس` | fields | only labelled/corroborated venues were read | conservative natural-venue path |
| duplicate Event | grouping | a frame repeating the caption title was its own unit; whole-wording date comparison treated `3 am` as a conflict | repeated-anchor handling in `conservative/2` |

Normalization was not changed: it already accepted suffixed months, ordinals and ranges
when given the wording.

**Before/after (fixture, `extract instagram … --evidence --normalize` on a scratch data dir).**

| | Before (`conservative/1`) | After (`conservative/2`) |
| --- | --- | --- |
| DiscoveryUnits / Events / Other | 6 / 3 / 3 | 3 / 1 / 2 |
| title | `رویداد باریستا تویی` ×3 | `رویداد باریستا تویی` |
| `source_date_text` | null, `3 am`, `9/25` | `۹ و ۱۰ مهرماه` |
| normalized date | none | none — listed days stay unresolved (`multiple_dates`), per contract |
| venue / area | null / null | `شعبه‌ی لواسان کافه رئیس` / null |
| duplicate status | three same-title candidates | one candidate; Stage 8 yields 1 Event, 0 possible duplicates; 4 frames kept as collapsed provenance |

**Live validation.** Not performed in this pass: the execution environment had no
local `data/` (no raw/evidence history and no authenticated browser profile), so the
bounded `refresh --source davvvat_instagram --limit 5 --days 14` run and the real
`Dd9K9nYxACp` re-extraction remain for the owner. No runtime data was created or changed.

**Remaining limitations.** Two listed days (`۹ و ۱۰ مهرماه`) are kept as wording but not
normalized; recurring/multi-session schedules are not expanded; a media-only fragment
whose only occurrence evidence is a noisy clock can still be an Event; title repetition
needs an exact folded title (OCR-misspelled titles stay separate); branch localities are
not split into `area_text`; a lone unlabelled OCR clock next to a caption is no longer
attached as support text.

## Release gate (previous)

Validated on 2026-09-27 on branch `feat/google-sheets`, HEAD `258286d`, over the
uncommitted Stage 9 tree. Baseline: 1,066 tests passed. Final: 1,075 passed (9 new).

**Davvvat Website.** Fresh `GET https://davvvat.ir/robots.txt` (HTTP 200) still contains
`User-Agent: GatherRadar` / `Disallow: /`. `davvvat_website` is now `enabled: false` with
the reason in `config/sources.yaml`; definition and adapter are kept, Davvvat Instagram
stays enabled. Offline fixture tests read a test-only registry copy re-enabling it.

**Category.** Previous false positives: Vadoostan `3InmPrceCpQR` (chip `بازی`) and
`DEBdEiHxk0bK` (chip `ورزش`) showed `کارگاه` from prose `کلاس`. New precedence: an
adapter-verified `source_category_text` (Vadoostan card chip) outranks text inference;
`category` is its supported mapping or null. Fresh Vadoostan values: `ورزش` ×3, `بازی`,
`آشپزی` shown verbatim, canonical category null for all five.

**OTHER → EVENT.**

| Item | Occurrence evidence | Before | After | Reason |
| --- | --- | --- | --- | --- |
| Vadoostan `9wv6eGjHFU78` board game | Detail header slot `۷ مهر ساعت ۱۸:۰۰`, card price | Other (event 3.0 − retrospective `خاطره انگیز` 2.0) | Event | Structured occurrence rule |
| Jabama Exp. `legacy-941` mug making | None visible (sessions only in script payload) | Other | Other | No concrete occurrence; not forced |
| Jabama Exp. `73484635` pottery painting | None visible | Other | Other | No concrete occurrence; not forced |

Fresh bounded run (`data/stage9-validation/release-gate-20260927/`, 5 items per source,
Instagram caption-only): run status **success** (no longer partial).

| Source | Observed | Event | Place | Other |
| --- | --- | --- | --- | --- |
| `vadoostan_website` | 5 | 5 | 0 | 0 |
| `jabama_events_website` | 5 | 5 | 0 | 0 |
| `jabama_experiences_website` | 5 | 5 | 0 | 0 |
| `davvvat_instagram` | 5 | 5 | 0 | 0 |

16 displayed Events (9 undated), 4 filtered by horizon. Only `9wv6eGjHFU78` used the new
rule; no other item was promoted. Field audit: 142/142 source-supported facts preserved,
BUG = 0 (one audit-script judgement corrected: Jabama `13251717` names only the city under
`محل برگزاری`, so venue is source-missing). SQLite integrity `ok`, 0 FK violations; workbook
schema 3 reopens (freeze A2); JSON/CSV/Gemini/XLSX field comparison: no mismatches; main
`data/raw`/`data/evidence` hashes unchanged. Jabama sessions remain deferred.

## Source-completeness pass (superseded)

Validated on 2026-09-26 on the existing uncommitted Stage 9 branch. This pass closes the
source-supported recall gap the owner found by comparing the workbook with live pages.
Per-source detail and the per-cell audit are in [source field coverage](SOURCE_FIELD_COVERAGE.md).

### A. Starting state

- Branch `feat/google-sheets`; HEAD `258286d3f5501e54e673948cc3d097207304c88c` (Stage 8 / PR 7).
- Dirty Stage 9 tree inspected (23 modified tracked files, Stage 9 modules/tests/docs
  untracked, nothing staged). Persistence, exports, review and the Google adapter preserved.
- Baseline `.venv` run: **1017 tests passed** (17.4 s).

### B. Loss points found and fixed

| Loss | Where it was lost | Fix |
| --- | --- | --- |
| List-only price and sold-out badge | Listing used only for URL discovery | Per-item card (the anchor's own text) stored with the RawItem; `website_listing` fragment from the current run only |
| Area/neighborhood | No domain field; detail slot unlabelled | `area_text`; card `محله:` label and detail header slot (structural) |
| Description | Retained but no field; `summary` means a generated summary | `description_text` from the explicit description section |
| Duration | No field; `۲ ساعت` misread as a clock time | `duration_text`; a number before `ساعت` is a length, never a time |
| Organizer | Section excluded together with the biography | Organizer name + caption label retained (biography still excluded); `organizer_name` |
| Multi-session schedule | Only one temporal fragment survived | `source_schedule_text` with exact sentences; no occurrence expansion |
| Primary date overridden | Labelled recurrence (`زمان: سه‌شنبه صبح‌ها`) beat the header slot | Structural header date takes precedence |
| Prose price vs badge | A breakfast cost in the description was read as the price | Structural values outrank prose; structural disagreements still conflict |
| Glued card words | Utility-class flex gaps rendered without separators (`هیلان۲`) | Class-based flex gaps render a space |

The audit of the first fresh run (kept in `source-coverage-20260926/`) found the last
three defects; they were fixed and a new final run was taken.

### C. Contract changes

Six source-worded facts — `description_text`, `area_text`, `duration_text`,
`organizer_name`, `availability_text`, `source_schedule_text` — flow through extraction
facts, `EventCandidate`, normalization (copied unchanged), Stage 8 resolution with field
provenance, SQLite payloads, XLSX, CSV, JSON, Gemini and the shared Sheets row. Explicit
sold-out wording maps status to `sold_out`. Listing/detail disagreement leaves the field
null with `source_field_conflict`. Descriptions never conflict across sources and never
participate in matching. New matcher rule `same_source_page` groups the same detail page
listed by two sources of one publisher. See
[data contracts](DATA_CONTRACTS.md#source-supported-review-facts).

### D. Vadoostan findings

| Event | Source facts (live) | Previous output | New output |
| --- | --- | --- | --- |
| Harry Potter D&D (`3InmPrceCpQR`) | `۵ مهر ساعت ۱۷:۰۰`; card `محله: ایرانشهر - سمیه`, `۵۰۰٬۰۰۰ تومان`; detail `۳ ساعت`, `توضیحات`, organizer | title, date, time only | + area, price 500000 TOMAN, duration, 1,213-character description, organizer |
| Music group (`sRpNLcEpMk8J`) | `۵ مهر ساعت ۱۹:۰۰`; card area and `تکمیل ظرفیت`; `۲ ساعت`; description with `در چهار جلسه یکشنبه‌ها … 5،12،19 و 26 مهر`; organizer | title, date, time only | + area, availability `تکمیل ظرفیت` and status `sold_out`, duration, schedule sentence, 1,947-character description, organizer; price correctly empty |

Loss points: price, availability and the labelled area were listing-only (not collected);
area and duration were unlabelled header slots; the description had no field; the
organizer was cut off at the FAQ; the schedule sentence had no field.

### E. Jabama Experiences

Supported. Listing `https://jabama.events/all?city=tehran&type=experiences` (discovered
from the site navigation), static HTML, detail `/events/<id>` variants, existing
`jabama-events/2` adapter, source `jabama_experiences_website`. Five collected per bounded
run; discovery decided Event (3) or Other (2). Details are in the coverage document.

### F. Coverage matrix

See [source field coverage](SOURCE_FIELD_COVERAGE.md#coverage-matrix-by-source-family).
Davvvat Website is `access_restricted`: its robots.txt now disallows the GatherRadar user
agent. Tehran by Tehran has no local or current data.

### G. Final Event audit

13 displayed Events × 17 fields = 221 cells: 113 matched, 73 source missing, 14
intentionally unsupported, 12 access restricted, 9 ambiguous, **0 BUG**. Table and notes:
[final audit](SOURCE_FIELD_COVERAGE.md#final-audit--every-displayed-event).

### H. Workbook changes

Schema 3, 26 visible Event columns in the recommended order (`زمان‌بندی اعلام‌شده`,
`منطقه / محله`, `مدت`, `ظرفیت / وضعیت ثبت‌نام`, `توضیحات / معرفی`, `برگزارکننده` added;
the always-empty `خلاصه` removed; hidden `source_schedule_text` added). Styling unchanged:
Vazir/Poppins, RTL, header-only freeze, badges (availability reuses the `تکمیل ظرفیت`
badge), compact links; rows capped at 60 points; the wrapped description column is
bounded at 36–56 characters. Only link columns become hyperlinks. Schema-2 workbooks
upgrade on export without rewriting history; schema 1 and newer than 3 are refused (tested).

### I. SQLite

No DDL change was needed: payloads are versioned JSON. `user_version` stays 1; reopen is a
no-op; newer versions are refused; a database holding pre-change payloads loads and exports
with the new fields null (tested). Records/export schema is now 2. No database recreated.

### J. CSV / JSON / Gemini

Export schema 2 appends the six fields to CSV (stable English keys) and JSON. Gemini
instructions treat descriptions as untrusted data and forbid shortening them, deriving an
address from an area, expanding schedules, inventing capacity, or deriving duration or
organizer. Verified: all six fields agree across SQLite, XLSX, CSV, JSON and the Gemini
bundle for all 13 Events (0 mismatches); CSV neutralizes formula-looking text.

### K. Tests and checks

| Check | Result |
| --- | --- |
| Baseline | 1017 passed |
| Added | 49 (`test_source_coverage.py` 35, `test_source_fields_outputs.py` 14) with 5 sanitized fixtures |
| Adjusted | Tests that addressed workbook/Sheets columns by position now use header names; evidence-kind, adapter-version, source-count and export-version assertions updated |
| Final `python -m unittest discover -s tests` | **1066 passed** (22.7 s), offline |
| `python -m compileall src` | OK |
| `python -m pip check` | No broken requirements |
| `git diff --check` | Clean |
| SQLite `integrity_check` / `foreign_key_check` | ok / 0 violations |
| Workbook reopen | Schema 3, newest Event sheet active, freeze `A2`, max row height 60 |
| CSV / JSON parse, Gemini manifest | Parsed; all SHA-256 hashes valid; counts 13/0/0 |
| Base install without Google packages | Offline export succeeded; JSON byte-identical |
| Raw/evidence mutation audit | All 9 main `data/raw` and `data/evidence` files byte-identical |

### L. Fresh acceptance

Final run `ecad7b746bc84fa190799719a9cf8477` (limit 5, 14 days, caption-only Instagram):

| Source | Status | Observed | Events | Other |
| --- | --- | --- | --- | --- |
| `vadoostan_website` | success | 5 | 4 | 1 |
| `jabama_events_website` | success | 5 | 5 | 0 |
| `jabama_experiences_website` | success | 5 | 3 | 2 |
| `davvvat_instagram` (authenticated) | success | 5 | 5 | 0 |
| `davvvat_website` | failed (`robots`) | 0 | — | — |

17 canonical Events; 13 displayed (8 undated) and 4 filtered by the horizon. The run
status is `partial` only because of the Davvvat robots refusal. Source-supported →
preserved: **113 / 113** audited facts. Completeness is in the coverage document.

Artifacts (runtime data, ignored by Git) under
`data/stage9-validation/source-coverage-final-20260926/`:

- XLSX: `review/GatherRadar.xlsx`
- SQLite: `state/gatherradar.sqlite3`
- CSV/JSON: `exports/latest/{events,places,possible_duplicates}.csv`, `exports/latest/review.json`
- Gemini bundle: `exports/gemini/latest/`
- Audit: `field-audit.json`, `field-audit.csv`, `audit-dump.json`, `verification.json`

### M. Repository safety

No runtime or private data in tracked or unignored files; fixtures use fictional names
and example domains; no credential patterns found. No commit, push, merge, reset or stash.

### N. Readiness

**STAGE 9 READY FOR OWNER REVIEW**

Residual, explicitly classified items for the owner: the provisional category taxonomy
(two Vadoostan items show an inferred `کارگاه`), Jabama booking sessions available only
in embedded script data, three captured items classified Other by discovery, and the
Davvvat Website robots opt-out.

## Earlier pass: source accuracy (superseded)

Validated on 2026-09-26. This supersedes the earlier six-row acceptance report.
The owner has accepted the Stage 9 architecture and XLSX UX. This pass changes
source-neutral extraction and deterministic normalization, with no workbook redesign.

### A. Starting state

- Branch: `feat/google-sheets`.
- HEAD: `258286d3f5501e54e673948cc3d097207304c88c` (Stage 8 / PR 7).
- Existing uncommitted Stage 9 work: 22 tracked modifications and 42 untracked files.
  No staged changes. Existing persistence, exports, review round-trip and Google code preserved.
- Baseline rerun: **987 tests passed** in `.venv` (43.598 seconds).
- Instructions, product brief, status and relevant/full Stage 9 diff inspected. RTK
  was unavailable on PATH and in its usual local locations; underlying commands ran directly.
- No commit, push, merge, reset, stash or milestone transition.

### B. Confirmed defects and trace

| Event/source | Supported evidence | Failing stage | Root cause |
| --- | --- | --- | --- |
| اکران و نقد فیلم‌تئاتر احتمالات / Davvvat Website | Separate `حیات راوی`; occurrence prose `برنامه اتودخانه در حیات راوی،`; labelled full address containing the name | DiscoveryFacts → EventCandidate | Venue extraction accepted labelled venues only. The separate name was under an organizer section, so that card alone was insufficient; corroborating event-location prose was unused. |
| ایونت آرت سنتر / Davvvat Instagram | `یکم تا سوم مهرماه از ساعت ۱۰ تا ۲۲` | Stage 7 temporal normalization | Day grammar accepted numeric days only and did not accept an attached `ماه` suffix. Existing time/composition logic could not recover from the unparsed date prefix. |
| Same film-theater Event / Davvvat Website | `خرید بلیط آنلاین` | Discovery format extraction | Any online token anywhere set `online`, confusing ticket purchase with attendance. |

Film-theater trace: the Website RawItem already retained all three supporting text
roles. Its `WEBSITE_TEXT` fragment and DiscoveryUnit preserve that text exactly.
The old DiscoveryFacts venue was null, then EventCandidate, normalization, canonical
Event, SQLite and XLSX faithfully carried the null. The fix belongs in shared semantic
field extraction. The fresh trace asserts the venue/address/city at Facts, candidate,
normalized candidate, canonical Event and SQLite, with candidate-linked field provenance.
XLSX now displays the same venue and full separate address. No serializer patch was used.

All adapters retain scoped detail text; verified headings are the existing narrow
structured semantic input. Metadata-only content links and JSON-LD remain outside the
discovery contract. The live Davvvat page labels the name as organizer, while its prose
establishes the event location. Its JSON-LD location name is a neighborhood, not the
venue; attendance mode says Offline, but is not an admitted extraction input. JSON-LD
also has an end before its start. No general metadata bypass or fabricated sentence was
introduced. Existing retained text is sufficient for the venue fix. Labelled Jabama
venues continue to pass the shared extraction path.

### C. Venue/address fix

An explicit venue label still wins, except an ambiguous location label containing
street/directional details remains an address. The conservative fallback requires all
three: a separately written short complete name, explicit event-at-that-name wording,
and a labelled street address containing the same complete name. It rejects historical
occurrence wording and conflicting names. Organizer identity, ambiguous prose or an
address's final comma-separated token alone cannot establish a venue.

The full address remains unchanged, including its repeated venue suffix; trimming it
would discard source wording without improving the separate venue field. City extraction
is unchanged. The rule has no source ID, URL, publisher name or website selector.
A sanitized generic-adapter fixture exercises the complete path to SQLite and XLSX.

### D. Temporal fix

- Reusable Persian ordinal map covers days 1–31, including `اول`/`یکم`, compound
  ordinals, and safe space/ZWNJ/harakat variants. Invalid month days use existing
  calendar validation, including Esfand leap-year cases.
- Month tokens accept `مهر`, `مهرماه`, `مهر ماه` and equivalent forms for all months.
- Numeric/textual clear ranges use the same grammar. Discrete `۱ و ۲ مهر` and textual
  lists remain unresolved rather than becoming continuous ranges.
- Existing clock parsing validates `از ساعت ۱۰ تا ۲۲`, `از ساعت ۱۰:۳۰ تا ۲۲`, and
  minute-bearing endpoints. No new time heuristic was needed.
- Existing reference policy remains publication time, else capture time, in the
  configured IANA timezone. Year inference still requires one adjacent-year candidate
  within ±45 days; yearless ranges must fit one Jalali year and span ≤90 days.
  No wall clock, second year heuristic or aggressive Nowruz rollover was added.
- The exact Art Center wording is retained. Its dates are **1405-07-01 through
  1405-07-03 / 2026-09-23 through 2026-09-25**, hours **10:00–22:00**, precision `range`.
  `starts_at` and `ends_at` are null; `inferred_year` and `multi_day_hours` retain the
  uncertainty and daily-hours semantics. Its stored publication time supplies the reference.
- On the September 26 review date it is expired, filtered from current exports and
  retained in the immutable SQLite snapshot. Recurring `شنبه ها، ساعت 21` and
  `دوشنبه تا جمعه هر هفته` still receive no invented exact date.

### E. Event-format audit

The film-theater `online` value was a defect: the token described buying tickets.
Format now requires direct attendance/holding wording or a standalone format statement.
Historical/negated wording, registration/payment method, descriptive virtual-space prose
and physical addresses cannot establish attendance mode. Both explicitly supported
attendance modes, including a joint attendance phrase, yield `hybrid`.

The corrected film-theater format is **null**, not an inferred `in_person`. Its physical
address does not prove attendance mode; metadata-only Offline remains outside the
current contract. Tests distinguish these cases. The other five audited rows have no
admitted direct attendance-format wording and remain null.

### F. Six-row source-recall audit

“Absent” below means absent from the retained public evidence, not a claim about facts
hidden behind booking interactions. All six titles and selected source-date strings are
preserved exactly. Yearless resolved dates remain diagnostic/inferred. Unstated end dates
and end times remain null. Registration URLs are never replaced with a page URL.

| Event/source | Field and source support | Extracted / final review | Missing-field decision |
| --- | --- | --- | --- |
| بازی D&D هری‌ پاتر: بازگشت به هاگوارتز / Vadoostan | Title; `۵ مهر ساعت ۱۷:۰۰`; neighborhood `ایرانشهر - سمیه`; 3-hour duration | Title/date wording retained; Sep 27, 17:00 displayed; venue/city/address/price/registration/format null | Explicit venue, city, street address, price, booking URL and attendance mode absent. Neighborhood does not imply city/address; duration-to-end-time inference unsupported. |
| گروه کشف و موسیقی: «موسیقی راک: تنهایی، خشم و آزادی» (۴ جلسه) / Vadoostan | Title; selected schedule `۵ مهر ساعت ۱۹:۰۰`; prose also lists 5/12/19/26 Mehr | Selected advertised start Sep 27, 19:00 displayed; all location/price/registration/format fields null | Exact location, city, price, booking URL and direct format absent. Additional discrete sessions are present but unsupported by the single-occurrence contract; the first advertised schedule is not an expansion of all four sessions. No range or additional dates invented. |
| اکران و نقد فیلم‌تئاتر احتمالات / Davvvat Website | Title; `دوشنبه ۶ مهر` + `۱۹:۰۰`; explicit Tehran/full address and corroborated venue | Sep 28, 19:00; `حیات راوی`, Tehran and full separate address displayed; format now null | Venue extraction bug fixed. Price absent. Ticket anchor destination exists only in metadata (organizer Instagram), so registration remains unsupported by text-only URL evidence. Offline JSON-LD format remains outside contract; online ticket wording is not online attendance. |
| پرفورمنس از چهارباغ تا شانزه‌لیزه / Jabama | Title; `پنجشنبه ۹ مهر`; `خانه فرهنگ و هنر دوبارِ`; Tehran; `از ۹۵۰٬۰۰۰ تومان` | Oct 1; venue/city/price wording displayed; time/address/registration/format null | Exact clock, street address, explicit booking URL and direct attendance mode absent. Price is a lower bound, not a single amount; numeric amount intentionally null with ambiguity diagnostic. |
| ایونت آرت سنتر / Davvvat Instagram | Title; exact ordinal date/time range; `مکان: روبروی پارک ملت، بازارچه‌ی صفویه` | Sep 23–25, 10:00–22:00 now stored; directional address retained; filtered as expired | Temporal normalization bug fixed. Separately identified venue, explicit city, price, registration and direct format absent. Do not infer Tehran or a venue from the directional address. |
| نمایش/موسیقی «بودن پس از حذف» / Jabama | Title; `شنبه ها، ساعت 21`; `عمارت روبرو تجریش`; Tehran; `از ۱٬۱۰۰٬۰۰۰ تومان` | Venue/city/price wording displayed; recurring source wording retained; undated row remains last | Recurrence/occurrence clock semantics unsupported; no arbitrary date/time interval. Street address and booking URL absent (a map link is not a street address). Direct format absent; numeric lower-bound price intentionally unresolved. |

No additional source-supported extraction/normalization defect was confirmed in these
fields. Metadata-only integration, recurrence expansion and lower-bound money are
explicit capability boundaries, not fabricated completed facts.

### G. Tests and engineering checks

- Baseline: **987 passed**. Added **30 tests** in `test_stage9_accuracy.py`, including
  parameterized ordinal/month/calendar cases, time/range composition, recurring safety,
  venue/format negatives, generic fixture → persistence/XLSX, and expired-range history.
- Final `.venv`: **1,017 passed**, no skips (40.441 seconds).
- Previously provisioned clean base environment without Google packages: **1,017
  discovered; 1,008 passed, 9 optional Google skips**. Google package absence and local
  exporter imports checked. No dependency or packaging changes in this accuracy pass.
- `python -m compileall src`, `python -m pip check` in both environments,
  `git diff --check`, repository status/diff and documentation link review pass.
- Optional Google behavior stays covered by the full `.venv` suite. No Google network
  publication or credentials operation was performed.

### H. Fresh acceptance run

Run `e0a43e8ac15b44288f83de3e73725fe7`, September 26, **11:30:20–11:30:54 UTC**
(**15:00 Tehran**), 14-day review horizon, fresh empty isolated output root.

| Source | Fresh observations | Canonical Events | Displayed | Filtered |
| --- | ---: | ---: | ---: | ---: |
| Davvvat Website | 2 | 2 | 1 | 1 |
| Vadoostan Website | 2 | 2 | 2 | 0 |
| Jabama Events Website | 2 | 2 | 2 | 0 |
| Davvvat Instagram | 1 | 1 | 0 | 1 |
| Total | **7** | **7** | **5** | **2** |

All four sources succeeded; no collection/export failures, Places or duplicate pairs.
The two expired items are Davvvat اشاره‌بازی and Instagram Art Center. One displayed
Event remains undated (Jabama recurring schedule).

Website validation retained the six previously discovered detail URLs, fetching them
live through the normal robots-aware, bounded transport/adapters. A validation-only
injected discovery list fixes sample membership so the exact reported defect is included;
this does not assert those details are the first six links in today's listings. Listings
and robots were still fetched. Bounds stayed two details per website. Instagram used
the existing authenticated browser profile, one caption/post and one scroll attempt;
Art Center was available again. Media/OCR was explicitly disabled. No raw record or old
workbook was copied into the new run.

Completeness among the five displayed Events: title/date wording/source URL **5/5**,
start date **4/5**, start time **3/5**, venue **3/5**, city **3/5**, street address **1/5**,
price wording **2/5**, registration **0/5**. Among all seven historical Events: start
date **6/7**, start time **5/7**, bounded end date **1/7**, end time **2/7**. Blanks follow
the evidence decisions above.

Local output root: `data/stage9-validation/accuracy-20260926/`

- SQLite: `state/gatherradar.sqlite3`
- Fresh XLSX: `review/GatherRadar.xlsx`
- CSV: `exports/latest/events.csv`, `places.csv`, `possible_duplicates.csv`
- JSON: `exports/latest/review.json`
- Gemini: `exports/gemini/latest/` (six files, including instructions and hash manifest)
- Matching immutable run exports under `exports/runs/<run_id>/` and
  `exports/gemini/runs/<run_id>/`.
- Local evidence: `acceptance.json`, `validation.json`, `traces.json`, `field-audit.json`.

### I. Before/after

| Field | Previous six-row snapshot | New snapshot/history |
| --- | --- | --- |
| Film-theater venue | null | `حیات راوی` |
| Film-theater address/city | Full address / Tehran | Same full address / Tehran, independently retained |
| Film-theater date/time | 6 Mehr 1405, 19:00 | Unchanged |
| Film-theater format | `online` from ticket text | null; direct attendance format not admitted |
| Art Center source wording | Exact range present | Exact range unchanged |
| Art Center normalized date/time | All four components null | Sep 23–25; daily 10:00–22:00 |
| Art Center interval | null; unknown precision | Null timestamps; range precision; honest daily-hours diagnostic |
| Art Center review visibility | Retained as undated | Filtered as expired; complete historical SQLite facts |
| Displayed / filtered / undated | 6 / 1 / 2 | 5 / 2 / 1 |

### J. Offline consistency and accepted UX

A SQLite-only re-export ran with network connections, browser/process launch,
collection/canonical acquisition and JSONL append operations blocked. All **21 output
paths** were regenerated successfully. SQLite `integrity_check` returned `ok`, foreign-key
check was empty. XLSX reopened; displayed IDs/order, title, dates, clocks, source wording,
venue, city, address, format and source links agreed with SQLite. JSON matched the whole
review document. CSV IDs/counts and material fields matched. Gemini file hashes and
review JSON matched the portable exports. Filtered facts remain in SQLite by design,
not in upcoming-review CSV/JSON/Gemini files. Workbook review import had 0 changes,
5 unchanged rows, 0 malformed/conflicting rows; owner decisions/notes remain untouched.

Accepted schema-2 UX is unchanged: latest Events active, Persian tabs, RTL, Vazir/Poppins,
header hierarchy, sizing, badges/dropdowns, compact hyperlinks, hidden technical fields,
header-only `A2` freeze. Programmatic checks confirmed this in the new workbook.
No design/source stylesheet/exporter was modified by this pass. Owner visual acceptance
was already provided; the new artifact is for source-accuracy review.

SHA-256 checks confirm all **13 original raw/evidence files** unchanged. The four fresh
raw files were created only by the explicit live run and stayed byte-identical through
tracing and offline export. No media/evidence acquisition was performed.

### K. Repository safety

Working tree remains uncommitted on the same branch/HEAD, with the original Stage 9
changes intact. Current tree: **23 modified tracked files and 45 untracked files**;
none staged. The accuracy pass adds the ordinal module, sanitized fixture and tests,
and updates only extraction/normalization plus relevant docs. Runtime SQLite, XLSX,
CSV/JSON, browser profile, collected text and validation scripts remain ignored under
`data/`. Repository audit found no runtime/private artifacts or credential patterns
among changed/new deliverables, and no broken documentation links/trailing whitespace.
No commit, push, merge, reset or Stage 10 work occurred.

### L. Readiness

**STAGE 9 READY FOR OWNER REVIEW**

The reported venue, temporal and format defects are corrected and verified on fresh
source observations. Remaining unknowns and unsupported recurrence/metadata semantics
are explicit in the six-row audit; they are not filled with inferred facts.
