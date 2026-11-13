"""
product_parser.py
-----------------
Everything this repo knows about Maison KOSÉ. If you are writing a site fact
anywhere else, it belongs here.

Which site this is, and why it is not `kose.com`
------------------------------------------------
`kose.com` is registered and does not resolve. Measured 2026-09-18: the .com
gTLD servers delegate it to `dns1.supremecenter.com` / `dns2.supremecenter.com`,
both of which answer **REFUSED** for the zone, so 8.8.8.8 and 1.1.1.1 both
return **SERVFAIL** and no client anywhere gets an address. It is a lame
delegation on a domain registered in 1998 and paid up to 2029, not a site
behind a bot manager — there is nothing at that name to scrape.

Kosé's actual storefront is `maison.kose.co.jp` (Maison KOSÉ), which is where
`www.kose.co.jp` sends a visitor with its own `<meta http-equiv="refresh">`.
That is the site this repo reads, and it is one market: Japanese, JPY, no
`hreflang` set and no `/en/` route (all three checked 2026-09-18). The "run a SECOND country site" step is therefore answered by "there is
only one", and the diversity in the fixtures is across BRANDS and page KINDS
instead — which is where this site's traps turned out to live.

Three routes, and the brand segment in all of them is a LIE
-----------------------------------------------------------
    category listing   /site/{brand}/c/{cNN}/        paginates  /c/{cNN}_p{N}/
    tag listing        /site/itemtags/list.aspx?tags=A,B   paginates  &p={N}
    product detail     /site/{brand}/g/g{SKU}/

The `{brand}` segment selects nothing. Measured 2026-09-18: `/site/xyz/c/c15/`,
`/site/jillstuart/c/c15/` and `/site/cosmedecorte/c/c15/` return **byte-identical**
97,017-byte responses, and the page's own `rel="canonical"` rewrites all of
them to `/site/cosmedecorte/c/c15/`. Same on a product: `/site/zzz/g/gJLCW/`
serves the Cosme Decorté product. Only `cNN` and `g{SKU}` address anything.

Two consequences, both of which bit during the capture pass:

* **`brand` is read from the TILE, never from the URL.** A capture requested
  as `sekkiseiclearwellness/c/c68/` came back holding 11 ウルミナプラス
  products — the slug was ignored and the fixture was misnamed for an hour.
  Fixtures are named by `cNN` for that reason. And a tag listing genuinely
  mixes brands: `tags_shiwa_skincare_p1` carries five in 24 tiles, so there
  is no per-page brand to fall back on even if the URL were honest.
* **`category_from_url` keys on `cNN`**, and `canonical_url` prefers the
  page's own canonical over the address that was requested.

Two pagination conventions, and one of them repeats its last page
-----------------------------------------------------------------
Both listing routes publish `<link rel="next">`, which is the
layer 1 and leads `NEXT_PAGE_SELECTOR`. Layer 2 is `page_url()`, and it is
route-dependent — a category takes `_p{N}` glued onto the id, a tag listing
takes `?p={N}`. Layer 3, the data-based stop, is not optional here, because
each route ends differently and one of them ends by lying:

    /c/c15_p13/  is the last page (16 tiles).
    /c/c15_p14/  returns 71,199 bytes  -- byte-identical to p13.
    /c/c15_p15/  returns 71,199 bytes  -- byte-identical to p13.

    ?p=4  is the last page (6 tiles).
    ?p=5  returns a served page with ZERO tiles.

So a category overshoot is not a 404 and not an empty page: it is the last
page again, forever. A run that stopped on "no tiles" would never stop, and a
run that trusted a page count would be fine only until the catalogue changed
under it. `parse_listing` reports the site's own `N／Mページ` counter so the
engines can PLAN against it (with the site doing the arithmetic),
and the engines still stop on "this page added no new sku".
Wrong parameters are silent rather than loud, which is the same trap from the
other side: `&pageno=2` and `&page=2` on a tag listing both return page 1
with HTTP 200.

Where the data is: no JSON-LD on a listing, one block on a product
-------------------------------------------------------------------
Counted before a line of parser was written step 2:

    listing pages    0 `application/ld+json` blocks   (all 8 captures)
    product pages    1 block, `@type: Product`        (all 4 captures)

So the primary path does not exist on the route that matters most,
and the listing parser is built on the site's own tile markup instead —
which here is unusually good: `li.c-product__item` holding
`p.c-product__brand`, `p.c-product__product-name`, `p.c-product__price` and
a `/g/g{SKU}/` link. Coverage over 171 tiles in 8 listing captures: sku,
title, brand, price, image and tax rate all **171/171**.

`li.` is not decoration — it is the whole guard
-----------------------------------------------
A product DETAIL page reuses the class `c-product__item` on a `<div>` for
staff-review cards linking to `/staff/skincaredetail/…`. Measured on
`product_MUSC`: **15** of them. A class-only selector would invent fifteen
products per detail page, each with a `/staff/` URL and no sku — the junk-link data theft wearing a new costume. The element-qualified
`li.c-product__item` sees zero, and `smoke_test.py` pins that.

The same page also carries an `awoo-product-list` recommendation block
(`awoo-product-name` ×15), which is the "similar products carousel" to watch for
about. Both are excluded by construction rather than by a filter: the tile
selector names the element, and the detail parser reads the page's own
JSON-LD, never tiles.

Prices: one number, tax-inclusive, and no discount chain to reconcile
---------------------------------------------------------------------
360 price nodes surveyed across the captures. Every one is a single amount
in one of these shapes, and there is **no struck-through price anywhere**:

    1,234円（税込）        249 + 51 + 31 of the sampled nodes, by magnitude
    1,234円（税込）※       the same, with the footnote marker
    3,024円（税込/8%）※    the reduced rate -- 2 nodes, both on /c/c15_p10/

So the tile-price overlay is **deleted rather than ported**, which is what
that section says to do when a site has no discount chain: there is no second
view to reconcile against, and an overlay here would be dead code that looks
load-bearing. `price_source` records WHICH NODE was read (`tile` / `jsonld` /
`detail_dom`) instead, which keeps `diff_runs.py` honest about comparing like
with like.

The structured and displayed prices AGREE, which was checked rather than
assumed: JLCW 7700/7,700円, MUSC 5940/5,940円, SIRY 3300/3,300円.

`※` is `Maison KOSÉ販売価格` — "the Maison KOSÉ selling price", the store's
own figure as opposed to a maker's suggested one. It is kept as
`price_is_store_price` rather than thrown away, because it says which of two
different things a number is.

`（税込/8%）` is Japan's reduced consumption-tax rate, which applies to
ingestible products — a beauty supplement sits at 8% while the cream beside
it is at 10%. It is a real column: two rows in 171 carry it, and a consumer
computing a pre-tax price from the wrong rate is wrong by two percent
silently.

Stock is read from the site's own button text, as an allowlist
---------------------------------------------------------------
Measured across the same 171 tiles, and this is the rule — map
availability as an ALLOWLIST so an unanticipated value reads as "not
available" rather than as a quiet True:

    種類を選ぶ         83   choose a variety      -> available
    カートに入れる      54   add to cart           -> available
    商品を購入する      12   purchase this product -> available
    予約受付中          3   pre-orders open       -> available
    現在購入頂けません   18   currently unavailable -> NOT available
    予約受付終了        1   pre-orders closed     -> NOT available

The column is verified in BOTH directions, which is otherwise not
verified at all: 19 of 171 tiles are unavailable, and the JSON-LD on
`gJQBA` independently says `OutOfStock` where its tile says 現在購入頂けません.

Detection: there is nothing to detect, and that is the measurement
-------------------------------------------------------------------
Every candidate marker was counted on pages known to be good BEFORE any was
added, across all 13 captures including the site's own 404 and an
empty listing:

    recaptcha · grecaptcha · g-recaptcha · data-sitekey · api.js?render ·
    hcaptcha · turnstile · cf-turnstile · challenges.cloudflare.com ·
    datadome · px-captcha · _Incapsula_ · perimeterx · kasada · awswaf ·
    "Request unsuccessful" · errors.edgesuite.net · "Access Denied" ·
    CAPTCHA_SITE_KEY · <captcha …>

**Zero occurrences of every one of them, on every capture.** So
`BOT_CHALLENGE_MARKERS` is a short list of shapes that would have to appear
if this site ever turned a challenge on — it is a tripwire, not a description
of something observed, and it is documented as such so nobody later reads it
as evidence that a challenge was met. The scan only ever REFINES the
reason for a page the policy already gave up on.

`cf-turnstile` is deliberately ABSENT from that list: 2Captcha's own
Scraping Browser auto-solve extension injects it into every page it loads, so
it fires on good pages and misses real ones. `challenges.cloudflare.com` is
the one that works, and it is what this list carries.

The positive structural signal is `/js/sys/`, which is the site's own script
directory: **9 to 11 references on every served page**, including the 404 and
the empty listing, and none on anything the site did not build. That is
the `assets.mmsrg.com` trick, which also answers Chromium's own
network-error page — it carries the site's hostname in its title and
would fool a title check.
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from output_writer import Product, SOURCE_DEFAULT, utc_now


# ---------------------------------------------------------------------------
# Hosts
# ---------------------------------------------------------------------------

# The store, and the only host this scraper reads. `www.kose.co.jp` is the
# CORPORATE site: it publishes no catalogue and redirects a visitor here with
# a meta refresh, so it is not a second host to support, it is a doorway.
HOSTS = ("maison.kose.co.jp",)
CANONICAL_HOST = "maison.kose.co.jp"

# A host that is a real Kosé property but NOT this site, kept so the refusal
# can say WHY rather than "unsupported host", which sends the reader hunting
# for a typo.
_OTHER_KOSE_HOSTS = {
    "www.kose.co.jp": "the Kosé corporate site, which publishes no catalogue "
                      "and redirects to maison.kose.co.jp",
    "kose.co.jp": "the Kosé corporate site, which publishes no catalogue "
                  "and redirects to maison.kose.co.jp",
    "koseholdings.co.jp": "Kosé's investor-relations site, which sells nothing",
    "kose.com.tw": "Kosé Taiwan, a separate site on a different platform",
    "sekkisei.jp": "a single-brand Kosé site on a different platform",
    "kose.com": "a registered domain with a broken delegation: its nameservers "
                "answer REFUSED and it resolves for nobody",
}

# 24 tiles per page on every listing route, measured on 8 captures. Only the
# LAST page of a listing carries fewer (16 on /c/c15_p13/, 6 on ?p=4).
PAGE_SIZE = 24


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# `/site/{brand}/c/{cNN}/` and `/site/{brand}/c/{cNN}_p{N}/`. The brand
# segment is optional in practice (`/site/c/c21/` is served) and ignored
# always -- see the module docstring.
_CATEGORY_RE = re.compile(r"^/site/(?:[^/]+/)?c/(c\d+)(?:_p(\d+))?/?$", re.I)

# The tag listing is the site's own faceted route and is an .aspx endpoint
# with a query string rather than a path.
_TAGLIST_PATH = "/site/itemtags/list.aspx"

# `/site/{brand}/g/g{SKU}/`. The leading `g` in the last segment is the
# route's marker and is NOT part of the sku: the JSON-LD on `/g/gJLCW/`
# publishes `"sku": "JLCW"`, and the site's own bookmark link on the tile
# says `?goods=JLCW`. Stripping it is what makes a row's `sku` join against
# the site's own id rather than against a URL artefact.
_PRODUCT_RE = re.compile(r"^/site/(?:[^/]+/)?g/g([A-Za-z0-9]+)/?$")

ROUTE_CATEGORY = "category"
ROUTE_TAGS = "tags"
ROUTE_PRODUCT = "product"


def _split(url: str):
    """`urlsplit`, tolerant of the three shapes a URL reaches this module in.

    A tile's href is ROOT-RELATIVE on a category listing
    ("/site/cosmedecorte/g/gJQBA/") and ABSOLUTE on a tag listing
    ("https://maison.kose.co.jp/site/…/g/gBAQQ/") — the same site, the same
    tile markup, two spellings. A bare "maison.kose.co.jp/site/…" is what a
    user types.

    The first version of this promoted anything without "//" to
    `https://` + the string, which turned "/site/x/g/gJQBA/" into a URL whose
    HOST was "site" and whose path had lost its first segment. Every category
    row then parsed to `sku=None` and was dropped: 24 tiles in, ZERO rows
    out, while `tile_count` went on reporting 24. That is this codebase's
    most common bug class (doing less than it says while reporting
    success) and it survived the first run because the tag fixtures, whose
    hrefs are absolute, passed throughout. The suite now pins both spellings.
    """
    if url.startswith("/"):
        return urlsplit(f"https://{CANONICAL_HOST}{url}")
    if "//" not in url:
        return urlsplit(f"https://{url}")
    return urlsplit(url)


def route_of(url: str) -> Optional[str]:
    """Which of the three routes this URL is, or None.

    Named rather than inferred at each call site: `page_url` and the engines
    both branch on it, and two copies of the branch would drift.
    """
    if not url:
        return None
    parts = _split(url)
    path = parts.path or "/"
    if _PRODUCT_RE.match(path):
        return ROUTE_PRODUCT
    if _CATEGORY_RE.match(path):
        return ROUTE_CATEGORY
    if path.lower() == _TAGLIST_PATH:
        return ROUTE_TAGS
    return None


def is_product_url(url: str) -> bool:
    return route_of(url) == ROUTE_PRODUCT


def is_listing_url(url: str) -> bool:
    return route_of(url) in (ROUTE_CATEGORY, ROUTE_TAGS)


def is_supported_url(url: str) -> Tuple[bool, str]:
    """`(ok, reason)`. The reason is for a human and names the real problem."""
    if not url or not url.strip():
        return False, "no URL given"
    parts = _split(url.strip())
    host = (parts.hostname or "").lower()
    if host in _OTHER_KOSE_HOSTS:
        return False, (f"{host} is {_OTHER_KOSE_HOSTS[host]}; this scraper "
                       f"reads {CANONICAL_HOST}")
    if host not in HOSTS:
        return False, f"{host or 'that host'} is not {CANONICAL_HOST}"
    route = route_of(url)
    if route is None:
        return False, (f"{parts.path or '/'} is not a Maison KOSÉ listing or "
                       f"product path: expected /site/…/c/cNN/, "
                       f"{_TAGLIST_PATH}?tags=… or /site/…/g/gSKU/")
    return True, route


def sku_from_url(url: Optional[str]) -> Optional[str]:
    """The site's own goods code, with the route's `g` prefix removed."""
    if not url:
        return None
    m = _PRODUCT_RE.match(_split(url).path or "")
    return m.group(1) if m else None


def category_from_url(url: str) -> Optional[str]:
    """The `cNN` id, which is the ONLY thing that selects a category.

    Deliberately not the brand slug beside it: `/site/xyz/c/c15/` serves the
    same bytes as `/site/cosmedecorte/c/c15/`, so a slug read as a category
    would be a value the site never agreed to.
    """
    m = _CATEGORY_RE.match(_split(url).path or "")
    return m.group(1) if m else None


def tags_from_url(url: str) -> Optional[List[str]]:
    """The tag listing's own `tags=` facet, as a list."""
    if route_of(url) != ROUTE_TAGS:
        return None
    for key, value in parse_qsl(_split(url).query, keep_blank_values=False):
        if key == "tags" and value:
            return [t for t in value.split(",") if t]
    return None


