"""
product_parser.py
------------------
Extraction for flippa.com listing pages. **This module IS the site** — every
other module in this repo is family core with a handful of named constants.

What the captures say. Sources, all 2026-10-14: the daily canary's own
browser capture of `/search?filter[property_type]=saas` (CI run 38561094467,
1.3 MB, 50 cards) and plain-HTTP captures of `/search`, `/fr/search`,
`/es/search`, `/websites`, `/buy/sitetype/saas`, the same filter's pages 2,
14 (the last) and 15 (past the end), and a query that matches nothing.

**Flippa rebuilt its search page between 2026-09-28 and 2026-09-29.** The
version this module was first written against embedded every listing as
`const STATE = {...}` JSON and rendered it with Angular into
`<div id="listing-N">` cards linking to `flippa.com/<id>`. All three are gone:
0 occurrences of `STATE` on any 2026-10-14 capture. The daily canary went red
on 2026-09-29 and stayed red until this rewrite. What the page is now:

1. **There is no structured listing data at all.** One `application/ld+json`
   block (not a listing), no embedded JSON, no `__NEXT_DATA__`-style payload.
   The page is server-rendered HTML (Rails, Hotwire/Turbo), so plain HTTP
   gets exactly what a browser gets — 50 cards either way.

2. **A card is `<li id="listing-NNN">`**, and its boundary is that id: not a
   CSS class (Tailwind build output) and not a widen-up-from-a-link heuristic
   (a card links to its listing twice, title and "View Listing"). The same
   page also carries `<span id="listing-category-count-…">` filter counters,
   which is why the id is matched as `listing-` + DIGITS, never as a prefix.

3. **A listing link is `flippa.com/<id>-<slug>`** (`/fr/<id>-<slug>` on the
   French page). The id is the leading digits; the slug is the seller's
   title, lower-cased, and is not part of the id.

4. **The key-data grid prints money ABBREVIATED** — "USD $160K", "USD $51.7K",
   "USD $1.23M" — so `monthly_revenue` and `monthly_profit` carry the
   precision the site shows (three significant figures), not the exact
   figure the old embedded JSON had. The asking price and the struck-through
   original are printed in full. Labels are translated per locale.

5. **Columns the card no longer shows stay null**: `monetization`,
   `revenue_multiple`, `status`, `sale_method`, `sponsored`,
   `editors_choice`, `confidential`, `verified_listing` and `image_url`
   (the only image on a card is the broker's photo, which is not a picture
   of the business). Nothing is inferred to fill them.

6. **Pagination is `?page=N`.** The page's own next link is
   `?page=2&pagination=true`. Measured 2026-10-14: `?page=2`,
   `?page=2&pagination=true` and the old `?page[number]=2` return the same 50
   ids, none of them page 1's; the last page of a 676-match filter is page 14
   with 26 cards; page 15 answers 200 with no cards and the same
   "Show 676 results" count. Every run still verifies the convention against
   the data (see the engines' addressability check).
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple
from urllib.parse import (urljoin, urlparse, urlunparse, parse_qsl, urlencode)

from bs4 import BeautifulSoup

from output_writer import Product

logger = logging.getLogger("product_parser")

SELECTORS = {
    # The site's own id attribute on the card wrapper: where a site publishes
    # no structured data, its own id is a better anchor than any class.
    # Used by every engine as the "has the grid rendered?" marker too.
    #
    # Deliberately tag-agnostic: the card changed from <div> to <li> on
    # 2026-09-29 and a `div[...]` selector silently stopped matching. The
    # `:not` excludes the filter counters (`listing-category-count-saas`),
    # which share the prefix — 19 of them on a search page.
    "item_card": '[id^="listing-"]:not([id^="listing-category"])',
}

# A listing's own URL is flippa.com/<digits>-<slug>, optionally under a locale
# segment (/fr/, /es/). The digits are the id; that is also how a listing link
# is told apart from the other links on a card (/product/premium,
# /listings/<id>/watchlists/toggle).
_LISTING_PATH_RE = re.compile(r"^(?:/[a-z]{2})?/(\d{5,10})(?:-[^/]*)?/?$")
_CARD_ID_RE = re.compile(r"^listing-(\d+)$")

# ---------------------------------------------------------------------------
# Price parsing
# ---------------------------------------------------------------------------
# Flippa prints money as "USD $573,006" — an ISO code AND a symbol — and the
# key-data block prints monthly profit as "USD $13,202 p/mo", or
# "-USD $315 p/mo" when the business loses money.
#
# An explicit ISO allowlist, never a bare [A-Z]{3}: the card text carries
# "MRR", "MAU", "ARR" and "SEO" next to numbers, and each of those would
# otherwise become a currency and a phantom price. Measured on the 2026-08-27
# capture: a bare [A-Z]{3} pattern matched MRR and MAU as currencies.
_CURRENCY_CODES = frozenset("""
    USD EUR GBP AUD CAD NZD SGD HKD JPY CHF SEK NOK DKK PLN CZK
    INR IDR MYR THB PHP VND ZAR AED SAR BRL MXN ARS CLP COP TRY ILS
