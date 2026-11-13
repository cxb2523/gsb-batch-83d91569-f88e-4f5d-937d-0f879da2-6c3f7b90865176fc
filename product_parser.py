"""Extraction for andieswim.com — Andie Swim, a Shopify storefront.

This module is the site. Everything else in the repo is family core.

WHAT THIS SITE PUBLISHES, AND WHY THE PARSER READS JSON RATHER THAN MARKUP
=========================================================================

Measured 2026-09-18 from a datacenter address (Hetzner/netcup-class, no
proxy, no key), against captures kept in ../captures/andieswim/:

* `andieswim.com` is Shopify (`andie-swim-1.myshopify.com`) behind a custom
  React theme.  Every route answered **HTTP 200** — with a browser UA, with
  `curl/8.5.0`, with `python-urllib`, with a crawler UA, and with **no
  User-Agent header at all**.  Twenty rapid requests in 4.9 s: twenty 200s.
  Nothing on the read path is gated.  See README for what the paid products
  are still worth here, which is honest and small.

* A **collection page's HTML carries no product grid.**  793 KB of
  `/collections/one-pieces` holds exactly 5 distinct `/products/` links, all
  of them from recommendation widgets, and `?page=2` returns the SAME five —
  the grid is painted by a React component (`react-component=
  "VisualNavProductListPage"`) that fetches over the Storefront GraphQL API
  after load.  So an HTML-tile parser on this site would report five products
  for a 180-product collection and call it success.

* A **product page publishes no Product JSON-LD.**  One `application/ld+json`
  block on `/products/the-amalfi-flat-black-classic`, and its `@type` is
  `BreadcrumbList`.  The rule is to count the blocks before writing
  either path; the count here is zero for products, so there is no
  structured-data path to write.

* What the site DOES publish, ungated, is **its own JSON** — Shopify's
  storefront endpoints, which are the same objects the theme itself consumes:

      /collections/{handle}/products.json?limit=250&page=N   listing
      /products/{handle}.js                                  detail, cents
      /products/{handle}.json                                detail, decimal
                                                             + price_currency
      /search/suggest.json?q=...                             search
      /collections.json?limit=250&page=N                     collection index

  Richer than any rendered tile: every variant with its own sku, price,
  compare-at price and availability.  The rule — ask what the
  front end calls before assuming a browser — answered the whole repo here.

So the engines navigate to the ENDPOINT and this module parses the JSON.  The
browser is still the transport (it is what the family's proxy, fingerprint and
Scraping Browser paths plug into), and `--mode product` additionally reads the
rendered page when asked, but the DATA is JSON on every route.

THE TRAPS, EACH MEASURED
========================

`products_count` is not a product count.  `/collections.json` reports
`one-pieces` at **472** and `all-swimwear` at **3089**, while the storefront
serves **180** and **322** respectively — and the whole store holds 772
published products, so 3089 cannot be a count of anything a visitor can
reach.  It is not a variant count either (all-swimwear has 1997 variants).
Used as a completeness target it would mark every run partial forever, so
this module records it as `catalog_count` with that warning attached and
plans nothing from it.  The honest completeness signal is the site's own
sitemap: `sitemap_products_1.xml` lists 753 product URLs and every one of
them is in `/products.json`'s 772, a strict superset with zero misses.

A bogus collection handle answers **HTTP 200 with an empty list**, not 404 —
`/collections/does-not-exist/products.json` returns `{"products":[]}`.  Only
the HTML route 404s.  So "no rows" cannot be read as "empty collection"
without checking the handle exists.  `/collections/{handle}.json` answers
that in one request — 200 with a `products_count`, or a 404 with zero bytes —
which is why this repo distinguishes `unknown_collection` from `empty` in its
stop reasons.

Options are not positional.  `variants[].option1/2/3` are commonly Color and
Size, but the store also ships `Rate`, `Length`, `Quantity`, `SPF`,
`Pack Size`, `Strength` and `Product Size` as first or second options.
Measured over 665 products: Color 647, Size 622, Rate 13, Length 5,
Quantity 4, SPF 2, Pack Size 2.  Reading `option2` as "the size" therefore
writes a rate band into a size column on a gift card.  This module maps by
the product's own `options[].name` instead, and `smoke_test.py` pins a
product whose options are `('Rate','Color','Length')`.

Prices do not vary within a swimwear product but DO within accessories — 0 of
180 one-pieces, 13 of 85 accessories.  A listing row therefore carries
`price` (the minimum) and sets `price_varies` with `price_max` beside it
rather than silently publishing one variant's figure as the product's.

Markets are path prefixes and the prices are SET per market, not converted.
The site's own sitemap index lists **200** of them, all `en-xx`.  The same
variant, 2026-09-18: 112.00 USD · 195.00 CAD · 110.00 GBP · 175.00 AUD ·
130.00 EUR · 21600 JPY.  110 GBP is about 148 USD against a 112 USD list, so
a cross-market comparison is pricing policy, not arbitrage.  Join on
`sku`, never on a label.

An HTML page on this store is TIMING-DEPENDENT and a JSON endpoint is not.
There is no HTTP redirect anywhere — `curl -L` follows zero hops on every
route — but the theme ships a client-side geolocation app that rewrites the
location to the visitor's own market after load.  Measured 2026-09-18 from a
Finnish address: `/collections/all` read at `domcontentloaded` is the bare
path and says USD; the same URL read after a full load has become
`/en-fi/collections/all` and says EUR.  Three engines that wait for different
things therefore disagree about which market an HTML page is on — which they
did, until everything this repo depends on was moved off HTML.  The JSON
routes run no JavaScript and cannot be moved that way.

Currency is never guessed.  `/collections/{h}/products.json` carries NO
currency field at all, so this module refuses to stamp one from the market
prefix — a mapping this file would have to invent.  It is read from the
site: `/products/{h}.json` publishes `variants[].price_currency`, and any
HTML page on the market publishes `Shopify.currency = {"active":"GBP",...}`.
The engines fetch one of those once per run and pass it in; a run that could
not read one writes `currency: null` and says so.
"""

import html as _html
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import (parse_qsl, quote, urlencode, urljoin, urlparse,
                          urlunparse)

from output_writer import Product

# NOTE: no BeautifulSoup here, and the absence is deliberate rather than an
# omission.  The family makes `BeautifulSoup(html, "html.parser")` the
# family default, and the reason it does not apply is the shape of this site:
# every field this repo publishes comes out of a JSON document, because a
# collection page's HTML carries no grid and a product page's HTML carries no
# Product JSON-LD (see the module docstring for both counts).  The only two
# things ever read out of markup are the market's currency and the store's
# 404 template, and both are single anchored patterns over a document whose
# structure is irrelevant — souping 800 KB of theme to reach them cost 74 ms
# per fetch when it was tried, measured, for nothing.  Adding a parser back
# is right the moment a field has to come from the DOM; until then it would
# be a dependency with no reader.

# ---------------------------------------------------------------------------
# Hosts and markets
# ---------------------------------------------------------------------------

HOSTS = ("andieswim.com", "www.andieswim.com")
CANONICAL_HOST = "andieswim.com"

# Both answer, and they answer DIFFERENTLY depending on the route — measured
# 2026-09-18, after a first version of this comment got it half wrong:
#
#   www.andieswim.com/collections/one-pieces               301 -> bare host
#   www.andieswim.com/collections/one-pieces/products.json 200, stays on www.
#
# So the HTML route canonicalises and the JSON routes do not — and the JSON
# routes are the ones this repo actually fetches. Nothing breaks either way
# (both spellings serve the same payload), but it is the reason rows are
# rebuilt on CANONICAL_HOST rather than on whatever the caller typed: without
# that, two runs of the same collection would differ by a hostname in `url`
# and every row would read as changed in a diff.
#
# The family warns about the opposite case — a host that does NOT answer on
# `www.` — which is not this site. Here it is the JOIN that matters, not
# reachability.

