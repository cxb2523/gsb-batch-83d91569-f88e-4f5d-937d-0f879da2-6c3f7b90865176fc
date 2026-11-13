# Source field coverage

The historical Stage 9 source-completeness pass below is dated 2026-09-26. It records which review facts
each approved source family publicly exposes, where GatherRadar reads them, and a
field-by-field audit of every Event in that run's acceptance workbook. Its counts are
not a current claim of zero extraction defects. The current hardening addendum follows;
historical observations and metrics are retained for comparison.

## 2026-10-20 hardening: public session evidence

The Jabama audit used the already saved public HTML
`data/website-inspection/jabama-event-detail.html` read-only. No new HTTP request,
authenticated browser session, checkout or private API was used. This file contains
one supported `/events/` route with one explicit session, repeated as `firstSession`.
The current parser recovers **one session**, with no parser diagnostics, from that
same stored page. Its source ISO start is `2026-09-24T17:00:00.000Z`, duration is
2 hours, remaining seats 45 and enabled flag true; session price keys are null.
These observations do not establish current availability.
The same saved page's visible wording names two days (`۱ و ۲ مهر ماه ساعت ۲۰:۳۰`).
Offline pipeline replay preserves two occurrences: the first has only its visible
date/clock, and the overlapping second combines that wording with the native
session's duration/seat evidence. It does not create a third duplicate occurrence or
lend the second session's price/availability to the first. The first date's inferred
year remains flagged; the visible starting-price interpretation remains unresolved.

Earliest loss point: `jabama-events/2` excluded scripts and retained only a boolean
structured-data marker. Consequently the collector discarded supported session
facts before discovery or normalization could see them. `jabama-events/3` retains
whitelisted `SourceSession` evidence and diagnoses absent, malformed, conflicting
or unsupported session data. Existing JSONL observations that discarded scripts
cannot recover them through stored-only reanalysis; their unknowns stay unknown.

| Sampled fact | Before | After | Evidence / restriction |
| --- | --- | --- | --- |
| One bookable session and identity | `INTENTIONALLY_UNSUPPORTED` under the old contract | `MATCHED` | Own route's `sessions`; repeated `firstSession` is ignored |
| Session date and clock | `INTENTIONALLY_UNSUPPORTED` | `MATCHED` | Original aware `startIso`; converted to configured source timezone |
| Session duration and end instant | `INTENTIONALLY_UNSUPPORTED` | `MATCHED` | Explicit `durationHours`; elapsed-time derivation is traceable |
| Session remaining seats / enabled | `INTENTIONALLY_UNSUPPORTED` | `MATCHED` | Session's own numeric/boolean values; not Event status |
| Session price | `SOURCE_MISSING` | `SOURCE_MISSING` | Both session price keys null; event starting price is never borrowed |
| Session currency | `AMBIGUOUS` | `AMBIGUOUS` | No session currency field; page JSON-LD and visible price units are not safely interchangeable |
| Nonempty timeslots / different stream shapes | `INTENTIONALLY_UNSUPPORTED` | `INTENTIONALLY_UNSUPPORTED` | Unsupported shapes emit schema diagnostics rather than fabricated dates |

The sanitized fixture is
[`jabama-sessions-detail.html`](../tests/fixtures/websites/jabama-sessions-detail.html);
[its note](../tests/fixtures/websites/jabama-sessions-README.txt) separates verified
source structure from synthetic regression variations. Tests additionally cover
multiple sessions, separate prices/availability, discounts, cross-event IDs, repeated
and conflicting session identities, malformed clocks, unsafe script arguments and
schema drift. They do not claim broader live source coverage.

Session-only details with a retained heading now become Events even when visible
prose is classified as Place/Other. Offline integration tests verify the same session
facts through discovery, normalization, canonicalization, SQLite, CSV, JSON, Gemini
and reopened XLSX. Per-session provenance is retained, parent dates stay null for
multiple sessions, and malformed siblings prevent a fully ready classification.
Price modifiers remain structured source facts; no discounted final price or source
currency is invented.

Current field audits use the following vocabulary consistently. Each extraction bug
must identify the earliest stage that dropped a supported fact; missing optional
facts are not defects:

| Classification | Meaning |
| --- | --- |
| `MATCHED` | Supported value preserved with its own evidence |
| `SOURCE_MISSING` | Inspected source does not publish the fact |
| `EXTRACTION_BUG` | Published supported value lost or misread by the pipeline |
| `AMBIGUOUS` | Evidence admits more than one defensible interpretation |
| `ACCESS_RESTRICTED` | Fact cannot be inspected within permitted access |
| `INTENTIONALLY_UNSUPPORTED` | Explicitly unsupported input shape, reported for review |
| `CONFLICT` | Source evidence supplies contradictory values |

