"""
output_writer.py
-----------------
Shared row models + JSON/CSV writers used by all three scrapers.

Three modes, one row shape
--------------------------
    --mode listing    /collections/{handle}/products.json   a collection
    --mode search     /search/suggest.json?q=…              a keyword lookup
    --mode product    /products/{handle}.js                 one product

All three yield the SAME class. The store publishes one leaf — a PRODUCT —
and a collection, a search result and a product document are three views of
it. The first two are ways of SELECTING products; the third is one product
described more fully, and here "more fully" means its VARIANTS, because the
product document carries one entry per size and colour with its own sku, its
own price and its own availability.

So `--mode product` emits one row PER VARIANT, not one row per document. A
seven-size one-piece is seven rows, which is the only shape that can answer
"is the 2X in stock" — and that is the question the product document exists
to answer: on `one-pieces`, MOST products are available in some sizes and not
others — 63 / 116 / 1 (every size / some / none) of 180 on 2026-09-18, and
64 / 115 / 1 the same evening. The split moves with stock; what does not move
is that the partial bucket is the biggest one.
`product_id` carries the product's id so the rows fold back together, and
`sku` holds the VARIANT's own SKU string because rows are variants.

Columns this site does NOT have, and the measurement behind each
--------------------------------------------------------------
A column null on every row of every run should not exist, and
removing one needs the measurement written down so someone can put it back
with a better one. Counted 2026-09-18 over 665 products across four
collection captures, plus product documents and rendered pages:

    rating / review_count            The store uses Okendo. Its stars are
                                     `display:none` in the collection grid —
                                     0 rendered star ratings on a fully
                                     scrolled listing — and no JSON route
                                     read here carries a rating at all.
                                     Okendo's own API answers per PRODUCT,
                                     so the column would cost 180 extra
                                     third-party requests for one collection.
                                     Absent rather than null, and this is the
                                     measurement to beat if someone wants it
                                     back.

    lowest_price_30d                 0 occurrences of an EU-Omnibus 30-day-low
                                     disclosure on any market, including the
                                     EU ones. The column a sibling repo needs
                                     for `mediamarkt` has nothing to hold
                                     here.

    ean / gtin / mpn                 0 `gtin`, 0 `mpn`, 0 `barcode` values
                                     populated in any payload. The store
                                     identifies by its own product id and by
                                     a style code inside the variant sku
                                     (`AO292` of `AO292-BLK-XS`), which is
                                     `base_sku`.

Columns this site DOES have that a sibling dropped
---------------------------------------------------
`original_price` and `discount_pct` are present here, and the sibling repo
this code came from correctly drops them: that site is a full-price house
with no reduced price anywhere. This one discounts heavily — 81 of 180
one-pieces and 150 of 150 items in `/collections/sale` carry a
`compare_at_price`, at 20–75% off — so both columns earn their place.

`discount_pct` is None, never 0 and never negative, when the pair is not a
discount. Shopify lets a merchant leave a stale `compare_at_price` UNDER the
current price; read as a was-price that publishes a negative discount on a
product that is not on sale.

`in_stock` is a real column, and `null` is not `False`
-------------------------------------------------------
Worth stating loudly, because which ENDPOINT a run reads decides whether the
column exists at all:

    /collections/{h}/products.json   publishes `available` per variant
    /products/{handle}.js            publishes `available` per variant
    /products/{handle}.json          publishes NO availability AT ALL

That last one is why `product_endpoint()` returns `.js` — the `.json`
document carries `price_currency` and would otherwise be the better source,
but a product run off it returns seven rows with `in_stock: null`, which is
honest and useless.

Where a payload states availability for no variant, `in_stock` stays None
rather than False: an unknown recorded as unknown (never present a guess
as a fact). On a listing row it is True when ANY variant is available, which
is what "can I buy this product" means; `variants_available` and
`variants_total` beside it are what make that actionable, because a bare
`in_stock: true` hides a product down to its last size.
"""

import contextlib
import csv
import json
import os
import tempfile
from dataclasses import dataclass, asdict, field, fields
from datetime import datetime, timezone
from typing import Optional, List, Set, Sequence, Any, Type