def brand_slug_from_url(url: str) -> Optional[str]:
    """The decorative brand segment, recorded for provenance only.

    It is in the URL a caller typed and it is NOT a fact about the products
    on the page, so it never reaches a row: `brand` comes off each tile.
    """
    parts = (_split(url).path or "").strip("/").split("/")
    if len(parts) >= 3 and parts[0] == "site" and parts[1] not in ("c", "g"):
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def page_url(url: str, page_num: int) -> str:
    """Layer 2 of pagination: page N's address, built from the convention.

    Route-dependent, because this site has two conventions and using the
    wrong one FAILS SILENTLY: `?p=2` paginates a tag listing while `&page=2`
    and `&pageno=2` are ignored and return page 1 with HTTP 200 (measured
    2026-09-18). A run that built the wrong URL would dedupe every page down
    to page 1's rows and report a complete run holding a single page.

    Page 1 is the bare URL on both routes -- `/c/c15/` and `/c/c15_p1/` are
    both served, but the site's own canonical and its `rel=next` chain use
    the bare form, so that is what this builds.
    """
    if page_num <= 1:
        return _strip_page(url)
    route = route_of(url)
    parts = _split(url)
    if route == ROUTE_CATEGORY:
        m = _CATEGORY_RE.match(parts.path)
        cat = m.group(1)
        prefix = parts.path[: m.start(1)]
        return urlunsplit((parts.scheme, parts.netloc,
                           f"{prefix}{cat}_p{page_num}/", parts.query,
                           parts.fragment))
    if route == ROUTE_TAGS:
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k != "p"]
        query.append(("p", str(page_num)))
        # `tags=` holds Japanese text and commas. `urlencode` would escape the
        # comma to %2C; the site's own links do not, and the endpoint is
        # happier with what it publishes. quote() with a safe comma keeps the
        # round trip byte-identical to the site's own href.
        encoded = "&".join(f"{quote(k)}={quote(v, safe=',')}" for k, v in query)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded,
                           parts.fragment))
    return url