""".split())
_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}

# Grouping spaces: plain, NBSP, narrow NBSP, thin space. A rendered page uses
# a no-break variant so a number does not wrap, and missing them reads
# "1 234" as 234.
_GROUP_SPACES = "    "
_AMOUNT = (r"\d{1,3}(?:[" + _GROUP_SPACES + r"]\d{3})+(?:[.,]\d{1,2})?"
           r"|[\d.,]+(?:[.,]\d{1,2})?")
_PRICE_RE = re.compile(
    r"(-?)\s*"                                   # a leading minus belongs to the number
    r"(?:\b([A-Z]{3})\b\s*)?"                    # optional ISO code:  USD $13,202
    r"(?:([$€£¥])\s?)?"                          # optional symbol
    r"(" + _AMOUNT + r")")
_BID_COUNT_RE = re.compile(r"(\d[\d,]*)\s*bids?\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Blocked-page detection
# ---------------------------------------------------------------------------
# flippa.com is fronted by Cloudflare (Server: cloudflare, CF-RAY, __cf_bm),
# and this family's rule applies with force here: COUNT A MARKER ON A PAGE
# YOU KNOW IS GOOD BEFORE ADDING IT. Measured on a served page holding the
# full catalogue (2026-09-19, 964 KB):
#
#     cdn-cgi                1 occurrence   <- Cloudflare's JS-detections tag
#     challenge-platform     1 occurrence   <- ditto: /cdn-cgi/challenge-platform/scripts/jsd/main.js
#     cloudflare             2 occurrences  <- a cdnjs.cloudflare.com preconnect
#
# All three are on EVERY page Flippa serves, so all three are facts about the
# site rather than markers — the family's inherited "challenge-platform" entry
# would have reported exit 3 on every successful run. What is left are strings
# that only a challenge carries.
BOT_CHALLENGE_MARKERS = {
    "cloudflare": ("_cf_chl_opt", "cf-browser-verification", "cf_chl_",
                   "Attention Required! | Cloudflare",
                   "Checking your browser before accessing",
                   "Just a moment...", "/cdn-cgi/challenge-platform/h/"),
}

# Flippa serves every page out of its own asset hosts. An interstitial, and
# Chromium's own network-error page, do not (measured elsewhere in this family: "a served page
# is built out of the site's own assets; an interstitial is not"). Measured:
# 333-432 references on good pages, and this is the ONLY signal that
# classifies Chromium's error page correctly, since that page carries the
# site's own hostname in its <title>.
_ASSET_HOST_RE = re.compile(r"static2?\.flippa\.com|flippa\.com/assets")
MIN_ASSET_REFERENCES = 5

# The 2Captcha Scraping Browser's auto-solve extension injects its own
# captcha hunters into every page it loads, and one of them carries
# data-ts-input="cf-turnstile-response". Flippa's own captcha mount point is
# <captcha-widgets>, which is EMPTY on a listing page and holds a real
# <captcha-widget data-captcha-type="turnstile" data-sitekey="..."> on
# /signup — so the extension's tags must be removed before any marker scan
# (measured elsewhere in this family: add this guard only where the marker set can actually match
# one — here it can).
_EXTENSION_SCRIPT_RE = re.compile(
    r"<script\b[^>]*(?:chrome|moz)-extension://[^>]*>\s*</script>", re.IGNORECASE)


def strip_extension_scripts(html: str) -> str:
    """Remove browser-extension <script> tags, whole, before scanning markers."""
    return _EXTENSION_SCRIPT_RE.sub("", html)


def detect_bot_challenge(html: str) -> Optional[str]:
    """Vendor name if `html` looks like a challenge interstitial, else None."""
    cleaned = strip_extension_scripts(html)
    for vendor, markers in BOT_CHALLENGE_MARKERS.items():
        if any(marker in cleaned for marker in markers):
            return vendor
    return None


def asset_reference_count(html: str) -> int:
    """How many times the page references Flippa's own asset hosts."""
    return len(_ASSET_HOST_RE.findall(html))