# The market prefixes, taken from the site's OWN sitemap index rather than
# guessed or read off hreflang.  Re-derive with:
#
#   curl -sS https://andieswim.com/sitemap.xml \
#     | grep -o 'andieswim\.com/[a-z][a-z]-[a-z][a-z]/' \
#     | cut -d/ -f2 | sort -u
#
# 200 of them on 2026-09-18, every one `en-<cc>`: the store is English
# everywhere and the prefix selects COUNTRY, which selects currency and
# price.  The list is not hardcoded here because 200 two-letter pairs in a
# source file is a table that rots; the SHAPE is validated instead and
# an unknown-but-well-formed market is accepted with a warning.
_MARKET_RE = re.compile(r"^/(en-[a-z]{2})(?=/|$)")

DEFAULT_MARKET = ""          # the bare path is the US store
DEFAULT_LOCALE = "en-us"     # what a row carries when no prefix is present

# Markets confirmed by a live fetch on 2026-09-18, each returning a different
# currency.  Used by the suite and by `--locale` validation as a known-good
# sample, NOT as an exhaustive list.
VERIFIED_MARKETS = ("en-ca", "en-gb", "en-au", "en-de", "en-jp")

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

MODES = ("listing", "product", "search")
DEFAULT_MODE = "listing"

# Shopify's storefront JSON caps `limit` at 250 and ignores anything larger.
# Verified: `limit=250` returned 250 on a collection holding more, and
# `limit=1000` also returned 250.
PAGE_SIZE = 250
MAX_PAGE_SIZE = 250
PAGE_PARAM = "page"
LIMIT_PARAM = "limit"

_COLLECTION_PATH_RE = re.compile(r"^(?:/en-[a-z]{2})?/collections/([a-z0-9][a-z0-9_-]*)"
                                 r"(?:/|$)", re.I)
_PRODUCT_PATH_RE = re.compile(r"^(?:/en-[a-z]{2})?/products/([a-z0-9][a-z0-9_-]*)"
                              r"(?:\.js|\.json)?(?:/|$)", re.I)
_SEARCH_PATH_RE = re.compile(r"^(?:/en-[a-z]{2})?/search(?:/|$)", re.I)

# Collection handles that are routes rather than catalogues.  `/collections/all`
# is Shopify's built-in everything-collection and IS a real listing, so it is
# deliberately absent from this set.
_NOT_A_COLLECTION = frozenset({
    "account", "orders", "checkout", "cart", "search",
})


def market_from_url(url: str) -> Optional[str]:
    """The `en-xx` prefix on this URL, or None for the bare (US) store."""
    m = _MARKET_RE.match(urlparse(url or "").path or "/")
    return m.group(1).lower() if m else None


def locale_from_url(url: str) -> str:
    """The locale a row fetched from this URL should carry.

    Never None: the bare path is a real market (the US one) and writing
    `null` there would make a US row indistinguishable from a row whose
    market could not be determined.
    """
    return market_from_url(url) or DEFAULT_LOCALE


def market_is_well_formed(market: Optional[str]) -> bool:
    return bool(market) and bool(re.fullmatch(r"en-[a-z]{2}", market or ""))


def _strip_market(path: str) -> str:
    m = _MARKET_RE.match(path or "/")
    return path[m.end():] or "/" if m else (path or "/")


def _with_market(path: str, market: Optional[str]) -> str:
    bare = _strip_market(path)
    if not market:
        return bare
    return "/" + market + ("" if bare == "/" else bare)