# The hostname a row came from. The store serves all 200 of its markets from
# ONE host — `andieswim.com` — with the market in the PATH (`/en-gb/`,
# `/en-jp/`) rather than in a TLD, so this column is `andieswim.com` on every
# row of every run. It is kept because the family's schema has it in this
# position and consumers read the columns by name across repos; `locale`
# below is what actually varies.
SOURCE_DEFAULT = "andieswim.com"


@dataclass
class Product:
    # ---- the family prefix, byte-identical and in order ------------
    source: str = SOURCE_DEFAULT
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # The absolute product URL, rebuilt from the handle on the canonical host
    # and carrying the market prefix the row was read from. The listing
    # payload does NOT publish a URL — it publishes `handle` — so this is
    # constructed rather than copied, and `handle` is kept beside it so a
    # reader can see the input as well as the result.
    url: str = ""
    # The dedupe key, and WHICH id it holds depends on the mode:
    #
    #   --mode listing / search   Shopify's numeric product id ("7022167785544")
    #   --mode product            the variant's own SKU string ("AO292-BLK-XS")
    #
    # Deliberate, and the reason is that rows are different things in the two
    # modes. A listing row is a product; a product-mode row is a VARIANT, and
    # 1137 variants of a 180-product collection share 180 product ids between
    # them. Measured unique in both modes within a run: 180 of 180 product
    # ids, 1137 of 1137 variant skus, and no sku shared between two different
    # products across 665 products. `diff_runs.py` refuses to compare two runs
    # whose modes disagree, which is what keeps the two keys from ever being
    # lined up against each other.
    sku: Optional[str] = None
    title: Optional[str] = None

    # ---- commerce -------------------------------------------------------
    # Shopify's `vendor`. Mostly the literal "Andie" — this is a single-brand
    # store — but NOT always: the shop carries stocked third-party labels
    # (`featured-brand-the-handloom` is a whole collection), so this is a real
    # column rather than a constant.
    brand: Optional[str] = None
    # The MINIMUM price across the product's variants, in the market's
    # currency and in major units. See `price_max` for when that minimum is
    # not the whole story.
    price: Optional[float] = None
    # Never defaulted, never inferred from the market prefix. The listing
    # endpoint publishes NO currency field at all, so this is filled from
    # something the site stated — `variants[].price_currency` on a product
    # document, or `Shopify.currency.active` in the market's HTML — and is
    # None when the run could not read either.
    currency: Optional[str] = None
    # Listing row: True when ANY variant is available. Product row: this
    # variant's own availability. None means the payload stated it for no
    # variant — `/products/{h}.json` omits `available` entirely — and None is
    # not False.
    in_stock: Optional[bool] = None
    image_url: Optional[str] = None
    # Shopify's `product_type` ("One Piece", "Bikini Top", "Cover Up"), or
    # whatever `--category` overrode it with.
    category: Optional[str] = None

    # ---- provenance and ordering ---------------------------------------
    # WHICH endpoint the price was read from. There is no rendered-tile
    # view to reconcile against on this site — a collection page paints its
    # grid from the Storefront API after load and serves no prices in its
    # HTML — so the rule is to record the source rather than port a DOM overlay that
    # could never confirm anything:
    #
    #   "products_json"  /collections/{h}/products.json  — decimal string
    #   "product_json"   /products/{h}.json              — decimal string,
    #                                                      carries its currency
    #   "product_js"     /products/{h}.js                — INTEGER CENTS,
    #                                                      divided by 100 here
    #   "search_json"    /search/suggest.json
    #
    # The distinction is not cosmetic: reading a `.js` document as a `.json`
    # one is a factor of 100 in every price, silently, and this column is how
    # a consumer can tell which convention produced a number.
    price_source: Optional[str] = None
    # `page` is 1-based over the run; `position` is the item's rank WITHIN its
    # page and restarts at 1 on each one. Neither is unique alone — the suite
    # asserts the PAIR is unique across a multi-page run.
    page: Optional[int] = None
    position: Optional[int] = None
    # Which mode produced the row. The repo no longer implies it — three modes
    # share this schema — and `diff_runs.py` refuses to compare two runs whose
    # modes it cannot line up.
    mode: Optional[str] = None

    # ---- site-specific, at the end ---------------------------------
    # The market this row was read from ("en-gb"), or "en-us" for the bare
    # path. Load-bearing because THE PRICE IS SET PER MARKET, not converted:
    # the same variant on 2026-09-18 was 112.00 USD · 195.00 CAD · 110.00 GBP
    # · 175.00 AUD · 130.00 EUR · 21600 JPY. 110 GBP is roughly 148 USD
    # against a 112 USD list, so a cross-market gap is pricing policy and not
    # arbitrage — say so before anyone builds on it.
    locale: Optional[str] = None
    # Shopify's numeric product id, as a string. Equal to `sku` on a listing
    # row and NOT equal on a product row, which is the point: it is what lines
    # a variant row back up with the listing row it came from.
    product_id: Optional[str] = None
    # The URL slug — `the-amalfi-flat-black-classic`. The human-readable id,
    # stable across markets, and the thing `/products/{handle}.json` is keyed
    # on. Present on 665 of 665 measured products.
    handle: Optional[str] = None
    # The style code shared by a product's variants — `AO292` of
    # `AO292-BLK-XS`. None when the variants do not agree on one, which is 52
    # of 665 products: a bundle or a multi-style set legitimately has no
    # single style code, and taking the first variant's would make unrelated
    # products look related in a diff.
    base_sku: Optional[str] = None
    # Shopify's own `product_type`, kept beside `category` because `category`
    # can be overridden from the command line and this one cannot.
    product_type: Optional[str] = None
    # `compare_at_price` — the was-price, from the SAME variant that set
    # `price`. Pairing the cheapest size's price with the priciest size's
    # was-price manufactures a discount, so the pair is never crossed.
    original_price: Optional[float] = None
    # Whole percent, and None rather than 0 or a negative when the pair is not
    # a discount: Shopify lets a stale `compare_at_price` sit BELOW the
    # current price, which read as a was-price publishes a negative discount
    # on a product that is not on sale. The canary pins that no row
    # carries an `original_price` at or below its `price`.
    discount_pct: Optional[int] = None
    # The MAXIMUM variant price, written only when the variants genuinely
    # disagree — 0 of 180 one-pieces, 13 of 85 accessories. A populated
    # `price_max` is therefore a fact about the product rather than noise on
    # every row.
    price_max: Optional[float] = None
    price_varies: Optional[bool] = None
    # How many variants the product has, and how many of them can be bought.
    # The pair is what makes "in stock" actionable: the MAJORITY of
    # one-pieces are available in some sizes and not others (63/116/1 of 180
    # one morning, 64/115/1 that evening — it moves), so a bare
    # `in_stock: true` hides a product down to its last size.
    variants_total: Optional[int] = None
    variants_available: Optional[int] = None
    # Pipe-joined, because the tags themselves contain commas
    # ("bust-support:medium bust support"). The store's merchandising lives
    # here — `category:swimwear`, `class:Open Back`, `badge:new` — and it is
    # the only structured taxonomy this site publishes.
    tags: Optional[str] = None
    published_at: Optional[str] = None
    # The collection handle this run walked. None on a product or search row,
    # where no collection was involved.
    collection: Optional[str] = None
    # The ordering the response came back in. Always "collection-default":
    # the JSON endpoint does not take `sort_by` and ignores one that is
    # passed, verified. Unlike the sibling repo where ordering decides WHICH
    # rows are in a capped file, nothing is capped here — a listing run
    # fetches every published product in the collection — so ordering decides
    # `position` only, and two runs under different orderings hold the same
    # rows. The column says which ordering produced the positions.
    sort: Optional[str] = None
    # ---- product mode only ----------------------------------------------
    # Shopify's numeric variant id. None on a listing row.
    variant_id: Optional[str] = None
    # The variant's own label — "BLACK / XS".
    variant_title: Optional[str] = None
    # Read by OPTION NAME, never by position. `option2` is Size on 622 of 665
    # products and is `Color` on a product whose options are
    # ('Rate','Color','Length') — reading it positionally writes a colour into
    # the size column, silently, on exactly the rows nobody checks.
    color: Optional[str] = None
    size: Optional[str] = None