def count_cards(html: str) -> int:
    """How many listing cards the markup holds (each id counted once).

    Matches `listing-` followed by DIGITS on any tag, so the filter counters
    (`listing-category-count-saas`) are never counted and a change of the
    card's tag cannot hide the grid.
    """
    return len(set(_CARD_ID_RE.match(m).group(1)
                   for m in re.findall(r'id="(listing-\d+)"', html)))


# ---------------------------------------------------------------------------
# Number and price helpers
# ---------------------------------------------------------------------------
def _normalize_amount(raw: str) -> Optional[float]:
    """Parse an amount written in either decimal convention.

    When both separators appear, whichever comes last is the decimal point.
    When only one appears, exactly three trailing digits is a thousands
    grouping — no currency here has a three-digit subunit.
    """
    for space in _GROUP_SPACES:
        raw = raw.replace(space, "")
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")
    if last_dot != -1 and last_comma != -1:
        norm = (raw.replace(",", "") if last_dot > last_comma
                else raw.replace(".", "").replace(",", "."))
    else:
        sep = max(last_dot, last_comma)
        trailing = raw[sep + 1:] if sep != -1 else ""
        if len(trailing) == 3 and trailing.isdigit():
            norm = raw.replace(".", "").replace(",", "")
        else:
            norm = raw.replace(",", ".")
    try:
        return float(norm)
    except ValueError:
        return None


_PERCENT_RE = re.compile(r"-?\s*\d{1,3}(?:[.,]\d+)?\s*%")


def strip_percentages(text: str) -> str:
    """Remove percentage badges before any price is matched.

    The rule this family settled on: rejecting a percentage match afterwards is not enough,
    because the rejected match has already consumed the currency symbol. On a
    reduced Flippa listing the price node also carries "Reduced 38%", and a
    layout class renders that badge FIRST, so a reader that matched in
    document order could return 38 as the asking price.
    """
    return _PERCENT_RE.sub(" ", text)


def prices_in(text: str) -> Tuple[List[float], Optional[str]]:
    """Return ([amounts], currency_or_None) for the money written in `text`.

    A leading minus is part of the amount: Flippa writes a loss-making
    business's net profit as "-USD $315 p/mo", and dropping the sign turns a
    loss into a profit.

    Currency, in descending trustworthiness: a written ISO code
    names itself and is matched against a real allowlist; a bare "$" is a
    guess, and reads as USD because that is what Flippa prices in; anything
    else is None rather than a default.
    """
    amounts: List[float] = []
    currency: Optional[str] = None
    for m in _PRICE_RE.finditer(text):
        sign, code, symbol, raw = m.groups()
        if code and code not in _CURRENCY_CODES:
            continue
        amount = _normalize_amount(raw)
        if amount is None:
            continue
        if sign == "-":
            amount = -amount
        if currency is None:
            currency = code or _CURRENCY_SYMBOLS.get(symbol or "")
        amounts.append(amount)
    return amounts, currency