def with_market(url: str, market: Optional[str]) -> str:
    """`url` re-addressed to `market` (None or the default = the bare path)."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    if market == DEFAULT_LOCALE:
        market = None
    return urlunsplit(parts._replace(path=_with_market(parts.path, market)))


def is_supported_url(url: str) -> Tuple[bool, str]:
    """(supported, reason).  The reason is shown to the user verbatim.

    Refusing WITH the reason matters: "is not an Andie Swim site" would
    be false for `andieswim.com/pages/about` and sends the reader hunting for
    a typo in a hostname that was correct.
    """
    if not url:
        return False, "no URL given"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, "%r is not an http(s) URL" % (url,)
    host = (parsed.hostname or "").lower()
    if host not in HOSTS:
        return False, ("%s is not an andieswim.com host (this scraper reads "
                       "%s)" % (host or "that URL", " and ".join(HOSTS)))
    market = market_from_url(url)
    if market and not market_is_well_formed(market):
        return False, "%r is not a market prefix this store publishes" % (market,)
    path = _strip_market(parsed.path or "/")
    if _COLLECTION_PATH_RE.match(path):
        handle = collection_from_url(url)
        if handle in _NOT_A_COLLECTION:
            return False, ("/collections/%s is an account route, not a "
                           "catalogue" % (handle,))
        return True, ""
    if _PRODUCT_PATH_RE.match(path):
        return True, ""
    if _SEARCH_PATH_RE.match(path):
        return True, ""
    return False, ("%s is a page on andieswim.com but not a collection, "
                   "product or search URL — this scraper reads "
                   "/collections/…, /products/… and /search" % (parsed.path,))


def is_collection_url(url: str) -> bool:
    return bool(_COLLECTION_PATH_RE.match(_strip_market(urlparse(url or "").path)))


def is_product_url(url: str) -> bool:
    return bool(_PRODUCT_PATH_RE.match(_strip_market(urlparse(url or "").path)))


def is_search_url(url: str) -> bool:
    return bool(_SEARCH_PATH_RE.match(_strip_market(urlparse(url or "").path)))


def collection_from_url(url: str) -> Optional[str]:
    m = _COLLECTION_PATH_RE.match(_strip_market(urlparse(url or "").path))
    return m.group(1).lower() if m else None


def handle_from_url(url: str) -> Optional[str]:
    """The product handle in a `/products/…` URL.

    Shopify's handle IS the id a reader can act on, and it is in the URL, so
    there is no id-recovery regex to write beyond this.  The numeric
    product id is in the payload and is carried separately.
    """
    m = _PRODUCT_PATH_RE.match(_strip_market(urlparse(url or "").path))
    return m.group(1).lower() if m else None


def sku_from_url(url: Optional[str]) -> Optional[str]:
    """Family-named alias for `handle_from_url`.

    Kept because `diff_runs.py` and the suite both expect every repo to be
    able to recover an id from a URL under this name.
    """
    return handle_from_url(url or "")


def search_query_from_url(url: str) -> Optional[str]:
    q = dict(parse_qsl(urlparse(url or "").query)).get("q")
    return q or None


def mode_for_url(url: str) -> Optional[str]:
    if is_product_url(url):
        return "product"
    if is_search_url(url):
        return "search"
    if is_collection_url(url):
        return "listing"
    return None


def canonical_url(url: str) -> str:
    """The URL rebuilt on the canonical host, market prefix preserved."""
    p = urlparse(url)
    return urlunparse((p.scheme or "https", CANONICAL_HOST, p.path,
                       "", p.query, ""))


def product_url(handle: str, market: Optional[str] = None) -> str:
    return "https://%s%s" % (CANONICAL_HOST,
                             _with_market("/products/%s" % (handle,), market))


def collection_url(handle: str, market: Optional[str] = None) -> str:
    return "https://%s%s" % (CANONICAL_HOST,
                             _with_market("/collections/%s" % (handle,), market))


# ---------------------------------------------------------------------------
# The endpoints the engines actually fetch
# ---------------------------------------------------------------------------

def listing_endpoint(url: str, page: int = 1, limit: int = PAGE_SIZE) -> str:
    """`/collections/{handle}/products.json` for a collection URL.

    Query params on the human URL are DROPPED rather than forwarded.  The
    storefront JSON endpoint understands `limit` and `page` and nothing else:
    a `?sort_by=best-selling` carried over would be silently ignored, which
    would put a `sort` in the sidecar that the fetch never applied (never
    present a guess as a fact).  `sort_from_url` reads it for reporting and
    `listing_sort_is_applied()` says plainly that it is not.
    """
    handle = collection_from_url(url)
    if not handle:
        raise ValueError("not a collection URL: %r" % (url,))
    market = market_from_url(url)
    limit = max(1, min(int(limit or PAGE_SIZE), MAX_PAGE_SIZE))
    path = _with_market("/collections/%s/products.json" % (handle,), market)
    return "https://%s%s?%s" % (
        CANONICAL_HOST, path,
        urlencode({LIMIT_PARAM: limit, PAGE_PARAM: max(1, int(page or 1))}))


def product_endpoint(url: str) -> str:
    """`/products/{handle}.js` for a product URL.

    `.js` rather than `.json`, and the choice was made the wrong way round
    first — the reversal is worth recording because the two documents each
    carry something the other does not:

        /products/{h}.js      per-variant `available`      NO currency
                              prices in INTEGER CENTS
        /products/{h}.json    `variants[].price_currency`  NO `available`
                              prices as a decimal string     AT ALL

    Availability wins, because it is the question `--mode product` exists to
    answer. 116 of 180 one-pieces are available in SOME sizes and not others,
    1 is sold out entirely, and a listing row cannot say which — that is the
    only thing a product document adds that the listing does not already have
    at a fraction of the requests. A product run off `.json` returns seven
    rows with `in_stock: null`, which is honest and useless.

    Currency is not lost by choosing `.js`: the engines read it once per run
    from `Shopify.currency.active` on the market's own HTML, which is the
    same fact one step further from the price (a written code rather than structured data)
    and is what a listing run already relies on.

    The unit difference is the trap and it is handled in the parser rather
    than here: `.js` prices in integer cents, so 11200 is $112.00 and reading
    it as a decimal string publishes a $11,200 swimsuit. `payload_is_cents()`
    decides from the payload's own shape, not from this URL, because a
    `--dump-html` replay arrives without one.
    """
    handle = handle_from_url(url)
    if not handle:
        raise ValueError("not a product URL: %r" % (url,))
    market = market_from_url(url)
    return "https://%s%s" % (CANONICAL_HOST,
                             _with_market("/products/%s.js" % (handle,), market))


def search_endpoint(query: str, limit: int = 10,
                    market: Optional[str] = None) -> str:
    """Shopify's predictive-search endpoint.

    Capped by Shopify at 10 resources per type — `resources[limit]=50`
    returns 10.  That cap is the site's, is reported in the sidecar as
    `capped_by_site`, and is why `--mode search` is a lookup rather than a
    catalogue walk: for the catalogue use `--mode listing` on
    `/collections/all`.
    """
    limit = max(1, min(int(limit or 10), SEARCH_MAX_RESULTS))
    path = _with_market("/search/suggest.json", market)
    q = urlencode({"q": query, "resources[type]": "product",
                   "resources[limit]": limit})
    return "https://%s%s?%s" % (CANONICAL_HOST, path, q)


SEARCH_MAX_RESULTS = 10

def collection_endpoint(handle: str, market: Optional[str] = None) -> str:
    """`/collections/{handle}.json` — ONE collection, by name.

    This replaced a walk of the whole collection index, and the saving is the
    point: the index pages at 250, the store publishes 834 collections, so
    answering "does this handle exist" by walking it cost **five requests and
    about a megabyte on every run**, including every run that was never going
    to need the answer. Measured 2026-10-13: 7 preflight requests to fetch
    one page of 5 products.

    This endpoint answers the same question exactly and unambiguously in 536
    bytes:

        /collections/one-pieces.json          HTTP 200, products_count 472
        /collections/does-not-exist.json      HTTP 404, ZERO bytes

    Note the 404, which is what makes it better rather than merely cheaper.
    The index walk could only ever report "the handle was not among the ones
    I managed to read", so a truncated walk and a missing collection looked
    the same. Here the store says outright that the route is not there — and
    it is the only route on this store that says so about a collection, since
    `/collections/{bogus}/products.json` answers 200 with an empty list.

    It carries `products_count` too (472 for one-pieces, byte-identical to
    the index's figure), so the sidecar keeps `catalog_count` with no extra
    request — still NOT a count of products the storefront serves, and still
    planned from by nothing.
    """
    market = market or None
    return "https://%s%s" % (
        CANONICAL_HOST,
        _with_market("/collections/%s.json" % (handle,), market))


def parse_collection(text: str) -> Optional[Dict[str, Any]]:
    """The collection object from `/collections/{handle}.json`, or None.

    None means "the store did not answer with a collection" — a 404's empty
    body, or anything else. It deliberately does NOT distinguish "absent"
    from "unreadable" on its own: the caller has the HTTP status, which is
    the signal that separates them, and inventing the distinction here would
    be guessing from a shape.
    """
    payload = load_payload(text)
    if not isinstance(payload, dict):
        return None
    collection = payload.get("collection")
    return collection if isinstance(collection, dict) else None


def store_products_endpoint(market: Optional[str] = None,
                            limit: int = 1) -> str:
    """`/products.json` — the whole store, not one collection.

    Used for two things and neither is a catalogue walk: sampling ONE handle
    so the run can resolve the market's currency from a document that states
    it, and (by a caller who wants it) enumerating every published product.
    Verified 2026-09-18 by walking it: 250 + 250 + 250 + 22 = 772 distinct
    handles, page 5 empty, a strict superset of the sitemap's 753.
    """
    limit = max(1, min(int(limit or 1), MAX_PAGE_SIZE))
    path = _with_market("/products.json", market)
    return "https://%s%s?%s" % (CANONICAL_HOST, path,
                                urlencode({LIMIT_PARAM: limit}))


def product_json_endpoint(handle: str, market: Optional[str] = None) -> str:
    """`/products/{handle}.json` — the sibling of `product_endpoint`.

    NOT what `--mode product` fetches: this document omits `available`
    entirely, which is the column that mode exists to produce (see
    `product_endpoint`). It is here because it is the one place the store
    states a price's CURRENCY beside the price, which is the most trustworthy source, and the
    engines resolve a run's currency from it.

    Kept in this module rather than assembled in each engine: three copies of
    a URL shape is exactly the drift keeping site knowledge in one place prevents, and a currency
    read from a path one engine spelled differently is a silent wrong answer
    rather than a crash.
    """
    return "https://%s%s" % (
        CANONICAL_HOST,
        _with_market("/products/%s.json" % (handle,), market))


def endpoint_for(url: str, page: int = 1, limit: int = PAGE_SIZE) -> str:
    """The JSON address for whichever route this URL names."""
    if is_product_url(url):
        return product_endpoint(url)
    if is_search_url(url):
        return search_endpoint(search_query_from_url(url) or "",
                               market=market_from_url(url))
    return listing_endpoint(url, page=page, limit=limit)


def is_endpoint_url(url: str) -> bool:
    """Whether this address answers with JSON rather than a page.

    The engines branch on it to read `document.body.innerText` instead of
    `content()` — Chromium wraps a JSON document in its own viewer markup and
    `content()` there returns the viewer, not the payload.  Getting it wrong
    is silent: the viewer parses as "not a listing payload", which reads as
    an empty result rather than as a bug.
    """
    path = (urlparse(url or "").path or "").lower()
    return (path.endswith(".json") or path.endswith(".js")
            or path.endswith("/suggest.json"))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def page_url(url: str, page_num: int, limit: int = PAGE_SIZE) -> str:
    """Page N of this listing, as an address that can be fetched on its own.

    The listing is genuinely addressable — page 2 of `one-pieces` is a
    different set from page 1 — which is what makes `--concurrency` legal
    here.  Verified on 2026-09-18: `/products.json?limit=250&page=1..4`
    over the whole store returned 250 + 250 + 250 + 22 = 772 distinct
    handles, no repeats, page 5 empty.

    Note what this does NOT do: walking off the end is FREE on this site.
    Page 5 answers 200 with `{"products":[]}` rather than the 500 bbb-scraper's site returns, so
    an overshoot costs a request and manufactures no error.  The terminating
    condition is therefore data — an empty array, or a page that added no new
    id — and never a selector.
    """
    if is_product_url(url) or is_search_url(url):
        return url
    return listing_endpoint(url, page=page_num, limit=limit)


def page_number_from_url(url: str) -> Optional[int]:
    v = dict(parse_qsl(urlparse(url or "").query)).get(PAGE_PARAM)
    try:
        return max(1, int(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def pagination_is_addressable(url: str) -> bool:
    """Whether page N can be fetched without walking pages 1..N-1.

    True for collections, False for the two single-response routes.  A
    product or a predictive-search lookup is ONE response and has no page 2
    at all, so handing "page 3" of one to a worker would refetch page 1 and
    report its rows three times.
    """
    return is_collection_url(url) and not is_product_url(url)


# `sort_by` is a parameter of the HTML collection route.  The JSON endpoint
# does not take it — checked: `products.json?sort_by=price-ascending` returns
# the same order as without.  So a run reports the ordering it received
# rather than one it asked for, and `--sort` is deliberately absent from the
# engines (see README).  These exist so the sidecar can say so.
SITE_DEFAULT_SORT = "collection-default"


def sort_from_url(url: str) -> Optional[str]:
    return dict(parse_qsl(urlparse(url or "").query)).get("sort_by") or None


def listing_sort_is_applied(url: str) -> bool:
    """False whenever a `sort_by` was present: the endpoint ignores it.

    Reported rather than silently dropped.  Sibling repos make ordering a
    COLUMN because it decides WHICH rows are in a capped file; here nothing
    is capped — a listing run fetches every published product in the
    collection — so ordering decides `position` only, and two runs under
    different `sort_by` values hold the same rows.  That is worth stating
    because it is the opposite of the sibling repo's situation.
    """
    return sort_from_url(url) is None


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

_ISO_4217 = frozenset("""
AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB
BRL BSD BTN BWP BYN BZD CAD CDF CHF CLP CNY COP CRC CUP CVE CZK DJF DKK DOP
DZD EGP ERN ETB EUR FJD FKP GBP GEL GHS GIP GMD GNF GTQ GYD HKD HNL HRK HTG
HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR KMF KPW KRW KWD KYD KZT
LAK LBP LKR LRD LSL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN MYR
MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB
RWF SAR SBD SCR SDG SEK SGD SHP SLE SOS SRD SSP STN SVC SYP SZL THB TJS TMT
TND TOP TRY TTD TWD TZS UAH UGX USD UYU UZS VES VND VUV WST XAF XCD XOF XPF
YER ZAR ZMW ZWL
""".split())


def is_currency_code(code: Optional[str]) -> bool:
    """An allowlist, never a bare `[A-Z]{3}`.

    Shopify publishes `price_currency` as a real code, so this is a guard
    against a malformed payload rather than against a size chart — but the
    guard is the same one and costs nothing.
    """
    return bool(code) and str(code).strip().upper() in _ISO_4217


# NOTE on the source NOT used here.
#
# Every HTML page this store serves carries
# `Shopify.currency = {"active":"GBP","rate":"0.76678"}`, which is the
# obvious place to read a market's currency from and is what this module did
# first.  It is wrong, and only running all three engines showed why: they
# disagreed on the same URL, two reporting USD where the third reported EUR.
#
# There is no HTTP redirect anywhere on this store — `curl -L` follows zero
# hops on every route — but the theme ships a CLIENT-SIDE geolocation app
# that rewrites the location to the visitor's own market after load.
# Measured 2026-09-18 from a Finnish address: `/collections/all` read at
# `domcontentloaded` says USD, and the same URL read after a full load has
# become `/en-fi/collections/all` and says EUR.  One address, two answers,
# decided by how long the engine happened to wait.
#
# So currency is read from a JSON document instead (`payload_currency`
# below), which runs no JavaScript, cannot be redirected that way, and is
# Structured data rather than a written code — stated beside the price it belongs to.
# A `page_currency()` reader was written, used, and then deleted rather than
# left in place as a fallback: a second source that can disagree with the
# first, silently, on a column whose whole job is to be trustworthy, is
# worse than no fallback.


def payload_currency(payload: Any) -> Optional[str]:
    """`variants[].price_currency` out of a `/products/{h}.json` document.

    This is the trustworthy source (structured data): the site states it as a fact
    beside the price it belongs to.
    """
    product = _as_product_object(payload)
    if not isinstance(product, dict):
        return None
    for v in product.get("variants") or []:
        if isinstance(v, dict) and is_currency_code(v.get("price_currency")):
            return str(v["price_currency"]).upper()
    return None


def _money(value: Any) -> Optional[float]:
    """A Shopify price to a float, or None.

    Three shapes are legal in these payloads and all three appear:
      "112.00"  decimal string          /products/{h}.json, products.json
      11200     integer cents           /products/{h}.js
      "21600"   decimal string, JPY     a zero-decimal currency
      ""        empty string            an ABSENT compare-at price
      None      explicit null           ditto

    The empty string is the one that bites: `float("")` raises, and a
    `.get(key, default)` never fires because the key is PRESENT.  Same shape
    as a JSON-LD `"offers": null`.

    Integers are NOT divided by 100 here.  Which shape a number is depends on
    which endpoint it came from, and the caller knows; guessing from
    magnitude would turn a ¥21600 price into ¥216.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _was_price(value: Any) -> Optional[float]:
    """A compare-at price, with ZERO read as ABSENT.

    `/search/suggest.json` writes `compare_at_price_min: "0.00"` for a
    product that is not on sale — measured: 8 of 10 results on one query
    carried "0.00" while the two genuinely reduced ones carried "72.00"
    against a 29.00 price and "52.00" against 31.00.  Written through, a
    was-price of zero is a claim that the product used to be free, and it
    would also make `discount_pct` meaningless.

    Same shape as the sibling repo's `rating: "" / ratingScore: 0.0`:
    a numeric field whose absent state is 0 rather than null, where the
    absence has to be recovered rather than read.  Unlike that case this site
    publishes no "should I show this" flag, so zero is the only signal and it
    is unambiguous here — nothing in this catalogue is free, and a genuine
    0.00 compare-at would be a merchandising error either way.
    """
    v = _money(value)
    if v is None or v <= 0:
        return None
    return v


def _cents(value: Any) -> Optional[float]:
    """A `/products/{h}.js` integer-cents amount to a major-unit float.

    Only ever called on the `.js` payload, where the unit is documented by
    the endpoint rather than inferred.
    """
    v = _money(value)
    return None if v is None else v / 100.0


def discount_pct(price: Optional[float],
                 original: Optional[float]) -> Optional[int]:
    """Whole-percent discount, or None when the pair is not a discount.

    None rather than 0 or a negative when `original` is missing, equal, or
    BELOW `price`.  Shopify lets a merchant leave a stale
    `compare_at_price` under the current price; read as a was-price that
    publishes a negative discount on a product that is not discounted at all.
    A canary assertion pins that no row carries an `original_price` at or
    below its `price`.
    """
    if price is None or original is None:
        return None
    if original <= 0 or price < 0 or original <= price:
        return None
    return int(round((original - price) / original * 100.0))


# ---------------------------------------------------------------------------
# Payload plumbing
# ---------------------------------------------------------------------------

# Chromium's JSON viewer opens its `<pre>` in the first few hundred bytes.
# 4 KB is a wide margin over every capture taken here and still leaves an
# 800 KB theme page costing a single bounded scan.
_VIEWER_PROBE_BYTES = 4096
_JSON_VIEWER_PRE_RE = re.compile(r"<pre\b[^>]*>", re.I)


def load_payload(text: str) -> Optional[Any]:
    """Parse an endpoint response, tolerating what a browser hands back.

    Returns None — never `{}` or `[]` — when the text is not the JSON this
    site serves.  A function returning an empty container on failure is this
    codebase's most common historical bug class: the caller cannot tell
    "no products" from "we were handed a challenge page".

    Chromium's JSON viewer is the reason for the strip: even read through
    `innerText` the text can arrive with leading/trailing whitespace, and a
    `--dump-html` capture replayed through the parser can arrive wrapped in
    `<pre>`.
    """
    if not text:
        return None
    s = text.strip()
    if s.startswith("<"):
        # An HTML document reached a JSON reader.  That happens on a 404 (the
        # store answers its HTML 404 page at `/collections/x`), on any
        # interstitial, and on a `--dump-html` capture taken through
        # Chromium's JSON viewer, which wraps the payload in a `<pre>`.
        #
        # Only the last of those is recoverable, and it is recognisable
        # CHEAPLY: the viewer opens its `<pre>` within the first few hundred
        # bytes.  The first version of this ran an HTML parser over the whole
        # document to find that tag, which cost **74 ms on a 793 KB theme
        # page** — measured — on a function the classifier calls for every
        # fetch.  Bounding the search to the head of the document makes a
        # real page cost nothing and still recovers every viewer capture.
        m = _JSON_VIEWER_PRE_RE.search(s[:_VIEWER_PROBE_BYTES])
        if not m:
            return None
        end = s.find("</pre>", m.end())
        s = (s[m.end():end] if end != -1 else s[m.end():]).strip()
        s = _html.unescape(s)
        if not s:
            return None
    if not (s.startswith("{") or s.startswith("[")):
        return None
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return None


def _as_product_object(payload: Any) -> Optional[Dict[str, Any]]:
    """The product dict out of any of the three shapes that carry one.

      /products/{h}.json  ->  {"product": {...}}
      /products/{h}.js    ->  {...}
      a listing element   ->  {...}
    """
    if not isinstance(payload, dict):
        return None
    if isinstance(payload.get("product"), dict):
        return payload["product"]
    if "variants" in payload and "handle" in payload:
        return payload
    return None


def _products_in(payload: Any) -> Optional[List[Dict[str, Any]]]:
    """The product list out of a listing or search payload, or None.

    None means "this is not a listing payload"; an empty LIST means "this
    listing has no products", and the two want different answers from the
    caller (tell a broken parser apart from an empty category).
    """
    if isinstance(payload, dict):
        if isinstance(payload.get("products"), list):
            return [p for p in payload["products"] if isinstance(p, dict)]
        # /search/suggest.json
        res = payload.get("resources")
        if isinstance(res, dict):
            results = res.get("results")
            if isinstance(results, dict) and isinstance(results.get("products"), list):
                return [p for p in results["products"] if isinstance(p, dict)]
    return None


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = _html.unescape(str(value)).strip()
    return s or None


def _image_url(product: Dict[str, Any]) -> Optional[str]:
    """The product's first image, from whichever of the shapes is present.

    Shopify ships three legal spellings across these endpoints and a naive
    read gets None on two of them:
      products.json      images: [{"src": "..."}]
      /products/{h}.js   featured_image: "//cdn.shopify.com/..." (string)
      suggest.json       featured_image: "https://..." | image: "..."
    Protocol-relative URLs are made absolute so a row carries something a
    reader can open.
    """
    def _abs(u: Optional[str]) -> Optional[str]:
        u = _text(u)
        if not u:
            return None
        if u.startswith("//"):
            return "https:" + u
        return u

    images = product.get("images")
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, dict):
            got = _abs(first.get("src") or first.get("url"))
            if got:
                return got
        elif isinstance(first, str):
            got = _abs(first)
            if got:
                return got
    fi = product.get("featured_image")
    if isinstance(fi, dict):
        got = _abs(fi.get("src") or fi.get("url"))
        if got:
            return got
    got = _abs(fi if isinstance(fi, str) else None)
    if got:
        return got
    img = product.get("image")
    if isinstance(img, dict):
        return _abs(img.get("src") or img.get("url"))
    return _abs(img if isinstance(img, str) else None)


