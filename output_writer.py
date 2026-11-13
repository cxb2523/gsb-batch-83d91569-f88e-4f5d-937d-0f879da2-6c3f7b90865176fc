"""
output_writer.py
-----------------
Shared row model + JSON/CSV writers used by all three engines.

Three modes, one row shape
--------------------------
    --mode listings  work.mercor.com/explore           the marketplace index
    --mode job       work.mercor.com/jobs/{id}/{slug}  one marketplace listing
    --mode careers   www.mercor.com/careers            Mercor's OWN hiring

`listings` and `job` are two views of one thing, keyed by the same
`listingId`, which is what lets a `job` run enrich a `listings` run and what
`diff_runs.py` joins on. What they populate is genuinely different, and that
is why `data_source` is a COLUMN rather than a sidecar field: an `explore`
row carries the site's category (`domain`), the slot counters and
`posted_at`; a `detail` row carries `company_website`,
`company_description`, `available_spots`, `active_contractors_count` and a
currency. Neither is a subset of the other.

Checked field by field on 2026-09-18, the same job read both ways: **zero
disagreements** on the 37 fields both publish. So `diff_runs.py` comparing
an `explore` run against a `detail` run is comparing like with like on every
shared column — which is exactly what `source_changed` exists to keep
honest where it is not.

`careers` is the OTHER population
---------------------------------
Mercor the marketplace sells contract work; Mercor the company hires
salaried employees, and publishes those through Ashby on a different host
with a UUID id space that shares nothing with a `list_…` id. The rows fit
this dataclass — they are job postings with a title, a pay range and a
location — but the two sets have no key in common and comparing them would
produce a diff whose every line is an artefact. So `mode` goes in the
sidecar and `diff_runs.py` REFUSES a cross-population comparison, as
any repo that reads more than one kind of thing has to.

The row is `JobPosting` and not `Product`
-----------------------------------------
Every shop repo in this family names its row `Product` and keeps the
commerce columns even where they are null, because on a shop a null price
is a fact worth recording. Mercor sells no products: there is no price, no
currency on a product, no discount, no stock and no brand, and six columns
null on every row of every run of every mode is a set of columns that
should not exist. `wellfound-scraper`, `bbb-scraper` and `quora-scraper` are the
precedent.

What a job board has where a shop has a price is a RANGE, which is two
columns and not one, plus a PERIOD that is not always hourly — measured
across the 390 listings on 2026-09-18: hourly 347, per-task 31, one-time 9,
yearly 3. `rate_min`/`rate_max`/`rate_currency`/`rate_period` are those four
facts, and the careers route's own rendered string is kept verbatim beside
them in `compensation` so a consumer can always see what was published.

What IS kept, byte-identical and in order, is the family prefix — `source`,
`scraped_at`, `url`, `sku`, `title` — so one column name works across the
family and a consumer reading several of these repos reads the same first
five columns in the same order.

Twenty-one columns that are absent, and the measurement
-------------------------------------------------------
The `/explore` record has 50 fields and 21 of them hold ONE distinct value
across all 390 listings: `matchQuality`, `submittedOn`, `userSimilarityScore`,
`searchSimilarityScore`, `applicationStepsCompleted`, `applicationStepsPending`,
`prequalifiedListing`, `isRecommended`, `hourlyPayRate`, `companyLogo`,
`companyAlias`, `interviewDuration`, `interviewScheduleLink`,
`interviewSchedulingEnabled`, `disableApplications`, `autoRedirectToApply`,
`isPrivate`, `isMostRecent`, `deletedAt`, `offersEquity` and `status`
itself on that route. Most are logged-in personalisation that an anonymous
fetch always sees as null or zero.

They are not columns. A column that is null on every row of every run
should not exist, and removing one needs the measurement written down so
someone can add it back with a better one. Two exceptions are carried
anyway and the reason is in each field's comment: `status`, because a
DETAIL page can publish a closed listing where `/explore` only ever shows
active ones, and `offers_equity`, because the careers route publishes real
equity components on 98 of 145.

`rating` is absent, and that one is a measurement too
-----------------------------------------------------
Mercor publishes no rating, score or review count for a listing, a company
or a contractor on any route this scraper reads: zero such fields across
390 listing records, 7 detail captures and 108 careers records in the
2026-09-18 captures. The nearest thing is `userSimilarityScore`, which is 0
on every anonymous row and is a match score for the logged-in viewer rather
than a rating of anything. A `rating` column would be null on every row of
every run.

Everything below the dataclass is row-class-agnostic: pass `row_cls` so an
empty CSV still gets the right header for the mode that produced it.
"""