def _norm_space(text: Optional[str]) -> Optional[str]:
    """Collapse runs of whitespace, or None for nothing at all.

    Applied to every free-text column on BOTH paths, so the same listing reads
    byte-identically whether it came from the embedded JSON or from the card:
    the JSON keeps the seller's own double spaces and newlines, while the
    rendered card has them collapsed by the browser. Without this the two
    paths disagreed on 25 of 25 descriptions for no real reason.
    """
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", str(text)).strip()
    return collapsed or None


def discount_pct(price: Optional[float], original: Optional[float],
                 stated: Optional[float] = None,
                 sku: Optional[str] = None) -> Optional[float]:
    """The discount, computed from the two prices — never read off the badge.

    Flippa prints its own "Reduced 38%", and on every dropped listing measured
    (8 on 2026-09-19, 14 on 2026-08-27) it agrees with the computed figure to
    within its own rounding. It is still not what goes in the column: the
    family learned on farfetch-scraper that a printed percentage can be the
    first of two compounding discounts, and a figure computed from the two
    numbers in the same row is checkable by the reader. `stated` is used as a
    cross-check only, and a disagreement is logged with the sku.

    Returns None — not 0, not a negative — when the two figures are not what
    they were taken for, so an "original price" at or below the price cannot
    be reported as a discount.
    """
    if price is None or original is None or original <= 0 or original <= price:
        return None
    computed = round((1 - price / original) * 100, 1)
    if stated is not None and abs(stated - computed) > 1.0:
        logger.warning("Listing %s: Flippa prints a %.0f%% drop but %s -> %s is "
                       "%.1f%% — keeping the computed figure.",
                       sku or "?", stated, original, price, computed)
    return computed


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
_PAGE_PARAM = "page"
# Every spelling of "which page" the site has used or still honours, all of
# which have to be removed before a new one is set, or two of them end up in
# the same URL disagreeing with each other. `page[number]` is the spelling of
# the pre-2026-09-29 site; it still works, and a URL saved from back then
# must not end up carrying both.
_PAGE_PARAM_ALIASES = ("page[number]", "page_number", "page")


def page_url(url: str, page_num: int) -> str:
    """`url` with Flippa's own page parameter set to `page_num`.

    Site knowledge, hence here rather than in an engine. Page 1 carries no
    page parameter at all — the site's own page-1 URL has none, and a `page=1`
    would make page 1's URL differ from the URL a user pastes for no reason.

    Existing query parameters (filters, sort order, keyword) are preserved,
    and every spelling of the page parameter is replaced rather than appended
    twice.
    """
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in _PAGE_PARAM_ALIASES]
    if page_num > 1:
        query.append((_PAGE_PARAM, str(page_num)))
    return urlunparse(parts._replace(query=urlencode(query)))


# Route prefixes that are not a category, and the LOCALE segments Flippa's own
# hreflang set publishes: `/search`, `/fr/search` and `/es/search` are the same
# listing in three languages. Without these, a French URL labelled every row
# with the category "fr".
_SITE_LOCALES = ("fr", "es")
_NOT_A_CATEGORY = {"search", "buy", "browse", "sitetype", ""} | set(_SITE_LOCALES)


def locale_from_url(url: str) -> Optional[str]:
    """The locale segment of a Flippa URL, or None for the default English.

    Worth knowing before a run rather than after: a localised path does not
    merely translate labels, it CONVERTS THE PRICES. Measured 2026-09-19,
    listing 12857417 on the same day — `/search`: USD 436,829. `/fr/search`:
    EUR 380,546. Both are correct for their page; mixing the two in one
    dataset is not.
    """
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts and parts[0].lower() in _SITE_LOCALES:
        return parts[0].lower()
    return None