def _option_names(product: Dict[str, Any]) -> List[str]:
    """The product's own option names, in the order the variants use.

    Two legal shapes, both present in this store's payloads:
      products.json / .json   options: [{"name":"Color","position":1}, ...]
      /products/{h}.js        options: ["Color", "Size"]   (bare strings)
    """
    out: List[str] = []
    for o in product.get("options") or []:
        if isinstance(o, dict):
            name = _text(o.get("name"))
        else:
            name = _text(o)
        out.append(name or "")
    return out


def option_value(product: Dict[str, Any], variant: Dict[str, Any],
                 wanted: str) -> Optional[str]:
    """A named option's value on this variant, matched case-insensitively.

    By NAME, never by position.  `option2` is Size on 622 of 665 products and
    is `Color` on a `('Rate','Color','Length')` gift card — reading it
    positionally writes a colour into the size column, silently, on exactly
    the rows nobody checks.
    """
    names = _option_names(product)
    for i, name in enumerate(names, start=1):
        if name.strip().lower() == wanted.strip().lower():
            return _text(variant.get("option%d" % (i,)))
    return None


def base_sku(product: Dict[str, Any]) -> Optional[str]:
    """The style code shared by a product's variants — `AO292` of
    `AO292-BLK-XS`.

    None when the variants do not agree on one, which is 52 of 665 products
    measured: a bundle or a multi-style set legitimately has no single style
    code, and inventing one by taking the first variant's would make two
    unrelated products look related in a diff.
    """
    prefixes = set()
    for v in product.get("variants") or []:
        if not isinstance(v, dict):
            continue
        sku = _text(v.get("sku"))
        if not sku:
            continue
        prefixes.add(sku.split("-", 1)[0])
    if len(prefixes) == 1:
        return prefixes.pop()
    return None