# Row classes by --mode, so an engine maps its mode to a schema in one place.
# All three are Product here; the mapping exists so adding a mode later is a
# one-line change rather than a search for every place that assumed Product.
ROW_CLASS_BY_MODE = {"listing": Product, "search": Product, "product": Product}

# Modes whose rows are one-per-sku, and therefore safe to dedupe on `sku` and
# to hand to diff_runs.py.
#
# All three qualify, but `product` qualifies for a different reason and it is
# worth saying why. A listing names each product once, so its `sku` is unique
# by construction. A product page emits one row per VARIANT, and a variant's
# `sku` ("MB132464") is distinct from its siblings' and from the group's
# ("MB132460") — 16 distinct variant skus on one pen, measured. So the key is
# still unique; it just identifies something one level finer.
UNIQUE_BY_SKU_MODES = ("listing", "search", "product")


def dedupe_by_key(rows: Sequence[Any], seen: Set[str], key: str = "sku") -> List[Any]:
    """Drop rows whose key already appeared earlier in this same run.

    `seen` is mutated in place, so callers thread the same set across pages —
    a repeated page then re-parses without duplicating its rows into the
    final output. On this store it should fire NEVER on a healthy run, and
    that is measured: walking the whole catalogue at `limit=250` gave 772
    rows and **772 distinct handles** — no product appeared on two pages.

    A non-zero drop count here therefore means a page was genuinely
    re-fetched — or that the run changed `--sort` mid-flight, which it
    cannot, because the ordering is fixed for the whole run and recorded on
    every row.

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


@contextlib.contextmanager
def _atomic(path: str, newline: Optional[str] = None):
    """Write to a temporary file beside `path`, then rename over it.

    `open(path, "w")` truncates before a single byte is written, so a crash,
    a kill, a full disk or a Ctrl-C halfway through `json.dump` leaves a
    SHORTER file where a complete one was. That breaks exactly the promise
    `save()` keeps by refusing to overwrite good output with an empty
    result: the previous good run is destroyed by the ATTEMPT to replace it
    rather than by its outcome. Measured here before the fix: a 780-byte
    good `out.json` came back as 12 bytes of invalid JSON after a write that
    failed halfway.

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
        # temp file's mode, so without this every output would come out
        # readable by its owner alone, a regression from `open(path, "w")`,
        # which honours the umask.
        #
        # An existing target keeps its OWN mode, because someone may have
        # tightened it on purpose and a save should not undo that. A new one
        # gets exactly what `open()` would have given it. Never a flat
        # `0o644 & ~umask`: that narrows 0664 to 0644 under umask 002.
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
# rather than as text, and every string in these rows was written by the
# merchant: titles, tags, product types, variant names. `=HYPERLINK(...)`,
# `+cmd|...` and `@SUM(...)` are the classic shapes; the tab and the two
# newlines are here because some readers strip a leading one and then
# execute whatever followed it.
CSV_FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r", "\n")

