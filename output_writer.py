"""
output_writer.py
-----------------
Shared row model + JSON/CSV writers used by all three scrapers.

Three modes, one row shape
--------------------------
    --mode role   /role/{role}, /role/r/{role}, /role/l/{role}/{location}
    --mode jobs   /jobs                          the discovery feed
    --mode job    /jobs/{id}-{slug}              one job, described fully

All three yield the SAME class, because they are three views of one thing.
The leaf Wellfound publishes is a JOB AT A COMPANY: the landing routes and
the feed are two ways of selecting them, and a detail page is one of them
described more fully. So there is one dataclass here, and `diff_runs.py`
can compare a `role` run against a `job` run on the columns both populate.

What they populate is genuinely different, though, and that is why
`data_source` is a column rather than a sidecar field. A landing row comes
out of the Next.js Apollo cache (`data_source="apollo"`) and carries the
company's badges, size and tagline, the equity split and the full
description. A detail row comes out of a schema.org `JobPosting`
(`data_source="jsonld"`) and carries a stated salary PERIOD, benefits and
an industry, but no equity — schema.org has no expression for it. Neither
is a subset of the other. See `product_parser.py`'s docstring for the
measurement, including the check that where both publish a salary they
agree: job 4697947 is 100000-180000 USD in both.

The row is `JobPosting` and not `Product`
-----------------------------------------
Every shop repo in this family names its row `Product` and keeps the
commerce columns even where they are null, because on a shop a null price
is a fact worth recording. Wellfound is a job board: it has no price, no
currency on a product, no discount, no stock and no brand, and six columns
null on every row of every run of every mode is a schema that must not
exist. `bbb-scraper` and `quora-scraper` are the precedent.

What a job board has where a shop has a price is a RANGE, which is two
columns and not one, plus an equity range that no shop has at all. Those
are `salary_min`/`salary_max` and `equity_min`/`equity_max`, and the site's
own rendered string is kept verbatim beside them in `compensation` so a
consumer can always see what was published.

What IS kept, byte-identical and in order, is the family prefix — `source`,
`scraped_at`, `url`, `sku`, `title` — so one column name works across the
family and a consumer reading several of these repos reads the same first
five columns in the same order.

`rating` is absent, and that one is a measurement
-------------------------------------------------
Wellfound publishes no rating for a job or for a company on any route this
scraper reads: 0 rating fields across 432 job records and 210 company
records in the 2026-09-17 captures. The nearest thing is a company BADGE
("Highly Rated", "Top Responder"), which is a label and not a scale, and
those are in `company_badges`. A `rating` column would be null on every row
of every run.

Everything below the dataclass is row-class-agnostic: pass `row_cls` so an
empty CSV still gets the right header for the mode that produced it.
"""

import contextlib
import csv
import json
import tempfile
import os
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timezone
from typing import Optional, List, Set, Sequence, Any, Type


# The hostname a row came from. Wellfound serves one host with no
# per-country TLD and no locale segment, so this column is
# "wellfound.com" on every row of every run. It is kept because the
# family's schema has it in this position and consumers read the
# columns by name across repos.
SOURCE_DEFAULT = "wellfound.com"