import contextlib
import csv
import json
import os
import tempfile
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timezone
from typing import Optional, List, Set, Sequence, Any, Type


# The site a row came from. Mercor serves the marketplace on
# `work.mercor.com` and the corporate site on `www.mercor.com`; this column
# names the SITE rather than the host, so one value covers both and a
# consumer reading several repos in this family reads the same shape. Which
# host a given row came from is recoverable from `url`.
SOURCE_DEFAULT = "mercor.com"


def utc_now() -> str:
    """The run's timestamp, as a UTC ISO-8601 string with a `Z`.

    One helper so every row in a run can be given the SAME stamp by the
    caller rather than each row calling the clock. Rows from one page that
    disagree in `scraped_at` by a few milliseconds make a diff noisier for
    no information.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class JobPosting:
    """One job posting — a marketplace listing, or a role at Mercor itself.

    The family prefix — `source`, `scraped_at`, `url`, `sku`, `title` — is
    byte-identical and in this order across every repo in the family, so a
    consumer reading several of them reads the same first five columns.
    Everything after it is Mercor's.
    """

    source: str = SOURCE_DEFAULT
    scraped_at: str = ""
    # The absolute URL for this posting. A marketplace row points at
    # `work.mercor.com/jobs/{listingId}/{slug}`; a careers row points at
    # Ashby, because that is where the site itself links.
    url: str = ""
    # `listingId` ("list_AAABoLBL8QQESPRVXb9Aybnn") on a marketplace row,
    # Ashby's UUID on a careers row. Stable across the listing and the
    # detail page, which is what lets `--mode job` enrich a `--mode
    # listings` run and what `diff_runs.py` joins on. The two id spaces
    # never collide, so `sku` is unique within a run of any single mode.
    sku: Optional[str] = None
    title: Optional[str] = None

    # ---- what kind of posting ------------------------------------------
    # "standard" (335) or "evergreen" (55). An evergreen listing is an
    # always-open talent pool rather than a dated opening, and it is worth
    # a column because the site's OWN `ItemList` JSON-LD omits every one of
    # them — see product_parser's docstring.
    listing_type: Optional[str] = None
    # "active" on every /explore row, because that route shows nothing
    # else. Carried anyway: a DETAIL page can publish a listing under
    # `closedListing`, so this column is the only place a closed listing
    # could ever announce itself.
    status: Optional[str] = None
    # `listingDomain` — Mercor's own category for the work. 12 distinct
    # values across the 390 listings, the largest being "Life, Physical,
    # and Social Science" (82) and "Language and Audio" (45). Marketplace
    # only; the detail route does not publish it.
    domain: Optional[str] = None
    # Careers only. Ashby's org chart: 57 of 108 roles are Engineering.
    department: Optional[str] = None
    team: Optional[str] = None

    # ---- the work -------------------------------------------------------
    # Markdown on a marketplace row, HTML converted to text on a careers
    # row. `data_source` says which.
    description: Optional[str] = None
    # The time commitment asked for: hourly 228, part-time 104, task-based
    # 35, full-time 23. A DIFFERENT axis from `rate_period` below, which is
    # how the pay is quoted — a task-based commitment can still be paid an
    # hourly rate, and 31 listings are.
    commitment: Optional[str] = None
    # schema.org's vocabulary (CONTRACTOR / PART_TIME / FULL_TIME) on a
    # detail row, Ashby's (FullTime / Temporary) on a careers row. Null on
    # an /explore row: that payload carries no employment type in any form.
    employment_type: Optional[str] = None
    hours_per_week: Optional[int] = None

    # ---- pay ------------------------------------------------------------
    rate_min: Optional[float] = None
    rate_max: Optional[float] = None
    # Read, never defaulted. Null on every /explore row because that
    # payload states no currency anywhere; USD on 40 of 40 sampled detail
    # pages; USD or GBP on a careers row. A null here means the route did
    # not say, not that the job is unpaid.
    rate_currency: Optional[str] = None
    # hourly / per-task / one-time / yearly on a marketplace row. Taken
    # from the record's own `payRateFrequency` and NOT from the JSON-LD's
    # `unitText`, which said HOUR on 3 of 40 sampled pages whose pay is
    # per-task.
    rate_period: Optional[str] = None
    # The careers route's own rendered summary, verbatim — including the
    # "• Multiple Ranges" suffix that says the numbers span two seniority
    # bands. Null on a marketplace row, which renders no such string.
    compensation: Optional[str] = None
    # True only where the posting publishes an equity component. False
    # means it published compensation and no equity in it; null means it
    # published no compensation at all. Constant False across the 390
    # marketplace listings and real on the careers route (98 equity
    # components of 145).
    offers_equity: Optional[bool] = None
    # What Mercor pays for a successful referral, in the same currency as
    # the rate. Marketplace only.
    referral_amount: Optional[float] = None

    # ---- where ----------------------------------------------------------
    # Free text as published — "France / Europe (remote)", "San Francisco".
    location: Optional[str] = None
    # remote (375) / hybrid (14) / onsite (1) on a marketplace row;
    # Ashby's OnSite / Remote / Hybrid on a careers row.
    work_arrangement: Optional[str] = None
    # ISO-3166 alpha-3 codes a candidate may WORK from. Non-empty on 134 of
    # 390 listings; an empty list and a null both mean "no restriction
    # stated", so both are written as null rather than putting a
    # distinction in the data that is not in the site.
    eligible_locations: Optional[List[str]] = None
    # Where a candidate may RESIDE, which the site states separately and
    # which is not the same question. Non-empty on 45 of 390.
    eligible_residence_locations: Optional[List[str]] = None

    # ---- the company ----------------------------------------------------
    # Non-null on 99 of 390 listings. Mercor runs much of its marketplace
    # on behalf of unnamed clients, so a null here is usual and is not a
    # parsing failure — read it together with the flag below.
    company_name: Optional[str] = None
    # The site's own "may I show this client's name" flag: False on 291 of
    # 390, True on 99. Where a site publishes a
    # should-I-show-this flag, use it rather than inferring from the value.
    # A null `company_name` beside False is WITHHELD; beside True it would
    # be genuinely unset, and is worth looking at.
    company_brand_visible: Optional[bool] = None
    # Detail route only — neither appears in the /explore payload.
    company_website: Optional[str] = None
    company_description: Optional[str] = None

    # ---- how much work is left ------------------------------------------
    # Mercor publishes how many slots a listing still has, which is the
    # nearest thing this site has to stock. The two routes count it
    # differently and neither is wrong: /explore states `remainingSlots`
    # and `suppliedSlots` (both non-null on 337 of 390), a detail page
    # states `availableSpots` and `activeContractorsCount`. They are kept
    # as four columns rather than folded into two, because folding them
    # would put this parser's opinion about which is authoritative into the
    # data.
    remaining_slots: Optional[int] = None
    supplied_slots: Optional[int] = None
    available_spots: Optional[int] = None
    active_contractors_count: Optional[int] = None
    recent_candidates_count: Optional[int] = None

    # ---- dates ----------------------------------------------------------
    # Both normalised to UTC ISO-8601 with a `Z`, from three different
    # spellings across the three routes. `validThrough` from the JSON-LD is
    # deliberately NOT a column: it read as the render date plus thirty
    # days on 40 of 40 sampled pages and says nothing about the listing.
    posted_at: Optional[str] = None
    created_at: Optional[str] = None

    # ---- links ----------------------------------------------------------
    # Ashby's application URL. Careers only; a marketplace listing is
    # applied to on the listing page itself.
    apply_url: Optional[str] = None

    # ---- provenance -----------------------------------------------------
    # Which route this row was read out of: `explore`, `detail` or
    # `careers`. Provenance of a value goes in a column, and
    # `diff_runs.py` reports a difference that comes with a `data_source`
    # difference as `source_changed` rather than as a real change, so two
    # runs that differ only in which route they read do not read as the
    # site having changed.
    data_source: Optional[str] = None
    page: Optional[int] = None
    position: Optional[int] = None


# Row classes by --mode, so an engine maps its mode to a schema in one
# place. All three are JobPosting here; the mapping exists so adding a mode
# later is a one-line change rather than a search for every place that
# assumed it.
ROW_CLASS_BY_MODE = {"listings": JobPosting, "job": JobPosting,
                     "careers": JobPosting}

# Modes whose rows are one-per-sku, and therefore safe to dedupe on `sku`
# and to hand to diff_runs.py. All three qualify: `/explore` names each
# listing exactly once (390 records, 390 distinct `listingId`s measured
# 2026-09-18), a detail page IS one listing, and the careers payload names
# each Ashby role once (108 records, 108 distinct ids).
#
# Because `/explore` has no second page there is no adjacent-page overlap
# on this site at all, so ANY drop during dedupe means something unexpected
# — either the site started repeating rows, or a `--mode job` run was
# handed the same URL twice. That is why the drop count is logged rather
# than silently applied.
UNIQUE_BY_SKU_MODES = ("listings", "job", "careers")


def dedupe_by_key(rows: Sequence[Any], seen: Set[str], key: str = "sku") -> List[Any]:
    """Drop rows whose key already appeared earlier in this same run.

    `seen` is mutated in place, so callers thread the same set across pages —
    a repeated page then re-parses without duplicating its rows into the
    final output.

    On Mercor ANY drop here is unexpected, which is why the count is logged
    rather than quietly applied. `/explore` names each listing exactly once
    (390 records, 390 distinct ids, measured 2026-09-18) and has no second
    page to overlap with; `--mode job` fetches a de-duplicated enumeration,
    one URL per listing. So unlike a site that paginates over one entity and
    lists another, there is no legitimate source of duplicates at all.

    A non-zero count therefore means one of two things worth seeing: the
    site started repeating rows, or two workers were handed the same URL.
    The function stays regardless — it is the backstop that keeps the output
    clean, and "should never fire" is a poor reason to remove a guard that
    costs one pass over a list.

    A row with no key is always kept: there is nothing to check a duplicate
    against, and dropping it would be a silent data loss rather than a
    duplicate removal.

    All three of this repo's modes are one row per `sku`, so `key` is never
    overridden here — the parameter exists because the rest of the family
    shares this function and one of them needs it.
    """
    fresh = []
    for r in rows:
        val = getattr(r, key, None)
        if val is None or val not in seen:
            if val is not None:
                seen.add(val)
            fresh.append(r)
    return fresh


# Kept under its old name: the engines and smoke tests in this family all
# call it, and a listing run does dedupe by sku.
def dedupe_by_sku(rows: Sequence[Any], seen: Set[str]) -> List[Any]:
    return dedupe_by_key(rows, seen, key="sku")


# CSV cannot hold a list. Joining with " | " keeps the cell readable in a
# spreadsheet and round-trippable by splitting on the same separator; the
# JSON output keeps the real list, so nothing is lost for a consumer that
# wants structure. `repr()` of a Python list (the default if this is not
# handled) is neither readable nor parseable by anything but Python.
LIST_CSV_SEPARATOR = " | "


def _csv_value(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return LIST_CSV_SEPARATOR.join(str(x) for x in v)
    return v


@contextlib.contextmanager
def _atomic(path: str, newline: Optional[str] = None):
    """Write to a temporary file beside `path`, then rename over it.

    `open(path, "w")` truncates before a single byte is written, so a crash,
    a kill or a full disk halfway through `json.dump` leaves a SHORTER file
    where a complete one was: the previous good run is destroyed by the
    attempt to replace it rather than by its outcome. Measured here before
    the fix: a write that failed on an unserialisable row left a 1,042-byte
    `out.json` as 96 bytes of invalid JSON.

    The temporary file goes in the SAME directory on purpose: `os.replace`
    is only atomic within one filesystem, and a temp file under /tmp can be
    on another one, where the rename degrades to an interruptible copy.
    `fsync` before the rename makes the content durable, not merely visible.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline=newline, dir=directory,
        prefix=os.path.basename(path) + ".", suffix=".tmp", delete=False)
    try:
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        # `NamedTemporaryFile` creates the file 0600 and a rename keeps that
        # mode, so without this every output would be readable by its owner
        # alone. An existing target keeps its own mode (someone may have set
        # it on purpose); a new one gets what `open()` would have given it,
        # which honours the umask. Never a flat 0644: that narrows 0664
        # under umask 002.
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(handle.name, mode)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