def _strip_page(url: str) -> str:
    """The same listing at page 1."""
    parts = _split(url)
    route = route_of(url)
    if route == ROUTE_CATEGORY:
        m = _CATEGORY_RE.match(parts.path)
        if m and m.group(2):
            prefix = parts.path[: m.start(1)]
            return urlunsplit((parts.scheme, parts.netloc,
                               f"{prefix}{m.group(1)}/", parts.query,
                               parts.fragment))
        return url
    if route == ROUTE_TAGS:
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if k != "p"]
        encoded = "&".join(f"{quote(k)}={quote(v, safe=',')}" for k, v in query)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, encoded,
                           parts.fragment))
    return url


def page_number_from_url(url: str) -> Optional[int]:
    """Which page an address asks for. 1 where the convention is absent."""
    route = route_of(url)
    parts = _split(url)
    if route == ROUTE_CATEGORY:
        m = _CATEGORY_RE.match(parts.path)
        return int(m.group(2)) if m and m.group(2) else 1
    if route == ROUTE_TAGS:
        for key, value in parse_qsl(parts.query):
            if key == "p" and value.isdigit():
                return int(value)
        return 1
    return None


# "2／13ページ" -- the site's own counter, in the <title> and above the grid.
# The separator is the FULLWIDTH solidus U+FF0F, not an ASCII slash: a `/`
# here matches nothing, and the failure would be a silent loss of the site's
# own arithmetic rather than an error.
_PAGE_COUNTER_RE = re.compile(r"(\d+)／(\d+)\s*ページ")