# Excel, Google Sheets and LibreOffice all read a leading apostrophe as
# "the rest of this cell is text" and do not display it. A consumer parsing
# the file with the `csv` module DOES see it, which is why the count goes
# into the sidecar rather than staying silent.
CSV_FORMULA_ESCAPE = "'"


def _csv_escape(v: Any):
    """Neutralise a formula-shaped cell. Returns (value, was_escaped).

    Only STRINGS are touched. Escaping a number would turn `-5` into text
    and break every sum a consumer writes over the column.

    CSV only, on purpose. The JSON output keeps the site's bytes exactly as
    served, so the two files deliberately differ, and `csv_cells_escaped`
    in the sidecar is what declares that divergence rather than leaving it
    to be discovered as a stray apostrophe.
    """
    if isinstance(v, str) and v.startswith(CSV_FORMULA_LEADS):
        return CSV_FORMULA_ESCAPE + v, True
    return v, False


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
                # string, so `_csv_escape` would skip it, and the joined
                # cell it becomes can perfectly well start with a formula
                # character.
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
# On this store this code does NOT cover a listing that simply ran out. A
# `page=` past the end answers HTTP 200 with `{"products": []}` and no error.
# That is EXIT_NO_PRODUCTS at worst and normally just the end of pagination:
# the request was served exactly as asked. Reporting it as blocked would
# send a user hunting for a proxy problem that does not exist.
#
# It also does not cover a MISSPELT collection handle, which answers
# identically — HTTP 200 and an empty list. That one is resolved against the
# store's own collection index and reported as `unknown_collection`, not as
# a block.
#
# EXIT_BLOCKED has never been produced against this store. Measured
# 2026-09-18 from a datacenter address: every route HTTP 200 with a browser
# UA, with curl, with python-urllib, with a crawler UA and with no
# User-Agent header at all; twenty rapid requests, twenty 200s. The code
# stays wired because a store can be put behind a bot manager between
# deploys, and the day that happens the run should say `blocked` rather than
# report a parse failure.
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
    repo: the same output prefix can hold a search run, a category run or a
    product run, and those populate different columns. diff_runs.py refuses
    a pair whose modes or sources differ. `source` is `andieswim.com` on
    every row of every run here, since all 200 markets share one host with
    the market in the path; it is kept because consumers read these columns
    by name across the family, and `locale` is the column that varies.

    `locale` is recorded for a harder reason: the store SETS prices per
    market rather than converting them, so two runs differing in it are two
    price lists rather than two observations of one.

    `extra` carries facts about the run that are not about any single row.
    A listing run uses it for the market, the resolved currency and where
    that currency was read from — and for `catalog_count`, the collection
    index's `products_count`, WITH the warning that it is not a count of
    products the storefront serves (472 against 180 measured). That warning
    travels with the number rather than living only in a README, because the
    artefact is what a reader opens six months later.

    `total_results` and `pages_available` are present in the schema and
    always None here: this store states no result count anywhere. None means
    UNKNOWN and is never read as zero — treating a missing count as zero
    would cap every run after page 1 at no pages at all.

    Unlike bbb-scraper, where the same field had to carry a warning, here it
    is good news and the sidecar says so plainly: this store applies no page
    cap. Walking the whole catalogue gave 250 + 250 + 250 + 22 = 772
    distinct handles with page 5 empty (measured 2026-09-18). A run that
    walks to the end of a collection holds the whole collection, so
    "complete" here means
    what the word ought to mean.

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
        # `shop_rating` at the top level beside `products`. Run fields win a
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
        # it. The caller threads it into the sidecar.
        if stats is not None:
            stats["csv_cells_escaped"] = escaped
        if escaped:
            print(f"[!] {escaped} CSV cell(s) began with a formula character "
                  f"and were prefixed with {CSV_FORMULA_ESCAPE!r} so a "
                  f"spreadsheet reads them as text. The JSON output is "
                  f"unchanged; see csv_cells_escaped in the sidecar.")
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
# On this store there is NO third signal, and the absence is the finding:
# the site states no result count anywhere, and the one count it does
# publish (`products_count`) is not a count of products it serves. So the
# run discovers its own end from the data, and "no_new_products" is the
# normal way a healthy listing run stops.
#
# "page_cap_reached" therefore does NOT mean a site cap here — this store
# imposes none. It means a single-response route (`product`, `search`)
# reporting that it has no page 2, which is a complete answer.
#
# Walking off the end is free either way: a page past the last one is HTTP
# 200 with an empty array, not the HTTP 500 the same overshoot produces on
# bbb-scraper's site. So an overshoot costs one request and manufactures no error.
#
# "single_page_mode" is complete by construction: --mode product reads one
# page because one page is all there is. Note that it still emits MANY rows
# — one per variant — so "single page" is a statement about fetching, not
# about the size of the output.
# Note "parser_found_nothing" is deliberately ABSENT. A payload the store
# served that names products and parsed to zero rows is OUR failure, not a
# complete answer, and a run that ends that way must not report `complete`.
# With no rows it exits EXIT_FETCH_FAILED (5) through `finish_run`'s
# not-complete branch, not EXIT_NO_PRODUCTS: the store said there were
# products, so "the catalogue is empty" would be the one wrong answer.
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

    if wrote_output:
        status = "complete" if (rows and complete) else (
            "partial" if rows else "failed")
        write_run_meta(out_prefix, run_meta(
            status=status, stop_reason=stop_reason,
            pages_requested=pages_requested, pages_completed=pages_completed,
            pages_failed=pages_failed, mode=mode, source=source,
            start_url=start_url, final_url=final_url, products=len(rows),
            # UNDER the caller's `extra`, never over it: a collision here
            # would be housekeeping silently dropping something the site said.
            extra=({**write_stats, **(extra or {})} if write_stats else extra)))

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