# A spreadsheet treats a cell beginning with one of these as a FORMULA, not
# as text, and every string in a row here (job titles, descriptions,
# company names, locations) was written by a third party rather than by this
# code. `=HYPERLINK(...)`, `+cmd|...` and `@SUM(...)` are the classic shapes;
# a leading tab or newline is stripped by some readers, exposing whatever
# follows it.
CSV_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r", "\n")

# Prefixed to a cell that would otherwise be read as a formula. Excel, Google
# Sheets and LibreOffice treat the apostrophe as "the rest is text"; a
# consumer parsing the CSV with `csv` sees it, which is why the count goes in
# the sidecar rather than staying silent.
CSV_FORMULA_ESCAPE = "'"


def _csv_escape(v: Any):
    """Neutralise a formula-shaped cell. Returns (value, was_escaped).

    Only STRINGS are touched: escaping a number would turn a negative
    number into the text `'-5.0` and break every calculation over the
    column. CSV only — the JSON output keeps the site's bytes as served, and
    `csv_cells_escaped` in the sidecar declares that the two differ.
    """
    if isinstance(v, str) and v.startswith(CSV_FORMULA_LEADS):
        return CSV_FORMULA_ESCAPE + v, True
    return v, False


def write_json(rows: Sequence[Any], path: str) -> None:
    with _atomic(path) as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


