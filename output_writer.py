"""
output_writer.py
-----------------
Shared row model + JSON/CSV writers used by all three engines.

Two modes, one row shape
------------------------
    --mode listing   /site/{brand}/c/{cNN}/            a category listing
                     /site/itemtags/list.aspx?tags=…   a tag listing
    --mode product   /site/{brand}/g/g{SKU}/           one product page

Both yield the SAME class. Maison KOSÉ publishes one leaf — a PRODUCT — and a
listing is a way of SELECTING products while a detail page is one product
described more fully. Unlike montblanc-scraper's site, "more fully" here is
NOT more rows: a Kosé product page publishes a single `Product` block, never a
`ProductGroup` with `hasVariant`, so `--mode product` emits exactly one row
per page. What it adds is columns a tile does not carry — `subcategory`,
`volume`, `colour_count`, `release_date` — plus a structured price and availability
straight from the site's own JSON-LD.

The two listing ROUTES are one mode and not two, because they return the
identical tile markup and differ only in how they paginate. Splitting them
would have put the same parser behind two names and made `diff_runs.py`
refuse a comparison that is perfectly sound: a product is the same product
whether a category or a tag facet led to it.

Columns this site does NOT have, and the measurement behind each
----------------------------------------------------------------
A column null on every row of every run should not exist, and
removing one needs the measurement written down so someone can put it back
with a better one. Counted 2026-09-18 over 171 tiles in 8 listing captures
and 4 product captures:

  `original_price` / `discount_pct` / `lowest_price_30d` — **absent, and this
  is the load-bearing one.** 360 price nodes were surveyed and not one
  carries a struck-through, was-, or reference price: every node is a single
  amount in `1,234円（税込）` shape. So there is no discount chain, and
  the rule is explicit that the tile-price overlay must be DELETED rather
  than ported when that is true — there is no second view to reconcile
  against, and an overlay would be dead code that looks load-bearing. The EU
  Omnibus 30-day-low column that mediamarkt-scraper needs has no counterpart
  in Japanese price-indication law and no node on this site.

  `rating` / `review_count` — absent from every tile and every product page's
  JSON-LD. The site does publish staff opinion pieces (`/staff/…`), which is
  editorial content by named employees rather than a customer rating, and it
  is not a score of anything.

  `locale` — absent, and it is a measurement rather than an oversight.
  maison.kose.co.jp is one market: no `hreflang` set at all, no `/en/`,
  `/site/en/` or `/global/` route (all 404), and every price in JPY. A locale
  column would hold `ja-jp` on every row of every run forever.

  `sort` — absent. The site exposes facet filters (category, price band) but
  no ordering control on either listing route, so there is no ordering to
  record and nothing a run could have asked for. That is the opposite of
  bbb-scraper, where the ordering decides WHICH rows are in the file and
  therefore had to be a column.

What IS kept, byte-identical and in order, is the family prefix — `source`,
`scraped_at`, `url`, `sku`, `title` — so one column name works across the
family and a consumer reading several of these repos reads the same first
five columns in the same order.
"""

import contextlib
import csv
import json
import os
import tempfile
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timezone
from typing import Optional, List, Set, Sequence, Any, Type


# The site a row came from. Maison KOSÉ is one host and one market, so this
# is `maison.kose.co.jp` on every row; it is kept because the family's schema
# has it in this position and consumers read columns by name across repos.
#
# It is deliberately NOT `kose.com`: that domain resolves for nobody
# (delegated to nameservers that answer REFUSED, measured 2026-09-18), and a
# column naming a dead host would be a fact about nothing.
SOURCE_DEFAULT = "maison.kose.co.jp"