@dataclass
class JobPosting:
    """One job listing at one company.

    The family prefix — `source`, `scraped_at`, `url`, `sku`, `title` — is
    byte-identical and in this order across every repo in the family, so a
    consumer reading several of them reads the same first five columns.
    Everything after it is Wellfound's.

    The commerce columns the shop repos carry (`price`, `currency`,
    `discount_pct`, `in_stock`, `brand`) are absent rather than null: a job
    board has none of them, and six columns null on every row of every run
    is a schema that must not exist. `bbb-scraper` and
    `quora-scraper` are the precedent. What a job board has instead of a
    price is a salary RANGE, which is two columns, not one.
    """

    source: str = SOURCE_DEFAULT
    scraped_at: str = ""
    # The absolute job URL, rebuilt as /jobs/{id}-{slug} from the row's own
    # id and slug. The listing payload carries no href of its own.
    url: str = ""
    # Wellfound's `id` for the job listing — "4697947". Stable across the
    # listing and the detail page, which is what lets `--mode job` enrich a
    # `--mode role` run and what `diff_runs.py` joins on.
    sku: Optional[str] = None
    title: Optional[str] = None

    # ---- the company ----------------------------------------------------
    company_name: Optional[str] = None
    company_slug: Optional[str] = None
    company_id: Optional[str] = None
    company_url: Optional[str] = None
    company_logo_url: Optional[str] = None
    # `companySize` arrives as an enum token ("SIZE_11_50") and is written
    # out as the human range it denotes ("11-50"). An unrecognised token is
    # passed through unchanged rather than dropped, so a new size band shows
    # up in the data instead of vanishing from it.
    company_size: Optional[str] = None
    # `highConcept` — the one-line pitch under the company name.
    company_tagline: Optional[str] = None
    # The company badges Wellfound prints on the tile, as their display
    # labels ("Actively Hiring", "Y Combinator"). 15 distinct badge names
    # were measured across the captures. Present only on the landing routes:
    # the /jobs feed's thinner `Startup` type carries none.
    company_badges: Optional[List[str]] = None

    # ---- the role -------------------------------------------------------
    job_slug: Optional[str] = None
    # "full-time" / "contract" / "internship" / "cofounder". Null on every
    # /jobs-feed row, which does not publish it.
    job_type: Optional[str] = None
    primary_role: Optional[str] = None
    years_experience_min: Optional[int] = None
    years_experience_max: Optional[int] = None
    # `liveStartAt` is a unix timestamp; written out as UTC ISO-8601 so the
    # column sorts as text and diffs cleanly.
    posted_at: Optional[str] = None

    # ---- where ----------------------------------------------------------
    locations: Optional[List[str]] = None
    remote: Optional[bool] = None
    # REMOTE / ONSITE / ONSITE_OR_REMOTE, from `remoteConfig.kind`. Absent
    # on 231 of 432 measured records, so a null here means the listing did
    # not configure it — `remote` above is the field to trust.
    remote_kind: Optional[str] = None
    wfh_flexible: Optional[bool] = None
    # Countries/regions a remote hire may sit in.
    remote_locations: Optional[List[str]] = None

    # ---- pay ------------------------------------------------------------
    # The site's own rendered string, kept verbatim beside the parsed
    # numbers so a consumer can always see what was actually published.
    compensation: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    # Null on a listing row: the string carries no period. Filled from the
    # detail page's JSON-LD, which states one. See the module docstring.
    salary_period: Optional[str] = None
    equity_min: Optional[float] = None
    equity_max: Optional[float] = None
    # False means the listing said "No equity"; null means it did not say.
    has_equity: Optional[bool] = None

    # ---- content --------------------------------------------------------
    # The full job description. Markdown on a landing row, HTML on a detail
    # row — `data_source` says which. Null on every /jobs-feed row.
    description: Optional[str] = None
    benefits: Optional[str] = None
    industry: Optional[str] = None

    # ---- provenance -----------------------------------------------------
    # Which structured source this row was read out of: `apollo` for the
    # Next.js cache on a landing or feed page, `jsonld` for a detail page's
    # JobPosting. Provenance of a value goes in a column, and
    # `diff_runs.py` reports a difference that comes with a `data_source`
    # difference as `source_changed` rather than as a real change.
    data_source: Optional[str] = None
    page: Optional[int] = None
    position: Optional[int] = None


# Row classes by --mode, so an engine maps its mode to a schema in one place.
# All three are JobPosting here; the mapping exists so adding a mode later is
# a one-line change rather than a search for every place that assumed it.
ROW_CLASS_BY_MODE = {"role": JobPosting, "jobs": JobPosting, "job": JobPosting}

# Modes whose rows are one-per-sku, and therefore safe to dedupe on `sku`
# and to hand to diff_runs.py. All three qualify: a landing page names each
# job listing once, the feed does too, and a detail page IS one job.
#
# Measured on the 2026-09-17 captures: 37 job ids on page 1 of
# /role/r/software-engineer and 45 on page 2, sharing exactly ONE id — so a
# small overlap between adjacent pages is normal on this site and a large
# one means a page was re-served. That distinction is the reason the drop
# count is logged rather than silently applied.
UNIQUE_BY_SKU_MODES = ("role", "jobs", "job")