def write_csv(rows: Sequence[Any], path: str, row_cls: Type = JobPosting) -> int:
    """Write the CSV; return how many cells were formula-escaped."""
    # An empty result still gets the header row. A zero-byte file makes a
    # consumer fail on read (no columns to parse) instead of reading a valid
    # table with zero rows — and "an empty result is still a well-formed
    # result" is the same principle as `save` refusing to overwrite good data.
    #
    # The header comes from `row_cls`, not from the first row, so an empty
    # run still writes the columns of the mode that produced it.
    fieldnames = [f.name for f in fields(row_cls)]
    escaped = 0
    # `newline=""` is the csv module's documented requirement and has to
    # survive the move to a temp file, or every row gains a stray CR on
    # Windows.
    with _atomic(path, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = {}
            for k, v in asdict(r).items():
                # Escape AFTER `_csv_value`: a list joined into one cell is
                # text too, and its first element can be formula-shaped.
                value, was_escaped = _csv_escape(_csv_value(v))
                row[k] = value
                escaped += was_escaped
            writer.writerow(row)
    return escaped


# Exit code used when a run completes but produced nothing. Distinct from 1
# (crash) so a caller can tell "ran, found nothing" from "blew up".
EXIT_NO_PRODUCTS = 4

# Exit code for a run blocked by a bot-check/challenge page before parsing
# even started — distinct from EXIT_NO_PRODUCTS so a caller can tell "the
# search genuinely matched nothing" from "something stood between us and the
# content". See product_parser.detect_bot_challenge.
#
# On Mercor this code does NOT cover a page that simply holds no records.
# That answers HTTP 200 with a payload carrying an empty set, and it is
# EXIT_NO_PRODUCTS: the request was served exactly as asked and has nothing
# in it. Reporting it as blocked would send a user hunting for a proxy
# problem that does not exist.
#
# Nor does it cover a 404, which is its own state (`not_found`): a listing
# taken down between the sitemap being read and its page being fetched is
# an ordinary event in `--mode job`, and it is not a block.
#
# What EXIT_BLOCKED would mean here is unmeasured, and saying so is more
# use than inventing a description. Mercor is fronted by Cloudflare but
# refused nothing on 2026-09-18: eighteen candidate challenge markers across
# seven captures all zero, and identical 200s from curl, from
# python-requests and from an empty User-Agent, to a bare Hetzner datacentre
# address. This scraper has never seen this site block it, so there is no
# refusal shape to document. If a run reports exit 3, the saved debug HTML
# is the evidence, and it is new.
EXIT_BLOCKED = 3

# Exit code for a run that gathered SOME rows and then stopped early — a
# page-load timeout, a 503 throttle, or a challenge on page 3 of 10. The
# output file is still written (throwing away three good pages would be
# worse), but it is not a complete picture, and a consumer that cannot tell
# the difference will read the pages that were never fetched as products that
# disappeared from the catalogue. See write_run_meta.
# A REMOTE service failed — the Scraping Browser refusing the connection
# (`profile_locked` is the common one: a profile allows a single live
# connection), or the Scraper API answering an error. Distinct from 1 (a
# crash in this code) and from 2 (bad usage) because it means "try again, or
# use a different profile", not "there is a bug here". Defined once, here,
# because the browser engines and scraper_api_client.py both return it and
# two definitions of the same code is exactly how a family's exit contract
# drifts.
EXIT_API_ERROR = 5

EXIT_PARTIAL = 6


# Exit code for a run that never GOT its pages: a navigation timeout, a dead
# or unauthenticated proxy, a DNS failure, or an edge answering with
# something that is not the page that was asked for.
#
# Distinct from EXIT_NO_PRODUCTS because those are opposite facts. Exit 4 is
# a statement about the CATALOGUE — "we asked, and the answer was nothing" —
# so handing it to a run that never reached the site tells a pipeline the
# listing is empty when nothing was read at all.
#
# 5 rather than a new number, and 5 rather than EXIT_PARTIAL:
#
#   * this family's contract already reserves 5 for a transport failure
#     (scraper_api_client has used it for a remote API error since it was
#     written), so this needs no new code and no per-repo table for a caller
#     driving more than one of these scrapers;
#   * EXIT_PARTIAL (6) means "some rows were gathered and the output is
#     incomplete". A run holding nothing writes no output at all, so a
#     consumer that reads the file on a 6 finds either nothing or the
#     PREVIOUS run's good data, which `save` deliberately does not
#     overwrite. Exit 5 promises no file.
#
# Deliberately NOT applied when rows WERE gathered: a timeout on page 7 of
# 10 is a partial run (exit 6, output written), which is already right. This
# decides only what a run holding nothing reports.
EXIT_FETCH_FAILED = 5


def write_run_meta(out_prefix: str, meta: dict) -> str:
    """Write a run-metadata sidecar next to the output, return its path.

    Deliberately a separate `<out>.meta.json` rather than columns on every
    row: this describes the RUN, not the product, and repeating it across
    every row would both bloat the output and change the schema every
    consumer of this project already parses.

    diff_runs.py reads it to refuse a comparison between runs that are not
    both complete, and between runs of different `mode`.
    """
    path = f"{out_prefix}.meta.json"
    # Atomic for the same reason as the rows, and more urgently: this is the
    # file a consumer BRANCHES on, so a truncated sidecar beside good rows
    # reads as a broken run over data that is fine.
    with _atomic(path) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[+] Wrote run metadata -> {path} (status={meta.get('status')})")
    return path


def run_meta(status: str, stop_reason: str, pages_requested: int,
             pages_completed: int, start_url: str, final_url: str,
             products: int, pages_failed: Optional[List[int]] = None,
             mode: str = "listing", source: str = SOURCE_DEFAULT,
             extra: Optional[dict] = None) -> dict:
    """Build the metadata dict for a finished run.

    `status` is the field a consumer branches on:
      complete — every requested page was fetched, or the site's own
                 pagination genuinely ran out (nothing more existed to get)
      partial  — rows were gathered, then the run stopped early
      failed   — nothing was gathered at all

    `mode` and `source` are recorded because `mode` is not implied by the
    repo: the same output prefix can hold a listings run, a job run or a
    careers run, and those populate different columns — a listings row has
    the site's `domain` and its slot counters, a job row has the company
    website and a currency, a careers row has a department and an Ashby
    apply URL. `diff_runs.py` refuses a pair whose modes or sources differ,
    which matters more here than on most sites in this family: a careers run
    and a marketplace run have NO ids in common at all, so a diff of the two
    would report every row as both added and removed.

    `source` is `mercor.com` on every row of every run. The site is served
    on two hosts (`work.mercor.com` and `www.mercor.com`) and this column
    names the SITE rather than the host, so one value covers both; which
    host a row came from is recoverable from `url`. It is kept because
    consumers read these columns by name across the family.

    `extra` carries facts about the run that are not about any single row.
    Mercor publishes no catalogue total on any route, so unlike a site that
    states `totalResults` there is no figure to copy — what goes in instead
    is the run's OWN coverage arithmetic: `records_in_payload` and
    `urls_in_itemlist` for a listings run (390 and 326 on 2026-09-18, and
    the gap is why the parser reads the React Query cache), and
    `jobs_enumerated`/`jobs_fetched` for a job run.

    That is the only honest way to say what a run holds here, because
    "complete" and "exhaustive" come apart on this site: a `--mode listings`
    run fetches everything `/explore` serves — genuinely complete — while
    `/explore` held 390 of the 462 listings the sitemap and the index
    enumerate between them. Nothing in the row count reveals that.

    `pages_failed` lists the pages that did not yield data, by number.
    `pages_completed` alone was enough only while pages were fetched strictly
    in order, where "3 of 10 completed" could only mean 1-2-3: a count is not
    a description once pages can be fetched independently and page 3 can fail
    while 4 and 5 succeed. Recording the numbers keeps the sidecar honest
    about WHICH part of the catalogue is missing, not just how much.
    """
    meta = {
        "source": source,
        "mode": mode,
        "status": status,
        "stop_reason": stop_reason,
        "pages_requested": pages_requested,
        "pages_completed": pages_completed,
        "pages_failed": pages_failed or [],
        # Named "products" even though these are job listings, and kept that
        # way deliberately: every repo in this family writes this key, and a
        # consumer reading several of them reads one sidecar shape.
        # quora-scraper made the same call for answers. The row TYPE is
        # `mode` plus `source`, which are right beside it.
        "products": products,
        "start_url": start_url,
        "final_url": final_url,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        # Merged rather than nested under a key, so a consumer reads
        # `records_in_payload` at the top level beside `products`. Run fields win a
        # name collision: a caller cannot accidentally overwrite `status`.
        meta.update({k: v for k, v in extra.items() if k not in meta})
    return meta


def save(rows: Sequence[Any], out_prefix: str, fmt: str,
         allow_empty: bool = False, row_cls: Type = JobPosting,
         stats: Optional[dict] = None) -> int:
    """Write JSON/CSV and return a process exit code.

    Returns 0 when rows were written, EXIT_NO_PRODUCTS when there were none.
    Callers are expected to exit with it.

    On zero rows, nothing is written at all unless `allow_empty`. Two reasons,
    and a live run demonstrated both. A page-load timeout produced
    `Saved 0 jobs -> out.json` and exit 0: a two-byte `[]` that a
    consuming pipeline reads as a successful run with no stock. Worse, if the
    file already held a good result from an earlier run, that result is now
    gone — the failure destroyed the last known good data. So an empty result
    leaves the previous file intact and says why.

    `allow_empty=True` is for the legitimate case: a filter that genuinely
    matches nothing, where an empty file is the answer.
    """
    if not rows and not allow_empty:
        print(f"[!] 0 jobs — refusing to write {out_prefix}.json/.csv, so an "
              f"earlier good result isn't overwritten with an empty one. "
              f"Pass --allow-empty if an empty result is the expected answer.")
        return EXIT_NO_PRODUCTS

    if fmt in ("json", "both"):
        write_json(rows, f"{out_prefix}.json")
        print(f"[+] Saved {len(rows)} jobs -> {out_prefix}.json")
    if fmt in ("csv", "both"):
        escaped = write_csv(rows, f"{out_prefix}.csv", row_cls=row_cls)
        print(f"[+] Saved {len(rows)} jobs -> {out_prefix}.csv")
        # Reported through `stats` because this function's return IS the
        # exit code. The caller threads it into the sidecar.
        if stats is not None:
            stats["csv_cells_escaped"] = escaped
        if escaped:
            print(f"[!] {escaped} CSV cell(s) began with a formula character "
                  f"and were prefixed with {CSV_FORMULA_ESCAPE!r} so a "
                  f"spreadsheet reads them as text. The JSON output is "
                  f"unchanged — see csv_cells_escaped in the sidecar.")
    return 0 if rows else EXIT_NO_PRODUCTS


# Stop reasons that mean the run saw everything there was to see. Anything
# else ended the page loop early, so the result is only a partial view.
#
# "no_new_products" belongs here and "pagination_exhausted" is kept for the
# engines that still stop on a missing next-link: the first is a property of
# the DATA (a page contributed nothing not already seen, so the listing is
# over), while the second is a property of a CSS SELECTOR and is therefore
# the weaker signal — a renamed attribute looks identical to a short
# catalogue.
#
# On Mercor there is no third signal, and that is not a gap: there is
# nothing for one to do. `/explore` and `/careers` each hold their whole
# result set in one response, so a run cannot walk off an end that does not
# exist, and `--mode job` plans from a finite enumerated list rather than
# from a `?page=N` convention — asking for more pages than the list holds
# is capped by `page_flow.pages_to_plan`, not discovered by overshooting.
#
# So the stop reasons a sibling repo needs for that — "page_cap_reached"
# and "page_echo_mismatch" — are carried in the tuple below for the family's
# shared vocabulary and cannot fire here. They are left in rather than
# pruned so that all repos in this family name the same states.
#
# "single_page_route" is complete by construction AND by measurement:
# `/explore` and `/careers` each serve their whole result set in one
# response, and every pagination parameter tried on `/explore` returned a
# byte-identical payload (2026-09-18). A run that stopped after one fetch
# fetched the whole route.
#
# Note what it does NOT mean: `/explore` holds 390 of the 462 listings
# Mercor publishes, so a complete `--mode listings` run is still a slice.
# Complete and exhaustive are different words — and the
# sidecar records both figures so a consumer is not left inferring one from
# the other.
COMPLETE_STOP_REASONS = ("completed", "pagination_exhausted", "no_new_products",
                         "page_cap_reached", "page_echo_mismatch",
                         "single_page_route")


def finish_run(rows: Sequence[Any], out_prefix: str, fmt: str,
               allow_empty: bool, *, blocked: bool, stop_reason: str,
               pages_requested: int, pages_completed: int,
               start_url: str, final_url: str,
               pages_failed: Optional[List[int]] = None,
               mode: str = "listing", source: str = SOURCE_DEFAULT,
               extra: Optional[dict] = None) -> int:
    """Write output + the run-metadata sidecar; return the exit code.

    Shared by all three browser engines so the status/exit-code mapping
    cannot drift between them.

    The metadata sidecar is written when the row file was written, and for
    a blocked or failed `--allow-empty` run only when no earlier row file
    exists at that path. Otherwise a failed run would leave a "status": "failed" sidecar next to
    the previous run's still-intact good output (which `save` deliberately
    does not overwrite) — the two files would contradict each other, and
    diff_runs.py would refuse to compare data that is in fact fine.
    """
    # Completeness is decided by the reason AND by the evidence. A named
    # list of stop reasons cannot cover a failure recorded somewhere else,
    # and `pages_failed` is somewhere else: a run whose loop ended for a
    # COMPLETE reason while individual pages failed reported exit 0 and
    # `status: complete` with a non-empty `pages_failed` in the same
    # sidecar — a file that contradicts itself, and a pipeline branching
    # on `status` reading a short run as a whole one.
    #
    # Found by a third-party audit of a sibling repo and measured across
    # the family by CALLING each `finish_run` rather than grepping for the
    # fix: 28 of 32 repos behaved this way. Same shape as the exit-code
    # unification this file already carries — a rule keyed on a list of
    # names has a hole for every name nobody added to it.
    complete = stop_reason in COMPLETE_STOP_REASONS and not pages_failed
    row_cls = ROW_CLASS_BY_MODE.get(mode, JobPosting)
    stats: dict = {}
    # `--allow-empty` writes an empty file ONLY for a genuine empty result:
    # the run finished, nothing stood in its way, and the answer was
    # nothing. A blocked or failed run is not an answer, so the flag never
    # writes an empty file over an earlier good result for one, and never
    # turns its exit code into 4.
    genuine_empty = not rows and complete and not blocked
    failure_sidecar = False
    if rows or genuine_empty:
        rc = save(rows, out_prefix, fmt, allow_empty=allow_empty,
                  row_cls=row_cls, stats=stats)
        wrote_output = bool(rows) or allow_empty
    else:
        rc = EXIT_FETCH_FAILED   # replaced below by blocked/failed
        wrote_output = False
        kept = [f"{out_prefix}{ext}" for ext in (".json", ".csv")
                if os.path.exists(f"{out_prefix}{ext}")]
        if kept:
            print(f"[!] Nothing was written: this run was "
                  f"{'blocked' if blocked else 'a failure'} ({stop_reason}), so "
                  f"the earlier output ({', '.join(kept)}) and its sidecar "
                  f"are kept as they were.")
        elif allow_empty:
            # Nothing to preserve, so the sidecar can say what happened
            # without contradicting an earlier good result. No row file.
            failure_sidecar = True
            print(f"[!] --allow-empty writes an empty file only for a "
                  f"genuine empty result. This run was "
                  f"{'blocked' if blocked else 'a failure'} ({stop_reason}): no "
                  f"row file was written, only {out_prefix}.meta.json.")
    if stats:
        # Housekeeping goes UNDER the caller's `extra`: a name collision must
        # never drop site data in favour of a count.
        extra = {**stats, **(extra or {})}

    if wrote_output or failure_sidecar:
        if rows:
            status = "complete" if complete else "partial"
        elif genuine_empty:
            # A finished run whose answer was nothing: complete, and empty.
            status = "empty"
        else:
            status = "blocked" if blocked else "failed"
        write_run_meta(out_prefix, run_meta(
            status=status, stop_reason=stop_reason,
            pages_requested=pages_requested, pages_completed=pages_completed,
            pages_failed=pages_failed, mode=mode, source=source,
            start_url=start_url, final_url=final_url, products=len(rows),
            extra=extra))

    if not rows:
        # Nothing gathered at all, and WHY decides the code. The three
        # outcomes are different facts and a pipeline branches on them
        # (blocked is not empty is not "never reached"):
        #
        #   blocked            something stood between the run and the content
        #   did not complete   we never got the pages — a dead proxy, a load
        #                      timeout, an edge serving something else
        #   completed          we asked, and the answer was nothing
        #
        # Keyed on `not complete` rather than on a list of stop reasons, on
        # purpose: a list cannot cover a reason nobody has added to it yet,
        # so a new one falls silently through to "the catalogue is empty" —
        # which is the defect this branch exists to prevent.
        if blocked:
            return EXIT_BLOCKED
        if not complete:
            print(f"[!] Nothing was gathered and the run did not finish "
                  f"({stop_reason}) — exit {EXIT_FETCH_FAILED}, NOT an empty "
                  f"result (exit {EXIT_NO_PRODUCTS}). Nothing can be "
                  f"concluded about the catalogue from this run.")
            return EXIT_FETCH_FAILED
        return rc
    if not complete:
        print(f"[!] Partial run: stopped after {pages_completed} of "
              f"{pages_requested} page(s) ({stop_reason}). The output holds "
              f"what was gathered, but it is NOT a complete view — see "
              f"{out_prefix}.meta.json.")
        return EXIT_PARTIAL
    return rc