def page_counter(html: str) -> Tuple[Optional[int], Optional[int]]:
    """`(current, total)` from the site's own counter, or `(None, None)`.

    Present on a category listing and ABSENT on a tag listing (checked on
    both: `tags_shiwa_skincare_p1` carries no counter at all), so None here
    means unknown and never zero -- treating it as zero would cap a tag run
    at no pages.
    """
    m = _PAGE_COUNTER_RE.search(html)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def total_pages(html: str) -> Optional[int]:
    return page_counter(html)[1]


# `pages_to_fetch` used to live here and was removed on 2026-09-18, because
# how many pages a RUN should ask for is policy rather than site knowledge
# and `page_flow.pages_to_plan` is the one implementation the engines
# call. What is site knowledge, and stays here, is that the site publishes a
# counter at all — `total_pages` above — and what that counter means when it
# is absent.
#
# Recorded rather than deleted silently: it was found by grepping every
# public name for a consumer outside its own module (the check #5), which
# turned it up as a function only its own test still called. A check that
# exercises something nothing uses passes for the wrong reason.


# `<link rel="next">` is published by both listing routes and is
# pagination's layer 1: a standards-based signal, ahead of any build artefact.
NEXT_PAGE_SELECTOR = ("link[rel='next']", "a[rel='next']")


def next_page_url(html: str, base_url: str = "") -> Optional[str]:
    """The site's own next-page link, absolute."""
    soup = BeautifulSoup(html, "html.parser")
    for selector in NEXT_PAGE_SELECTOR:
        node = soup.select_one(selector)
        if node and node.get("href"):
            return _absolute(node["href"], base_url)
    return None


def canonical_url(html: str, base_url: str = "") -> Optional[str]:
    """The page's own `rel=canonical`.

    Worth reading on this site rather than trusting the requested address:
    the brand segment is decorative, so `/site/xyz/c/c15/` is served happily
    and the canonical is what says the page is really Cosme Decorté's.
    """
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("link[rel='canonical']")
    return _absolute(node["href"], base_url) if node and node.get("href") else None


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

# JPY is the only currency this site quotes and it has no subunit, so the
# comma is unambiguously a thousands separator and there is no decimal form
# to disambiguate (the three grouping conventions collapse to one
# here). The largest price measured is 264,000 円.
_PRICE_RE = re.compile(r"([0-9][0-9,]*)\s*円")

# `（税込）`, `（税込/8%）`. Fullwidth parentheses, and the rate is optional:
# where it is absent the site means the standard rate, which is 10%.
_TAX_RE = re.compile(r"[（(]税込(?:\s*/\s*(\d+)\s*%)?[）)]")

STANDARD_TAX_RATE = 10

CURRENCY = "JPY"


def parse_price(text: str) -> Optional[float]:
    """The first yen amount in a node's text, or None.

    Returns a float for the family's schema even though JPY is integral;
    `output_writer` writes it back without a spurious decimal.
    """
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_tax_rate(text: str) -> Optional[int]:
    """The consumption-tax rate the price includes, as a percentage.

    `（税込/8%）` states the reduced rate explicitly; a bare `（税込）` means
    the standard 10%. Absent entirely -> None, never a defaulted number,
    because a price with no tax annotation is not a tax-inclusive price we
    can vouch for (never present a guess as a fact).
    """
    if not text:
        return None
    m = _TAX_RE.search(text)
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else STANDARD_TAX_RATE


# ---------------------------------------------------------------------------
# Stock
# ---------------------------------------------------------------------------

# The site's own call-to-action text, as an ALLOWLIST. Counts
# are over the 171 tiles in the 2026-09-18 captures and are in the module
# docstring. Anything not named here reads as "not available" rather than as
# a quiet True, so a wording the site adds tomorrow under-reports instead of
# inventing stock.
_AVAILABLE_CTA = {
    "種類を選ぶ",        # choose a variety (the product has variants)
    "カートに入れる",     # add to cart
    "商品を購入する",     # purchase this product
    "予約受付中",        # pre-orders open
}
_UNAVAILABLE_CTA = {
    "現在購入頂けません",  # currently unavailable
    "予約受付終了",       # pre-orders closed
}