`review.coverage.audit_field` accepts an explicit evidence reference, explanation and
verified retention checks across collection, evidence, grouping, extraction,
normalization, canonicalization, persistence and export. `True` means inspected and
retained, `False` inspected and lost, `None` not inspected. An uninspected earlier
stage prevents an unsupported earliest-loss claim. Missing output alone cannot prove
`SOURCE_MISSING` or `EXTRACTION_BUG`; those require inspected evidence.
`coverage_summary` groups counts by publisher, source, website/Instagram channel,
field, evidence type and readiness. It produces no invented completeness percentage.

Readiness is separate from coverage and human decisions. Records/export schema 3
includes `ready_for_review`, `needs_enrichment`, `needs_schedule_review` and
`source_unavailable`, with reason codes and Persian explanations. The schema-3
workbook exposes filters in `آمادگی داده`, `دلیل بررسی` and a separate `جلسه‌ها`
column, while preserving historical snapshots and owner fields. SQLite DDL remains
version 1; older record payloads receive additive read-time defaults.

The historical matrices below describe their dated sampling only. In particular,
their blanket Jabama session `U` classifications and caption-description exclusions
are superseded by the current supported contracts. No new full-source coverage
percentage or zero-defect conclusion follows from this one saved-page audit.

## Historical 2026-09-26 audit

Acceptance principle: if an approved public source clearly exposes a fact and the
supported data contract includes it, the fact must survive into SQLite and every
portable output. Every empty field must be explained as one of:

| Code | Classification | Meaning |
| --- | --- | --- |
| M | `matched` | Source-supported, stored and displayed |
| S | `source_missing` | The source does not expose the fact for this item |
| A | `ambiguous` | Exposed but deliberately unresolved (recurrence, broad relative date) |
| U | `intentionally_unsupported` | Outside the current contract (taxonomy, structured data) |
| R | `access_restricted` | Only behind login, checkout or a robots-disallowed path |
| BUG | `BUG` (now `EXTRACTION_BUG`) | Source-supported and lost in the historical audited sample |

## Field semantics

| Workbook column | Machine field | Meaning |
| --- | --- | --- |
| `مکان` | `venue_name` | A named physical venue |
| `منطقه / محله` | `area_text` | Approximate neighborhood/district, never a precise address |
| `شهر` | `city` | City, only when the text names one |
| `آدرس` | `address` | Detailed street/postal address |
| `زمان‌بندی اعلام‌شده` | `source_schedule_text` (else `source_date_text`) | Exact source schedule wording |
| `مدت` | `duration_text` | Explicitly stated length |
| `ظرفیت / وضعیت ثبت‌نام` | `availability_text` | Explicit availability wording |
| `توضیحات / معرفی` | `description_text` | The source's own description, never a generated summary |
| `برگزارکننده` | `organizer_name` | Explicitly labelled organizer/host |

## Per-adapter source-fact inventory

Where each fact is read. "Card" is the item's own listing anchor; "structural" means an
adapter-verified value from explicit page structure (see [data contracts](DATA_CONTRACTS.md)).

| Adapter | Listing card | Detail header | Detail body / sections | Structured labels | Explicit links |
| --- | --- | --- | --- | --- | --- |
| `vadoostan/2` | category chip (kept as evidence), title, `محله:` area (structural), `ساعت:` time, one badge = price **or** availability (structural) | title heading; date/time · area · duration slots (structural) | `توضیحات` description (structural); FAQ excluded | organizer card caption `برگزار کننده` (structural name; biography excluded) | booking is `/app/auth/login` only |
| `jabama-events/2` (Events and Experiences) | title, `city · venue`, leading length in the meta slot (structural), price row (structural), rating/“new” labels (kept, not interpreted) | h1; clock tile (date, schedule, or leading length — length structural); map-pin tile (venue) | `درباره این …` description (structural); `قوانین و نکته‌ها`, `ساعت و تاریخ رویداد` text; booking-aside price (structural) | `محل برگزاری` venue section; `میزبان` host section (structural name, profile link excluded) | purchase is a script button; `/checkout`, `/tickets` robots-disallowed |
| `davvvat/1` | generic anchor text | retained panel | detail panel text | standalone `برگزارکننده` heading (organizer), `آدرس` label | registration hrefs in text |
| Instagram | — | — | caption only (media OCR optional, not used in this bounded run) | text labels only (`محله:`, `مدت:`, `برگزارکننده:`, `ظرفیت:`) | “link in bio”; no URL |

The Jabama detail page also embeds booking-session datetimes in its script payload
(observed on all four inspected Jabama details) that are not visible text. Metadata-only
structured data and occurrence expansion are outside the current contract, so these are
classified `U`, and are a clear candidate for a future stage.

## Coverage matrix by source family

