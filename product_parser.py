"""
product_parser.py
-----------------
Everything this repo knows about Mercor. The engines are site-agnostic apart
from a handful of named constants; if you are adding site knowledge anywhere
else, it belongs here.

What Mercor publishes, and where
--------------------------------
Mercor runs two different things under one brand, on two hosts, and this
scraper reads three routes across them:

    --mode listings  work.mercor.com/explore              the marketplace index
    --mode job       work.mercor.com/jobs/{id}/{slug}     one marketplace listing
    --mode careers   www.mercor.com/careers               Mercor's OWN hiring

The first two are two views of ONE thing — a contract role on the Mercor
marketplace, keyed by the same `listingId` — which is what lets a `job` run
enrich a `listings` run and what `diff_runs.py` joins on. The third is a
different population entirely: salaried employment at Mercor the company,
served off a different host out of the Ashby ATS, with its own id space. It
shares the row shape and nothing else, so `diff_runs.py` refuses to compare
a careers run against a marketplace one.

The structured source is the React Query cache, NOT the JSON-LD
--------------------------------------------------------------
Count the JSON-LD blocks before writing a line.
Counted on the 2026-09-18 captures, `/explore` carries three — a
`BreadcrumbList`, an `Organization`, and an `ItemList` of 46 KB. The
`ItemList` looks like the primary path and is the wrong one twice over:

  * it carries **URLs only** — `@type: ListItem`, `position`, `url`. No
    title, no pay, no location. Every field would have to come from a
    second fetch per job.
  * it is **incomplete**. 326 URLs against 390 records in the same
    response's `__NEXT_DATA__`, and the 64 it drops are not random: all 55
    `evergreen` listings plus 9 standard ones. Anchoring on it silently
    loses 16% of the catalogue, which is "fail loudly" failing quietly.

So the primary path is the Next.js `__NEXT_DATA__` payload, specifically the
dehydrated React Query cache at

    props.pageProps.dehydratedState.queries[0].state.data.listings

which held 390 complete records in a single 1.5 MB response. The JSON-LD is
still read, but only on a DETAIL page and only for the two things the React
Query object does not state: the currency, and the schema.org employment
type. See `_row_from_jsonld`.

`__NEXT_DATA__` carries a `nonce`
---------------------------------
    <script id="__NEXT_DATA__" type="application/json" nonce="x50vDK…">

A regex written as `<script id="__NEXT_DATA__" type="application/json">`
misses every page on this site. It cost twenty minutes here before the
attribute was noticed, and it is the kind of miss that reads as "the site
stopped server-rendering" rather than as a typo. `_NEXT_DATA_RE` tolerates
any attributes in any order.

No single route enumerates the catalogue
----------------------------------------
Measured 2026-09-18. Neither of the two enumeration sources contains the
other:

    /explore  __NEXT_DATA__   390 listings
    /sitemap.xml              447 job URLs
    shared                    375
    sitemap only               72   -- all `status: active`, live detail pages
    explore only               15
    union                     462

Three sitemap-only listings were fetched to check what they were, and all
three answered 200 with `role.status == "active"`: they are live jobs that
`/explore` simply does not show. So `--mode job` enumerates the UNION and
says so in the sidecar, and a `listings` run is honest about being a
390-of-462 slice. Complete and exhaustive are
different words, with the twist that here neither source is the superset.

`/explore` has no pagination at all
-----------------------------------
`?page=2`, `?limit=10`, `?offset=100` and `?domain=Finance` were each tried
against `/explore` on 2026-09-18 and every one returned a byte-identical
payload (the only size difference is the query string echoed back into the
canonical `<link>`). The route ships the entire set in one response. So
`page_url()` refuses to build a page URL for it rather than manufacturing
duplicates and reporting a complete multi-page run holding page 1 several
times.

In `--mode job` a "page" IS one job detail page. That is not a stretch of
the flag: a job URL is the unit this site addresses independently, it is
exactly what the concurrency machinery wants, and it makes the sidecar's
"which pages failed by number" meaningful. `--pages 462` fetches the lot.

Traps that cost time here
-------------------------
* **JSON-LD `unitText` is not the pay period.** On 3 of 40 randomly
  sampled detail pages (2026-09-18) `baseSalary.value.unitText` said
  `HOUR` while the record's own `payRateFrequency` said `per-task`. The
  React Query field is the one to trust; `unitText` is normalised for
  Google's job schema and is wrong for anything non-hourly.
* **JSON-LD drops non-hourly pay entirely.** The `one-time` fixture has
  `rateMin == rateMax == 60` in the record and NO `baseSalary` node at
  all. A parser anchored on JSON-LD reports that job as unpaid.
* **`validThrough` is not an expiry.** It read `2026-10-18` on 40 of 40
  sampled pages, fetched on 2026-09-18 — render time plus thirty days,
  computed per request. It says nothing about the listing and is not
  carried as a column.
* **21 of the record's 50 fields are constant across all 390 listings**
  and are not carried: `matchQuality`, `submittedOn`, `userSimilarityScore`,
  `applicationStepsCompleted` and the rest are logged-in personalisation
  that an anonymous fetch always sees as null or zero. A column null
  on every row of every run should not exist. The measurement is here so
  someone can add one back with a better one.
* **Currency is measured, not assumed.** USD on 40 of 40 sampled
  marketplace detail pages, but the careers route publishes GBP on 4 of
  145 salary components. Nothing defaults to USD anywhere in this file.

Detection: there is nothing to detect
-------------------------------------
Eighteen candidate bot-challenge markers were counted across three page
kinds on 2026-09-18 — `cf-turnstile`, `challenges.cloudflare.com`,
DataDome, PerimeterX, Incapsula, Akamai, `errors.edgesuite.net`, AWS WAF,
reCAPTCHA in both spellings, hCaptcha, `data-sitekey`, `<captcha-widgets>`
and the rest. Every one was **zero**. Identical 200s came back from `curl`,
from `python-requests` and from an EMPTY User-Agent, and twelve rapid
sequential detail fetches were all 200 at ~0.4s each. Mercor is not gated,
at least from a Hetzner datacentre address (AS24940, Helsinki) on that date.

`BOT_CHALLENGE_MARKERS` is therefore deliberately SHORT rather than
deliberately broad. A marker that fires on a page the site plainly
served is worse than no marker, and `cf-turnstile` is measured
useless in any repo that can reach the Scraping Browser, whose auto-solve
extension injects it into every page it loads. It is not here.

And the positive-asset trick does NOT work on this site
-------------------------------------------------------
Sibling repos use "was this built out of the site's own assets?" as the
structural signal, proven on two other sites. Counted here
it is **backwards**: `/_next/static` appears 23-27 times on every real page
and **32 times on the 404**, because Mercor's not-found page is the same
Next.js app. A threshold on it would classify the one page that is
genuinely not content as the most content-like page on the site.

What works instead is an unambiguous positive signal, which belongs
before any heuristic anyway: **a real page carries `__NEXT_DATA__`
and the 404 carries none at all**. `references_own_assets` is kept for the
engines' interface and is documented as the weak signal it is here.
"""

import html as _html
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from bs4 import BeautifulSoup

log = logging.getLogger("product_parser")


# ---------------------------------------------------------------------------
# Hosts and routes
# ---------------------------------------------------------------------------

# Mercor serves the marketplace and the corporate site on two different
# hosts, and they are not interchangeable: `work.mercor.com/careers` is a
# 404 and `www.mercor.com/explore` redirects. Both are carried because both
# are read, and `canonical_url` moves a URL to the host that answers for its
# route rather than rebuilding every URL onto one host.
MARKETPLACE_HOST = "work.mercor.com"
CORPORATE_HOST = "www.mercor.com"

HOSTS = (MARKETPLACE_HOST, CORPORATE_HOST, "mercor.com")

# `mercor.com` and `www.mercor.com` both answer; the bare host 301s to the
# `www.` one. Unlike MediaMarkt there is no host here that
# refuses a `www.` prefix, so a rebuilt URL always matches the page's own.
_HOST_ALIASES = {"mercor.com": CORPORATE_HOST}

SOURCE_DEFAULT = "mercor.com"