_IN_STOCK_LD = {"instock", "in_stock", "preorder", "backorder",
                "limitedavailability", "onlineonly"}
_OUT_OF_STOCK_LD = {"outofstock", "soldout", "discontinued"}


def _cta_in_stock(tile) -> Optional[bool]:
    for node in tile.select(".btn-items-cart a, .btn-items-cart button"):
        text = node.get_text(strip=True)
        if text in _AVAILABLE_CTA:
            return True
        if text in _UNAVAILABLE_CTA:
            return False
        if text:
            # A wording nobody has seen. Under-report rather than guess, and
            # say nothing rather than say False about a real product: None is
            # "unknown", which is a different claim from "sold out".
            return None
    return None


def _ld_in_stock(offer: dict) -> Optional[bool]:
    value = offer.get("availability")
    if not isinstance(value, str):
        return None
    token = value.rstrip("/").rsplit("/", 1)[-1].replace(" ", "").lower()
    if token in _IN_STOCK_LD:
        return True
    if token in _OUT_OF_STOCK_LD:
        return False
    return None


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# A TRIPWIRE, not a description of anything seen. Every entry was counted on
# 13 captures known to be good -- 8 listings, 4 product pages, the site's own
# 404 and an empty listing -- and every one was ZERO (count a candidate
# on a page you know is good before adding it). They are here so that a
# challenge switched on next month is reported as a challenge rather than as
# an empty catalogue.
#
# `cf-turnstile` is deliberately absent: 2Captcha's Scraping Browser
# auto-solve extension injects it into every page it loads, so it fires on
# good pages and misses real ones. `challenges.cloudflare.com`
# is the marker that works and is what stands in for Turnstile here.
#
# Because nothing in this set matches anything that extension injects, the
# `chrome-extension://` strip would be dead code in this
# repo and is deliberately not carried.
BOT_CHALLENGE_MARKERS = (
    # NOT a bare `recaptcha`. That is what this set carried until
    # 2026-10-13, and it FIRES ON A GOOD PAGE: fetched over
    # `--cdp-endpoint`, 2Captcha's own auto-solve extension injects sixteen
    # `chrome-extension://…/content/captcha/<vendor>/hunter.js` scripts into
    # every page it loads, two of which contain the substring `recaptcha`.
    # Counted on a 101 KB listing holding 24 real tiles:
    #
    #     recaptcha (bare)         2      <- the extension's own scripts
    #     captcha (bare)          21
    #     cf-turnstile             1
    #     recaptcha/api.js         0      <- what the SITE would ship
    #     recaptcha/api2/anchor    0
    #     www.google.com/recaptcha 0
    #
    # Nothing broke, because `detect_page_state` checks for rendered tiles
    # BEFORE it looks for a marker (the ordering) — but a page with no
    # tiles, an exhausted tag facet say, would have been reported as a
    # CHALLENGE over CDP: exit 3 for a correct answer.
    #
    # This repo's own claim that no marker fires on a good page was true of
    # every capture it had and false of one it did not have, because all of
    # them were fetched locally. That is the "guard passed
    # for the wrong reason: a fixture fetched the way a real run does not
    # fetch", and that calls for exactly the narrowing below.
    ("recaptcha/api.js", "google recaptcha"),
    ("recaptcha/api2/anchor", "google recaptcha"),
    ("recaptcha/api2/bframe", "google recaptcha"),
    ("www.google.com/recaptcha", "google recaptcha"),
    ("challenges.cloudflare.com", "cloudflare turnstile"),
    ("hcaptcha.com", "hcaptcha"),
    ("datadome", "datadome"),
    ("px-captcha", "perimeterx"),
    ("_incapsula_", "imperva incapsula"),
    ("awswaf", "aws waf"),
    ("errors.edgesuite.net", "akamai"),
)

# A refusal page is small. Unescaping the whole of a 100 KB listing on every
# fetch buys nothing and risks a product name deep in a grid reading as a
# marker.
_UNESCAPE_PREFIX = 20_000


def _normalised_head(html: str) -> str:
    import html as html_module
    return html_module.unescape(html[:_UNESCAPE_PREFIX]).lower()


def detect_bot_challenge(html: str, url: str = "") -> Optional[str]:
    """The vendor whose challenge this page is, or None.

    Normalises HTML entities over a bounded prefix first, because an edge can
    entity-escape the punctuation in its own marker and a literal then
    matches a browser's DOM and misses a raw HTTP response.
    """
    if not html:
        return None
    head = _normalised_head(html)
    for marker, vendor in BOT_CHALLENGE_MARKERS:
        if marker in head:
            return vendor
    return None


# The site's own script directory, referenced 9 to 11 times on every served
# page including its 404 and an empty listing, and zero times on anything the
# site did not build. the positive-asset signal, which is also the
# only thing that answers Chromium's own network-error page -- that page
# carries the site's hostname in its <title> and no vendor marker at all.
_ASSET_MARKERS = ("/js/sys/", "/freepage/maison-kose/")
_MIN_ASSET_REFERENCES = 2


def references_own_assets(html: str) -> int:
    if not html:
        return 0
    return sum(html.count(marker) for marker in _ASSET_MARKERS)


_PRODUCT_HREF_RE = re.compile(r'href="[^"]*/g/g[A-Za-z0-9]+/?"')


def product_link_count(html: str) -> int:
    """Product-shaped links in the raw markup.

    Deliberately a link count and NOT the tile count: it answers "did the
    site serve a catalogue page at all", which is a readiness question, and
    it is generous on purpose. The gap between the two is real and is why
    rows are built from tiles instead -- a grid page carries 28 such links
    against 24 tiles, the extra four being carousel banners.
    """
    return len(_PRODUCT_HREF_RE.findall(html or ""))


