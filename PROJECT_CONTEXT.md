# GatherRadar Project Context

**Status:** Living product and architecture brief

**Stage:** Early MVP

**Primary audience:** The project owner and a private community of approximately 20–40 people

**Current contract extension (2026-10-20):** Events can own source-supported dated
occurrences. Explicit day lists and validated Jabama public embedded sessions stay
separate; weekly recurrence never generates arbitrary future dates. Data readiness
is separate from owner decisions, availability and collection health. Records/export
schema 3 adds occurrences and readiness without recreating SQLite (DDL schema 1) or
rewriting historical workbook snapshots (XLSX schema 3). The owner explicitly
authorized this extension; Telegram remained deferred until the owner-authorized bot
foundation below.

**Event admission clarification (2026-10-23):** Establish a real activity before
resolving its display title. A formal source heading is not mandatory: a named
activity or concise deterministic description supported by this candidate's own
evidence may supply `title`. Preserve `source_title`, origin, evidence span/IDs and
the derived-title review warning separately. Collection covers, ambiguous series
invitations, ordinary promotions and unrelated content are not individual Events.
The same admission policy guards persistence and current exports, including old
run projections; raw reprocessing is required to recover facts absent from a saved
snapshot. Historical SQLite records, decisions and workbook snapshots remain intact.
See [the admission contract](docs/DATA_CONTRACTS.md#event-admission).

**Cloud field hardening (2026-10-29):** Jabama descriptions include the adjacent
program section; unsupported embedded session shapes report value-free causes and
route to schedule review without inferred sessions. Explicit date lists with one
shared clock become dated sessions; header/list clock and length disagreements are
kept as conflicts, never chosen. Narrow venue/city/length/approximate-area grammars,
noisy same-Reel title tolerance and null remaining-session counts for ranges are
described in [the data contracts](docs/DATA_CONTRACTS.md#cloud-field-hardening-2026-10-29).
OCR and live-source defects without accessible evidence remain open; see
[the cloud hardening report](docs/CLOUD_FIELD_HARDENING_VALIDATION.md).

**Live-run QA (2026-10-29):** Fixes from run `e3ddedf3…`: nested labels, `·` clock
separators, bounded Persian day-part words, bare early hours as `ambiguous_meridiem`,
ordered weekday lists, two corroborated venue forms, reviewable Jabama sessions with
unknown additive properties, and the optional local OCR fallback chain. See
[the live-run QA report](docs/LIVE_RUN_QA_2026-10-29.md).

**Jabama timeslots (2026-10-29):** `soldOut` is a typed boolean and child timeslots are
parsed strictly (twelve allowlisted keys, parent ownership, explicit-offset ordered
timestamps, unique IDs, parent-window check), each kept as its own occurrence with parent
and timeslot identity. The owner's relationship report (88 parents / 295 timeslots)
verified those relationships, so valid timeslots are dated occurrences (temporal
eligibility only, never a booking guarantee). `soldOut=true` stays an unverified booking
flag that never affects temporal relevance. See
[the data contracts](docs/DATA_CONTRACTS.md#jabama-session-evidence-boundary-2026-10-29).

**Final Excel closure (GR-EXCEL-CLOSURE-20261029):** attributable presence/address-building
venues, no hashtag cities, narrative length conflicts with both values quoted, nonadjacent
Jabama program sections, whole-session windows that contradict the stated activity length
held for review, a booking column separate from date relevance, a quality-aware OCR
fallback and cache, and one Windows acceptance script that runs one fresh bounded crawl
and writes one review bundle. See [the closure report](docs/FINAL_EXCEL_ACCEPTANCE.md).

**Telegram bot Phase 1 (owner-authorized, 2026-10-31):** `python -m gatherradar telegram run`
runs `@GatherRadar_Bot` locally with long polling (no server or webhook). Only the numeric
owner ID from `GATHERRADAR_TELEGRAM_OWNER_ID`, in a private chat, gets the Persian menu and a
read-only source list from `config/sources.yaml`; before it is set only `/whoami` answers.
Phase 2 (2026-11-01) adds owner-confirmed crawls of all enabled or selected sources (one job
at a time in a worker thread, the same `RefreshService` wiring as the CLI, cooperative stop
between sources), delivery of the existing workbook when its run index holds that run,
read-only Persian event browsing from the persisted projection, and run history. Phase 3
(2026-11-01) adds:
- monotonic elapsed time and a history-based remaining-time range, never invented (per-source
  medians and ranges in `data/telegram/timings.json`);
- owner source management: guided Instagram/website add, reversible disable and archive.

One effective registry, used by the CLI and the bot alike, is the tracked
`config/sources.yaml` plus the git-ignored overlay `config/sources.local.json`. Base definitions
win, and policy/unsupported reasons cannot be cleared. Websites are runnable only through an
existing adapter, with SSRF checks; unsupported sites stay inactive. Auto-start is documented,
not installed. See [the bot setup](docs/TELEGRAM_BOT_SETUP.md).

## 1. Product summary

GatherRadar helps its owner answer a practical question: **What worthwhile
events can our community attend next?**

The product replaces repeated browsing across selected websites and Instagram
pages with a reviewable event-discovery pipeline. It collects public event
content, preserves the source, extracts structured facts, normalizes them,
groups likely duplicates, persists canonical state in SQLite, and exports a local review workbook.

This is a small, private validation project. Optimize for trustworthy output,
fast learning, and easy changes rather than public scale or feature breadth.

## 2. Product boundaries

### Current MVP outcome

A repeatable run produces a Persian RTL XLSX containing current Events and separate
Place observations that the owner can filter, verify, compare, and shortlist.
SQLite persists canonical history and supported review decisions. Default use needs
no Google account, server, paid API, or Office installation.

### In scope

- A manually curated registry of public event sources.
- Website and Instagram source adapters where access is permitted and reliable.
- Raw source capture with timestamps and provenance.
- Deterministic, free discovery: classifying source content as an event, a place,
  or neither, and extracting structured fields from it. No paid AI or API key is
  required to run the core MVP.
- Persian and English text handling.
- Date, time, timezone, location, category, and price normalization.
- Duplicate detection without destructive deletion.
- Confidence and review states for uncertain records.
- Local JSONL evidence audit, SQLite canonical/review history, and XLSX review snapshots.
- Portable CSV/JSON and optional manual Gemini handoff bundles.
- Optional Google Sheets API integration, isolated from default operation.
- Manually triggered local execution with understandable run summaries; scheduling is deferred.

### Deferred

- Selecting events through a dedicated dashboard.
- Telegram publishing to the community, polls, or voting (the owner-only bot crawls, delivers
  outputs and manages sources for the owner only).
- Personalized ranking and recommendation models.
- Automated booking or registration.
- A public SaaS product, accounts, roles, payments, or multi-tenant infrastructure.
- Broad, unsupervised crawling of the web or Instagram.

## 3. Primary workflow

1. The owner maintains a small list of approved sources.
2. A collection run checks each enabled source and records what was observed.
3. The pipeline identifies event-like content and extracts candidate facts.
4. Deterministic rules normalize and validate those facts.
5. Exact and probable duplicates are grouped.
6. Canonical results commit to SQLite, then export to XLSX, CSV, JSON and a Gemini bundle.
7. The owner verifies uncertain fields and chooses what is worth sharing.

Human review is a product feature in this phase, not an exception. The system
must expose uncertainty rather than silently inventing missing information.

## 4. MVP architecture

```text
Source registry
      ↓
Source adapters (website / Instagram)
      ↓
Raw capture store
      ↓
Evidence selection and conservative grouping (explicit opt-in for media)
      ↓
Discovery (event / place / other) and extraction
      ↓
Normalization and validation
      ↓
Deduplication
      ↓
Source-supported title admission
      ↓
Review-window filtering
      ↓
SQLite canonical/review repository
      ↓
XLSX (default review), CSV, JSON, manual Gemini bundle; optional Google Sheets
```

### Architectural responsibilities

- **Source registry:** Declarative source name, type, URL, locale, timezone,
  enabled state, collection interval, and adapter configuration.
- **Source adapters:** Fetch content only. Source-specific behavior remains
  isolated behind a shared interface.
- **Raw capture store:** Retains enough source material, hashes, and timestamps
  to reproduce or audit an extraction.
- **Discovery:** Classifies source content as an event, a place, or neither, and
  converts it into candidate facts. The default engine is deterministic, rule-based,
  and free; any other implementation must sit behind the same provider-neutral
  interface.
- **Normalization and validation:** Applies deterministic conversions and flags
  incomplete or contradictory data.
- **Deduplication:** Stage 8 distinguishes strong automatic matches from possible
  duplicates for review. Every pair in an automatic group must match; normalized
  occurrence evidence and source/publisher context support explainable decisions.
- **Canonical persistence:** standard-library SQLite behind `CanonicalRepository`.
  Runs, current Event identity, immutable fact snapshots, and human review are separate.
  Raw observations/OCR remain in JSONL. Only a caption deliberately attributed
  as an Event description can also appear in the structured fact payload.
- **XLSX:** default Persian RTL review workspace. Only supported decisions/notes import;
  arbitrary fact edits stay visual and never feed extraction or matching.
- **CSV/JSON:** portable tabular/structured exports generated from persisted runs.
- **Gemini bundle:** optional manual one-way publishing, no API/auth inside GatherRadar.
- **Google Sheets:** optional authenticated adapter; live validation is pending.

Keep the pipeline modular. A change to one website, extraction provider, or
output destination should not require rewriting the rest of the system.

## 5. Data contract

Use two related records: an immutable-enough source observation and a canonical
event candidate. Exact implementation types may change, but the separation and
meaning of the fields should remain stable.

Discovery also recognizes a third outcome. Content that describes a venue worth
visiting rather than an occurrence becomes a **place candidate** — name, summary,
category, address, city, opening-hours text, price text, language, and evidence URL —
kept separate so place content is never forced into an event record. Content that is
neither becomes no candidate at all. See `docs/DATA_CONTRACTS.md` for the full shape.

### Source observation

| Field | Meaning |
| --- | --- |
| `source_record_id` | Stable internal identifier for the observation |
| `source_type` | Adapter family, such as `website` or `instagram` |
| `source_name` | Human-readable configured source name |
| `source_url` | Root page or account URL |
| `content_url` | Direct URL of the observed page or post |
| `captured_at` | Time the collector observed the content |
| `content_hash` | Hash used to recognize unchanged content |
| `raw_text` | Extracted source text without semantic rewriting |
| `raw_metadata` | Adapter-specific metadata stored as structured data |
| `collector_version` | Version or identifier of the collection logic |

### Canonical event candidate

| Field | Meaning |
| --- | --- |
| `event_id` | Stable internal event identifier |
| `title` | Human-readable display title, explicit or deterministically derived from Event-specific source evidence |
| `source_title` / `display_title_origin` | Original explicit title when available; explicit caption/website/OCR versus descriptive recovery |
| `title_evidence_text` / `display_title_evidence_ids` / `title_review_required` | Supporting source span, candidate-specific fragment IDs, and derived-title warning |
| `summary` | Reserved for a future dedicated summary contract; not generated, normally empty |
| `description_text` | The source's own description text, never rewritten or summarized |
| `category` / `tags` | Controlled category plus optional discovery tags |
| `source_date_text` | Original date wording for audit and review |
| `starts_at` / `ends_at` | Timezone-aware normalized timestamps when known |
| `start_date` / `end_date`, `start_time` / `end_time` | Separate normalized components; unknown clock never becomes midnight |
| `date_precision` | `exact`, `day`, `range`, `inferred` (single date with inferred year), or `unknown` |
| `timezone` | IANA timezone used for interpretation |
| `venue_name` / `address` / `city` | Structured location fields when known |
| `area_text` | Approximate neighborhood/locality as written; never a venue, address or geocode |
| `source_schedule_text` | Exact multi-session/recurring wording; concrete dates can support occurrences, recurrence alone cannot |
| `occurrences` / `schedule_kind` / `recurrence_rule` | Deterministic dated sessions, explicit range bounds, or a source-backed weekly rule without generated future dates |
| `duration_text` / `organizer_name` | Explicitly stated length and labelled organizer/host |
| `availability_text` | Explicit availability wording; sold-out wording sets status `sold_out` |
| `event_format` | `in_person`, `online`, `hybrid`, or `unknown` |
| `price_text` | Source wording for price; never discard it after normalization |
| `price_amount` / `currency` | Parsed price fields when unambiguous |
| `registration_url` / `registration_deadline` | Registration facts when present |
| `canonical_source_url` | Best direct evidence URL for the event |
| `language` | Detected source language |
| `extraction_confidence` | Preserved provider score when agreed; not calibrated duplicate probability or proof |
| `review_status` | `needs_review`, `verified`, or `rejected` |
| `duplicate_group_id` | Hash of current canonical group membership, separate from stable event identity |
| `first_seen_at` / `last_seen_at` | Discovery history |
| `reviewer_notes` | Human corrections or decisions |

Unknown fields remain null or explicitly unknown. Never infer a venue, price,
date, or registration detail merely to make a row look complete.

### Local review view

Each run creates a Persian RTL Event snapshot and an optional separate Place snapshot.
Decision/title/date/schedule/location (venue, area, city, address)/price/availability/
description/organizer/action links come first; IDs, ISO values and provenance are hidden. Jalali dates/weekdays are computed from normalized values.
Permanent local sheets: `راهنما`, `تاریخچه اجراها`, `بررسی تکراری‌ها`, hidden `_meta`.
Workbook schema 3 (schema-2 workbooks upgrade in place) opens on the newest Event snapshot, freezes only row 1, and uses
centralized compact styles: Vazir for Persian/mixed text, Poppins for English/technical
content. Fonts are referenced, not bundled; clients choose a fallback if absent.
Schema-1 prerelease workbooks are refused intact; export to a separate recovery path.

SQLite is the completion authority. Event decisions and notes carry only by stable
Event ID; duplicate pair review persists without changing matching. Place review is
run/candidate-scoped, with no Place deduplication. Historical workbook snapshots are
not rewritten. Invalid/conflicting review rows are reported; no arbitrary source-fact
correction is imported. See [local workflow](docs/LOCAL_REVIEW.md).

The same snapshot also offers filterable Persian readiness, an explanation, and
session details. Incomplete discoveries retain their raw evidence for investigation.
Only positively identified activities meeting Event title admission enter current Event review outputs;
eligible Events with unresolved schedules remain in a separate schedule-review dataset.
Only run-time actionable Events enter the current Event view and publishing exports.
A supported ongoing exhibition range stays actionable when visiting hours need
confirmation. Schedule completeness and publication readiness do not erase known
temporal relevance. Explicit date lists preserve every date without borrowing a
header's clock for all sessions. Relative dates require the original publication
timestamp in the source timezone; capture time never substitutes for it.
Optional missing price/description/venue does not by itself fail readiness. Known
extraction loss, contradictory evidence, incomplete OCR and unresolved schedules do.
The source's unchanged caption may be a description only when its unit identifies
one defensible Event; roundup captions are not copied onto separate media Events.

## 6. Data and language rules

- Store normalized timestamps as timezone-aware values. Preserve the source
  timezone and render review dates consistently.
- Use `Asia/Tehran` only when the source configuration or event evidence makes
  that interpretation valid; do not assume every event is in Tehran.
- Support Persian digits, Persian month names, and Jalali dates. Convert them to
  Gregorian ISO values while retaining `source_date_text`.
- Keep a controlled top-level category vocabulary; keep free-form labels as tags.
- Prefer exact source IDs, URLs, and hashes for deduplication. Fuzzy matches must
  be reviewable and must not delete records automatically.
- Mark expired, cancelled, postponed, or sold-out events when the source says so.
- Every canonical fact must be traceable to at least one source observation.

## 7. Collection and safety policy

- Collect only public event information from sources approved by the owner.
- Follow applicable terms, robots directives, rate limits, and platform rules.
- Prefer official feeds, APIs, exports, or permitted access methods when they are
  available.
- Never bypass authentication, CAPTCHAs, access controls, or anti-bot measures.
- Do not collect followers, comments, private profiles, direct messages, or
  unrelated personal data.
- Never commit cookies, tokens, credentials, raw session data, or private exports.
- Isolate a failing source, use bounded retries, and report the failure without
  blocking the remaining sources.
- Make retention of raw captures configurable and keep only what is needed for
  debugging, provenance, and reprocessing.

## 8. Quality and observability

Each run should have a `run_id`, start and finish timestamps, per-source status,
counts for observed/extracted/new/updated/duplicate/rejected records, and concise
errors. Logs must be useful without exposing secrets.

The pilot should measure:

- source coverage against a small manual sample;
- required-field completeness;
- false-positive and missed-event rates;
- duplicate rate after grouping;
- time needed for owner review;
- percentage of records requiring correction.

Set numeric acceptance thresholds only after a baseline run. Avoid inventing
precision targets before real source samples exist.

## 9. Proposed repository shape

Create this structure incrementally as implementation begins:

```text
src/gatherradar/
  domain/           # records, enums, and validation contracts
  collectors/       # source adapter interface and implementations
  acquisition/      # publisher channels: strategies, channel status, coverage, policy re-check
  ocr/              # provider boundary and local Tesseract implementation
  grouping/         # semantic snapshot selection and conservative discovery units
  extraction/       # discovery: classification, rule engine, and field extraction
  normalization/    # dates, text, locations, categories, and prices
  deduplication/    # exact and fuzzy grouping
  storage/          # JSONL/media audit and SQLite canonical/review state
  review/           # shared contracts, serialization and owner workflow
  exports/          # local XLSX, CSV/JSON and manual Gemini bundle
  sheets/           # optional Desktop OAuth/API adapter
  orchestration/    # run coordination and summaries
tests/
  fixtures/         # sanitized, stable source samples
  unit/
  integration/
config/
  sources.example.*
data/               # local runtime data; add to .gitignore before use
```

Python 3.11+ with `pip`, a local `.venv`, and setuptools via `pyproject.toml` is the
chosen toolchain. Tests run on `unittest` from the standard library. No formatter or
linter is final yet. Discovery uses the standard library only and adds no AI dependency;
`openai`, `anthropic`, LangChain, and any other paid or cloud AI service are deliberately
out of the core MVP. See the README for exact setup and run commands.

Instagram access runs through [Playwright](https://playwright.dev/python/) driving the
installed Google Chrome with a dedicated, persistent GatherRadar profile under
`data/browser/instagram-profile/`. The owner logs in manually once in that profile; it is
the persisted session. Responsibilities stay separate: `collectors/instagram_browser.py`
owns the profile, launch, and login checks and navigates pages;
`collectors/instagram_dom.py` extracts media links, captions, and timestamps from page
HTML using URL patterns and semantic elements; `collectors/instagram.py` maps the result
into `RawItem`; storage is unchanged. The browser runs visibly and unmodified — no stealth,
fingerprint changes, proxies, or checkpoint bypasses.

Visual evidence acquisition is a separate explicit run over already-stored `RawItem` records.
`collectors/instagram_evidence.py` revisits only those approved media URLs through the same
authenticated Chrome profile, captures the displayed image or bounded ordered carousel slides,
and samples a small deterministic set of reel frames. It stores content-addressed PNG artifacts
below `data/media/`; one artifact failure is isolated from other items. Audio is out of scope.

`OcrProvider` keeps evidence independent of one OCR engine. The first implementation invokes
the local Tesseract executable with `fas+eng`, a bounded timeout, and no `shell=True`; it never
downloads an executable or language pack. Raw and lightly cleaned OCR output, engine/version/
configuration, artifact provenance, empty results, and failures are represented explicitly.
No cloud OCR, paid AI, API key, or new Python dependency is required. An optional local
fallback chain (default `tesseract,easyocr,windows`) skips engines that are not installed and
tries a later engine only after a failed or empty result; each attempt stays separate
evidence. EasyOCR is an optional extra; Windows OCR runs through built-in PowerShell.

The earlier [Instaloader](https://instaloader.github.io/) transport remains as a legacy
fallback reference in `collectors/instagram_instaloader.py`, since its profile lookup is
refused with HTTP 429. It is used only when explicitly selected, never as an automatic
fallback.

Discovery lives in `extraction/`. `DiscoveryProvider` is a provider-neutral protocol whose
single `discover` call both classifies a raw item and returns source-supported facts
(`DiscoveryFacts`) from a deliberate `ExtractionInput` that excludes adapter `raw_metadata`.
The classification is a typed `DiscoveryType` — `EVENT`, `PLACE`, or `OTHER` — never a free
string. `DiscoveryService` validates that output, maps it onto `EventCandidate`,
`PlaceCandidate`, or no candidate at all, sets provenance (`raw_item_id`, `evidence_url`) from
the `RawItem` itself, and derives the candidate id from the raw item id and content hash so it
never depends on the provider. `orchestration/discovery_run.py` analyzes a batch item by item
and keeps candidates in memory. Discovery leaves normalization-owned fields null;
the opt-in normalization step below produces an updated candidate copy.

The source-neutral evidence boundary is `RawItem -> EvidenceBundle -> 0..N DiscoveryUnits ->
DiscoveryService`. The original caption is a `CAPTION` fragment and still reaches the rule
engine unchanged. Media OCR is stored as separate `IMAGE_OCR`, `CAROUSEL_SLIDE_OCR`, and
`REEL_FRAME_OCR` fragments; website adapters use `WEBSITE_TEXT` through the same layer.
`RawItem.raw_text` is never replaced with OCR. Default Instagram extraction still creates only the
caption unit. Stage 5 adds explicit `extract --evidence`: `grouping/` selects the current
caption plus the latest stored fragment per semantic media position, then `conservative/2`
builds zero or more units. Failed/empty latest versions suppress older OCR without changing
storage. Unit identity includes raw item id, strategy version, and ordered fragment ids;
unit text joins only deliberately grouped source fragments, unchanged, with newlines.

Grouping reuses existing signals without changing classification rules. New anchors split
groups; only adjacent, structured supporting facts without recognized conflicts may attach.
Ambiguous or unavailable fragments break attachment. Consecutive Reel samples with fully
equivalent folded text group together; changed wording/digits stay separate. Captions are
never copied to multiple groups, and a single media group joins a caption only when their
roles are complementary and nonconflicting, or their complete texts are equivalent.
Uncertain relationships remain separate. This does not reliably segment multiple events
inside one image or resolve noisy OCR, implicit references, or semantic contradictions.

`conservative/2` adds same-occurrence handling inside one RawItem. A media fragment that
repeats an anchor's exact folded title (numbers significant, no fuzzy matching) joins that
anchor — the caption first, else the earlier media anchor — when it adds nothing that
conflicts. A repetition carrying no readable fact, or only an isolated unlabelled
clock/numeric-date OCR line (`3 am`, `9/25`), is kept as collapsed provenance outside the
unit text; one carrying compatible support lines contributes its text. Same post alone, a
different title, or a conflicting date/venue/address/price/registration keeps units apart.
Date-only and clock-only wording are complementary rather than conflicting. Media-only
Events are unchanged. Grouping explanations (`support_attached_to_anchor`,
`repeated_anchor_collapsed`, `ocr_fragment_insufficient_for_independent_event`) appear only
in `extract --evidence` output.

`orchestration/evidence_discovery_run.py` reads local raw/evidence stores, selects items with
the existing recency policy, isolates malformed records and per-item/unit failures, and
returns transient candidates plus units for provenance review. It invokes no collector or
OCR engine. Evidence-aware candidate IDs are unit-specific; default caption-only IDs and
output remain unchanged. No database-specific logic or candidate persistence is introduced.

The append-only evidence contract lacks run manifests, removed-slot markers, and observation
timestamps. Selection means latest stored version per slot, not a full capture snapshot:
missing positions can remain stale, and returning to an already-stored fragment is not
recorded by Stage 4 deduplication. This limitation is documented rather than changing
persistence in Stage 5. Stage 9 persists local canonical/review state; the stored-media
slot-selection limitation remains explicit and is not a full capture snapshot.

`storage/evidence_jsonl.py` persists evidence append-only and idempotently below
`data/evidence/`. Artifact hash plus media position avoids identity based on signed CDN URLs;
OCR engine/configuration and output changes remain auditable. Candidates remain transient.
Carousel and reel OCR fragments require their respective non-negative integer position;
other fragment kinds reject media positions. Valid persisted identities remain unchanged.

**GatherRadar's core MVP runs completely free.** The default and only implementation of that
protocol is `RuleBasedDiscoveryProvider` (`rule-based/1`): deterministic rules with no model,
no API key, no paid service, and no network access. The engine is split so its judgement is
reviewable — `text.py` (length-preserving folding and whole-token matching), `rules.py` (all
vocabulary, weights, and thresholds in one place), `signals.py` (explainable signal detection),
`fields.py` (source-supported field reading), `rule_based.py` (scoring and the decision). It is
source-neutral: it reads `ExtractionInput`, so website observations and later source families
use the same engine unchanged. Every decision carries `DiscoveryEvidence` — scores, matched
signals, negative signals, and a reason — which belongs to the run outcome and is never
persisted.

`storage/jsonl.py` gained a read-only side, `read_latest_items()`, which returns the most
recently stored observation of each id and isolates malformed lines instead of raising.
`python -m gatherradar extract instagram <source_id> --limit 5` runs discovery over stored
items only: it never collects, never opens a browser, and persists nothing.

Stage 6 adds `WebsiteCollector -> WebsiteAdapter`, with a replaceable public static HTTP
transport and a small adapter factory. The generic adapter takes a detail-path prefix,
one tag/class/id content selector, excludes, and explicitly safe query keys to remove.
Small Davvvat, Vadoostan, and Jabama adapters isolate measured layout differences; shared
collection/orchestration never switches on source IDs. No new dependency or authenticated
website browser was needed. Adding an ordinary supported site requires configuration and
validation; unusual layouts need an adapter plus registration/fixtures, not semantic changes.

The listing page also supplies each item's own card (only its anchor's text) as a
current-run `website_listing` evidence fragment, and adapters record verified structural
facts (price/status badges, header slots, labelled sections) with `detail`/`listing`
provenance. Structural values outrank prose readings; explicit card/detail disagreement
leaves the field null with a `source_field_conflict` diagnostic. See
`docs/SOURCE_FIELD_COVERAGE.md`. Jabama Experiences (`/all?city=tehran&type=experiences`,
static) is a separate source sharing the Jabama adapter; the same detail page listed by
both Jabama sources groups as one Event. Davvvat's robots.txt disallows GatherRadar, so
`davvvat_website` stays defined but disabled by default and is never bypassed.

One detail page becomes one `webpage` RawItem, stored append-only under
`data/raw/website/<source_id>.jsonl`. IDs combine source ID with a native path ID (current
specialized adapters, query-free URLs) or canonical URL hash (generic/query-dependent URLs).
Known tracking keys can be removed, but meaningful query parameters remain. Publication time
stays null. HTML text preserves relevant source wording without injected labels/URLs;
metadata retains adapter version, source title, URLs/links, native ID, and transport.
The item's own listing card and verified structural fields join the content hash (a newly
sold-out card appends a revision); other metadata-only edits still do not append.

`collect website <source_id> --limit N` checks robots and every redirect, isolates failed
details, and takes first valid listing-order items, up to 30 and `min(3*N,30)` attempts.
It does not paginate. `extract website` reads latest stored observations in first-seen order,
rebuilds fresh `WEBSITE_TEXT`, and calls the shared conservative grouping and `DiscoveryService`.
It opens no browser, runs no OCR, contacts no source, and writes no candidates. Instagram
caption-only semantics and Stage 5 grouping/classification policy are unchanged.

Bounded live validation on 2026-09-24 collected five items per source: Davvvat yielded five
Events; Vadoostan four Events/one Other; Jabama five Events. Vadoostan/Jabama normal reruns
returned five Existing with no append. Davvvat's homepage selection changed between CLI
runs; holding one actual listing response fixed and refetching its five details live
confirmed five Existing and byte-identical raw storage on the unchanged rerun. Offline
unit/candidate reruns were deterministic. Comments/reviews, navigation, mobile duplicates,
FAQ/account content were excluded in the inspected layouts. Jabama `/events/` is supported;
its separately observed `/theaters/` layout is deliberately outside coverage. Raw addresses
and full titles can still be missing/partial in candidate fields; no rule tuning was done.

This is not universal scraping. Static UTF-8 list/detail layouts only; no arbitrary CSS,
JavaScript rendering, card-only roundup extraction, arbitrary recurrence expansion, or full visibility
computation. Layout drift and unrecognized recommendation containers need owner review.
Neither website storage nor discovery reconstructs a historical listing snapshot or marks
removed events. Broader source coverage and extraction accuracy remain unvalidated.

## 10. Delivery sequence

Stage 7 adds source-neutral `normalization/` after discovery, with separate date, clock,
price, result and service modules. It preserves all original fields, identities, confidence
and provenance. Candidate dates/times remain separate; only safe single-date clocks compose
aware timestamps. Typed precision and diagnostics make unresolved and inferred values visible.
Places reuse price results without event semantics. Stage 7 does not instantiate `Event`;
Stage 8 now reconciles and creates it in memory, without persistence.

Jalali conversion uses `persiantools>=6.2,<7.0` (verified 6.2.0 on Python 3.13.15/Windows).
Timezone comes from `Source` and is validated with `ZoneInfo`, including DST gap/fold checks.
Relative dates require stored publication time, never capture time or the wall clock. Bare
relative tokens require a standalone/labelled temporal evidence line to avoid proper-name
false positives. Finite weekday pairs also require corroborating publication/week context.
Yearless day/month inference accepts one adjacent-year candidate within
45 days of that local reference, always flagged for review; yearless ranges must fit one
Jalali year and span <=90 days. Money uses Decimal and distinct TOMAN/IRR stated units.
Free is zero with unspecified currency. Source wording is never replaced with parsing text.

Explicit Persian day ordinals through 31 and attached/separate `ماه` month suffixes
are supported in single dates and clear ranges. Explicit same-month day lists now
produce separate occurrences when every date passes the same year/reference bounds;
date ranges with daily hours retain date/time components and `multi_day_hours`, with
no continuous `starts_at`/`ends_at` interval. Existing reference/year bounds still apply.
Discovery keeps the full wording of these shapes in `source_date_text` for every Jalali
month: attached `مهرماه` and separate `مهر ماه` suffixes, ordinal and numeric leading days
(`۹ و ۱۰`, `۸ تا ۱۰`, `۵، ۱۲، ۱۹ و ۲۶`), and an explicit trailing year. An ordinal that
names part of a month (`هفته اول مهر`) is not a day.

`extract ... --normalize` appends an offline, write-free review of the exact discovery
snapshot. Recurrences, discrete sessions, broad weeks/weekends, overnight ambiguity, and
multi-tier prices are deliberately not forced into a single occurrence/price. Multi-day
hours never become a continuous timestamp interval. See `docs/DATA_CONTRACTS.md` for the
complete rules and `docs/STAGE7_VALIDATION.md` for actual bounded local validation.

Normalization is independent of persistence. Stage 9 selects local SQLite review
persistence; Stage 7 itself remains pure and write-free.

Stage 8 adds source-neutral `deduplication/` after normalization: deterministic pair
decisions, all-member automatic groups, separate possible-duplicate suggestions and
canonical `Event` drafts. Precision is preferred over recall. Only distinctive titles
with explicit single-date occurrence evidence can auto-group; cross-publisher pairs need
matching clocks plus venue/address or registration corroboration. Inferred/relative
dates, ranges and unresolved schedules stay review-only. Conflicting fields and upstream
diagnostics remain visible, with candidate-level provenance and all input contexts retained.

Canonical IDs anchor to the earliest captured RawItem in local history, with stable
evidence slots for multiple events in one media item. They do not hash candidate membership;
adding later support or editing content normally preserves identity. Duplicate-group IDs
describe current composition. Earlier imported history, regrouping, splits/merges and
media-slot changes can still alter identity. Stage 9 records authoritative anchors in
`event_identity_map`; it does not guess aliases or automatically resolve splits/merges.

`canonicalize --source ...` (repeatable) or `--all-enabled` runs local discovery,
normalization and canonicalization without acquisition or writes. Instagram media is
explicitly selected through `--instagram-evidence`, with caption fallback. Places pass
through unchanged. See `docs/DATA_CONTRACTS.md` and `docs/STAGE8_VALIDATION.md` for policy,
validation and limitations. No canonical database, sheet, or export file is created.

The project intentionally became Instagram-first for initial source validation: an
Instagram collector was easier to stand up before a website adapter and gives an early
read on whether anonymous access is viable at all, which the rest of the pipeline
depends on knowing.

1. Define schemas, source registry format, and one sanitized fixture. **Done.**
2. Implement the Instagram collector end to end into local raw JSONL storage. **Done.**
3. Complete live Instagram validation. **Done** — the browser-backed collector has been
   validated live against `@davvvat`: authentication, profile and media discovery, real
   Persian caption extraction, published timestamps and image URLs, recency-based
   selection that pinned posts do not displace, and New/Changed/Existing behavior across
   repeated runs. This closes the Instagram Collector MVP milestone.
4. Add detection and structured extraction over collected raw items. **Done** — the
   provider-neutral boundary (`RawItem` → `DiscoveryService` → `DiscoveryProvider` →
   transient `EventCandidate` | `PlaceCandidate` | none) plus a deterministic, free rule
   engine behind it, reachable through `python -m gatherradar extract`. Tested offline with
   fake providers for the architecture and synthetic Persian and English captions for the
   rules. No AI is used and none is required.
5. Add source-neutral visual evidence, bounded Instagram image/carousel/reel capture, local
   OCR, and evidence persistence. **Implemented and validated on bounded live samples:** one
   Davvvat Reel (six frames) and one Vadoostan carousel (five slides), local `fas+eng` OCR,
   artifact/provenance inspection, and unchanged reruns with zero new evidence. Persian OCR
   quality remains variable; standalone images and broader media/layout coverage are not yet
   validated. The existing caption candidate semantics remain unchanged.
6. Add conservative evidence grouping and explicit offline evidence-aware discovery
   (**Stage 5**). Implemented with synthetic offline tests and bounded read-only inspection
   of the existing Stage 4 evidence: Davvvat produced a caption Event and six noisy frame
   Others; Vadoostan produced a caption Other and five independent slide Others. No blind
   carousel concatenation or new media candidates occurred. Broader segmentation accuracy
   remains unvalidated. Stage 5 was merged through PR #4. A realistic sanitized Persian
   carousel validates positive grouping; available runtime media did not provide a clear
   positive multi-fragment example (see README).
7. Add website adapters and broader source coverage (**Stage 6**). **Implemented and
   validated on bounded public samples** from Davvvat, Vadoostan, and Jabama `/events/`,
   including unchanged-detail idempotency and offline shared discovery. Generic future-source
   configuration is tested offline; other layouts and broader coverage remain unvalidated.
8. Add deterministic normalization and validation: Jalali-to-Gregorian conversion, normalized
   dates/times and numeric prices (**Stage 7**). Implemented for owner review; partial and
   unresolved cases remain explicit, with no candidate persistence.
9. Add conservative event canonicalization and deduplication (**Stage 8**). Implemented
   in memory with offline multi-source review; no destructive deletion or persistence.
10. Local SQLite persistence, XLSX review, CSV/JSON and manual Gemini export (**Stage 9**):
    implemented with fresh bounded Website/Instagram and offline/local validation.
    The owner has accepted the architecture and workbook UX; the latest accuracy
    pass corrects corroborated venues, ordinal dates and attendance-format evidence,
    and the source-completeness pass preserves listing-card facts, area, description,
    duration, organizer, availability and schedule wording, and adds Jabama Experiences.
    Google API publishing remains optional.
    See `docs/STAGE9_VALIDATION.md` for actual evidence and limitations.
11. Pilot with a small curated source set and refine from measured errors.
12. Evaluate Telegram and recommendations only after the discovery loop works.

## 11. Open decisions

- Initial source list and source priority.
- **Resolved:** optional personal-owner Desktop OAuth, Sheets-only scope; no service account or sharing automation.
- **Resolved:** local SQLite canonical/review state, default XLSX, portable CSV/JSON,
  optional manual Gemini bundle and optional Sheets API. JSONL remains the audit trail.
- Raw capture retention period.
- Category taxonomy and Persian/English display conventions. The rule engine ships a small
  provisional vocabulary in `rules.py`; the final taxonomy is still open. Source genre chips
  (e.g. Vadoostan `بازی`/`ورزش`/`موسیقی`) have no taxonomy entry yet; they are kept verbatim as `source_category_text` and displayed.
- **Resolved:** bounded parsing of verified Jabama public embedded session data is
  supported without executing scripts or calling APIs. Explicit dated sessions are
  occurrences; recurrence expansion without source dates remains unsupported.
- **Resolved:** `davvvat_website` is disabled by default because its robots.txt disallows
  GatherRadar (re-checked 2026-09-27); its definition and adapter are kept.
- Scheduling is deferred; Stage 9 is manually triggered only.
- Whether anything beyond the rule engine is ever needed. **Resolved for now:** discovery is
  deterministic and free, and no paid AI or API key is part of the core MVP. `DiscoveryProvider`
  stays provider-neutral so that decision remains reversible, and measured rule-engine error
  rates from the pilot are what should reopen it.

Resolve these through small end-to-end experiments. Update this document when a
decision changes the product boundary, data contract, or architecture.

## 12. Publisher channels (post-Stage 9)

A publisher (`publisher_key`) is represented by one or more channels (Sources), each
acquired by a strategy chosen by capability (`acquisition/`). Channel status uses a
fixed vocabulary; `publisher_coverage` reports whether any channel contributed this run,
separately from channel health. Publisher coverage ≠ every channel available. A
policy-blocked channel of a covered publisher does not make a run partial. Depth-one
linked detail pages may be collected only on configured website-channel origins through
the normal Website boundary. Events keep `channel_provenance`, `reference_urls` and
`channel_gaps`; channels combine only through Stage 8 identity, never by publisher alone.
Robots-disabled website channels get a cached, robots-only re-check at most weekly and are
never re-enabled automatically. Davvvat's website is `policy_blocked`; Davvvat is covered
through Instagram. See `docs/PUBLISHER_RECOVERY.md`.

## 13. Stage 9 manual application service

`RefreshService.run` imports supported local workbook edits before acquisition,
observes exact current RawItems (including unchanged items), optionally acquires
Instagram evidence, then reuses discovery, normalization and Stage 8 canonicalization.
Failed sources remain visible while successful sources continue. `refresh --stored`
analyzes existing observations offline. `export --run latest` reads SQLite only.
`refresh` defaults to media acquisition; `--skip-instagram-evidence` is caption-only.

The default review horizon is 14 days (1–90), inclusive from the stored run start's
Asia/Tehran date. The exact run timestamp excludes reliably ended sessions, including
earlier today. Verified occurrences take precedence; ongoing source-supported ranges
remain eligible even when their start is old or their end exceeds the horizon. Daily
hours never imply continuous attendance; an unknown end is never invented. Unresolved
and recurring schedules without verified instances are a separate schedule-review
dataset, never upcoming publishing candidates. Inferred dates retain diagnostics.
`--review-timezone` controls presentation only; event timezones are preserved.
SQLite retains full historical facts and review decisions. Every current export uses
the same schedule projection; historical re-export uses that run's stored timestamp.

Instagram still selects five published posts/reels per source with `--limit 5`, using
the bounded three-item pinned-post buffer. Missing publication timestamps produce an
explicit recency warning, not a claim of verified newest-five membership. Carousel
capture waits for changed, loaded and stable visible media, including video slides
(one paused frame at zero). Three attempts stay on the same position; persistent or
duplicate capture stops that post with an explicit missing-position report while
retaining successful artifacts. Evenza Platform is an enabled generic Instagram source.

Persistence precedes export. SQLite version 1 uses foreign keys, explicit atomic
transactions, WAL, FULL synchronous writes and a five-second busy timeout. Newer or
unrecognized databases fail safely. Keep the DB local with one writer; no multi-user
or synced-folder database model is provided. The exporter interfaces and repository
protocol leave future integration seams without implementing future platforms.

XLSX uses openpyxl and temporary-save/readback/atomic-replace. Locked/corrupt workbooks
are preserved. CSV is UTF-8 BOM with formula escaping; JSON preserves exact structured
values. Automatic local Gemini bundles reuse both serializers and add deterministic
manifest/instructions. They contain no raw dumps, auth state or local absolute paths.
There is no Gemini upload, API, fact inference or automatic round-trip.

Runtime defaults are below ignored `data/`: `state/gatherradar.sqlite3`,
`review/GatherRadar.xlsx`, `exports/`, and lightweight `runs/` manifests.
See [data contracts](docs/DATA_CONTRACTS.md), [local review](docs/LOCAL_REVIEW.md),
[manual Gemini](docs/GEMINI_HANDOFF.md), and [actual validation](docs/STAGE9_VALIDATION.md).

Stage 9 supported-field hardening admits only an adapter-verified retained website
heading as optional `ExtractionInput.source_title`, after validating it against the
observation text. It names already-classified Events without changing classification.
Heading context participates in website observation hashing. Older captures without
that marker require fresh acquisition; arbitrary first-line titles remain prohibited.
Standalone address/venue section labels and the Persian recurring-weekday connector
preserve source wording. Unresolved recurrence/date interpretation remains explicit.
Event summaries remain null: there is no deterministic Event summary contract yet.

Metadata-only links/structured data remain outside semantic extraction; source URLs and
raw evidence remain available for owner verification. Unlabelled locations are read only
through a conservative natural-venue path: a recognized venue head (`کافه`, `گالری`, …)
after `در`/`توی`/`میزبان شما` or in a branch line, with attendance wording, a standalone
branch line, or — for generic heads such as `خانه`/`مرکز` — holding wording
(`برگزار …`) right after the name. Branch wording stays inside `venue_name`
(`شعبه‌ی لواسان کافه رئیس`); no area, city or address is derived from it.

The release gate adds two narrow, source-neutral discovery rules. An adapter-verified
source category label (`source_category_text`) outranks free-text category inference;
`category` is only its supported mapping, else null. A structured-occurrence path lets an
item without generic Event vocabulary be an Event only when its own detail page has one
verified date slot with a clock time plus price/registration/attendance evidence; listing
context alone never qualifies and generic thresholds are unchanged.

Field completeness adds nullable `location_context` for an explicitly stated building,
separate from venue, neighborhood, street address and city. A pinned three-part
area/building/venue line may supply those components without geographic inference;
an explicit pinned name/branch line may supply its neighborhood. Existing candidate
and fragment lineage is retained. Explicit AM/PM clocks are preserved and normalized.

Current local exports derive next-session date/clocks and remaining session count from
verified future occurrences inside the stored run's horizon, ordered by their aware
instants. Date-only sessions retain unknown clocks. Already-started sessions and
ongoing ranges remain actionable where appropriate but are not labelled a next session.
These are presentation values, never substituted into the parent Event dates.
XLSX uses Persian category labels on both current Event and schedule-review sheets;
factual re-projections preserve prior sheets. Future refresh manifests retain bounded
media failure categories, RawItem IDs, slide/frame positions and retry counts instead
of just the aggregate partial-evidence flag. Historical manifests cannot reconstruct
failure details that were never saved.