✓ = publicly exposed and supported (card = L, detail = D); ✗ = not exposed; U = outside
contract; R = restricted; — = not evaluated. Observed on live pages on 2026-09-26 unless noted.

| Source | Title | Cat. | Date | Time | Multi-session | Venue | Area | City | Addr | Price | Avail. | Duration | Organizer | Reg. URL | Format | Desc. |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Davvvat Website | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| Davvvat Instagram | some | ✗ | ✓ | ✓ | some | some | ✗ | some | some | ✗ | ✗ | ✗ | ✗ | ✗ (bio) | ✗ | U |
| Vadoostan Website | ✓ L/D | U (chip) | ✓ D | ✓ L/D | ✓ D | rare D | ✓ L/D | ✗ | ✗ | ✓ L | ✓ L | ✓ D | ✓ D | R | ✗ | ✓ D |
| Vadoostan Instagram¹ | ✗ | ✗ | rare | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | U |
| Jabama Events Website | ✓ L/D | some | ✓ D | U | ✓ D | ✓ D | ✗ | ✓ D | ✗ | ✓ L/D | ✗ | some D | ✓ D | R | ✗ | ✓ D |
| Jabama Events Instagram¹ | some | ✗ | ✓ | ✓ | some | ✗ | ✗ | some | some | ✗ | ✗ | ✗ | ✗ | ✗ (bio) | ✗ | U |
| Jabama Experiences Website | ✓ L/D | some | U | some D | some D | ✓ D | ✗ | ✓ D | ✗ | ✓ L/D | ✗ | ✓ L/D | ✓ D | R | ✗ | ✓ D |
| Emrooz Events Instagram¹ | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | U |
| Tehran by Tehran Instagram | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |

¹ From the five locally stored captions per source (collected 2026-09-20); not re-collected
live in this pass. Tehran by Tehran has no local or current data, so it is not evaluated.
Instagram captions have no structural description boundary: the caption remains the raw
evidence and is not copied into `description_text` (U).

**Davvvat Website is blocked by policy.** Its robots.txt now contains an explicit
`User-Agent: GatherRadar` / `Disallow: /` group. The transport refuses every request,
the source fails in isolation (`robots:robots`), and no bypass is attempted. Earlier stored
Davvvat website observations and the sanitized Davvvat fixture remain; the Davvvat
venue/address/organizer pattern is covered offline. `davvvat_website` is now disabled
with `disabled_reason: robots`; each run reports it as `policy_blocked` without contacting
it, and Davvvat stays covered through Instagram. Website-only structural fields
(description section, address, area, duration, organizer, availability, registration
metadata, source category) are listed as potentially unavailable and marked per Event in
`channel_gaps`. See [publisher recovery](PUBLISHER_RECOVERY.md).

## Jabama Experiences

| Item | Finding |
| --- | --- |
| Discovery | Site navigation tab `تجربه‌ها` on the Tehran listing (not guessed) |
| Listing URL | `https://jabama.events/all?city=tehran&type=experiences` |
| Detail pattern | `/events/<digits>`, `/events/legacy-<digits>`, `/events/event-<digits>` |
| Rendering | Static server-rendered HTML; the existing public HTTP transport works; no browser |
| Access | robots.txt allows `/all` and `/events/`; disallows `/checkout/`, `/profile`, `/tickets`, `/wallet` |
| Adapter | Existing `jabama-events/2` (same detail layout as Events); declarative source `jabama_experiences_website`, publisher `jabama_events` |
| Collected | 5 details per bounded run (22 cards on the first listing page; no pagination) |
| Semantics | One RawItem per detail; discovery decides Event/Place/Other (2 of 5 were Other in the final run) |
| Overlap | The same detail can appear in the Events listing; `same_source_page` groups it into one Event |
| Field support | Title, venue, city, price (“از …” starting price), description, host, and length (card/detail) or weekly schedule; no visible date for bookable experiences (sessions only in embedded booking data, U) |
| Restrictions | Purchase requires the script booking flow; no public registration URL |

## Final audit — every displayed Event

Run `ecad7b746bc84fa190799719a9cf8477`; artifacts under
`data/stage9-validation/source-coverage-final-20260926/` (runtime data, not in Git). The
machine-readable audit with stored/displayed values and a note for every cell is
`field-audit.json` / `field-audit.csv` in that directory.