def tile_count(html: str) -> int:
    """Real product tiles, element-qualified. See the module docstring."""
    return len(BeautifulSoup(html or "", "html.parser").select("li.c-product__item"))


_LD_PRODUCT_RE = re.compile(r'"@type"\s*:\s*"Product"', re.I)


def _has_product_ld(html: str) -> bool:
    """A JSON-LD `Product` block, cheaply.

    A regex rather than a parse, because `detect_page_state` runs on every
    response including refusals and a full JSON parse of a 100 KB page to
    answer a yes/no question is wasted work. The authoritative read is
    `ld_blocks`, which the detail parser uses.
    """
    return bool(_LD_PRODUCT_RE.search(html or ""))


# The status the SITE states in its own error page, for the engine that has
# no other way to learn it.
#
# `driver.get()` returns None and WebDriver exposes no HTTP status at all, so
# Selenium cannot thread one however carefully the other two do. Rather than
# leave one engine worse informed than its twins — which is exactly the
# drift a shared module exists to prevent — the parser reads the
# status out of the body where the site states one.
#
# Maison KOSE states it in the TITLE of its platform 404: the page is a bare
# 1,040-byte document reading `404- ページが見つかりません。`, with no site
# chrome on it at all. Measured 2026-09-18 on `/definitely-not-a-page`.
#
# Deliberately narrow. It is anchored to the <title>, and it is only ever
# consulted AFTER the unambiguous positives (tiles, a Product block) have
# already failed, so a product whose name happened to start "404-" cannot
# reach it.
_STATUS_IN_TITLE_RE = re.compile(r"<title>\s*(\d{3})\s*[-–—]", re.I)


def status_from_body(html: str) -> Optional[int]:
    """The HTTP status the site states in its own error page, or None."""
    m = _STATUS_IN_TITLE_RE.search(html or "")
    if not m:
        return None
    code = int(m.group(1))
    return code if 400 <= code <= 599 else None


def detect_page_state(html: str, status: Optional[int] = None,
                      url: str = "") -> Tuple[str, Optional[str]]:
    """`(state, detail)` -- the triage every engine shares.

    Signals are ordered by how much they PROVE, not by how cheap they are
    (the classification-order trap): a rendered tile is an unambiguous
    positive and is checked before any threshold, so a thin-but-real page
    cannot come back as "blocked" and send the reader hunting for a proxy
    problem.

    States: `content` · `empty` · `not_found` · `challenge` · `blocked` ·
    `unknown`.
    """
    html = html or ""

    # 1. Unambiguous positive: the site rendered product tiles, or — on a
    #    product page, which has no tiles at all — published its own JSON-LD
    #    `Product` block.
    #
    #    The second half is not tidiness. Without it a perfectly good product
    #    page classifies as "empty", every `--mode product` run logs "page 1
    #    came back as empty" while returning a correct row, and the reader
    #    goes hunting for a block that is not there. Order the signals
    #    by how much they PROVE, and a page publishing its own structured
    #    product data proves it was served.
    if tile_count(html) > 0:
        return "content", None
    if _has_product_ld(html):
        return "content", None

    # 2. A vendor challenge. Nothing on this site matches today -- see
    #    BOT_CHALLENGE_MARKERS -- so this is a tripwire for a future change.
    vendor = detect_bot_challenge(html, url)
    if vendor:
        return "challenge", vendor

    # 3. The address does not exist. A TERMINAL answer, not a failure and not
    #    a block: retrying it spends a fetch on something that will never be
    #    there, which is what a discarded status costs. The status is taken
    #    from the response where an engine could thread one, and from the
    #    site's own error page where it could not — see `status_from_body`.
    stated = status if status is not None else status_from_body(html)
    if stated == 404:
        return "not_found", "http 404"

    # 4. A status the site uses to refuse.
    if stated is not None and stated in (401, 403, 429):
        return "blocked", f"http {stated}"
    if stated is not None and stated >= 500:
        return "blocked", f"http {stated}"

    # 5. Built out of the site's own assets, but holding no tiles. That is a
    #    page Maison KOSÉ really served: an exhausted tag listing (`?p=5`
    #    returns exactly this), a bogus product code, or a genuinely empty
    #    facet. It is an answer, not a failure.
    if references_own_assets(html) >= _MIN_ASSET_REFERENCES:
        return "empty", "served by the site, no product tiles on it"

    # 6. Not built out of this site's assets and carrying no marker: an
    #    interstitial, a proxy's error page, or Chromium's own.
    return "unknown", None


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _absolute(url: Optional[str], base_url: str = "") -> str:
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base_url or f"https://{CANONICAL_HOST}/", url)


def _text(node) -> Optional[str]:
    if node is None:
        return None
    text = node.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text) or None


_BADGE_RE = re.compile(r"/badge/([a-z0-9_-]+)\.(?:png|svg|jpg)", re.I)


def _badges(tile) -> Optional[str]:
    """The site's own corner badges, as a comma-joined string.

    Measured over 171 tiles: `new` 54, `limited` 26, `online` 2. They are the
    site's own merchandising flags and carry information no other column
    does -- `limited` in particular is why a row can vanish between runs.
    """
    found = []
    for img in tile.select(".c-product__icon__wrap img"):
        m = _BADGE_RE.search(img.get("src") or "")
        if m and m.group(1) not in found:
            found.append(m.group(1))
    return ",".join(found) if found else None