def dedupe_by_key(rows: Sequence[Any], seen: Set[str], key: str = "sku") -> List[Any]:
    """Drop rows whose key already appeared earlier in this same run.

    `seen` is mutated in place, so callers thread the same set across pages —
    a repeated page then re-parses without duplicating its rows into the
    final output.

    On Wellfound a SMALL overlap between adjacent pages is normal and a
    large one is a symptom, which is why the drop count is logged rather
    than quietly applied. Measured 2026-09-17 on /role/r/software-engineer:
    page 1 carried 37 job ids and page 2 carried 45, sharing exactly one.
    The landing routes paginate over COMPANIES, so a company whose jobs
    straddle a page boundary contributes to both — a couple of shared ids
    is the site, thirty-seven is the server having re-served page 1.

    That re-serving is real and is why this function matters here: asking
    for `?page=48` of a 47-page listing returns HTTP 200 and page 1 again.
    `product_parser.echoed_page()` is the primary defence and stops the run;
    this is the backstop that keeps the output clean if it ever gets past.

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


# Leading characters a spreadsheet reads as the start of a formula (or, for
# TAB/CR/LF, that some importers strip to reveal one). Every string column
# here — title, company name, tagline, description, compensation — is text an
# employer typed, so a cell like `=HYPERLINK(...)` reaches the CSV verbatim
# unless it is neutralised.
CSV_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r", "\n")

# Prefixed to such a cell. Excel, Google Sheets and LibreOffice treat the
# apostrophe as "the rest of this cell is text" and do not show it; a
# consumer parsing the CSV with `csv` does see it, which is why the count goes
# in the sidecar rather than staying silent.
CSV_FORMULA_ESCAPE = "'"


def _csv_escape(v: Any) -> Any:
    """Neutralise a formula-shaped cell. Returns (value, was_escaped).

    Only STRINGS are touched: escaping a number would turn `-5` into the text
    `'-5` and break every sum over the column. CSV only — the JSON output
    keeps the site's text exactly as served, and `csv_cells_escaped` in the
    sidecar declares that the two files differ.
    """
    if isinstance(v, str) and v.startswith(CSV_FORMULA_LEADS):
        return CSV_FORMULA_ESCAPE + v, True
    return v, False


@contextlib.contextmanager
def _atomic(path: str, newline: Optional[str] = None):
    """Write to a temporary file beside `path`, then rename over it.

    `open(path, "w")` truncates before a single byte is written, so a crash,
    a kill or a full disk halfway through `json.dump` leaves a SHORTER file
    where a complete one was. That breaks the same promise `save` keeps when
    it refuses to overwrite good output with an empty result — the previous
    good run destroyed by the ATTEMPT to replace it rather than by its
    outcome.

    The sidecar is the part that matters most: `<out>.meta.json` is the file
    a consumer branches on, so a truncated one beside good rows reads as a
    broken run over data that is fine.

    Three details, each of which is wrong in the obvious version:

    * the temporary file goes in the SAME directory, because `os.replace` is
      atomic only within one filesystem and a temp file under /tmp can be on
      another, where the rename degrades to an interruptible copy;
    * `fsync` before the rename makes the content durable rather than merely
      visible, which is the difference on power loss;
    * **the MODE has to be restored.** `tempfile.NamedTemporaryFile` creates
      at 0600, so a naive port leaves every output readable only by the user
      who ran it — a scraper whose files a downstream job cannot open. An
      existing file's mode is preserved; a new one gets the process umask
      applied to 0666, which is what `open()` would have produced. Never a
      flat 0644: that would widen the file on a deliberately strict umask.
    """
    directory = os.path.dirname(os.path.abspath(path)) or "."
    try:
        mode = os.stat(path).st_mode & 0o777
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline=newline, dir=directory,
        prefix=os.path.basename(path) + ".", suffix=".tmp", delete=False)
    try:
        with handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, mode)
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def write_json(rows: Sequence[Any], path: str) -> None:
    with _atomic(path) as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


def write_csv(rows: Sequence[Any], path: str, row_cls: Type = JobPosting) -> int:
    # An empty result still gets the header row. A zero-byte file makes a
    # consumer fail on read (no columns to parse) instead of reading a valid
    # table with zero rows — and "an empty result is still a well-formed
    # result" is the same principle as `save` refusing to overwrite good data.
    #
    # The header comes from `row_cls`, not from the first row, so an empty
    # run still writes the columns of the mode that produced it.
    #
    # Returns how many cells were formula-escaped.
    fieldnames = [f.name for f in fields(row_cls)]
    escaped = 0
    with _atomic(path, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = {}
            for k, v in asdict(r).items():
                # Escaped AFTER the list join: a joined list is text too, and
                # its first element can be formula-shaped.
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
# On Wellfound this code does NOT cover a landing page that simply matched
# nothing. That answers HTTP 200 with a rendered page carrying the site's
# own "no jobs found" copy, and it is EXIT_NO_PRODUCTS: the request was
# served exactly as asked and has no jobs in it. Reporting it as blocked
# would send a user hunting for a proxy problem that does not exist.
#
# What EXIT_BLOCKED means here is Cloudflare, and Wellfound refuses in TWO
# shapes, both HTTP 403 (measured 2026-09-17):
#
#   "Security Check | Wellfound"   the branded refusal a plain HTTP client
#                                  gets: ~11 KB, the site's own styling and
#                                  logo, its name in the markup four times.
#   "Just a moment..."             Cloudflare's interstitial, which is what
#                                  a real Chromium gets instead: ~12.5 KB.
#
# Both carry `_cf_chl_opt`; NEITHER carries `challenges.cloudflare.com` or
# `cf-turnstile`, which the site's own served pages DO carry. That
# inversion is the reason `product_parser.BOT_CHALLENGE_MARKERS` does not
# use the marker the rest of this family settled on — see the counts beside
# it there.
#
# From a datacenter address the challenge never self-clears: headless and
# headful Chromium both sat on "Just a moment..." for the full wait, 0 of 1
# each. A residential exit clears every route except /company/, which stays
# 403 for a browser too. See page_flow.detect_page_state.
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
    # Atomic for the same reason as the rows, and more so: this is the file
    # a consumer branches on, so a truncated one beside good data reads as a
    # broken run over rows that are fine.
    with _atomic(path) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[+] Wrote run metadata -> {path} (status={meta.get('status')})")
    return path


ATTEMPT_META_SUFFIX = ".latest_attempt.meta.json"


def write_attempt_meta(out_prefix: str, meta: dict) -> str:
    """Write `<out>.latest_attempt.meta.json`: this attempt, whatever it got."""
    path = f"{out_prefix}{ATTEMPT_META_SUFFIX}"
    with _atomic(path) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[+] Wrote attempt metadata -> {path} (status={meta.get('status')}, "
          f"stop_reason={meta.get('stop_reason')})")
    return path


def finish_without_fetch(out_prefix: str, *, stop_reason: str,
                         pages_requested: int, start_url: str,
                         mode: str = "listing", source: str = SOURCE_DEFAULT,
                         message: str = "") -> int:
    """End a run that was stopped before anything was fetched; exit 5.

    Used by the proxy pre-check (a 407 or 402 from the proxy). The record
    goes to `<out>.latest_attempt.meta.json`, NOT `<out>.meta.json`: the
    latter describes the data file beside it, and a previous run's good
    output is still there, untouched, so overwriting its metadata with
    `status: failed` would make the pair contradict each other.
    """
    meta = run_meta(status="failed", stop_reason=stop_reason,
                    pages_requested=pages_requested, pages_completed=0,
                    start_url=start_url, final_url=start_url, products=0,
                    mode=mode, source=source)
    write_attempt_meta(out_prefix, meta)
    print(f"[!] Failed run: nothing was fetched ({stop_reason}). "
          f"{message} Any previous output and its .meta.json are untouched.")
    return EXIT_FETCH_FAILED


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
    repo: the same output prefix can hold a role run, a feed run or a job
    run, and those populate different columns — a `role` row has badges and
    equity, a `job` row has benefits and a salary period. diff_runs.py
    refuses a pair whose modes or sources differ. `source` is
    `wellfound.com` on every row of every run here, since the site has one
    host; it is kept because consumers read these columns by name across the
    family.

    `extra` carries facts about the run that are not about any single row.
    A listing run uses it for the site's OWN counts — `total_jobs`,
    `total_companies`, `per_page` and `pages_available` as the `Results`
    node reported them — and those belong to the run rather than repeated
    down a column.

    They are also the only honest way to say what a run holds, because
    Wellfound counts one thing and a consumer counts another: `pages_available`
    is a count of PAGES OF COMPANIES, twenty per page, while the rows in the
    file are jobs. /role/r/software-engineer reported 47 pages, 923 companies
    and 1,881 jobs on 2026-09-17, and its pages carried between 32 and 45 job
    rows each. Nothing in the row count reveals that, and dividing 1,881 by 47
    gives an answer that is wrong for every page.

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
        # `total_jobs` at the top level beside `products`. Run fields win a
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
        # Through `stats` rather than the return value, because the return
        # IS the exit code. The caller puts it in the sidecar.
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
# On Wellfound there is a THIRD signal and it is stronger than either,
# because it is the site's own arithmetic: every landing response states
# `pageCount`, so the end of the listing is known from page 1 rather than
# discovered by walking off it. "page_cap_reached" is that stop reason and
# it is a COMPLETE run.
#
# Walking off the end here does not fail — it LIES. `?page=48` of a 47-page
# listing answers HTTP 200 carrying page 1 again, so a run that overshot
# would re-collect the same rows for as long as it was asked to and report
# success. "page_echo_mismatch" is the stop reason for catching that: the
# server states which page it actually answered with inside the payload
# (`product_parser.echoed_page`), and a mismatch is an unambiguous
# end-of-listing rather than a heuristic. It is complete for the same reason
# `pagination_exhausted` is — everything that exists was fetched.
#
# "single_page_mode" is complete by construction: --mode job reads one page
# because one page is all there is. "single_page_listing" is the /jobs feed,
# which is served at one address only: `?page=2` on it returns the identical
# 46 job ids as page 1, so there is no second page to fetch and a run that
# stopped after one fetched the whole thing.
COMPLETE_STOP_REASONS = ("completed", "pagination_exhausted", "no_new_products",
                         "page_cap_reached", "page_echo_mismatch",
                         "single_page_mode", "single_page_listing")


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

    The metadata sidecar is written when the row file was written, and
    for a blocked or failed `--allow-empty` run only when no earlier row
    file exists at that path. Otherwise a failed run would leave a
    "status": "failed" sidecar next to the previous run's still-intact good
    output (which `save` deliberately
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
    write_stats: dict = {}
    # `--allow-empty` writes an empty file ONLY for a genuine empty result:
    # the run finished, nothing stood in its way, and the answer was
    # nothing. A blocked or failed run (a parser that found nothing on a
    # page stating rows included: it reaches here with a failed page) is
    # not an answer, so the flag never writes an empty file over a
    # previous good result for one, and never turns its exit code into 4.
    genuine_empty = not rows and complete and not blocked
    failure_sidecar = False
    if rows or genuine_empty:
        rc = save(rows, out_prefix, fmt, allow_empty=allow_empty, row_cls=row_cls,
                  stats=write_stats)
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

    if rows:
        status = "complete" if complete else "partial"
    elif genuine_empty:
        # A finished run whose answer was nothing: complete, and empty.
        status = "empty"
    else:
        status = "blocked" if blocked else "failed"
    # Merged UNDER the caller's `extra`: an engine's own facts win a name
    # collision, and run fields still win over both (see run_meta).
    if write_stats:
        extra = {**write_stats, **(extra or {})}
    meta = run_meta(
        status=status, stop_reason=stop_reason,
        pages_requested=pages_requested, pages_completed=pages_completed,
        pages_failed=pages_failed, mode=mode, source=source,
        start_url=start_url, final_url=final_url, products=len(rows),
        extra=extra)
    if wrote_output or failure_sidecar:
        write_run_meta(out_prefix, meta)
    if extra and "proxy_bytes" in extra:
        # A metered (proxied) run also records itself in the attempt
        # sidecar, every time: a run that wrote no rows leaves no
        # `<out>.meta.json`, and what it spent through the proxy must still
        # be on disk somewhere.
        write_attempt_meta(out_prefix, meta)

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