def _product_type(product: Dict[str, Any]) -> Optional[str]:
    """Shopify's product type, under either of the two names it ships under.

    `product_type` on the listing and product endpoints, `type` on
    `/search/suggest.json`.  Reading only the first leaves the column null on
    every search row while the listing rows are 100% populated, which looks
    like a site quirk rather than like a missed key.
    """
    return _text(product.get("product_type")) or _text(product.get("type"))


def _tags(product: Dict[str, Any]) -> Optional[str]:
    """The product's tags, joined.

    Shopify gives a list here and a comma-joined string on some endpoints;
    both are flattened to one pipe-joined string so the CSV column has one
    shape.  Pipe rather than comma because the tags themselves contain
    commas ("bust-support:medium bust support").
    """
    t = product.get("tags")
    if isinstance(t, list):
        vals = [x for x in (_text(v) for v in t) if x]
    elif isinstance(t, str):
        vals = [x for x in (_text(v) for v in t.split(",")) if x]
    else:
        return None
    return " | ".join(vals) or None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _variant_prices(product: Dict[str, Any], cents: bool
                    ) -> Tuple[Optional[float], Optional[float],
                               Optional[float], bool]:
    """(price, price_max, original_price, varies) across a product's variants.

    `price` is the MINIMUM, which is what a shopper sees on the tile and what
    a price monitor should track.  `price_max` is written only when the
    variants genuinely disagree — 0 of 180 one-pieces, 13 of 85 accessories —
    so a populated `price_max` is a fact about the product, not noise on
    every row.

    `original_price` is the compare-at belonging to the variant that set
    `price`, not the maximum compare-at on the product: pairing the cheapest
    size's price with the priciest size's was-price manufactures a discount.
    """
    conv = _cents if cents else _money
    was = (lambda x: (None if _cents(x) is None or _cents(x) <= 0
                      else _cents(x))) if cents else _was_price
    best: Optional[Tuple[float, Optional[float]]] = None
    highest: Optional[float] = None
    for v in product.get("variants") or []:
        if not isinstance(v, dict):
            continue
        p = conv(v.get("price"))
        if p is None:
            continue
        o = was(v.get("compare_at_price"))
        if best is None or p < best[0]:
            best = (p, o)
        highest = p if highest is None else max(highest, p)
    if best is not None:
        price, original = best
        varies = highest is not None and highest > price
        return price, (highest if varies else None), original, varies

    # No variants at all.  `/search/suggest.json` is that shape — it ships
    # `variants: []` on every result, measured on 10 of 10 — and publishes
    # the arithmetic at the PRODUCT level instead.  Without this branch a
    # search run returns ten rows with a null price and looks healthy.
    price = conv(product.get("price_min"))
    if price is None:
        price = conv(product.get("price"))
    if price is None:
        return None, None, None, False
    highest = conv(product.get("price_max"))
    original = was(product.get("compare_at_price_min"))
    if original is None:
        original = was(product.get("compare_at_price"))
    varies = highest is not None and highest > price
    return price, (highest if varies else None), original, varies