BASE_MARKETPLACE = "https://" + MARKETPLACE_HOST
BASE_CORPORATE = "https://" + CORPORATE_HOST

EXPLORE_URL = BASE_MARKETPLACE + "/explore"
CAREERS_URL = BASE_CORPORATE + "/careers"
SITEMAP_URL = BASE_MARKETPLACE + "/sitemap.xml"

MODES = ("listings", "job", "careers")
DEFAULT_MODE = "listings"

# `/jobs/list_XXXX/some-slug`. The id is the contract — the slug is
# cosmetic and the site serves the page with any slug, or none. Anchoring
# on the URL pattern rather than on a CSS class is deliberate: Mercor's
# classes are build-generated Tailwind strings that churn on every deploy.
_JOB_DETAIL_RE = re.compile(
    r"^/jobs/(?P<id>list_[A-Za-z0-9_-]+)(?:/(?P<slug>[^/?#]*))?/?$", re.I)
_EXPLORE_RE = re.compile(r"^/explore/?$", re.I)
_CAREERS_RE = re.compile(r"^/careers/?$", re.I)
_SITEMAP_RE = re.compile(r"^/sitemap\.xml$", re.I)

# Recovering the id from a URL, for a row whose payload somehow lacks one.
_SKU_IN_URL_RE = re.compile(r"/jobs/(list_[A-Za-z0-9_-]+)(?:/|$)")

_ROUTES = (
    ("job", _JOB_DETAIL_RE),
    ("explore", _EXPLORE_RE),
    ("careers", _CAREERS_RE),
    ("sitemap", _SITEMAP_RE),
)

# Which mode reads which route.
_MODE_BY_ROUTE = {"explore": "listings", "job": "job", "careers": "careers"}

# Which host each route answers on. A `/careers` path asked for on
# work.mercor.com is a 404, so this is checked rather than assumed.
_HOST_BY_ROUTE = {
    "explore": MARKETPLACE_HOST,
    "job": MARKETPLACE_HOST,
    "sitemap": MARKETPLACE_HOST,
    "careers": CORPORATE_HOST,
}


# ---------------------------------------------------------------------------
# Small coercions
#
# Everything below reads a JSON payload rather than markup, so the usual
# job is turning a JSON value into a column value without inventing one.
# `None` in, `None` out, always: never present a guess as a fact.
# ---------------------------------------------------------------------------