# The site TRUNCATES a long product name in the browser, and only there.
#
# Each tile carries `data-module="TruncateText" data-options='{"length": 36}'`
# on its name node, and the site's own JavaScript rewrites that node after
# load: 36 characters and an ellipsis. A plain HTTP fetch sees the full name
# the server rendered; a browser sees the truncated one. So for months the
# three browser engines returned a SHORTER title than the HTTP path for every
# long name, and nothing could see it because there was no non-browser engine
# to compare against — it took `http_scraper.py` existing for the two to
# disagree on 10 of 72 rows of one live run.
#
# The thumbnail's `alt` is the same name and is immune to the rewrite.
# Measured over 171 tiles in the captures: an `alt` is present on 171 of 171,
# and after whitespace normalisation it differs from the server-rendered name
# on **zero** of them — the 15 raw differences are all whitespace.
#
# The rule is therefore narrow rather than "always prefer alt": the `<p>` text
# stays primary, and the `alt` is used only when the `<p>` has visibly been
# truncated. That is unambiguous here because **0 of 171** server-rendered
# names end in an ellipsis while every truncated one does.
_TRUNCATION_MARKS = ("\u2026", "...", "\u2025")


def _full_title(tile) -> Optional[str]:
    """The product name, undoing the site's own in-browser truncation."""
    node = tile.select_one("p.c-product__product-name")
    text = _text(node)
    if not text or not text.endswith(_TRUNCATION_MARKS):
        return text
    image = tile.select_one(".c-product__thumb__img img")
    alt = (image.get("alt") or "").strip() if image else ""
    alt = re.sub(r"\s+", " ", alt)
    # Only when it is genuinely more than the truncated text, so a site that
    # one day ships an empty or shorter alt cannot make a title worse.
    if alt and len(alt) > len(text) - 1:
        return alt
    return text


def parse_products(html: str, base_url: str = "", *, page: int = 1,
                   mode: str = "listing") -> List[Product]:
    """Rows from a listing page, in the order the page publishes them.

    The tile is the scope, and it is the OUTERMOST ancestor covering exactly
    one product: `li.c-product__item` holds one `/g/g…/` id
    behind two links -- the thumbnail and the title -- which is exactly the
    MediaMarkt shape that section warns about. Counting distinct ids rather
    than links is what lets that pass; here the site names the boundary for
    us, so no widening walk is needed at all.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    scraped_at = utc_now()
    rows: List[Product] = []

    for position, tile in enumerate(soup.select("li.c-product__item"), start=1):
        link = tile.select_one('a[href*="/g/g"]')
        href = link.get("href") if link else None
        sku = sku_from_url(href) if href else None
        if not sku:
            # A tile with no product id is not a product. Skipped loudly by
            # being absent from the count the caller compares against
            # `tile_count`, rather than emitted as a row of nulls.
            continue

        price_node = tile.select_one("p.c-product__price")
        price_text = _text(price_node) or ""
        image = (tile.select_one(".c-product__thumb__img img")
                 or tile.select_one('img[src*="/img/goods/"]'))

        rows.append(Product(
            source=SOURCE_DEFAULT,
            scraped_at=scraped_at,
            url=_absolute(href, base_url),
            sku=sku,
            title=_full_title(tile),
            brand=_text(tile.select_one("p.c-product__brand")),
            price=parse_price(price_text),
            currency=CURRENCY if parse_price(price_text) is not None else None,
            in_stock=_cta_in_stock(tile),
            image_url=_absolute(image.get("src"), base_url) if image else None,
            category=category_from_url(base_url),
            price_source="tile" if parse_price(price_text) is not None else None,
            page=page,
            position=position,
            mode=mode,
            tax_rate=parse_tax_rate(price_text),
            price_is_store_price="※" in price_text or None,
            badges=_badges(tile),
        ))

    return rows


@dataclass
class ListingPage:
    """One listing page: its rows, plus what the SITE said about the run.

    `pages_available` is the site's own `N／Mページ` counter and is None on a
    tag listing, which publishes none. None means UNKNOWN and never zero:
    capping a tag run at zero pages because the site printed no counter
    would turn a working route into an empty file.
    """
    rows: List[Product]
    page_number: Optional[int] = None
    pages_available: Optional[int] = None
    page_size: Optional[int] = None
    next_url: Optional[str] = None
    canonical: Optional[str] = None
    tiles_on_page: int = 0
    product_links_on_page: int = 0


def parse_listing(html: str, base_url: str = "", *, page: int = 1,
                  mode: str = "listing") -> ListingPage:
    """`parse_products`, plus the page-level facts the engines plan from."""
    rows = parse_products(html, base_url, page=page, mode=mode)
    current, total = page_counter(html)
    tiles = tile_count(html)

    return ListingPage(
        rows=rows,
        page_number=current or page_number_from_url(base_url) or page,
        pages_available=total,
        page_size=PAGE_SIZE,
        next_url=next_page_url(html, base_url),
        canonical=canonical_url(html, base_url),
        tiles_on_page=tiles,
        product_links_on_page=product_link_count(html),
    )


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------

_LD_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S)


def ld_blocks(html: str) -> List[dict]:
    """Every parseable JSON-LD block on the page, flattened.

    A listing publishes none and a product page publishes exactly one, but
    the shapes listed are all legal and a site can start
    publishing any of them after a deploy: a list at the top level, a
    `@graph`, a block that does not parse at all. None of those should be an
    exception on a page whose products are readable.
    """
    out: List[dict] = []
    for raw in _LD_SCRIPT_RE.findall(html or ""):
        try:
            data = json.loads(raw.strip())
        except (ValueError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            graph = node.get("@graph")
            if isinstance(graph, list):
                out.extend(n for n in graph if isinstance(n, dict))
            else:
                out.append(node)
    return out


def _ld_offer(node: dict) -> dict:
    """`offers`, in any of its legal shapes.

    `.get("offers", {})` is not enough: an explicit `"offers": null` is legal
    schema.org and a default only applies to a MISSING key, so the naive form
    raises `AttributeError` on a page that is otherwise fine.
    """
    offers = node.get("offers")
    if isinstance(offers, dict):
        return offers
    if isinstance(offers, list):
        for item in offers:
            if isinstance(item, dict):
                return item
    return {}


def _ld_image(value: Any) -> Optional[str]:
    """`image` as a string, an ImageObject, or a list of either."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in ("url", "contentUrl"):
            if isinstance(value.get(key), str):
                return value[key]
        return None
    if isinstance(value, list):
        for item in value:
            found = _ld_image(item)
            if found:
                return found
    return None