def _availability(product: Dict[str, Any]) -> Tuple[Optional[bool], int, int]:
    """(in_stock, available_variants, total_variants).

    `in_stock` is True when ANY variant is available, which is what "can I
    buy this product" means.  It is genuinely a mixed column here rather than
    a constant nobody has seen take its other value: measured on
    one-pieces, 63 products had every size available, 116 had some, and 1
    has none.

    None — not False — when the payload states availability for no variant at
    all.  `/products/{h}.json` is that case: it omits `available` entirely,
    so a product read from it must not claim to be out of stock.
    """
    total = 0
    known = 0
    avail = 0
    for v in product.get("variants") or []:
        if not isinstance(v, dict):
            continue
        total += 1
        if "available" in v and v["available"] is not None:
            known += 1
            if bool(v["available"]):
                avail += 1
    if known == 0:
        # The search shape carries no variants and states availability once,
        # for the product.  `/products/{h}.json` states it nowhere at all and
        # must stay None rather than claim the product is out of stock.
        top = product.get("available")
        if total == 0 and top is not None:
            return bool(top), (1 if top else 0), 0
        return None, 0, total
    return (avail > 0), avail, total


def _row(product: Dict[str, Any], *, url: str, market: Optional[str],
         mode: str, page: Optional[int], position: Optional[int],
         currency: Optional[str], collection: Optional[str],
         cents: bool, price_source: str) -> Product:
    handle = _text(product.get("handle"))
    price, price_max, original, varies = _variant_prices(product, cents)
    in_stock, n_avail, n_total = _availability(product)
    return Product(
        url=product_url(handle, market) if handle else canonical_url(url),
        sku=_text(product.get("id")),
        title=_text(product.get("title")),
        brand=_text(product.get("vendor")),
        price=price,
        currency=currency,
        in_stock=in_stock,
        image_url=_image_url(product),
        category=_product_type(product),
        price_source=price_source,
        page=page,
        position=position,
        mode=mode,
        locale=market or DEFAULT_LOCALE,
        product_id=_text(product.get("id")),
        handle=handle,
        base_sku=base_sku(product),
        product_type=_product_type(product),
        original_price=original,
        discount_pct=discount_pct(price, original),
        price_max=price_max,
        price_varies=varies,
        variants_total=n_total,
        variants_available=n_avail,
        tags=_tags(product),
        published_at=_text(product.get("published_at")),
        collection=collection,
        sort=SITE_DEFAULT_SORT,
    )


def _variant_rows(product: Dict[str, Any], *, url: str,
                  market: Optional[str], mode: str,
                  currency: Optional[str], cents: bool,
                  price_source: str) -> List[Product]:
    """One row PER VARIANT — the whole reason to open a product.

    A listing row says "this style is in stock"; only a variant row says
    which SIZE is.  116 of 180 one-pieces are partially available, so the
    size-level answer is the one a buyer or a monitor actually wants, and it
    exists nowhere on a listing.

    `sku` here is the variant's real SKU string (`AO292-BLK-XS`), not the
    product id: rows are variants, so the dedupe key must be unique per
    variant.  Verified unique within a run — 1137 of 1137 in one-pieces, 1487
    of 1487 in all-swimwear, and no SKU is shared between two different
    products across 665 products.  `diff_runs.py` refuses to compare a
    `product` run against a `listing` run for that reason.
    """
    conv = _cents if cents else _money
    handle = _text(product.get("handle"))
    rows: List[Product] = []
    base = base_sku(product)
    tags = _tags(product)
    image = _image_url(product)
    n_total = len([v for v in (product.get("variants") or [])
                   if isinstance(v, dict)])
    _, n_avail, _ = _availability(product)
    for position, v in enumerate(
            [v for v in (product.get("variants") or []) if isinstance(v, dict)],
            start=1):
        price = conv(v.get("price"))
        original = conv(v.get("compare_at_price"))
        available = (bool(v["available"])
                     if "available" in v and v["available"] is not None
                     else None)
        vcur = (v.get("price_currency")
                if is_currency_code(v.get("price_currency")) else None)
        rows.append(Product(
            url=product_url(handle, market) if handle else canonical_url(url),
            sku=_text(v.get("sku")) or _text(v.get("id")),
            title=_text(product.get("title")),
            brand=_text(product.get("vendor")),
            price=price,
            currency=(str(vcur).upper() if vcur else currency),
            in_stock=available,
            image_url=_image_url(v) or image,
            category=_product_type(product),
            price_source=price_source,
            page=1,
            position=position,
            mode=mode,
            locale=market or DEFAULT_LOCALE,
            product_id=_text(product.get("id")),
            handle=handle,
            base_sku=base,
            product_type=_product_type(product),
            original_price=original,
            discount_pct=discount_pct(price, original),
            price_max=None,
            price_varies=False,
            variants_total=n_total,
            variants_available=n_avail,
            tags=tags,
            published_at=_text(product.get("published_at")),
            collection=None,
            sort=SITE_DEFAULT_SORT,
            variant_id=_text(v.get("id")),
            variant_title=_text(v.get("title")) or _text(v.get("public_title")),
            color=option_value(product, v, "Color"),
            size=option_value(product, v, "Size"),
        ))
    return rows


# ---------------------------------------------------------------------------
# The two public entry points
# ---------------------------------------------------------------------------

@dataclass
class ListingPage:
    """One listing response: its rows, plus what the SITE said about the run.

    `products_returned` is what THIS response held, before dedupe — the only
    way to tell "the collection ended" (0) from "we were handed something
    that is not a listing" (None).

    `catalog_count` is the collection index's `products_count` and is
    deliberately NOT used to plan pages or to judge completeness.  It reports
    472 for a collection the storefront serves 180 of, and 3089 for one it
    serves 322 of, against a whole-store total of 772 published products.
    Whatever it counts, it is not products a visitor can reach.  It is
    carried so a reader can see the gap rather than discover it.
    """
    rows: List[Product]
    products_returned: Optional[int] = None
    page_number: Optional[int] = None
    page_size: Optional[int] = None
    collection: Optional[str] = None
    locale: Optional[str] = None
    currency: Optional[str] = None
    catalog_count: Optional[int] = None
    sort: Optional[str] = None
    site_default_sort: str = SITE_DEFAULT_SORT
    sort_applied: bool = True
    capped_by_site: bool = False


def parse_products(text: str, base_url: str = "", *, page: int = 1,
                   mode: str = DEFAULT_MODE,
                   currency: Optional[str] = None,
                   collection: Optional[str] = None) -> List[Product]:
    """Rows from a listing or search payload.

    REFUSES a single-product payload.  Calling the listing parser on a
    product document is the broken-parser failure with the arrow reversed: here it
    would not silently return a carousel, it would return one row whose
    `position` is 1 and whose page-level arithmetic is invented, so the run
    would look complete.  `smoke_test.py` pins both directions.
    """
    payload = load_payload(text)
    if payload is None:
        return []
    if _products_in(payload) is None and _as_product_object(payload):
        raise ValueError(
            "this is a single-product payload; use parse_product_detail()")
    products = _products_in(payload)
    if not products:
        return []
    market = market_from_url(base_url)
    # The search payload prices at the product level and the listing payload
    # at the variant level, so the provenance column has to say which one a
    # number came from — they are not the same measurement.
    is_search = mode == "search" or is_search_url(base_url)
    rows: List[Product] = []
    for position, product in enumerate(products, start=1):
        if not _text(product.get("handle")):
            # Shopify has never served one of these in 665 measured products.
            # Skipping rather than emitting a row with no address, because a
            # row whose `url` points at the collection is the URL failure that
            # makes every row look right and point at the wrong page.
            continue
        rows.append(_row(product, url=base_url, market=market, mode=mode,
                         page=page, position=position, currency=currency,
                         collection=collection, cents=False,
                         price_source=("search_json" if is_search
                                       else "products_json")))
    return rows