def _str_or_none(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        # Mercor's detail payload serialises some fields through a JSON
        # encoder that writes Python's `None` as the four-character string
        # "None". Left alone it becomes a literal "None" in the CSV, which
        # a consumer cannot tell from a real value.
        return None if text in ("", "None", "null") else text
    return str(value)


def _int_or_none(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bool_or_none(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1"):
            return True
        if low in ("false", "0"):
            return False
    return None


def _text_list(value: Any) -> Optional[List[str]]:
    """A list column, or None.

    An EMPTY list becomes None on purpose. `eligibleLocation` is `[]` on 256
    of 390 listings and a list on 134, and the empty case means "no
    restriction stated" — the same thing the null case means. Writing `[]`
    for one and null for the other would put a distinction in the data that
    is not in the site.
    """
    if not isinstance(value, (list, tuple)):
        return None
    out = [t for t in (_str_or_none(v) for v in value) if t]
    return out or None


def _iso(value: Any) -> Optional[str]:
    """A timestamp, normalised to a UTC ISO-8601 string.

    Mercor publishes three spellings across the three routes:
    `2026-09-17T16:56:02` (naive, marketplace), `2026-04-18T00:34:24.377+00:00`
    (offset, careers) and `2026-09-03T17:47:13.000Z` (Zulu, JSON-LD). They
    are normalised so the column sorts as text and diffs cleanly.
    """
    text = _str_or_none(value)
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            # The marketplace payload is naive and Mercor states elsewhere
            # that it stores UTC; treating it as UTC is the assumption, and
            # it is written down rather than hidden.
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return text


def _plain_text(value: Any) -> Optional[str]:
    """HTML description -> text, entities resolved, whitespace collapsed.

    The careers route publishes `descriptionHtml`; the marketplace publishes
    markdown in `description`. Both end up in one column, and `data_source`
    says which route produced the row.
    """
    text = _str_or_none(value)
    if not text:
        return None
    if "<" in text and ">" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ")
    text = _html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*", "\n\n", text)
    return text.strip() or None


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------

def _split_url(url: str) -> Tuple[str, str, str, str]:
    parts = urlsplit((url or "").strip())
    host = (parts.netloc or "").lower()
    if "@" in host:
        host = host.split("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    host = _HOST_ALIASES.get(host, host)
    path = parts.path or "/"
    return parts.scheme or "https", host, path, parts.query or ""


def route_of(url: str) -> Optional[str]:
    """Name the route a URL addresses, or None if this repo does not read it."""
    _, _, path, _ = _split_url(url)
    for name, pattern in _ROUTES:
        if pattern.match(path):
            return name
    return None


def is_supported_url(url: str) -> Tuple[bool, str]:
    """(ok, reason). The reason is shown to the user, so it names the cause.

    Refuse WITH THE REASON. "is not a Mercor URL" is false for
    `work.mercor.com/login` and sends the reader hunting for a typo in a URL
    that is spelled correctly.
    """
    text = (url or "").strip()
    if not text:
        return False, "no URL given"
    scheme, host, path, _ = _split_url(text)
    if scheme not in ("http", "https"):
        return False, "%r is not an http(s) URL" % text
    if not host:
        return False, "%r has no hostname" % text
    if host not in HOSTS:
        return False, ("%s is not a Mercor host — this scraper reads %s"
                       % (host, " and ".join(HOSTS[:2])))
    route = route_of(text)
    if route is None:
        return False, ("%s is a Mercor URL but not a route this scraper "
                       "reads. It reads the marketplace index (%s), one "
                       "marketplace listing (%s/jobs/list_.../slug) and "
                       "Mercor's own careers page (%s)."
                       % (path, EXPLORE_URL, BASE_MARKETPLACE, CAREERS_URL))
    wanted_host = _HOST_BY_ROUTE.get(route)
    if wanted_host and host != wanted_host:
        return False, ("%s is served on %s, not on %s — %s answers 404 for "
                       "it" % (path, wanted_host, host, host))
    return True, ""


def mode_for_url(url: str) -> Optional[str]:
    """The mode that reads this URL, so `--url` alone is enough."""
    return _MODE_BY_ROUTE.get(route_of(url) or "")


def canonical_url(url: str) -> str:
    """Absolute, on the host that actually answers for the route."""
    scheme, host, path, query = _split_url(url)
    route = route_of(url)
    host = _HOST_BY_ROUTE.get(route or "", host or MARKETPLACE_HOST)
    return urlunsplit((scheme or "https", host, path, query, ""))


def page_url(url: str, page: int) -> Optional[str]:
    """Page N of a listing — or None, because Mercor has no such thing.

    This returns None rather than a constructed `?page=N` and the None is
    the point. Measured 2026-09-18: `?page=2`, `?limit=10`, `?offset=100`
    and `?domain=Finance` on `/explore` each returned a byte-identical
    payload. The route ships all 390 records in one response and has no
    second page to address.

    Building one anyway would cost this: the
    engine would fetch the same rows again, find no new `sku`, conclude the
    listing was exhausted and report a COMPLETE multi-page run holding page
    one several times. A caller that gets None here plans one page and says
    why.

    `--mode job` does not come through this function. There a "page" is one
    job detail page and the addresses come from `enumerate_job_urls`, which
    is a real list of real independent addresses rather than a convention
    guessed at.
    """
    return None


def job_url(listing_id: Any, slug: Optional[str] = None) -> Optional[str]:
    """Absolute URL for one marketplace listing.

    The slug is cosmetic: the site serves the page with the right slug, a
    wrong one, or none at all. It is included when known because that is
    the URL the site itself publishes and the one a reader can paste.
    """
    ident = _str_or_none(listing_id)
    if not ident:
        return None
    tail = _str_or_none(slug)
    return "%s/jobs/%s%s" % (BASE_MARKETPLACE, ident, "/" + tail if tail else "")


# NO `explore_url()` / `careers_url()` helpers here, and their absence is a
# removal rather than an omission. Both existed and only returned
# `EXPLORE_URL` / `CAREERS_URL` — module constants every caller already
# imports directly — so nothing ever called either. A
# wrapper that only delegates is the same defect as dead code, and harder
# to see, because it reads like an API.
#
# Found by grepping every public name in this module for a consumer outside
# it, which is the check that section recommends and which is worth running
# before publishing rather than after.


def sku_from_url(url: str) -> Optional[str]:
    match = _SKU_IN_URL_RE.search(url or "")
    return match.group(1) if match else None


def category_from_url(url: str) -> Optional[str]:
    """What this URL selects, for the sidecar and the log line.

    Mercor's routes carry no category segment — `/explore` is the whole
    index and a job URL names one job — so this reports the ROUTE rather
    than inventing a taxonomy. The real category lives in a column
    (`domain`, from `listingDomain`, 12 distinct values measured across the
    390 listings), which is where a filterable field belongs.
    """
    route = route_of(url)
    if route == "job":
        return sku_from_url(url)
    if route == "explore":
        return "explore"
    if route == "careers":
        return "careers"
    return None


# ---------------------------------------------------------------------------
# Getting the payload out of the page
# ---------------------------------------------------------------------------

# Tolerant of `nonce=` and of any attribute order. See the module docstring:
# every page on this site carries a nonce, so the tight form matches nothing.
_NEXT_DATA_RE = re.compile(
    r"<script\b[^>]*\bid=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
    re.I | re.S)

_LD_JSON_RE = re.compile(
    r"<script\b[^>]*\btype=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
    re.I | re.S)


def extract_next_data(html: str) -> Optional[Dict[str, Any]]:
    """The `__NEXT_DATA__` payload, or None if the page carries none.

    None is meaningful here rather than merely empty: Mercor's 404 page
    carries no `__NEXT_DATA__` at all, while every real page carries one.
    That is the unambiguous positive signal `detect_page_state` leads with.
    """
    if not html:
        return None
    match = _NEXT_DATA_RE.search(html)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except (ValueError, TypeError) as exc:
        log.warning("__NEXT_DATA__ present but did not parse as JSON: %s", exc)
        return None
    return payload if isinstance(payload, dict) else None


def jsonld_blocks(html: str) -> List[Any]:
    """Every `application/ld+json` block that parses, in document order.

    A block that does not parse is skipped with a warning rather than
    taking the page down: on a site where the JSON-LD is a SECONDARY source
    (see the module docstring) a malformed block must not cost the rows
    that the React Query payload would have produced.
    """
    out: List[Any] = []
    for raw in _LD_JSON_RE.findall(html or ""):
        try:
            out.append(json.loads(raw))
        except (ValueError, TypeError) as exc:
            log.warning("skipping an unparseable ld+json block: %s", exc)
    return out


def _ld_of_type(html: str, wanted: str) -> Optional[Dict[str, Any]]:
    """The first JSON-LD node of `@type`, looking inside lists and `@graph`.

    All three shapes are legal schema.org and all three break a naive
    parser. A top-level list and an `@graph` wrapper both appear in the
    wild even where this site does not currently use them, and handling
    them costs four lines.
    """
    for block in jsonld_blocks(html):
        candidates: List[Any] = []
        if isinstance(block, list):
            candidates.extend(block)
        elif isinstance(block, dict):
            candidates.append(block)
            graph = block.get("@graph")
            if isinstance(graph, list):
                candidates.extend(graph)
        for node in candidates:
            if isinstance(node, dict) and node.get("@type") == wanted:
                return node
    return None


def itemlist_urls(html: str) -> List[str]:
    """Job URLs from the `/explore` page's `ItemList` JSON-LD.

    Read for PROVENANCE and for the canary, not for rows. It held 326 URLs
    against the same response's 390 records on 2026-09-18, omitting all 55
    `evergreen` listings and 9 standard ones. `listing_meta` reports both
    counts so a run records the gap rather than inheriting a claim about
    it, and a canary assertion on "the React Query payload is not smaller
    than the ItemList" costs one line and catches an inversion forever.
    """
    node = _ld_of_type(html, "ItemList")
    if not node:
        return []
    out: List[str] = []
    for item in node.get("itemListElement") or []:
        if isinstance(item, dict):
            url = _str_or_none(item.get("url"))
            if url:
                out.append(url)
    return out


_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)


def sitemap_job_urls(xml: str) -> List[str]:
    """Job detail URLs from `/sitemap.xml`, in document order.

    Parsed with a regex rather than an XML parser on purpose: the file is a
    flat `<urlset>` with no namespacing that matters here, and a regex
    cannot be made to resolve an external entity. 447 job URLs out of 463
    total on 2026-09-18.
    """
    out: List[str] = []
    seen = set()
    for loc in _SITEMAP_LOC_RE.findall(xml or ""):
        loc = _html.unescape(loc.strip())
        if route_of(loc) != "job":
            continue
        ident = sku_from_url(loc)
        if ident and ident not in seen:
            seen.add(ident)
            out.append(loc)
    return out


def enumerate_job_urls(sitemap_xml: Optional[str] = None,
                       explore_html: Optional[str] = None) -> List[str]:
    """The union of the two enumeration sources, sitemap order first.

    Neither source contains the other (see the module docstring: 72
    sitemap-only, 15 explore-only, 375 shared, 462 union on 2026-09-18), so
    a `--mode job` run that used either alone would silently miss live
    jobs. Sitemap order leads because it is the site's own publication
    order and is stable between runs, which keeps `--pages 20` fetching the
    same twenty jobs rather than a different twenty each night.
    """
    out: List[str] = []
    seen = set()
    for url in sitemap_job_urls(sitemap_xml or ""):
        ident = sku_from_url(url)
        if ident and ident not in seen:
            seen.add(ident)
            out.append(url)
    for record in listings_from_html(explore_html or ""):
        ident = _str_or_none(record.get("listingId"))
        if ident and ident not in seen:
            seen.add(ident)
            url = job_url(ident, _slug_for(record))
            if url:
                out.append(url)
    return out


@dataclass
class EnumerationResult:
    """Which job addresses a run could see, and how far to trust that list.

    `enumerate_job_urls` used to return a bare list, and that was the defect:
    when the sitemap could not be read the run carried on with the index
    alone — a source this module's own docstring documents as missing 72 of
    462 live listings — and the sidecar then reported the fallback's size as
    `jobs_enumerated`, as if it were the union. Reproduced on the audited
    commit: sitemap raising, 7 index records, 100 pages asked for → 7 rows,
    `status: complete`, exit 0. The warning went to a log nobody reads once
    the run exits 0; nothing in the output said the catalogue was short.

    So the list travels WITH its provenance. `complete` is the only question
    a caller needs ("is this the union, or a fallback?"), `failures` says
    which source and why, and the counts say how much each contributed so a
    reader can see the size of what a failed source would have added.
    """

    urls: List[str] = field(default_factory=list)
    sitemap_urls: int = 0
    explore_records: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.failures

    def as_sidecar(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "enumeration_complete": self.complete,
            "enumeration_sources": {"sitemap_urls": self.sitemap_urls,
                                    "explore_records": self.explore_records,
                                    "union": len(self.urls)},
        }
        if self.failures:
            out["enumeration_failures"] = list(self.failures)
        return out


def enumerate_job_sources(fetch_source, scrub=lambda text: text,
                          attempts: int = 1, pause=lambda seconds: None
                          ) -> EnumerationResult:
    """Read both enumeration sources, and say which of them failed.

    `fetch_source(url)` returns the serialised document and may raise. It is
    supplied by the ENGINE, so both reads leave from the exit the pages will
    (see `product_parser`'s module docstring on why that matters).

    A source counts as failed in TWO ways, and the second is the quiet one:
    it raised, OR it answered and held nothing. A sitemap that loads but
    carries no `<loc>` — served an error shell, or restructured — is
    indistinguishable from "the site has no jobs" unless the caller asks, and
    a live marketplace does not have zero. Both sources hold hundreds of
    entries (447 and 390 on 2026-09-18), so an empty one is a failure to read
    rather than a fact about the catalogue.

    Each source gets `attempts` tries (the engines pass `--retries`, with
    `--retry-delay` as `pause`) before it is declared failed. That is not a
    nicety: now that a lost source is reported loudly — a `partial` run, exit
    6 — a single dropped connection would otherwise cost the run its status.
    It was found live: a navigation still in flight aborted the NEXT read
    with `net::ERR_ABORTED`, on a source that was perfectly healthy.

    `scrub` is applied to every exception message before it is stored or
    logged. An exception message ends up in logs and the sidecar, and one raised
    through a proxy can carry its credentials — the sidecar is a file that
    gets shared.
    """
    result = EnumerationResult()
    texts: Dict[str, str] = {}
    counts = {"sitemap": sitemap_job_urls, "explore": listings_from_html}
    for name, url in (("sitemap", SITEMAP_URL), ("explore", EXPLORE_URL)):
        text, why = "", ""
        for attempt in range(1, max(1, int(attempts)) + 1):
            try:
                text = fetch_source(url) or ""
                why = ("" if counts[name](text)
                       else "answered but held no job URLs")
            except Exception as exc:  # noqa: BLE001 - any driver error is the same
                text = ""
                why = "%s: %s" % (type(exc).__name__, scrub(str(exc))[:200])
            if not why:
                break
            if attempt < attempts:
                log.info("%s read failed (%s); attempt %d of %d, trying again.",
                         name, why, attempt, attempts)
                pause(min(2.0 * attempt, 10.0))
        texts[name] = text
        if why:
            result.failures.append(
                "%s: %s%s" % (name, why,
                              " (after %d attempts)" % attempts
                              if attempts > 1 else ""))
    result.sitemap_urls = len(sitemap_job_urls(texts["sitemap"]))
    result.explore_records = len(listings_from_html(texts["explore"]))
    result.urls = enumerate_job_urls(texts["sitemap"], texts["explore"])

    if result.failures:
        log.warning(
            "The job enumeration is INCOMPLETE (%s). Neither source "
            "contains the other — on 2026-09-18 the sitemap held 447, the "
            "index 390, they shared 375 and the union was 462 — so this run "
            "has %d address(es) and is short by whatever the failed source "
            "would have added. It will be reported as partial.",
            "; ".join(result.failures), len(result.urls))
    elif result.urls:
        log.info("Enumerated %d job(s): %d from the sitemap, %d in the "
                 "/explore payload, %d in both. Neither source is a "
                 "superset of the other on this site.", len(result.urls),
                 result.sitemap_urls, result.explore_records,
                 result.sitemap_urls + result.explore_records
                 - len(result.urls))
    return result


def _slug_for(record: Dict[str, Any]) -> Optional[str]:
    """Rebuild the URL slug Mercor uses, from the title.

    Only used for a listing the sitemap did not carry, where no published
    URL is available. Both halves of that were measured on 2026-09-18
    rather than assumed:

      * The slug really is cosmetic. `/jobs/{id}/totally-wrong-slug` and
        `/jobs/{id}/` with no slug at all each answered 200 with the same
        listing as the correct slug. The id is the whole address.
      * This rebuild reproduces Mercor's own slug on **373 of the 375**
        listings where both are available. The two it differs on are ones
        where Mercor splits digits from letters — it writes `b-2-b-sales`
        and `non-g-7-policy` where this writes `b2b-sales` and
        `non-g7-policy`. Since a wrong slug serves the right page, the
        cost of those two is cosmetic, and encoding that quirk would be
        guessing at a rule from two examples.
    """
    title = _str_or_none(record.get("title"))
    if not title:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or None


# ---------------------------------------------------------------------------
# Navigating the three payloads
# ---------------------------------------------------------------------------

def listings_from_next_data(payload: Any) -> List[Dict[str, Any]]:
    """The marketplace records out of the dehydrated React Query cache.

    The path is
        props.pageProps.dehydratedState.queries[*].state.data.listings
    and every query is searched rather than only `queries[0]`, because a
    cache's ORDER is an implementation detail of whichever component
    prefetched first. Indexing `[0]` would work today and break on a deploy
    that added a second prefetch, in the silent direction: zero rows from a
    page that plainly has them.
    """
    if not isinstance(payload, dict):
        return []
    state = (payload.get("props") or {}).get("pageProps") or {}
    dehydrated = state.get("dehydratedState") or {}
    out: List[Dict[str, Any]] = []
    for query in dehydrated.get("queries") or []:
        if not isinstance(query, dict):
            continue
        data = (query.get("state") or {}).get("data")
        if isinstance(data, dict):
            listings = data.get("listings")
            if isinstance(listings, list):
                out.extend(x for x in listings if isinstance(x, dict))
    return out


def listings_from_html(html: str) -> List[Dict[str, Any]]:
    return listings_from_next_data(extract_next_data(html))


def role_from_next_data(payload: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(record, kind) for a detail page, where kind names which prop held it.

    A detail page publishes its listing under one of three props and the
    prop is the listing's STATE, not a fallback chain:

        role           an open listing
        poolListing    a listing that funnels into an expert pool
        closedListing  a listing no longer accepting applications

    All three were empty but `role` across the 2026-09-18 captures, so the
    other two are unverified against a real page and are read defensively:
    the kind is recorded in the row's `status` only when the record does
    not state one itself, so a guess never overwrites a fact.
    """
    if not isinstance(payload, dict):
        return None, None
    props = (payload.get("props") or {}).get("pageProps") or {}
    for key in ("role", "poolListing", "closedListing"):
        node = props.get(key)
        if isinstance(node, dict) and node:
            return node, key
    return None, None


def careers_from_next_data(payload: Any) -> List[Dict[str, Any]]:
    """Mercor's own open roles, from `props.pageProps.jobs`."""
    if not isinstance(payload, dict):
        return []
    props = (payload.get("props") or {}).get("pageProps") or {}
    jobs = props.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [j for j in jobs if isinstance(j, dict)]


# ---------------------------------------------------------------------------
# Pay
# ---------------------------------------------------------------------------

# What the marketplace's `payRateFrequency` can say, measured across the 390
# listings on 2026-09-18: hourly 347, per-task 31, one-time 9, yearly 3.
# Passed through as published rather than mapped onto a shorter vocabulary —
# "per-task" and "one-time" are genuinely different arrangements and folding
# either into "hourly" would make the rate column mean two things.
RATE_PERIODS = ("hourly", "per-task", "one-time", "yearly")


def is_known_rate_period(value: Any) -> bool:
    """Whether `payRateFrequency` is one of the four periods measured here.

    This exists so `RATE_PERIODS` has a READER. A constant carrying a
    measurement and consulted by nothing is the same defect as dead code —
    it reads like enforcement and enforces nothing, and
    this one was exactly that until the pre-publication grep found it.

    It does not gate anything: an unknown period is passed through to the
    row unchanged, because a new arrangement Mercor invents should appear
    in the data rather than vanish from it. The value of knowing is in the
    log line and in the suite, which asserts that a live run's periods are
    a subset of this tuple — so a fifth one shows up as a failing check
    rather than as a column nobody rereads.
    """
    return _str_or_none(value) in RATE_PERIODS

# Ashby states an interval per compensation component. The mapping is to the
# marketplace's vocabulary so one `rate_period` column reads the same across
# all three modes.
_ASHBY_INTERVAL_TO_PERIOD = {
    "1 YEAR": "yearly",
    "1 MONTH": "monthly",
    "1 WEEK": "weekly",
    "1 HOUR": "hourly",
    "1 TIME": "one-time",
    "NONE": None,
}


def careers_salary(compensation: Any, *, may_display: Any = None
                   ) -> Tuple[Optional[float], Optional[float],
                              Optional[str], Optional[str], Optional[bool]]:
    """(min, max, currency, period, offers_equity) from an Ashby compensation.

    A role may publish SEVERAL tiers, which are seniority bands rather than
    alternatives: "Strategic Project Lead" publishes 120-150K and 150-200K,
    and Ashby's own `compensationTierSummary` for it reads "$120K - $200K".
    So the span across every Salary component — min of the mins, max of the
    maxes — is not this parser's arithmetic, it is the site's, and it was
    checked against that summary on all four multi-tier roles.

    4 of 108 roles publish two tiers and 2 publish none at all; those two
    get null pay rather than a zero. Currency is read, never defaulted: 141
    USD components against 4 GBP on 2026-09-18. Where tiers disagree on
    currency the row's currency is None and the mismatch is warned, because
    a range spanning two currencies is not a range.

    `may_display` is Ashby's `shouldDisplayCompensationOnJobPostings`, and
    it is the AUTHORITY rather than a hint: where a site
    publishes a should-I-show-this flag, use it rather than inferring from
    the value. False means the site is withholding the figure, so the pay
    columns are null whatever the tiers happen to contain.

    Today the flag and the tiers agree on all 108 roles: the three with
    `False` carry no tiers at all. Consulting the flag anyway is the safe
    direction — a role that ever carries both would otherwise have its
    withheld salary republished by this scraper.

    A ZERO is not the same as a missing value here, and the two are told
    apart by exactly this flag. "Mercor AI Safety Fund Grants" publishes
    `shouldDisplayCompensationOnJobPostings: True`, a
    `compensationTierSummary` of `"$0"` and a real `(0, 0, USD)` salary
    component: that is a grant programme and the zero is deliberate, so it
    is written through as `0.0`. The withheld roles get `None`. A consumer
    tells them apart without any extra column, because `compensation` keeps
    the site's own string — `"$0"` against `null`.
    """
    if not isinstance(compensation, dict):
        return None, None, None, None, None
    if may_display is False:
        # The site said not to show it. Nothing below may override that.
        return None, None, None, None, None
    mins: List[float] = []
    maxes: List[float] = []
    currencies: List[str] = []
    periods: List[str] = []
    equity = False
    saw_component = False
    for tier in compensation.get("compensationTiers") or []:
        if not isinstance(tier, dict):
            continue
        for comp in tier.get("components") or []:
            if not isinstance(comp, dict):
                continue
            saw_component = True
            kind = _str_or_none(comp.get("compensationType"))
            if kind and kind.lower().startswith("equity"):
                equity = True
            if kind != "Salary":
                continue
            low = _float_or_none(comp.get("minValue"))
            high = _float_or_none(comp.get("maxValue"))
            if low is not None:
                mins.append(low)
            if high is not None:
                maxes.append(high)
            cur = _str_or_none(comp.get("currencyCode"))
            if cur:
                currencies.append(cur)
            period = _ASHBY_INTERVAL_TO_PERIOD.get(
                (_str_or_none(comp.get("interval")) or "").upper())
            if period:
                periods.append(period)
    currency = None
    if currencies:
        distinct = sorted(set(currencies))
        if len(distinct) == 1:
            currency = distinct[0]
        else:
            log.warning("compensation tiers disagree on currency (%s); "
                        "leaving it null rather than picking one",
                        ", ".join(distinct))
    period = periods[0] if periods and len(set(periods)) == 1 else (
        periods[0] if periods else None)
    return (min(mins) if mins else None,
            max(maxes) if maxes else None,
            currency,
            period,
            equity if saw_component else None)


def jsonld_currency(node: Optional[Dict[str, Any]]) -> Optional[str]:
    """`baseSalary.currency` from a detail page's JobPosting, or None.

    This is the ONLY place the marketplace states a currency: the React
    Query record carries `rateMin`/`rateMax` as bare numbers with no
    currency field anywhere. Measured USD on 40 of 40 randomly sampled
    detail pages on 2026-09-18 — which is a measurement and not a licence
    to default, so a page without a `baseSalary` node yields None and the
    row's `rate_currency` stays null (absent is null, never a defaulted
    "USD").

    Note the node is NOT read for the rate itself. Its `value.unitText` said
    HOUR on 3 of 40 pages whose own `payRateFrequency` said `per-task`, and
    it omits `baseSalary` entirely for `one-time` pay, so the record's
    fields win on both the numbers and the period.
    """
    if not isinstance(node, dict):
        return None
    salary = node.get("baseSalary")
    if not isinstance(salary, dict):
        return None
    return _str_or_none(salary.get("currency"))


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

from output_writer import JobPosting, utc_now  # noqa: E402


def _row_from_listing(record: Dict[str, Any], *, page: Optional[int] = None,
                      position: Optional[int] = None,
                      scraped_at: Optional[str] = None) -> Optional[JobPosting]:
    """One row from one `/explore` React Query record.

    `data_source="explore"`. The fields this route has and the detail route
    does not are `listingDomain`, `postedAt`, `remainingSlots`,
    `suppliedSlots` and `recentCandidatesCount`; the detail route has six
    this one does not. Neither is a subset of the other, which is why
    `data_source` is a column and not a sidecar field.
    """
    ident = _str_or_none(record.get("listingId"))
    if not ident:
        # No id means no join and no dedupe key. A row like that is worse
        # than a missing row: it inflates the count while being unusable.
        log.warning("skipping a listing record with no listingId (title=%r)",
                    _str_or_none(record.get("title")))
        return None
    return JobPosting(
        source=SOURCE_DEFAULT,
        scraped_at=scraped_at or utc_now(),
        url=job_url(ident, _slug_for(record)) or "",
        sku=ident,
        title=_str_or_none(record.get("title")),
        listing_type=_str_or_none(record.get("listingType")),
        status=_str_or_none(record.get("status")),
        domain=_str_or_none(record.get("listingDomain")),
        description=_plain_text(record.get("description")),
        commitment=_str_or_none(record.get("commitment")),
        rate_min=_float_or_none(record.get("rateMin")),
        rate_max=_float_or_none(record.get("rateMax")),
        # Deliberately null. The marketplace's listing payload states no
        # currency anywhere; only a detail page's JSON-LD does. Writing
        # "USD" here because 40 sampled detail pages said USD would be
        # presenting a guess as a fact.
        rate_currency=None,
        rate_period=_str_or_none(record.get("payRateFrequency")),
        hours_per_week=_int_or_none(record.get("hoursPerWeek")),
        location=_str_or_none(record.get("location")),
        work_arrangement=_str_or_none(record.get("workArrangement")),
        eligible_locations=_text_list(record.get("eligibleLocation")),
        eligible_residence_locations=_text_list(
            record.get("eligibleResidenceLocation")),
        company_name=_str_or_none(record.get("companyName")),
        # `companyBrandVisible` is False on 291 of 390 records and True on
        # 99, and it is the site telling you which company names it is
        # willing to show. Kept as a column because a null `company_name`
        # beside `company_brand_visible=False` is "withheld", while a null
        # beside True would be "not set" — where a site
        # publishes a should-I-show-this flag, use it rather than inferring
        # from the value.
        company_brand_visible=_bool_or_none(record.get("companyBrandVisible")),
        referral_amount=_float_or_none(record.get("referralAmount")),
        posted_at=_iso(record.get("postedAt")),
        created_at=_iso(record.get("createdAt")),
        remaining_slots=_int_or_none(record.get("remainingSlots")),
        supplied_slots=_int_or_none(record.get("suppliedSlots")),
        recent_candidates_count=_int_or_none(record.get("recentCandidatesCount")),
        data_source="explore",
        page=page,
        position=position,
    )


def _row_from_role(record: Dict[str, Any], *, url: str = "",
                   kind: Optional[str] = None,
                   jsonld: Optional[Dict[str, Any]] = None,
                   scraped_at: Optional[str] = None) -> Optional[JobPosting]:
    """One row from a `/jobs/{id}/{slug}` detail page.

    `data_source="detail"`. Checked field by field against the same job's
    `/explore` record on 2026-09-18: **zero disagreements** on the 37
    fields both publish. So no reconciliation overlay is needed here, and
    porting one from a shop repo would be exactly the dead code that
    looks load-bearing. What the detail page adds is `companyWebsite`,
    `companyDescription`, `availableSpots` and `activeContractorsCount`;
    what it drops is `listingDomain`, `postedAt` and the slot counters.
    """
    ident = (_str_or_none(record.get("listingId")) or sku_from_url(url))
    if not ident:
        log.warning("detail page at %s carried no listingId", url or "?")
        return None
    status = _str_or_none(record.get("status"))
    if not status and kind == "closedListing":
        # Only ever a fallback: if the record states its own status that
        # wins. See `role_from_next_data` — the non-`role` props are
        # unverified against a live page.
        status = "closed"
    return JobPosting(
        source=SOURCE_DEFAULT,
        scraped_at=scraped_at or utc_now(),
        url=canonical_url(url) if url else (job_url(ident, _slug_for(record)) or ""),
        sku=ident,
        title=_str_or_none(record.get("title")),
        listing_type=_str_or_none(record.get("listingType")),
        status=status,
        description=_plain_text(record.get("description")),
        commitment=_str_or_none(record.get("commitment")),
        # schema.org's vocabulary (CONTRACTOR / PART_TIME / FULL_TIME),
        # which the React Query record does not carry in any form.
        employment_type=_str_or_none((jsonld or {}).get("employmentType")),
        rate_min=_float_or_none(record.get("rateMin")),
        rate_max=_float_or_none(record.get("rateMax")),
        rate_currency=jsonld_currency(jsonld),
        rate_period=_str_or_none(record.get("payRateFrequency")),
        hours_per_week=_int_or_none(record.get("hoursPerWeek")),
        location=_str_or_none(record.get("location")),
        work_arrangement=_str_or_none(record.get("workArrangement")),
        eligible_locations=_text_list(record.get("eligibleLocation")),
        eligible_residence_locations=_text_list(
            record.get("eligibleResidenceLocation")),
        company_name=_str_or_none(record.get("companyName")),
        company_brand_visible=_bool_or_none(record.get("companyBrandVisible")),
        company_website=_str_or_none(record.get("companyWebsite")),
        company_description=_plain_text(record.get("companyDescription")),
        referral_amount=_float_or_none(record.get("referralAmount")),
        created_at=_iso(record.get("createdAt")),
        available_spots=_int_or_none(record.get("availableSpots")),
        active_contractors_count=_int_or_none(
            record.get("activeContractorsCount")),
        data_source="detail",
    )


def _row_from_career(record: Dict[str, Any], *, position: Optional[int] = None,
                     scraped_at: Optional[str] = None) -> Optional[JobPosting]:
    """One row for one of Mercor's own open roles.

    `data_source="careers"`. This is the other population: salaried
    employment at Mercor the company, published through Ashby on a
    different host with a UUID id space that shares nothing with a
    `list_…` marketplace id.
    """
    ident = _str_or_none(record.get("id"))
    if not ident:
        log.warning("skipping a careers record with no id (title=%r)",
                    _str_or_none(record.get("title")))
        return None
    low, high, currency, period, equity = careers_salary(
        record.get("compensation"),
        may_display=record.get("shouldDisplayCompensationOnJobPostings"))
    address = ((record.get("address") or {}).get("postalAddress")
               if isinstance(record.get("address"), dict) else {}) or {}
    locations = [_str_or_none(record.get("location"))]
    locations += [_str_or_none(v) for v in (record.get("secondaryLocations") or [])
                  if not isinstance(v, dict)]
    locations += [_str_or_none((v or {}).get("location"))
                  for v in (record.get("secondaryLocations") or [])
                  if isinstance(v, dict)]
    return JobPosting(
        source=SOURCE_DEFAULT,
        scraped_at=scraped_at or utc_now(),
        # Ashby's own canonical job URL. Unlike the marketplace rows this
        # points off mercor.com, and that is what the site links to.
        url=_str_or_none(record.get("jobUrl")) or CAREERS_URL,
        sku=ident,
        title=_str_or_none(record.get("title")),
        status="active" if record.get("isListed") else None,
        department=_str_or_none(record.get("department")),
        team=_str_or_none(record.get("team")),
        description=_plain_text(record.get("descriptionHtml")
                                or record.get("descriptionPlain")),
        employment_type=_str_or_none(record.get("employmentType")),
        rate_min=low,
        rate_max=high,
        rate_currency=currency,
        rate_period=period,
        # The site's own rendered string, kept verbatim beside the parsed
        # numbers so a consumer can always see what was actually published
        # — including the "• Multiple Ranges" suffix that says the numbers
        # span two seniority bands.
        compensation=_str_or_none(
            (record.get("compensation") or {}).get("compensationTierSummary")
            if isinstance(record.get("compensation"), dict) else None),
        offers_equity=equity,
        location=_str_or_none(record.get("location")),
        work_arrangement=_str_or_none(record.get("workplaceType")),
        eligible_locations=_text_list(
            [t for t in locations if t]
            or [_str_or_none(address.get("addressCountry"))]),
        posted_at=_iso(record.get("publishedAt")),
        apply_url=_str_or_none(record.get("applyUrl")),
        data_source="careers",
        position=position,
    )


# ---------------------------------------------------------------------------
# The public parse entry points
# ---------------------------------------------------------------------------

@dataclass
class ListingPage:
    """One `/explore` response: its rows, and what it says about itself.

    The same shape every engine in this family expects from a listing
    parser, so the engines stay byte-identical across repos. Three of these
    fields are constants on this site rather than readings, and saying so
    here is cheaper than three engines each discovering it:

      * `pages_available` is 1. `/explore` has no second page (see
        `page_url`), so the index is always complete in one response.
      * `page_repeated` is always False. It exists because some sites in
        this family answer a request for page 48 of a 47-page listing with
        page 1 again under HTTP 200; Mercor cannot, having only one page.
      * `total_companies` is None. Mercor paginates over nothing and
        publishes no company count — 99 of 390 listings name a company at
        all.

    `records_in_payload` and `urls_in_itemlist` are the two views the
    response has of itself, and the gap between them (390 against 326 on
    2026-09-18) is the measurement that justifies reading the React Query
    cache instead of the JSON-LD. A run RECORDS both rather than a later
    reader inheriting the figure from a docstring.
    """

    rows: List[JobPosting] = field(default_factory=list)
    records_in_payload: int = 0
    urls_in_itemlist: int = 0
    requested_page: Optional[int] = None
    echoed_page: Optional[int] = None
    pages_available: Optional[int] = None
    page_size: Optional[int] = None
    page_repeated: bool = False

    @property
    def total_jobs(self) -> Optional[int]:
        """How many listings this response holds.

        Mercor states no catalogue total anywhere, so this is a count of
        what arrived and NOT a claim about the catalogue. The sidecar
        records the enumeration union (462 on 2026-09-18) separately, which
        is the figure that answers "how much is there".
        """
        return self.records_in_payload or None

    @property
    def total_companies(self) -> Optional[int]:
        return None


def parse_listing_page(html: str, *, url: str = "", page: Optional[int] = None,
                       scraped_at: Optional[str] = None) -> ListingPage:
    """Rows from `/explore`, plus what the response says about itself.

    `page` is threaded in rather than defaulted, because of the
    arithmetic bug this prevents: `position` restarts at 1 on each page,
    so a `page` that is 1 on every row makes `page`+`position` collide and
    the position column worthless. On this route there is only ever one
    page, and the parameter is still honoured so the invariant holds if that
    ever changes.
    """
    stamp = scraped_at or utc_now()
    records = listings_from_html(html)
    rows: List[JobPosting] = []
    for index, record in enumerate(records, start=1):
        row = _row_from_listing(record, page=page, position=index,
                                scraped_at=stamp)
        if row is not None:
            rows.append(row)
    return ListingPage(
        rows=rows,
        records_in_payload=len(records),
        urls_in_itemlist=len(itemlist_urls(html)),
        requested_page=page,
        # There is one page, so the server's answer is page 1 whatever was
        # asked for. Reported rather than left None so the engine's
        # "requested N, server answered M" check has something true to read.
        echoed_page=1 if records else None,
        pages_available=1 if records else 0,
        page_size=len(records) or None,
        page_repeated=False,
    )


def parse_detail(html: str, *, url: str = "",
                 scraped_at: Optional[str] = None) -> Optional[JobPosting]:
    """One row from one `/jobs/{id}/{slug}` page, or None.

    None means the page carried no listing record — a 404, or a route this
    parser does not read. The caller distinguishes those through
    `detect_page_state`, which is the thing that knows the difference.
    """
    payload = extract_next_data(html)
    record, kind = role_from_next_data(payload)
    if not record:
        return None
    return _row_from_role(record, url=url, kind=kind,
                          jsonld=_ld_of_type(html, "JobPosting"),
                          scraped_at=scraped_at or utc_now())


def parse_careers_page(html: str, *, url: str = "",
                       scraped_at: Optional[str] = None) -> List[JobPosting]:
    """Rows from `www.mercor.com/careers`."""
    stamp = scraped_at or utc_now()
    rows: List[JobPosting] = []
    for index, record in enumerate(careers_from_next_data(
            extract_next_data(html)), start=1):
        row = _row_from_career(record, position=index, scraped_at=stamp)
        if row is not None:
            rows.append(row)
    return rows


def parse_page(html: str, *, mode: str = DEFAULT_MODE, url: str = "",
               page: Optional[int] = None,
               scraped_at: Optional[str] = None) -> List[JobPosting]:
    """Dispatch to the right parser for a mode, so an engine has one call.

    Three engines each choosing a parser by mode is three chances to
    disagree about which one reads what — the same argument that applies to
    sharing `finish_run()` and `STATE_POLICY`.
    """
    if mode == "careers":
        return parse_careers_page(html, url=url, scraped_at=scraped_at)
    if mode == "job":
        row = parse_detail(html, url=url, scraped_at=scraped_at)
        return [row] if row is not None else []
    return parse_listing_page(html, url=url, page=page,
                              scraped_at=scraped_at).rows


def listing_meta(html: str) -> Dict[str, Any]:
    """What a `/explore` response says about its own completeness.

    Mercor states no total and no page count anywhere, so unlike a site
    that hands over `totalPages` the only arithmetic
    available is the gap between this response's two views of itself. Both
    counts go in the sidecar so a run RECORDS the gap instead of a later
    reader inheriting a number from this docstring.
    """
    records = listings_from_html(html)
    indexed = itemlist_urls(html)
    meta: Dict[str, Any] = {
        "records_in_payload": len(records),
        "urls_in_itemlist": len(indexed),
        # There is exactly one page. Stated rather than implied so the
        # sidecar does not read as a truncated multi-page run.
        "pages_available": 1 if records else 0,
        "pagination_is_addressable": False,
    }
    if records and indexed and len(indexed) > len(records):
        # The inversion this is watching for: the ItemList was the smaller
        # view on 2026-09-18 (326 against 390). If it ever becomes the
        # larger one, the React Query path has started dropping rows and
        # the primary source needs revisiting.
        log.warning("the ItemList JSON-LD carries MORE entries (%d) than the "
                    "React Query payload (%d) — the primary source may be "
                    "dropping rows; see product_parser's docstring",
                    len(indexed), len(records))
    return meta


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

# Deliberately short. Eighteen candidates were counted across `/explore`, a
# detail page, the homepage and both 404s on 2026-09-18 and every one was
# zero: Mercor rendered no challenge of any kind to a Hetzner datacentre
# address. These are kept because a site that is ungated today may not be
# tomorrow and a run should say "blocked" rather than "empty" when that
# happens — but nothing here was chosen from a vendor list without counting
# it first.
#
# `cf-turnstile` is NOT here, on purpose. It is the obvious marker for a
# Turnstile and it is measured useless in any repo that can reach the
# Scraping Browser: 2Captcha's auto-solve extension injects
# `data-ts-input="cf-turnstile-response"` into every page it loads, so it
# fires on good pages, and it was absent from two real Cloudflare
# challenges in sibling repos. `challenges.cloudflare.com` is the
# one that works and it is what is carried.
BOT_CHALLENGE_MARKERS = (
    "challenges.cloudflare.com",
    "_Incapsula_Resource",
    "perimeterx.net",
    "px-captcha",
    "geo.captcha-delivery.com",
    "awswaf.com",
    "www.google.com/recaptcha/api.js",
    "hcaptcha.com/1/api.js",
)

# `/cdn-cgi/challenge-platform` was in this set for about an hour and is
# NOT here now, which is the check earning its keep on an eighth site.
# Mercor is fronted by Cloudflare, and Cloudflare injects that script into
# ORDINARY traffic as part of bot management rather than only into a
# challenge. Counted 2026-09-18 across seven captures — `/explore`, the
# careers page, the homepage, two detail pages and BOTH 404s — it was
# present exactly once on every one of the seven. With it in the set the
# 404 page classified as `blocked`: a run that asked for a listing that no
# longer exists would have reported exit 3 and sent the reader looking for
# a proxy problem.
#
# The rule was already written in this file's docstring before the mistake
# was made, and it still took running the count to catch it — which is
# the general point, that a plain measurement beats a careful
# reading. Count every candidate on a page you know is good.
#
# `challenges.cloudflare.com` was 0 on all seven and is kept. It is
# UNVERIFIED against a real Mercor challenge, because this site has never
# rendered one to us — and a sibling repo has seen that exact marker fire
# on good pages and miss the refusals, so if Mercor ever does start
# challenging, count it again before trusting it.

# How much of a response to unescape before matching. An
# edge's refusal page reaches a parser entity-escaped over an HTTP client
# and plain through a browser DOM, so a literal marker matches three
# engines and silently misses the fourth. Unescaping a BOUNDED prefix
# catches both spellings without paying to unescape 1.5 MB of job
# descriptions on every fetch — and without a description deep in the
# payload reading as a marker.
_UNESCAPE_PREFIX = 4096


def _normalised(html: Optional[str]) -> str:
    if not html:
        return ""
    head = html[:_UNESCAPE_PREFIX]
    try:
        return _html.unescape(head) + html[_UNESCAPE_PREFIX:]
    except Exception:  # pragma: no cover - unescape does not raise in practice
        return html


def detect_bot_challenge(html: Optional[str],
                         url: str = "") -> Optional[str]:
    """The first challenge marker present, or None.

    Returns the marker so a caller can log WHICH vendor answered, which is
    the difference between "blocked" and a reader knowing what to do about
    it.

    `url` is accepted and used only for the log line. It is in the signature
    because all three engines pass it, and a callee that did not take it
    would raise `TypeError` — in the BLOCKED path, which is to say at the
    exact moment a run is already in trouble and nothing else is going
    right. No live run on this site reaches that path, because Mercor has
    never refused one, so the crash would have shipped invisibly. Found by
    the signature-binding check, which is the entire reason
    that check exists.
    """
    text = _normalised(html)
    if not text:
        return None
    for marker in BOT_CHALLENGE_MARKERS:
        if marker in text:
            if url:
                log.debug("challenge marker %r on %s", marker, url)
            return marker
    return None


def references_own_assets(html: Optional[str], minimum: int = 1) -> bool:
    """Whether the response is built out of Mercor's own asset paths.

    Kept for the engines' shared interface, and documented as the WEAK
    signal it is on this site rather than presented as the structural one.
    Sibling repos rely on this check on the strength of two other
    sites, where a served page references the site's own asset host and an
    interstitial does not. Counted here on 2026-09-18 it does not
    discriminate at all:

        /explore           27 occurrences of `/_next/static`
        a detail page      23
        the homepage       27
        the 404 page       32   <-- the highest count on the site

    Mercor's not-found page is the same Next.js application, so it loads
    the same bundles. A threshold would rank the one page that is not
    content above every page that is. `detect_page_state` therefore leads
    with `__NEXT_DATA__`, which the 404 carries none of.
    """
    text = html or ""
    return text.count("/_next/static") >= max(1, minimum)


def site_turnstile_sitekey(html: Optional[str]) -> Optional[str]:
    """A Turnstile sitekey belonging to MERCOR, if the site ever ships one.

    Nothing matched across the 2026-09-18 captures — no `data-sitekey`, no
    `*_SITE_KEY` in any page config, no `<captcha-widgets>` mount point,
    which is the grep to run on a good page rather than
    concluding from an absent challenge that none is configured. So this
    returns None on every page measured so far and exists for the day that
    changes.

    A sitekey found inside a `chrome-extension://` script tag is ignored:
    that is the Scraping Browser's own auto-solve extension, not the site.
    """
    if not html:
        return None
    text = re.sub(r"<script[^>]*\bsrc=[\"'](?:chrome|moz)-extension://[^>]*>"
                  r".*?</script>", "", html, flags=re.I | re.S)
    for pattern in (r"data-sitekey=[\"']([^\"']+)[\"']",
                    r"[\"'](?:CAPTCHA_SITE_KEY|TURNSTILE_SITE_KEY)[\"']\s*:\s*"
                    r"[\"']([^\"']+)[\"']"):
        match = re.search(pattern, text, re.I)
        if match:
            return match.group(1)
    return None


# How a dead address announces itself on this site, and it is NOT a body
# marker — measured in a live browser 2026-09-18, there is no such thing
# here.
#
# Two things had to be measured before this could be written, and both
# contradicted the raw `curl` capture this repo started from:
#
#   * The live 404 page carries `__NEXT_DATA__` like every other page, so
#     "no payload" does not distinguish it. Only the curl capture lacked
#     one.
#   * There is no text that does either. Counted on four live pages, the
#     string "404" appears 1 and 2 times on the two 404s and **7 and 17
#     times on the two GOOD pages** — so the obvious marker points the
#     wrong way, the third time in this file a candidate marker did. Every other
#     candidate ("Page not found", "This page could not be found",
#     "notFound", "next-error") was 0 on all four.
#
# What DOES distinguish a dead address is that Mercor bounces it to its
# login screen: `/jobs/list_DEAD/gone` answers HTTP 404 and then the client
# redirects to `/login?redirect=%2Fjobs%2Flist_DEAD%2Fgone`, while a live
# job stays on its own URL. Both 404 captures did this; neither good page
# did.
#
# So the HTTP STATUS is the primary signal and this is the cross-engine
# fallback, which matters because Selenium's `driver.get()` returns no
# status at all: without something a URL alone can carry, two engines would
# be better informed than the third about whether a listing still exists.
_LOGIN_BOUNCE_RE = re.compile(r"^/login(?:[/?]|$)", re.I)


def bounced_to_login(url: str) -> bool:
    """Whether a fetch ended on the login screen rather than the page asked for.

    On this site that is what a dead or withdrawn address does. It is read
    from the FINAL url, so a caller must pass the address the browser ended
    on rather than the one it asked for.

    Deliberately NOT treated as "blocked": nothing is challenging us and a
    different exit would change nothing. It is also not treated as `empty`,
    which is what it classified as before this existed — and `empty` is a
    claim that the site served an answer with nothing in it, which is a
    different and wronger thing to record about a listing that is simply
    gone.
    """
    _, _, path, _ = _split_url(url or "")
    return bool(_LOGIN_BOUNCE_RE.match(path))


def expected_container_present(payload: Any, mode: str) -> bool:
    """Whether the payload holds the PLACE the records would be, empty or not.

    `listings_from_next_data` returns [] both for a genuinely empty index and
    for a payload whose key was renamed, because it looks the key up and
    shrugs when it is missing. Those are different facts and want different
    answers: the first is the site saying "nothing here" (exit 4), the second
    is this parser failing to read a page the site served. Renaming
    `listings` to `listingsV2` in a real capture reproduced it on the audited
    commit: `empty`, zero rows, indistinguishable from a real empty index.

    So presence is asked SEPARATELY from length (a page that was served and
    parses to zero rows is a parser bug, and must not read as an
    empty category):

      listings  some query's `data.listings` is a list (even `[]`)
      careers   `pageProps.jobs` is a list (even `[]`)
      job       one of `role` / `poolListing` / `closedListing` is a KEY of
                `pageProps` — a listing the site has taken down may carry
                all three as null, which is the site speaking; none of them
                existing is the shape having moved.
    """
    if not isinstance(payload, dict):
        return False
    props = (payload.get("props") or {}).get("pageProps")
    if not isinstance(props, dict):
        return False
    if mode == "careers":
        return isinstance(props.get("jobs"), list)
    if mode == "job":
        return any(k in props for k in ("role", "poolListing", "closedListing"))
    for query in (props.get("dehydratedState") or {}).get("queries") or []:
        data = ((query or {}).get("state") or {}).get("data")
        if isinstance(data, dict) and isinstance(data.get("listings"), list):
            return True
    return False


def detect_page_state(html: Optional[str], status: Optional[int] = None,
                      url: str = "", mode: str = DEFAULT_MODE) -> str:
    """Name what Mercor answered with.

    One of: `content`, `empty`, `not_found`, `blocked`, `throttled`,
    `parse_error`, `unknown`.

    The ORDER here is the whole design, and it is the
    classification-order trap stated as code: **order the signals by how
    much they prove, not by how cheap they are.** A sibling repo checked a
    threshold heuristic before an unambiguous positive signal and reported
    exit 3 for a correct answer.

    So:

    1. A payload with records in it is `content`. Nothing overrides it —
       not a status code, not a marker. A page that gave us the rows IS
       the content, and this site's one measured false positive risk runs
       the other way (see `references_own_assets`).
    2. A vendor challenge marker is `blocked`. Unambiguous, and nothing on
       this site has ever matched one.
    3. HTTP 404 or 410, or the site's own not-found copy, is `not_found` —
       a real answer about a real question, not a failure to fetch. HTTP
       429 is `throttled`, and HTTP 403 is `blocked`.
    4. A payload with NO records is `empty`: the site served us a page and
       said there is nothing here. On `/explore` that would be a genuinely
       empty index, which is worth reporting as exit 4 rather than
       retrying forever.
    5. A page carrying no `__NEXT_DATA__` at all, under any other status,
       is `parse_error` if it is large and `unknown` if it is not. Large
       means the site sent us something substantial we could not read,
       which is OUR bug and must be told apart from an empty
       category — reported as "0 products" it sends the reader to check
       the URL instead of the parser.
    """
    text = html or ""
    payload = extract_next_data(text)
    if payload is not None:
        if mode == "careers":
            records: Sequence[Any] = careers_from_next_data(payload)
        elif mode == "job":
            record, _ = role_from_next_data(payload)
            records = [record] if record else []
        else:
            records = listings_from_next_data(payload)
        if records:
            return "content"

    # An origin 404 before any marker check. A bot manager answers a
    # refused request with 403, 429 or 503 and never with 404, so a 404 is
    # the origin itself saying this route does not exist — strictly more
    # proof than a substring, which is the right order.
    #
    # The status is the PRIMARY signal and on this site it is very nearly
    # the only one, so an engine that discards it reports a dead listing as
    # `empty`. All three thread it now; `smoke_test.py` pins that.
    # 410 is the origin saying the address existed and is gone for good:
    # the same answer as a 404 for this repo's purposes.
    if status in (404, 410):
        return "not_found"
    # The cross-engine fallback, for Selenium — which has no status to
    # thread, because WebDriver exposes none. A fetch that ended on the
    # login screen did not get the page it asked for.
    if bounced_to_login(url):
        return "not_found"

    # 429 is throttling: a refusal for now, not an answer about the page.
    # Before the marker check, because its body says nothing more useful.
    if status == 429:
        return "throttled"

    marker = detect_bot_challenge(text)
    if marker:
        log.warning("challenge marker %r on %s — this site rendered none to "
                    "any request measured on 2026-09-18, so this is new",
                    marker, url or "?")
        return "blocked"
    if status == 403:
        return "blocked"
    if status is not None and status >= 500:
        return "unknown"

    if payload is not None:
        # Served and parsed. Whether it told us there is nothing here, or we
        # simply could not find where the records would be, is the whole
        # difference between exit 4 and a parser that needs fixing — and it
        # used to be decided by `payload is not None` alone.
        if not expected_container_present(payload, mode):
            return "parse_error"
        if mode == "listings" and itemlist_urls(text):
            # The response contradicts itself: the structured data indexes
            # jobs while the payload holds none. Mercor states no catalogue
            # total, but this is the same arithmetic as a served page
            # inside its own total — a claim of "empty" that
            # the page itself disproves. Measured 2026-10-07: 237 ItemList
            # urls beside 305 payload records, so on a healthy page the
            # JSON-LD is the SMALLER view, never a non-empty one beside an
            # empty payload.
            return "parse_error"
        return "empty"

    if len(text) > 2000:
        # Substantial, and we could not find the payload in it. A page
        # that was served and parses to zero rows is OUR bug, and giving it
        # its own name is what stops it reading as an empty category.
        return "parse_error"
    return "unknown"