| # | Source | Event | Title | Cat | Date | Time | Sched | Venue | Area | City | Addr | Dur | Price | Avail | Desc | Org | Reg | Fmt | URL |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Vadoostan W | بازی D&D هری‌ پاتر: بازگشت به هاگوارتز | M | U | M | M | S | S | M | S | S | M | M | S | M | M | R | S | M |
| 2 | Vadoostan W | گروه کشف و موسیقی: «موسیقی راک: تنها… | M | U | M | M | M | S | M | S | S | M | S | M | M | M | R | S | M |
| 3 | Vadoostan W | گروه ورزش: «پینگ‌پنگ» (3 جلسه) | M | U | M | M | M | S | M | S | S | M | M | S | M | M | R | S | M |
| 4 | Vadoostan W | گروه «سیمرغ»: کوهپیمایی و داستان کود… | M | U | M | M | M | M | M | S | S | M | M | S | M | M | R | S | M |
| 5 | Jabama Events W | پرفورمنس از چهارباغ تا شانزه‌لیزه | M | U | M | U | S | M | S | M | S | S | M | S | M | M | R | S | M |
| 6 | Jabama Exp. W | رویداد هنری چرخ سفالگری | M | M | U | M | M | M | S | M | S | S | M | S | M | M | R | S | M |
| 7 | Davvvat IG | (no title) | S | S | A | S | M | S | S | S | S | S | S | S | U | S | S | S | M |
| 8 | Jabama Events W | استندآپ کمدی محمد معتضدی به همراه گر… | M | U | A | A | M | M | S | M | S | S | M | S | M | M | R | S | M |
| 9 | Jabama Events W | اکران فیلم داستان های موازی، اثر اصغ… | M | M | A | A | M | M | S | M | S | S | M | S | M | M | R | S | M |
| 10 | Jabama Events W | تور بازدید خانه‌موزه هایده چنگیزیان | M | M | A | A | M | M | S | M | S | M | M | S | M | M | R | S | M |
| 11 | Jabama Events W | نمایش/موسیقی «بودن پس از حذف» | M | U | A | A | M | M | S | M | S | S | M | S | M | M | R | S | M |
| 12 | Jabama Exp. W | ورکشاپ سفالگری با دست در کارگاه زیتو… | M | M | U | U | S | M | S | M | S | M | M | S | M | M | R | S | M |
| 13 | Jabama Exp. W | ورکشاپ سفالگری با چرخ سفال در کارگاه… | M | M | U | U | S | M | S | M | S | M | M | S | M | M | R | S | M |

221 audited cells: 113 matched, 73 source missing, 14 intentionally unsupported, 12
access restricted, 9 ambiguous, **0 BUG**. Source-supported → preserved: **113 / 113**
(every matched fact is stored in SQLite and displayed; outputs agree, see
[validation](STAGE9_VALIDATION.md)).

Notes behind the less obvious cells:

- **Category U on Vadoostan and some Jabama items.** The provisional taxonomy has no
  entry for the source genre (Vadoostan chips `بازی`/`موسیقی`/`ورزش`, Jabama stand-up or
  performance). For Events 1 and 3, the displayed `کارگاه` is inferred from prose (`کلاس`)
  and does not reflect the source chip. This is a known taxonomy limitation (an open
  product decision), not lost source text: the chip stays in the listing evidence.
- **Vadoostan city S.** Event evidence names only a neighborhood; the `تهران` filter
  button on the listing is not event evidence, and an area never implies a city.
- **Jabama date/time U.** Only the page's embedded booking data lists sessions.
- **Event 4 venue M.** The source description labels `📍 مکان: درکه`, so venue and area
  are both `درکه` by source wording.
- **Event 7.** A weekend round-up caption without a concrete occurrence (a discovery false
  positive); its detail would be in media, which this caption-only run did not acquire.
- **Events 12 and 13** show the same description: both public pages carry that identical
  text; each was extracted from its own page.

## Completeness of the final workbook (13 displayed Events)

| Field | Populated | Field | Populated |
| --- | --- | --- | --- |
| Title | 12 | Duration | 7 |
| Category | 7 | Price | 11 |
| Primary date | 5 | Availability | 1 (sold out) |
| Time | 5 | Description | 12 |
| Source schedule (machine / displayed) | 7 / 11 | Organizer | 12 |
| Venue | 9 | Registration URL | 0 |
| Area | 4 | Source URL | 13 |
| City | 8 | Address | 0 |

Population is not the success measure: every blank above is classified in the audit.

## Limitations

- Card/detail clock disagreement is not detected separately; temporal wording uses the
  existing ranking, with a structural detail header date taking precedence.
- Release gate (2026-09-27): the Vadoostan board-game night is now an Event through the
  structured-occurrence rule (verified detail date/time slot plus price). The two Jabama
  experiences stay Other: their visible pages state no date or clock time (sessions exist
  only in embedded script data), so they lack concrete occurrence evidence.
- Vadoostan genre chips are kept as `source_category_text`; `category` is set only by a
  supported mapping, so prose such as `کلاس‌های جادو` no longer yields `کارگاه`.
- Jabama booking sessions exist only in embedded script data (see above).
- Co-organizers are not guessed: several organizer cards yield no organizer.
- Area is never geocoded, and no address is derived from it.