def parse_listing(text: str, base_url: str = "", *, page: int = 1,
                  mode: str = DEFAULT_MODE, currency: Optional[str] = None,
                  collection: Optional[str] = None,
                  catalog_count: Optional[int] = None,
                  page_size: int = PAGE_SIZE) -> ListingPage:
    """`parse_products`, with the page-level facts the engines plan from.

    The engines call this rather than `parse_products` directly, so the
    site's own arithmetic reaches the sidecar by default instead of only when
    someone remembers to read it.
    """
    payload = load_payload(text)
    products = _products_in(payload) if payload is not None else None
    rows = parse_products(text, base_url, page=page, mode=mode,
                          currency=currency,
                          collection=collection or collection_from_url(base_url))
    is_search = is_search_url(base_url) or mode == "search"
    return ListingPage(
        rows=rows,
        products_returned=(len(products) if products is not None else None),
        page_number=page,
        page_size=page_size,
        collection=collection or collection_from_url(base_url),
        locale=market_from_url(base_url) or DEFAULT_LOCALE,
        currency=currency,
        catalog_count=catalog_count,
        sort=sort_from_url(base_url),
        sort_applied=listing_sort_is_applied(base_url),
        # Predictive search is capped by Shopify at 10 results per type,
        # measured.  A listing is not capped at all: every published product
        # in the collection is reachable by walking `page`.
        capped_by_site=bool(is_search and products
                            and len(products) >= SEARCH_MAX_RESULTS),
    )


def parse_product_detail(text: str, base_url: str = "", *,
                         mode: str = "product",
                         currency: Optional[str] = None) -> List[Product]:
    """One row per variant, from `/products/{h}.json` or `/products/{h}.js`.

    Which endpoint it was is detected from the payload rather than from the
    URL, because `--dump-html` replays go through here too: the `.js`
    document prices in integer CENTS and the `.json` document in a decimal
    string, and reading one as the other is a factor of 100 in a price
    column, silently, on every row.

    REFUSES a listing payload for the mirror of the reason `parse_products`
    refuses a product one.
    """
    payload = load_payload(text)
    if payload is None:
        return []
    if _products_in(payload) is not None:
        raise ValueError("this is a listing payload; use parse_products()")
    product = _as_product_object(payload)
    if not product:
        return []
    cents = payload_is_cents(payload)
    cur = currency or payload_currency(payload)
    return _variant_rows(product, url=base_url,
                         market=market_from_url(base_url), mode=mode,
                         currency=cur, cents=cents,
                         price_source="product_js" if cents else "product_json")


def payload_is_cents(payload: Any) -> bool:
    """Whether this product document prices in integer cents.

    The `.js` endpoint does and the `.json` endpoint does not, and the
    distinguishing feature is the TYPE Shopify used, not the magnitude: 21600
    is a legitimate JPY price in `.json` and a legitimate $216.00 in `.js`.

    `.js` is identified positively — it carries `price_min`/`price_max` and
    `description`, which `.json` does not — rather than by "the price is an
    int", so a `.json` document that happens to hold an integer price cannot
    be divided by 100.
    """
    product = _as_product_object(payload)
    if not isinstance(product, dict):
        return False
    if isinstance(payload, dict) and isinstance(payload.get("product"), dict):
        return False          # {"product": {...}} is only ever the .json shape
    return ("price_min" in product or "price_max" in product
            or "description" in product)


# ---------------------------------------------------------------------------
# The collection index — what makes "empty" distinguishable from "wrong"
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Classification inputs
# ---------------------------------------------------------------------------

# Vendor markers for an interstitial.  Counted on pages this store is KNOWN to
# serve before any was added, across the captures in
# ../captures/andieswim/:
#
#   marker                      served pages   refusals seen
#   challenges.cloudflare.com        0              n/a
#   datadome / _px / px-captcha      0              n/a
#   incapsula / _Incapsula_          0              n/a
#
# `cf-turnstile` is deliberately ABSENT.  It is the obvious marker for a
# Turnstile and is measured useless in any repo that can reach the Scraping
# Browser, whose auto-solve extension injects
# `data-ts-input="cf-turnstile-response"` into every page it loads.  `challenges.cloudflare.com` is the one that works.
#
# `hcaptcha` is likewise ABSENT, and this one is specific to this site: the
# store ships Shopify's storefront-forms hCaptcha bundle
# (`ce_storefront_forms_captcha_hcaptcha…iife.js`) on EVERY page it serves,
# bound to form submits.  Counted: 1 occurrence on five of five served pages
# and on zero refusals, because no refusal has ever been observed.  A marker
# that fires on every good page is worse than no marker — it would make
# every successful run report exit 3.
BOT_CHALLENGE_MARKERS = (
    ("challenges.cloudflare.com", "cloudflare"),
    ("/cdn-cgi/challenge-platform", "cloudflare"),
    ("captcha-delivery.com", "datadome"),
    ("geo.captcha-delivery", "datadome"),
    ("px-captcha", "perimeterx"),
    ("_Incapsula_Resource", "incapsula"),
    ("Request unsuccessful. Incapsula", "incapsula"),
    ("awswaf", "aws-waf"),
)

# An interstitial is not built out of the site's own assets; a page the store
# served is (proven again on tokopedia against Chromium's own error page).  `cdn.shopify.com` appears 18 times on a real collection page and 25
# on the homepage; Chromium's network-error page carries the site's HOSTNAME
# in its `<title>` and none of its assets, which is exactly the case a title
# check gets wrong.
_ASSET_MARKER = "cdn.shopify.com"
_MIN_ASSET_REFERENCES = 2

# The JSON routes carry no assets at all, so the asset test must never be
# applied to them — a valid 890 KB products.json has zero `cdn.shopify.com`
# references in its markup sense and would classify as blocked.  Image URLs
# inside it DO contain the host, which is worse: it would pass for the wrong
# reason on a listing and fail on an empty one.
_UNESCAPE_PREFIX = 20_000


def detect_bot_challenge(html: str, url: str = "") -> Optional[str]:
    """The vendor named by a marker in this document, or None.

    Entities are normalised over a bounded prefix before matching: an
    edge can entity-escape the punctuation in its own refusal URL, so a
    literal marker matches a browser's DOM and silently misses the same page
    read by an HTTP client.  Bounded because a refusal page is a few hundred
    bytes and unescaping 890 KB of catalogue on every fetch buys nothing and
    risks a product title reading as a marker.
    """
    if not html:
        return None
    head = html[:_UNESCAPE_PREFIX]
    try:
        head = _html.unescape(head)
    except Exception:                                  # pragma: no cover
        pass
    haystack = head.lower()
    for marker, vendor in BOT_CHALLENGE_MARKERS:
        if marker.lower() in haystack:
            return vendor
    return None


def references_own_assets(html: str) -> int:
    """How many times this document references the store's own asset host."""
    return (html or "").count(_ASSET_MARKER)


def looks_like_a_served_page(html: str) -> bool:
    return references_own_assets(html) >= _MIN_ASSET_REFERENCES


def payload_is_listing(text: str) -> bool:
    """Whether this text is a listing payload the store served.

    The positive signal for a JSON route, and it is UNAMBIGUOUS where the
    asset count is a heuristic — so it is checked first (order
    signals by how much they prove, not by how cheap they are).  An empty `{"products": []}` is a served
    listing and returns True; it is empty, not blocked.
    """
    payload = load_payload(text)
    return payload is not None and _products_in(payload) is not None