def category_from_url(url: str) -> Optional[str]:
    """A label for the `category` column, from the URL the user asked for.

    Flippa addresses a listing set three ways, all of them seen live:
        /search?filter[property_type]=saas   the general search
        /websites, /domains, /apps           category shortcuts
        /buy/sitetype/saas                   the older shortcut form
    and each of those can carry a locale prefix (`/fr/search`).

    The QUERY is read first, because it is what the user actually filtered on;
    the path is the fallback. Returns None rather than a made-up label when
    the URL says nothing — an empty column is honest, "search" is not.
    """
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    for key in ("filter[property_type]", "filter[sitetype]", "filter[vertical]",
                "query[keyword]"):
        if query.get(key):
            return query[key]
    for segment in reversed([p for p in parsed.path.split("/") if p]):
        if segment.lower() not in _NOT_A_CATEGORY:
            return segment.replace("-", " ").replace("_", " ")
    return None


# ---------------------------------------------------------------------------
# The listing cards
# ---------------------------------------------------------------------------
_MONEY_MARKER_RE = re.compile(r"[$€£¥]|\b(?:" + "|".join(sorted(_CURRENCY_CODES)) + r")\b")
_ISO_ANYWHERE_RE = re.compile(r"\b(" + "|".join(sorted(_CURRENCY_CODES)) + r")\b")
# A key-data amount is ABBREVIATED on the card: "USD $51.7K", "USD $2.1M",
# "51,7K € (EUR)". The number before the suffix is parsed with the same
# decimal rules as every other amount, then scaled.
_ABBREVIATED_RE = re.compile(
    r"(\d(?:[\d.," + _GROUP_SPACES + r"]*\d)?)\s*([KkMmBb])?(?![A-Za-z])")
_SCALE = {"k": 1e3, "m": 1e6, "b": 1e9}
_PERCENT_VALUE_RE = re.compile(r"(\d{1,3}(?:[.,]\d+)?)\s*%")
_MULTIPLE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*x\b", re.IGNORECASE)

# The key-data labels, in the three languages Flippa's hreflang set publishes.
# Measured on 2026-10-14 on /search, /fr/search and /es/search: the same six
# labels, translated, in the same order, with "Monthly Profit" and "Profit
# Multiple" absent on a card that has none to show. A label not in this table
# is ignored rather than guessed at, and the column stays null.
_KEY_DATA_LABELS = {
    "monthly revenue": "monthly_revenue", "revenu mensuel": "monthly_revenue",
    "ingresos mensuales": "monthly_revenue",
    "monthly profit": "monthly_profit", "bénéfice mensuel": "monthly_profit",
    "beneficio mensual": "monthly_profit",
    "profit multiple": "profit_multiple", "multiple de profit": "profit_multiple",
    "múltiplo de beneficio": "profit_multiple",
    "age": "age_text", "ancienneté": "age_text", "antigüedad": "age_text",
    "type": "asset_type", "tipo": "asset_type",
    "industry": "industry", "secteur": "industry", "industria": "industry",
}


def _money(text: Optional[str]) -> Tuple[Optional[float], Optional[str]]:
    """(amount, currency) out of one money value as the card prints it.

    Handles every shape seen on 2026-10-14: "USD $2,520,000",
    "-USD $9" (a loss), "USD $51.7K", "USD $1.23M", "2 520 000 € (EUR)" and
    "51,7K € (EUR)". The ISO code is read wherever it sits — the French page
    puts it AFTER the amount, in brackets — and is matched against the
    allowlist, never a bare [A-Z]{3}. "N/A" and anything without a currency
    marker is (None, None): an amount with no currency beside it on this card
    is not money.
    """
    if not text or not _MONEY_MARKER_RE.search(text):
        return None, None
    text = strip_percentages(text)
    m = _ABBREVIATED_RE.search(text)
    if not m:
        return None, None
    amount = _normalize_amount(m.group(1))
    if amount is None:
        return None, None
    if m.group(2):
        amount = round(amount * _SCALE[m.group(2).lower()], 2)
    if text.lstrip().startswith("-"):
        amount = -amount
    code = _ISO_ANYWHERE_RE.search(text)
    currency = code.group(1) if code else None
    if currency is None:
        sym = re.search(r"[$€£¥]", text)
        currency = _CURRENCY_SYMBOLS.get(sym.group(0)) if sym else None
    return amount, currency