_VOLUME_RE = re.compile(r"容量\s*(.+)")


def _breadcrumb(soup) -> List[str]:
    """`TOP › brand › category › subcategory › product name`.

    The site prints the trail twice -- once for desktop and once for mobile --
    so the raw list has duplicates; this keeps the first, longest run.
    """
    items = [_text(li) for li in soup.select("li.c-breadcrumb__item")]
    items = [i for i in items if i]
    if "TOP" in items[1:]:
        items = items[: items.index("TOP", 1)]
    return items


def parse_product_detail(html: str, base_url: str = "", *,
                         mode: str = "product") -> List[Product]:
    """The row for ONE product page, as a one-element list.

    A list because the family's engines treat every parse as rows and because
    a `ProductGroup` on a future deploy would be several; today every capture
    publishes a single `Product` block, so the list has one entry.

    Reads the page's own JSON-LD and never a tile. That is not a style
    preference: a detail page carries 15 `div.c-product__item` staff-review
    cards and an `awoo-product-list` recommendation block, and reading tiles
    here is exactly how a parser invents products.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    scraped_at = utc_now()

    node = next((b for b in ld_blocks(html)
                 if str(b.get("@type", "")).lower() == "product"), None)
    if node is None:
        return []

    offer = _ld_offer(node)
    sku = node.get("sku") or node.get("mpn") or sku_from_url(base_url)
    price = offer.get("price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None

    # The DOM's own price node, read as a CROSS-CHECK rather than as an
    # overlay: this site has no discount chain, so there is nothing to
    # reconcile (delete the overlay, do not port it). Where the two
    # disagree the row keeps the structured figure -- a fact's
    # trustworthiness ladder -- and the disagreement is reported rather than
    # silently resolved.
    dom_node = soup.select_one(".p-product-detail__item__price")
    dom_text = _text(dom_node) or ""
    dom_price = parse_price(dom_text)

    crumbs = _breadcrumb(soup)
    brand = crumbs[1] if len(crumbs) > 1 else None
    category = crumbs[2] if len(crumbs) > 2 else None
    subcategory = crumbs[3] if len(crumbs) > 3 else None

    variation = _text(soup.select_one(".p-product-detail__item__variation"))
    volume = None
    if variation:
        m = _VOLUME_RE.search(variation)
        volume = m.group(1).strip() if m else variation

    colours = len(soup.select('[class*="p-product-detail__color__group__item"]'))

    # The row's URL is the address this product is REALLY at, built from the
    # sku the page itself published -- deliberately NOT its `rel=canonical`.
    #
    # Measured over 20 product pages on 2026-09-18: **5 of them canonicalise
    # to a DIFFERENT sku**, a sibling size or shade rather than themselves.
    # `/g/gJQBA/` is the 60 g cream and points at `/g/gJQGA/`, which is the
    # 20 g one; MLYE010 -> MLYE001, JETC001 -> JETC000, MTVZ003 -> MTVX001,
    # MWJC -> MWJA. Taking the canonical as the row's URL would have produced
    # a quarter of all rows whose link opens a different product while their
    # title, sku and price describe this one -- the "every row
    # points at the wrong page while everything else looks right", which is
    # the shape of bug that survives every coverage check.
    #
    # The canonical is not discarded, because it says something real: it
    # names the product the site treats as the family's primary entry, which
    # is the only thing on the page that groups two sizes of one cream.
    # `variant_of` carries it, and is None where the page canonicalises to
    # itself (15 of the 20).
    canonical_sku = sku_from_url(canonical_url(html, base_url) or "")
    self_url = (f"https://{CANONICAL_HOST}/site/"
                f"{brand_slug_from_url(base_url) or 'c'}/g/g{sku}/"
                if sku else _absolute(base_url, base_url))

    return [Product(
        source=SOURCE_DEFAULT,
        scraped_at=scraped_at,
        url=self_url,
        sku=sku,
        title=node.get("name"),
        brand=brand,
        price=price if price is not None else dom_price,
        currency=(offer.get("priceCurrency") or (CURRENCY if dom_price else None)),
        in_stock=_ld_in_stock(offer),
        image_url=_ld_image(node.get("image")),
        category=category,
        price_source=("jsonld" if price is not None
                      else ("detail_dom" if dom_price is not None else None)),
        page=1,
        position=1,
        mode=mode,
        tax_rate=parse_tax_rate(dom_text),
        price_is_store_price="販売価格" in dom_text or None,
        badges=None,
        subcategory=subcategory,
        volume=volume,
        colour_count=colours or None,
        release_date=node.get("releaseDate"),
        variant_of=canonical_sku if canonical_sku and canonical_sku != sku else None,
    )]


def detail_price_agrees(html: str) -> Optional[bool]:
    """Does the page's JSON-LD price equal the one it prints?

    Its own function because the rule is to CHECK this on every new
    site rather than assume it, and because a check that is only ever run
    once during a capture pass is a check that stops being true. The canary
    asserts it. Measured 2026-09-18: agrees on 4 of 4 product captures.
    None where either figure is missing -- that is unknown, not a mismatch.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    node = next((b for b in ld_blocks(html)
                 if str(b.get("@type", "")).lower() == "product"), None)
    if node is None:
        return None
    offer = _ld_offer(node)
    try:
        structured = float(offer.get("price"))
    except (TypeError, ValueError):
        return None
    displayed = parse_price(_text(soup.select_one(".p-product-detail__item__price")) or "")
    if displayed is None:
        return None
    return structured == displayed