def payload_is_product(text: str) -> bool:
    payload = load_payload(text)
    return payload is not None and _as_product_object(payload) is not None


def product_link_count(html: str) -> int:
    """How many distinct product addresses this document names.

    Used to tell a served-but-unparsed document from an empty one: a
    document that links to products and parses to zero rows is OUR bug, not
    an empty collection.

    Counts JSON `"handle"` keys as well as `/products/…` hrefs, because on
    this site the thing being counted is usually a JSON payload and a listing
    response contains no anchors at all.
    """
    if not html:
        return 0
    hrefs = set(re.findall(r'/products/([a-z0-9][a-z0-9_-]*)', html, re.I))
    handles = set(re.findall(r'"handle"\s*:\s*"([a-z0-9][a-z0-9_-]*)"',
                             html, re.I))
    return len(hrefs | handles)


# ---------------------------------------------------------------------------
# Page state
# ---------------------------------------------------------------------------

# HTTP statuses this store uses, and what each one means here.  Measured
# 2026-09-18; the interesting one is the third.
#
#   200 on an HTML page        served
#   200 on a JSON endpoint     served — INCLUDING for a collection handle
#                              that does not exist, which answers
#                              `{"products": []}` rather than 404
#   404 on an HTML page        a route that is not there
#   404 on `/products/x.json`  a product handle that is not there
#
# No 403 and no 429 have ever been observed from this store, from any address
# or User-Agent, including twenty requests in 4.9 s.  They are still mapped,
# because the day one appears is the day the README's central claim stops
# being true and the run should say so rather than report a parse failure.
# The store's 404 template, matched on the BODY CLASS rather than on a bare
# substring and searched over the WHOLE document rather than over a prefix.
#
# Both details were bugs first.  The `<head>` on this theme is ~280 KB, so the
# `<body>` tag sits past any sane prefix bound and a 20 KB window never
# reached it — the marker was there and the check silently never fired.  And
# anchoring to `class="layout layout--404` rather than to `404` keeps it from
# matching a product whose title or tag happens to contain the digits; a
# scan over 635 KB costs about 5 ms (measured), which is the right price for
# a check whose failure mode is reporting a missing collection as a
# successfully-scraped empty one.
_NOT_FOUND_RE = re.compile(r'class="layout\s+layout--404\b'
                           r'|id="shopify-section-template--[0-9]+__404"')

_REFUSAL_STATUSES = frozenset({401, 403, 407, 451})

# A THROTTLE is not a refusal, and the two want opposite responses: a
# throttle wants a wait at the SAME exit, a refusal wants a different one.
# Counting 429 as blocked spends the block budget and a rotation on a page
# that was about to come back, and reports exit 3 to a reader who needs no
# proxy at all.
#
# Observed on this store 2026-10-13 by a third-party audit — Cloudflare's own
# `local_rate_limited`, 18 bytes, with `Retry-After: 60`. NOT reproduced from
# here that day: 30 requests in 5.9 s all answered 200, and a 3-page run was
# `complete`. So it is a real state of the edge rather than a property of the
# store's own rate policy, and it is handled rather than advertised.
_THROTTLE_STATUSES = frozenset({429, 503})

# Cloudflare's body for a per-colo rate limit. Kept as a SECONDARY signal
# only: the status is what decides, and this is what lets an engine with no
# status (Selenium) reach the same verdict. Counted on pages this store is
# known to serve: 0 occurrences across every capture.
_THROTTLE_MARKERS = ("local_rate_limited", "rate limited", "too many requests")
_SERVER_ERROR_STATUSES = frozenset({500, 502, 503, 504})


def detect_page_state(text: str, status: Optional[int] = None,
                      url: str = "") -> Tuple[str, Optional[str]]:
    """(state, detail) for whatever came back.

    ORDERED BY HOW MUCH EACH SIGNAL PROVES, not by how cheap it is.
    The unambiguous positive here is that the text IS one of this store's own
    JSON documents: nothing but Shopify serves `{"products": [...]}` at these
    addresses, and no interstitial or error page parses as one.  So that is
    tested first, ahead of the status and well ahead of any asset-count
    threshold — a sibling repo checked a heuristic first and reported exit 3
    for a correct answer on a page that happened to be minimal.

    An empty listing is `empty`, not `blocked`.  It is also not necessarily a
    real answer: a misspelt collection handle produces exactly the same
    document.  Telling those two apart needs the collection index, which this
    function does not have and should not fetch, so the engines do it — see
    `collection_endpoint`.  What this function guarantees is that the
    engines are never handed a false `blocked` to explain.
    """
    text = text or ""

    # 1. The site's own payloads — unambiguous, and cheap enough besides.
    if payload_is_listing(text):
        payload = load_payload(text)
        n = len(_products_in(payload) or [])
        return ("content" if n else "empty"), ("%d products" % (n,))
    if payload_is_product(text):
        return "content", "product payload"

    # 2. The store's own "this route is not here" template.
    #
    #    Checked BEFORE the status and not only after it, because Selenium
    #    exposes no status at all: without a structural marker a 404 read
    #    through chromedriver classifies as `content` (the 404 page is built
    #    out of the store's own assets like every other page) and the run
    #    reports a successfully-scraped empty collection.
    #
    #    `layout--404` and `template--404`, counted on a good page before either was
    #    added: 1 each on the 404 capture, 0 on the served collection page,
    #    which carries `layout--collection` in the same attribute.  The
    #    TEXT "not found" was rejected for this job — it appears once on the
    #    404 page and once on the good one, inside a script.
    if _NOT_FOUND_RE.search(text):
        return "not_found", "the store's 404 template"

    # 3. The status, where there is one.
    if status is not None:
        if status == 404:
            return "not_found", "HTTP 404"
        if status in _THROTTLE_STATUSES:
            # Wait, do not rotate, and do not solve. A throttle is the
            # one refusal whose right answer is patience at the same address.
            return "throttled", "HTTP %d" % status
        if status in _REFUSAL_STATUSES:
            vendor = detect_bot_challenge(text, url)
            return ("captcha" if vendor else "blocked"), (vendor or "HTTP %d" % status)
        if status in _SERVER_ERROR_STATUSES:
            # Retryable, and NOT blocked: a 5xx from Shopify is Shopify, and
            # spending a solve or a rotation on it buys nothing.
            return "unknown", "HTTP %d" % status

    # 4. A throttle body, for the engine that has no status to read.
    #    Selenium exposes none, so without this a 429 reaches it as 18 bytes
    #    of plain text and classifies as `unknown` — which RETRIES, which is
    #    the one thing a throttle must not do quickly.
    low = text[:_UNESCAPE_PREFIX].lower()
    for marker in _THROTTLE_MARKERS:
        if marker in low:
            return "throttled", marker

    # 5. A vendor marker.  Only consulted once the positive signals have
    #    failed: running it earlier lets it fire on a page the store
    #    plainly served and turn a correct answer into exit 3.
    vendor = detect_bot_challenge(text, url)
    if vendor:
        return "captcha", vendor

    # 6. An HTML document built out of the store's own assets is a page the
    #    store served — it just is not one of the JSON routes.  That is the
    #    `--mode product` HTML capture, and it is also what tells Chromium's
    #    own network-error page (which carries the site's HOSTNAME in its
    #    title and none of its assets) apart from a real one.
    if text.strip().startswith("<"):
        if looks_like_a_served_page(text):
            return "content", "html page"
        return "blocked", "an HTML document with none of the store's assets"

    if not text.strip():
        # How the JSON routes spell a missing handle: `/products/x.json`
        # answers 404 with a ZERO-BYTE body, so on the engines that see no
        # status an empty response is the only thing left to read.
        return ("not_found" if is_endpoint_url(url) else "unknown"), \
               "empty response"
    return "unknown", "not a document this store serves"