def utc_now() -> str:
    """The run's timestamp, as a UTC ISO-8601 string with a `Z`.

    One helper so every row in a run can be given the SAME stamp by the
    caller rather than each row calling the clock. Rows from one page that
    disagree in `scraped_at` by a few milliseconds make a diff noisier for
    no information.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Product:
    """One Maison KOSÉ product, from a listing tile or from a product page."""

    # ---- the family prefix, byte-identical and in order ------------
    source: str = SOURCE_DEFAULT
    scraped_at: str = field(default_factory=utc_now)
    # The absolute product URL. A tile publishes it ROOT-RELATIVE
    # ("/site/cosmedecorte/g/gJLCW/"); the parser joins it onto the host so
    # every row carries something a reader can open.
    #
    # Note the brand segment in it is decorative — `/site/xyz/g/gJLCW/` serves
    # the same product — so this URL identifies the product by its `g{SKU}`
    # tail and nothing else. In `--mode product` the row carries the page's
    # own `rel=canonical` instead, which is the site's spelling rather than
    # whatever was requested.
    url: str = ""
    # Kosé's own goods code, WITHOUT the route's `g` prefix: "JLCW", not
    # "gJLCW". That is the form the JSON-LD publishes as `sku`/`mpn` and the
    # form the site's own bookmark link uses (`?goods=JLCW`), so a row joins
    # against the site's id rather than against a URL artefact.
    sku: Optional[str] = None
    title: Optional[str] = None

    # ---- commerce -------------------------------------------------------
    # Read from the TILE (`p.c-product__brand`) on a listing and from the
    # breadcrumb on a product page. Never from the URL: the brand segment
    # there selects nothing, and a tag listing genuinely mixes brands — five
    # of them in 24 tiles on one measured page — so there is no per-page
    # brand to fall back on even if the URL were honest.
    brand: Optional[str] = None
    # Tax-INCLUSIVE, which is what this site prints and what its JSON-LD
    # publishes; `tax_rate` below says which rate is included. Structured and
    # displayed prices were checked against each other rather than assumed
    # and agree on 4 of 4 product captures.
    price: Optional[float] = None
    # "JPY" where a price was read, None where none was. Never defaulted: a
    # row with no price has no currency either.
    currency: Optional[str] = None
    # From the site's own call-to-action text on a listing and from
    # `offers.availability` on a product page, both as ALLOWLISTS so an
    # unanticipated value reads as unknown rather than as a quiet True.
    #
    # Verified in BOTH directions, which is otherwise not verified at
    # all: 19 of 171 measured tiles say 現在購入頂けません or 予約受付終了, and
    # `gJQBA`'s JSON-LD independently says `OutOfStock` where its tile does.
    in_stock: Optional[bool] = None
    image_url: Optional[str] = None
    # On a listing this is the `cNN` id the URL asked for — the only thing
    # that addresses a category on this site. On a product page it is the
    # breadcrumb's category NAME (スキンケア), which is a different kind of
    # value; `mode` on the row says which one a reader is looking at.
    category: Optional[str] = None

    # ---- provenance and ordering ---------------------------------------
    # WHICH node the price was read from. There is no discount chain
    # on this site and therefore no DOM overlay to reconcile against, so this
    # records the source rather than a confirmation:
    #
    #   "tile"        `p.c-product__price` in a listing tile.
    #   "jsonld"      `offers.price` on a product page.
    #   "detail_dom"  the product page's own price node, used only where its
    #                 JSON-LD carried no price.
    price_source: Optional[str] = None
    # `page` is 1-based over the run; `position` is the item's rank WITHIN its
    # page and restarts at 1 on each one. Neither is unique alone — the suite
    # asserts the PAIR is unique across a multi-page run.
    page: Optional[int] = None
    position: Optional[int] = None
    # Which mode produced the row. The repo no longer implies it and
    # `diff_runs.py` refuses to compare two runs whose modes it cannot line
    # up.
    mode: Optional[str] = None

    # ---- site-specific, at the end ---------------------------------
    # The consumption-tax rate the price INCLUDES, as a percentage. Japan runs
    # two: 10% standard, and 8% reduced on ingestibles — a beauty supplement
    # sits at 8% while the cream beside it is at 10%. The site states the
    # reduced rate explicitly (`（税込/8%）`) and leaves the standard one
    # implied. 2 of 171 measured tiles carry the reduced rate, both on
    # `/c/c15_p10/`, and a consumer computing a pre-tax figure from the wrong
    # rate is wrong by two percent in silence.
    tax_rate: Optional[int] = None
    # The site marks its own selling price with `※`, expanded on a product
    # page as `Maison KOSÉ販売価格` — the store's figure as opposed to a
    # maker's suggested one. True where that marker was present, None where
    # it was not, because its absence is not evidence of the opposite.
    price_is_store_price: Optional[bool] = None
    # The site's own corner badges, comma-joined: `new` 54, `limited` 26,
    # `online` 2 over 171 tiles. `limited` in particular is why a row can
    # vanish between two runs, which is information a diff otherwise lacks.
    badges: Optional[str] = None
    # Everything below is published on a PRODUCT page and not on a tile, and
    # is None on a listing row. They are the reason to open a detail page at
    # all, which is what keeps them off the "null on every row" list: in
    # `--mode product` they are populated.
    subcategory: Optional[str] = None
    # `容量 40g` — the pack size, from the detail page's variation line.
    volume: Optional[str] = None
    # How many colourways the product page offers. A foundation has several
    # and a cleanser has none; the site publishes no per-colour sku or price,
    # so this is a count and deliberately not a list of rows.
    colour_count: Optional[int] = None
    # `releaseDate` from the JSON-LD, in the site's own `YYYY/MM/DD HH:MM:SS`
    # spelling, kept verbatim rather than reformatted: a future date is how
    # the site marks a product announced but not yet on sale.
    release_date: Optional[str] = None
    # The sku this page's own `rel=canonical` points at, where that is NOT
    # this product. It is the only thing on the site that groups two sizes or
    # two shades of one product, so it answers "which family is this in".
    #
    # It exists as a column because it must NOT be used as the row's URL, and
    # a comment alone would not have stopped that: measured over 20 product
    # pages, **5 canonicalise to a different sku** -- `/g/gJQBA/` is the 60 g
    # cream and canonicalises to the 20 g `/g/gJQGA/`. A row built from the
    # canonical would link to the wrong product while every other column
    # described the right one. None on the 15 that point at themselves, and
    # None on every listing row, where the tile already names the product.
    variant_of: Optional[str] = None


# Row classes by --mode, so an engine maps its mode to a schema in one place.
# Both are Product here; the mapping exists so adding a mode later is a
# one-line change rather than a search for every place that assumed Product.
ROW_CLASS_BY_MODE = {"listing": Product, "product": Product}

# Modes whose rows are one-per-sku, and therefore safe to dedupe on `sku` and
# to hand to diff_runs.py.
#
# Both qualify, and on this site both qualify for the same simple reason: a
# listing names each product once, and a product page publishes a single
# `Product` block rather than a `ProductGroup`, so one page is one row. Where
# a Kosé product has colourways the site gives them no sku and no price of
# their own — `colour_count` records how many there are — so there is no
# finer key to dedupe on and none is invented.
UNIQUE_BY_SKU_MODES = ("listing", "product")



def dedupe_by_key(rows: Sequence[Any], seen: Set[str], key: str = "sku") -> List[Any]:
    """Drop rows whose key already appeared earlier in this same run.

    `seen` is mutated in place, so callers thread the same set across pages —
    a repeated page then re-parses without duplicating its rows into the
    final output. On Maison KOSÉ this should fire rarely on a healthy run and
    is measured: across 8 listing captures every page's skus were disjoint
    from every other page's, on both the category and the tag route — 171
    tiles, one repeat, and that repeat was one product legitimately present
    in both a category and a tag facet.

    A non-zero drop count on a SINGLE listing therefore means a page was
    genuinely re-fetched, and on this site that has a specific cause worth
    recognising: a category listing walked past its last page returns that
    last page AGAIN, byte-identical, rather than a 404 or an empty page
    (`/c/c15_p14/` and `/c/c15_p15/` both return `/c/c15_p13/`). A run that
    overshoots therefore shows up here as a full page of duplicates, which is
    the signal the engines' data-based stop is built on.

    A row with no key is always kept: there is nothing to check a duplicate
    against, and dropping it would be a silent data loss rather than a
    duplicate removal.

    Both of this repo's modes are one row per `sku`, so `key` is never
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
@contextlib.contextmanager
def _atomic(path: str, newline: Optional[str] = None):
    """Write to a temporary file beside `path`, then rename over it.

    `open(path, "w")` truncates before a single byte is written, so a crash,
    a kill, a full disk or a Ctrl-C halfway through `json.dump` leaves a
    SHORTER file where a complete one was. That breaks exactly the promise
    `save()` keeps by refusing to overwrite good output with an empty
    result: the previous good run is destroyed by the ATTEMPT to replace it
    rather than by its outcome. Reproduced on a sibling repo before the fix
    — a 2,084-byte good `out.json` came back 0 bytes and invalid JSON.

    The sidecar is the part that matters most. `<out>.meta.json` is the file
    a consumer branches on, so a truncated one beside good rows reads as a
    broken run over data that is fine.

    Three details, each of which is the reason for a line here:

    * the temp file goes in the target's OWN directory, because `os.replace`
      is atomic only within one filesystem and a temp file under /tmp can be
      on another, where the rename degrades to an interruptible copy;
    * `fsync` before the rename is what makes the bytes durable rather than
      merely visible, so a power loss cannot leave a renamed empty file;
    * `newline` is passed through because the csv module requires
      `newline=""` and that requirement has to survive the move into the
      temp file, or every row gains a stray CR on Windows.
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
        # `NamedTemporaryFile` creates at 0600 and `os.replace` keeps the
        # temp file's mode, so without this every output comes out readable
        # by its owner alone — a regression from `open(path, "w")`, which
        # honours the umask, and one that only appears once the write became
        # atomic. Measured across the family on 2026-10-08 by CALLING each
        # repo's sidecar writer: of 43 repos, 8 produce a 0600 sidecar, and
        # they are exactly the ones that took `_atomic` without this.
        #
        # An existing target keeps its OWN mode, because someone may have
        # tightened it on purpose and a save should not undo that. A new one
        # gets exactly what `open()` would have given it. Lifted from
        # hackernews-scraper, which fixed this first — the first version
        # written here used a flat `0o644 & ~umask`, which quietly narrows
        # 0664 to 0644 under umask 002 and clobbers a deliberately tightened
        # file (lift the sibling's fix, do not invent a second one).
        try:
            mode = os.stat(path).st_mode & 0o777
        except OSError:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(handle.name, mode)
        os.replace(handle.name, path)
    except BaseException:
        # Including KeyboardInterrupt and SystemExit: an interrupted run
        # must not leave `out.json.ab12cd.tmp` behind beside the good file.
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


# A spreadsheet treats a cell beginning with one of these as a FORMULA
# rather than as text, and every string in these rows was written by
# whoever listed the product — a name, a brand, a package size, a cup
# measure. `=HYPERLINK(...)`, `+cmd|...` and `@SUM(...)` are the classic
# shapes; the tab and the two newlines are here because some readers strip
# a leading one and then execute whatever followed it.
CSV_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r", "\n")

# Excel, Google Sheets and LibreOffice all read a leading apostrophe as
# "the rest of this cell is text" and do not display it. A consumer parsing
# the file with the `csv` module DOES see it, which is why the count goes
# into the sidecar rather than staying silent.
CSV_FORMULA_ESCAPE = "'"


def _csv_escape(v: Any):
    """Neutralise a formula-shaped cell. Returns (value, was_escaped).

    Only STRINGS are touched. Escaping a number would turn `-5` into text
    and break every sum a consumer writes over the column — `price` and
    `rating` are what anyone monitoring this site is actually summing.

    CSV only, on purpose. The JSON output keeps the site's bytes exactly as
    served, so the two files deliberately differ, and `csv_cells_escaped`
    in the sidecar is what declares that divergence rather than leaving it
    to be discovered as a stray apostrophe.
    """
    if isinstance(v, str) and v.startswith(CSV_FORMULA_LEADS):
        return CSV_FORMULA_ESCAPE + v, True
    return v, False


LIST_CSV_SEPARATOR = " | "


def _csv_value(v: Any) -> Any:
    if isinstance(v, (list, tuple)):
        return LIST_CSV_SEPARATOR.join(str(x) for x in v)
    return v


def write_json(rows: Sequence[Any], path: str) -> None:
    with _atomic(path) as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


def write_csv(rows: Sequence[Any], path: str, row_cls: Type = Product) -> int:
    # An empty result still gets the header row. A zero-byte file makes a
    # consumer fail on read (no columns to parse) instead of reading a valid
    # table with zero rows — and "an empty result is still a well-formed
    # result" is the same principle as `save` refusing to overwrite good data.
    #
    # The header comes from `row_cls`, not from the first row, so an empty
    # run still writes the columns of the mode that produced it.
    fieldnames = [f.name for f in fields(row_cls)]
    escaped = 0
    with _atomic(path, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            row = {}
            for k, v in asdict(r).items():
                # AFTER the list serialiser, not before it. A list is not a
                # string, so `_csv_escape` would skip it — and the joined
                # cell it becomes can perfectly well start with a formula
                # character, which is the case a naive ordering misses.
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
# On Maison KOSÉ this code does NOT cover a listing that simply ran out. A
# tag listing walked past its end answers HTTP 200 with zero tiles and no
# error, and a category listing walked past its end answers HTTP 200 with its
# LAST PAGE repeated. Both were served exactly as asked, so neither is a
# block: the first is EXIT_NO_PRODUCTS at worst and normally just the end of
# pagination, and the second is caught by the engines' data-based stop.
# Reporting either as blocked would send a user hunting for a proxy problem
# that does not exist.
#
# What EXIT_BLOCKED means here is a tripwire rather than a description. As
# measured on 2026-09-18 from a datacentre address, this site refuses
# nothing: `python-requests/2.31.0`, `curl/8.5.0`, a browser UA and NO
# User-Agent header at all each returned the same 90,310-byte listing, and
# twelve consecutive page fetches with no delay were all HTTP 200. No
# captcha, no challenge, no interstitial, no rate limit observed.
#
# That is a statement about one address on one day, not a promise, which is
# exactly why the code and the detection behind it are carried in full: if
# Kosé turns a challenge on, a run says so with exit 3 instead of reporting
# an empty catalogue.
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
    # Atomic, and this is the writer where it matters most: the sidecar is
    # the file a consumer branches on, so a truncated one beside good rows
    # reads as a broken run over data that is perfectly fine.
    with _atomic(path) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[+] Wrote run metadata -> {path} (status={meta.get('status')})")
    return path



def write_last_attempt(out_prefix: str, meta: dict) -> str:
    """Record a run that wrote no output, under its OWN filename.

    `finish_run` deliberately writes no `<out>.meta.json` for a failed run:
    `save` leaves the previous good output in place, and a "failed" sidecar
    beside good data would contradict it and make `diff_runs.py` refuse a
    comparison of data that is in fact fine.

    The cost of that, until this existed, was that a failed run left the
    caller NOTHING machine-readable — the exit code was the whole story, so
    "the proxy died" and "the facet matched nothing" were indistinguishable
    to anything driving the scraper. A third-party audit of this repo on
    2026-10-13 raised exactly that, and it was the half of its report that
    needed no argument: the invariant it ran into is right, and the gap
    beside it was real.

    A separate name is what lets both facts coexist: `<out>.meta.json` keeps
    describing the last SUCCESSFUL output, and `<out>.last_attempt.json`
    describes the most recent attempt whether or not it produced anything.

    Overwritten every run, including successful ones, so it is never stale:
    a `last_attempt` whose status is "complete" and whose `finished_at`
    matches the sidecar means the last attempt was the last success.
    """
    path = f"{out_prefix}.last_attempt.json"
    with _atomic(path) as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
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
    repo: the same output prefix can hold a search run, a category run or a
    product run, and those populate different columns. diff_runs.py refuses
    a pair whose modes or sources differ. `source` is `maison.kose.co.jp` on
    every row of every run here, since the site is one host and one market;
    it is kept because consumers read these columns by name across the
    family.

    The `url` a run was pointed at is recorded for a reason specific to this
    site: the brand segment in a listing address selects nothing, so two
    runs whose URLs differ only there fetched the identical page. The
    sidecar records the page's own `rel=canonical` alongside, which is the
    address the site agrees with.

    `extra` carries facts about the run that are not about any single row.
    A listing run uses it for the site's OWN page counter — the `N／Mページ`
    it prints in the title and above the grid — recorded as
    `pages_available`, plus the canonical URL of the page that was read.
    Those belong to the run rather than repeated down a column.

    Two warnings live here rather than in a column, and both are this site's
    own arithmetic. A category listing publishes its total page count, so a
    run can PLAN against it and "complete" means what the word ought to mean:
    on 2026-09-18 `/c/c15/` stated 13 pages, and 12 × 24 + 16 = 304 products
    was the whole category then (the count moves with the catalogue). A TAG listing publishes no counter at all, so `pages_available`
    is None there — which means UNKNOWN and never zero, because capping a tag
    run at zero pages would turn a working route into an empty file.

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
        # Named "products" even though these are products, and kept that
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
        # `pages_available` at the top level beside `products`. Run fields win a
        # name collision: a caller cannot accidentally overwrite `status`.
        meta.update({k: v for k, v in extra.items() if k not in meta})
    return meta


def save(rows: Sequence[Any], out_prefix: str, fmt: str,
         allow_empty: bool = False, row_cls: Type = Product,
         stats: Optional[dict] = None) -> int:
    """Write JSON/CSV and return a process exit code.

    Returns 0 when rows were written, EXIT_NO_PRODUCTS when there were none.
    Callers are expected to exit with it.

    On zero rows, nothing is written at all unless `allow_empty`. Two reasons,
    and a live run demonstrated both. A page-load timeout produced
    `Saved 0 products -> out.json` and exit 0: a two-byte `[]` that a
    consuming pipeline reads as a successful run with no stock. Worse, if the
    file already held a good result from an earlier run, that result is now
    gone — the failure destroyed the last known good data. So an empty result
    leaves the previous file intact and says why.

    `allow_empty=True` is for the legitimate case: a filter that genuinely
    matches nothing, where an empty file is the answer.
    """
    if not rows and not allow_empty:
        print(f"[!] 0 products — refusing to write {out_prefix}.json/.csv, so an "
              f"earlier good result isn't overwritten with an empty one. "
              f"Pass --allow-empty if an empty result is the expected answer.")
        return EXIT_NO_PRODUCTS

    if fmt in ("json", "both"):
        write_json(rows, f"{out_prefix}.json")
        print(f"[+] Saved {len(rows)} products -> {out_prefix}.json")
    if fmt in ("csv", "both"):
        escaped = write_csv(rows, f"{out_prefix}.csv", row_cls=row_cls)
        print(f"[+] Saved {len(rows)} products -> {out_prefix}.csv")
        # Reported through `stats` rather than as a return value, because
        # this function's return value is an EXIT CODE and callers exit with
        # it. The caller threads it into the sidecar, where a consumer
        # comparing the CSV against the JSON can see that the two diverge
        # and by how much, instead of finding an apostrophe and guessing.
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
# On a CATEGORY listing there is a THIRD, stronger signal, and it is the
# site's own arithmetic: every page prints `N／Mページ`, so the number of
# pages is known from the first response rather than discovered by walking
# off the end. "page_cap_reached" is that stop reason.
#
# It is a COMPLETE run, and here it is complete in the strong sense: the site
# imposes no cap of its own, so the planned page count IS the whole category.
# On 2026-09-18 `/c/c15/` stated 13 pages and 12 × 24 + 16 = 304 products
# was all of Cosme Decorté; the count moves as the catalogue changes.
#
# Planning against it is not merely an optimisation on this site, which is
# the part worth remembering. Walking off the end of a category returns the
# LAST PAGE AGAIN — byte-identical, HTTP 200, forever — rather than the empty
# grid montblanc-scraper's site returns or the HTTP 500 that the same
# overshoot produces for bbb-scraper. A run that trusted "keep going until a page is empty" would never
# terminate. A TAG listing does end with an empty page, so the two routes
# want the same data-based stop for opposite reasons.
#
# "single_page_mode" is complete by construction: --mode product reads one
# page because one page is all there is. On this site that is also exactly
# one ROW — a Kosé product page publishes a single `Product` block, never a
# `ProductGroup` with variants.
# Note "parser_found_nothing" is deliberately ABSENT. A page Maison KOSÉ
# served that links to products and parsed to zero rows is OUR failure, not a
# complete answer, and a run that ends that way must not report `complete`
# Its exit code is EXIT_API_ERROR (5) through finish_run's not-complete rule:
# with zero rows nothing was obtained that a consumer could use, and
# EXIT_NO_PRODUCTS (4) would claim an empty catalogue the page contradicts.
#
# It CAN fire on this site, which is worth checking before adding the signal:
# rows are built from `li.c-product__item` tiles while `product_link_count`
# counts `/g/g…/` hrefs, and a grid page carries 28 of those against 24
# tiles. So a tile-markup change leaves the links intact and the rows at
# zero, which is precisely the case this reason exists to name.
COMPLETE_STOP_REASONS = ("completed", "pagination_exhausted", "no_new_products",
                         "page_cap_reached", "single_page_mode")


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

    The metadata sidecar is written ONLY when the row file was written.
    Otherwise a failed run would leave a "status": "failed" sidecar next to
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
    row_cls = ROW_CLASS_BY_MODE.get(mode, Product)
    write_stats: dict = {}
    rc = save(rows, out_prefix, fmt, allow_empty=allow_empty, row_cls=row_cls,
              stats=write_stats)
    wrote_output = bool(rows) or allow_empty

    status = "complete" if (rows and complete) else (
        "partial" if rows else "failed")
    meta = run_meta(
        status=status, stop_reason=stop_reason,
        pages_requested=pages_requested, pages_completed=pages_completed,
        pages_failed=pages_failed, mode=mode, source=source,
        start_url=start_url, final_url=final_url, products=len(rows),
        # UNDER the caller's `extra`, never over it: a collision here would
        # be housekeeping silently dropping something the site said.
        extra=({**write_stats, **(extra or {})} if write_stats else extra))

    if wrote_output:
        write_run_meta(out_prefix, meta)
    # ALWAYS, and under its own name: a failed run must leave something a
    # machine can read, without contradicting a sidecar that still describes
    # good data. See write_last_attempt.
    write_last_attempt(out_prefix, meta)

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