def _listing_id_from_href(href: str) -> Optional[str]:
    """The listing id out of a listing link, or None for any other link."""
    path = re.sub(r"^https?://[^/]+", "", href or "").split("?")[0].split("#")[0]
    m = _LISTING_PATH_RE.match(path)
    return m.group(1) if m else None


def _card_country(card) -> Optional[str]:
    """The seller's country: the text beside the card's map-pin icon.

    There is no text label for it, and no attribute naming the field; the
    icon's own file name is the anchor.
    """
    for use in card.find_all("use"):
        href = use.get("href") or use.get("xlink:href") or ""
        if "map-pin" in href:
            svg = use.find_parent("svg")
            span = (svg or use).find_next("span")
            if span and span.get_text(strip=True):
                return _norm_space(span.get_text(" ", strip=True))
    return None


def _card_key_data(card) -> dict:
    """{column: raw value} from the card's label/value grid.

    The grid sits ABOVE the card's <hr>; the price column sits below it and
    has the same two-paragraph shape ("Asking price" / "USD $650,000"), so
    the walk stops at the rule rather than trusting a class name.
    """
    data = {}
    rule = card.find("hr")
    blocks = list(rule.find_previous_siblings()) if rule is not None else [card]
    for block in blocks:
        if not hasattr(block, "find_all"):
            continue
        for pair in block.find_all("div"):
            paras = pair.find_all("p", recursive=False)
            if len(paras) != 2 or pair.find("div"):
                continue
            label = _norm_space(paras[0].get_text(" ", strip=True)) or ""
            column = _KEY_DATA_LABELS.get(label.lower())
            if column is None:
                logger.debug("Unrecognised key-data label %r — ignored.", label)
                continue
            data[column] = _norm_space(paras[1].get_text(" ", strip=True))
    return data


def _is_struck(tag) -> bool:
    classes = " ".join(tag.get("class") or [])
    return tag.name in ("del", "s") or "line-through" in classes


def _card_prices(card, sku: Optional[str]):
    """(price, currency, original_price, discount_pct, bid_count) off the card.

    Scoped to the price column — the block after the card's <hr> — never to
    the whole card: the key-data grid carries "USD $51.7K" (monthly profit)
    EARLIER in document order than the asking price.

    The shapes, all measured on 2026-10-14:
        Asking price | USD $650,000
        Asking price | USD $2,520,000 | <struck> USD $3,500,000 | Reduced 28%
        Auction      | USD $4,000 | 21 bids · 4 days left
        Auction      | USD $500   | Starting Price
        Open to Offers | Price Guide: USD $75,000 - USD $100,000
        Partial Sale: 25% Equity

    The price is the first text-only element that carries a currency marker
    and ONE amount. That rule needs no class name and no English word: the
    label has no currency, a "Reduced 28%" badge has no currency, the bid line
    has no currency, and the price guide carries TWO amounts — a range is not
    an asking price, so an open-to-offers listing reports none, as the site
    does.
    """
    rule = card.find("hr")
    block = rule.find_next_sibling() if rule is not None else None
    if block is None:
        return None, None, None, None, None

    original = currency = None
    for tag in block.find_all(True):
        if _is_struck(tag):
            original, currency = _money(tag.get_text(" ", strip=True))
            break

    price = None
    for tag in block.find_all(True):
        if tag.find(True) is not None or _is_struck(tag):
            continue
        text = tag.get_text(" ", strip=True)
        if not _MONEY_MARKER_RE.search(text):
            continue
        if len(_ABBREVIATED_RE.findall(strip_percentages(text))) != 1:
            continue
        price, cur = _money(text)
        currency = currency or cur
        if price is not None:
            break

    block_text = block.get_text(" ", strip=True)
    stated = None
    if original is not None:
        m = _PERCENT_VALUE_RE.search(block_text)
        if m:
            stated = _normalize_amount(m.group(1))
    bids = _BID_COUNT_RE.search(block_text)
    bid_count = int(bids.group(1).replace(",", "")) if bids else None
    return (price, currency, original,
            discount_pct(price, original, stated, sku), bid_count)


def _row_from_card(card, sku: str, base_url: str, category: Optional[str],
                   page: Optional[int], position: Optional[int]) -> Product:
    heading = card.find(["h4", "h3", "h5", "h6"])
    title = _norm_space(heading.get_text(" ", strip=True)) if heading else None

    description = None
    if heading is not None:
        desc = heading.find_next_sibling("p")
        if desc is not None:
            description = _norm_space(desc.get_text(" ", strip=True))

    url = urljoin(base_url, f"/{sku}")
    for a in card.find_all("a", href=True):
        if _listing_id_from_href(a["href"]) == sku:
            url = urljoin(base_url, a["href"])
            break

    # The strip across the top of the card says who is selling: "Brokered by
    # Flippa" (with the broker's photo and name), "Listed by Partner Broker",
    # or "Marketplace · Listed by Owner". Translated on /fr/ and /es/, and in
    # all three languages only the first one names Flippa.
    header = card.find("div", recursive=False)
    header_text = _norm_space(header.get_text(" ", strip=True)) if header else None
    broker_name = None
    if header is not None and header.find("img") is not None:
        broker_name = _norm_space(header.find("img").get("alt"))
    managed = ("Flippa" in header_text) if header_text else None

    key_data = _card_key_data(card)
    monthly_revenue, _ = _money(key_data.get("monthly_revenue"))
    monthly_profit, _ = _money(key_data.get("monthly_profit"))
    profit_multiple = None
    m = _MULTIPLE_RE.search(key_data.get("profit_multiple") or "")
    if m:
        profit_multiple = _normalize_amount(m.group(1)) or None

    price, currency, original_price, drop, bid_count = _card_prices(card, sku)

    return Product(
        url=url,
        sku=sku,
        title=title,
        price=price,
        currency=currency,
        original_price=original_price,
        discount_pct=drop,
        category=category,
        price_source="dom",
        page=page,
        position=position,
        description=description,
        asset_type=key_data.get("asset_type"),
        industry=key_data.get("industry"),
        monthly_profit=monthly_profit,
        monthly_revenue=monthly_revenue,
        profit_multiple=profit_multiple,
        age_text=key_data.get("age_text"),
        country=_card_country(card),
        bid_count=bid_count,
        broker_name=broker_name,
        managed_by_flippa=managed,
    )


def iter_cards(soup):
    """(sku, card) for every listing card, in page order, each id once."""
    seen = set()
    for card in soup.find_all(id=_CARD_ID_RE):
        sku = _CARD_ID_RE.match(card["id"]).group(1)
        if sku in seen:
            continue
        seen.add(sku)
        yield sku, card


def results_count(html: str) -> Optional[int]:
    """Flippa's own count of matches for this query, or None.

    Read from the filter panel's "Show 676 results" button
    (`#filters-show-results-count`), which is present on every listing page
    the site serves — including a page past the end ("Show 676 results",
    no cards) and a query that matches nothing ("Show 0 results"). Localised
    ("Afficher 6 073 résultats", "Mostrar 6,073 resultados"), so every digit
    in it is the number and nothing else is.
    """
    m = _RESULTS_COUNT_RE.search(html or "")
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(1))
    return int(digits) if digits else None


_RESULTS_COUNT_RE = re.compile(
    r'id="filters-show-results-count"[^>]*>([^<]*)<')


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------
def parse_products(html: str, base_url: str, category: Optional[str] = None,
                   page: Optional[int] = None) -> List[Product]:
    """Rows for one listing page, one per rendered listing card.

    A query the site itself says matches nothing returns [] even if a card
    were present: such a card could only be a placement, not a match.
    """
    if results_count(html) == 0:
        logger.info("Flippa reports 0 matches for this query.")
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    return [_row_from_card(card, sku, base_url, category, page, position)
            for position, (sku, card) in enumerate(iter_cards(soup), start=1)]
