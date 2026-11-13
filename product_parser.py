"""
product_parser.py
-----------------
Everything this repo knows about wellfound.com lives here.

Where the data actually is
--------------------------
Counted on 2026-09-17 over the captures in `captures/wellfound`, because
The JSON-LD blocks were counted before writing a line of parser, and the
answer decides the whole design:

    /role/{role}                       0 JSON-LD blocks
    /role/r/{role}                     0 JSON-LD blocks
    /role/l/{role}/{location}          0 JSON-LD blocks
    /jobs                              0 JSON-LD blocks
    /jobs/{id}-{slug}                  1 JSON-LD block, @type JobPosting

So there is no single structured source on this site; there are two, and
they belong to different applications:

  * the LISTING routes are a Next.js app and carry a normalised Apollo cache
    in `<script id="__NEXT_DATA__">` at
    `props.pageProps.apolloState.data`. That cache is the same object the
    page renders from, so a row read out of it cannot drift from what a
    visitor sees.
  * the JOB DETAIL route carries no `__NEXT_DATA__` at all — it is
    server-rendered by a different stack — and publishes one schema.org
    `JobPosting` instead.

A DETAIL page may publish a different JSON-LD type than the listing, and
here that happens in its sharpest form: the detail page publishes a
different *mechanism*, not merely a different type. Porting the listing
parser to a detail page returns zero rows in silence, so `parse_detail()`
is a separate function and `smoke_test.py` pins that failure directly.

There is no CSS fallback, and that is a decision rather than an omission.
The family's usual second path anchors on a product-URL pattern; here every
field a row needs is inside the Apollo cache, the rendered tile carries a
strict subset of it, and the class names are build hashes. A DOM path would
be a worse copy of the same data. What replaces it is a shape check: if
`__NEXT_DATA__` is present and parses but yields no job records, that is
`parse_error` rather than "empty category".

Three routes, one query
-----------------------
All three landing shapes resolve to the same Apollo root field, which is
why one parser reads them:

    /role/{role}                 page=/seoLanding/roleSearch
    /role/r/{role}               page=/seoLanding/roleRemoteSearch
    /role/l/{role}/{location}    page=/seoLanding/roleLocationSearch

        ROOT_QUERY.talent.seoLandingPageJobSearchResults({...})

`/jobs` does NOT. It has no `Results` object at all — see PAGINATION below.

Pagination, and the two traps in it
-----------------------------------
The landing routes take `?page=N` and the site does the arithmetic for you:
the `Results` node publishes `perPage`, `pageCount`, `totalStartupCount` and
`totalJobCount`. Note what is counted — `pageCount` is over COMPANIES, not
over jobs. A 2026-09-17 capture of `/role/r/software-engineer` reported
`perPage: 20`, `pageCount: 47`, `totalStartupCount: 923`, `totalJobCount:
1881`: 47 pages of 20 companies, carrying between 30 and 50 job rows each.

Trap 1 — **the server clamps an out-of-range page back to page 1 and
answers HTTP 200.** `?page=48` against a 47-page listing returned the same
37 job ids as page 1, byte for byte. A run that walked past the end would
re-collect page 1 for as long as it was asked to. The "no new sku"
terminator does catch it, but there is a stronger and
unambiguous signal available and `echoed_page()` reads it: the Apollo cache
key embeds the arguments the SERVER used, so a response to a `?page=48`
request is keyed `seoLandingPageJobSearchResults({"page":1,...})` and says
in its own payload which page it really is.

Trap 2 — **`/jobs` is not addressable at all.** `?page=2` on it does not
fail and does not empty; it returns the identical 46 job ids as page 1.
One page kind may have no per-page addresses, so `pagination_is_addressable()` answers False for it, the engines refuse
`--concurrency > 1` with that reason, and a `--pages 5` run of that mode
stops after one page with `stop_reason=single_page_listing` rather than
reporting a complete 5-page run holding one page five times.

Compensation is a STRING, and this is the site's price parsing
--------------------------------------------------------------
The listing publishes pay as one rendered string, not as numbers. Measured
over the 312 non-null values in the captures (2026-09-17):

    202   '$140k – $250k'
     45   '$36k – $60k • No equity'
     41   '$180k – $200k • 0.5% – 1.0%'
      9   'No equity'
      8   '£120k – £160k'
      3   '₹30L – ₹80L'
      2   '0.5% – 1.0%'
      1   '€60k – €90k'
      1   '₹1,50,000 – ₹30L • No equity'

Which fixes the rules below:

  * the separator between pay and equity is U+2022 BULLET, and either side
    may be absent — 9 rows are equity-only and 2 are an equity range with
    no pay at all, so splitting on the bullet and taking `[0]` as the
    salary would have written an equity percentage into a salary column.
  * the range dash is U+2013 EN DASH, not a hyphen.
  * `k` means 1e3 and `L` means 1e5 (the Indian lakh) — 594 and 7
    occurrences. A parser that stripped non-digits would read `₹30L – ₹80L`
    as 30 to 80.
  * currency comes from the symbol, and only these four appear: `$` 576,
    `£` 16, `₹` 8, `€` 2. `$` is read as USD because that is what it means
    on a US job board and nothing better is on the page — a
    guess, and `salary_currency` is null rather than defaulted
    when no symbol is present at all.
  * `'No equity'` is a STATEMENT, not a missing value: it means the offer
    has none. It is recorded as `has_equity=False`, which is different from
    the null that means the listing did not say.

The listing string carries no period. `$140k` on a job board reads as a
year, but the page does not say so, so `salary_period` stays null on a
listing row and is filled only from the detail page's JSON-LD, which states
`unitText: "YEAR"`. Never present a guess as a fact.

Where both views exist they agree — see `smoke_test.py`, which pins job
4697947 at 100000–180000 USD from the detail page against `'$100k – $180k
• 0.05% – 0.25%'` from the listing.

Gating is per-ROUTE
-------------------
Measured from a 2Captcha US residential exit on 2026-09-17, three requests
each: `/`, `/jobs`, `/role/…` and `/jobs/{id}-{slug}` answered 200 every
time, and `/company/openai` and `/company/stripe` answered 403 every time —
including through a real Chromium on that same exit, which got Cloudflare's
"Just a moment..." interstitial rather than the page. See `page_flow.py`
for the detection, and the README for what that means for `--mode`.
"""

import html as _html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple


# --------------------------------------------------------------------------
# Hosts and routes
# --------------------------------------------------------------------------

# Wellfound serves one host. There is no per-country TLD and no locale
# segment: the site is english-only and the exit country decides nothing
# about the markup (unlike mediamarkt-scraper's ten sites). `www.` answers
# too and redirects to the bare host, so both are accepted and requests are
# rebuilt onto the canonical one.
HOSTS = ("wellfound.com", "www.wellfound.com")
CANONICAL_HOST = "wellfound.com"
BASE_URL = "https://" + CANONICAL_HOST

# angel.co was AngelList Talent's old home and still redirects here — and
# the redirect really does carry the path: measured 2026-09-17,
# `angel.co/role/r/software-engineer` came back 200 at
# `wellfound.com/role/r/software-engineer` with byte-for-byte the same page.
#
# It is still refused rather than silently rewritten, and the reason is
# narrow enough to be true: this scraper's route table, its canonical URLs
# and every row's `url` column are wellfound.com, so accepting a second
# spelling of the same host would put two spellings into the output for one
# job. The refusal says the host redirects and asks for the wellfound.com
# form — it does NOT claim the address is dead, because it is not
# (a refusal with a false reason sends the reader hunting for
# a typo).
LEGACY_HOSTS = ("angel.co", "www.angel.co", "angellist.com", "www.angellist.com")

# The one address `--mode jobs` reads. Named HERE rather than written out in
# each engine: three copies of a URL literal is three places for it to drift,
# and site knowledge belongs in this module and a handful of named
# constants in the engines — not a bare URL in all three.
FEED_URL = BASE_URL + "/jobs"

MODES = ("role", "jobs", "job")
DEFAULT_MODE = "role"

# The site's own page size for the landing routes, published as `perPage` in
# every Results node measured. Kept as a constant only as the fallback for a
# payload that omits it; the value read off the page always wins.
PAGE_SIZE = 20

_ROLE_REMOTE_RE = re.compile(r"^/role/r/(?P<role>[^/?#]+)/?$", re.I)
_ROLE_LOCATION_RE = re.compile(
    r"^/role/l/(?P<role>[^/?#]+)/(?P<location>[^/?#]+)/?$", re.I)
_ROLE_PLAIN_RE = re.compile(r"^/role/(?P<role>[^/?#]+)/?$", re.I)
_JOBS_FEED_RE = re.compile(r"^/jobs/?$", re.I)
_JOB_DETAIL_RE = re.compile(r"^/jobs/(?P<id>\d+)(?:-(?P<slug>[^/?#]*))?/?$", re.I)
_COMPANY_RE = re.compile(r"^/company/(?P<slug>[^/?#]+)(?:/[^?#]*)?/?$", re.I)

# `/role/r/x` must be tried before `/role/x`, or the plain pattern claims
# the literal segment "r" as a role slug. Ordered most-specific first.
_ROUTES = (
    ("role_remote", _ROLE_REMOTE_RE),
    ("role_location", _ROLE_LOCATION_RE),
    ("role_plain", _ROLE_PLAIN_RE),
    ("jobs_feed", _JOBS_FEED_RE),
    ("job_detail", _JOB_DETAIL_RE),
    ("company", _COMPANY_RE),
)

# The id is in the job URL's own first path segment, so a row keeps its sku
# even when read from a page that publishes no id field.
_SKU_IN_URL_RE = re.compile(r"/jobs/(\d+)(?:-|/|$)")


# --------------------------------------------------------------------------
# The row
# --------------------------------------------------------------------------

# The row model lives in `output_writer.py` with the rest of the output
# contract, the way every repo in this family arranges it.
from output_writer import JobPosting, SOURCE_DEFAULT  # noqa: E402


# --------------------------------------------------------------------------
# Small conversions
# --------------------------------------------------------------------------

_SIZE_TOKEN_RE = re.compile(r"^SIZE_(\d+)_(\d+|PLUS)$", re.I)


def company_size(token: Any) -> Optional[str]:
    """`SIZE_11_50` -> `11-50`; `SIZE_5000_PLUS` -> `5000+`.

    Eight distinct tokens were measured. An unknown one is returned
    unchanged: a band this repo has not seen is still data, and dropping it
    would make a new value look like a missing one.
    """
    if not isinstance(token, str) or not token:
        return None
    m = _SIZE_TOKEN_RE.match(token)
    if not m:
        return token
    low, high = m.group(1), m.group(2)
    return f"{low}+" if high.upper() == "PLUS" else f"{low}-{high}"


def _epoch_to_iso(value: Any) -> Optional[str]:
    """`liveStartAt` -> UTC ISO-8601, or None.

    Guarded against a value out of range rather than trusted: a bad
    timestamp raises inside `utcfromtimestamp`, and one malformed row must
    not take a page of good ones down with it (fail loudly but locally).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _str_or_none(value: Any) -> Optional[str]:
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return None


def _bool_or_none(value: Any) -> Optional[bool]:
    return value if isinstance(value, bool) else None


def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return int(value)
    except (ValueError, OverflowError):
        return None


def _text_list(values: Any) -> Optional[List[str]]:
    """A list of non-empty strings, or None for an absent or empty list.

    An empty list is None and not `[]`: `locationNames` is `[]` on 31 of
    432 measured records and means "this listing named no location", which
    is the same absence any other null column reports.
    """
    if not isinstance(values, (list, tuple)):
        return None
    out = [v.strip() for v in values if isinstance(v, str) and v.strip()]
    return out or None


# --------------------------------------------------------------------------
# Compensation
# --------------------------------------------------------------------------

# U+2022 is what the site prints; the ASCII forms are accepted so a
# hand-written fixture or a copy-paste through a lossy pipe still parses.
_COMP_SEPARATORS = ("•", "|", "·")

# Only these four were measured. An allowlist rather than a general symbol
# class, for the same reason a currency code needs an allowlist: a
# stray glyph beside a number must not mint a currency.
_CURRENCY_BY_SYMBOL = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}

# `k` is 1e3 and `L` is the Indian lakh, 1e5. `m` is not in the measured
# data and is included because a Wellfound salary written `$1.2m` would
# otherwise parse as 1.2.
_MULTIPLIERS = {"k": 1e3, "l": 1e5, "m": 1e6}

# A number with an optional multiplier suffix, allowing the grouping commas
# that '₹1,50,000' uses (Indian grouping is 2-2-3, not 3-3-3, so a
# fixed-width group pattern would not match it).
_AMOUNT_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*([kKlLmM])?")
_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_NO_EQUITY_RE = re.compile(r"\bno\s+equity\b", re.I)

# En dash is what the site prints between the two ends of a range; em dash
# and hyphen are accepted for the same robustness reason as the separators.
_RANGE_SPLIT_RE = re.compile(r"\s*[–—-]\s*")


def _amount(text: str) -> Optional[float]:
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suffix = (m.group(2) or "").lower()
    return value * _MULTIPLIERS.get(suffix, 1.0)


def _currency(text: str) -> Optional[str]:
    for symbol, code in _CURRENCY_BY_SYMBOL.items():
        if symbol in text:
            return code
    return None


@dataclass
class Compensation:
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    currency: Optional[str] = None
    equity_min: Optional[float] = None
    equity_max: Optional[float] = None
    has_equity: Optional[bool] = None


def parse_compensation(text: Any) -> Compensation:
    """Split Wellfound's rendered pay string into numbers.

    The shapes this handles are enumerated with their counts in the module
    docstring. The two that break a naive parser:

      * `'0.5% – 1.0%'` — equity with NO salary. Taking the part before the
        bullet as the salary writes 0.5 into a salary column; there is no
        bullet at all here, so the part must be classified by whether it
        holds a `%`, not by its position.
      * `'$36k – $60k • No equity'` — a statement of absence. `has_equity`
        False is a fact the listing published; None is "it did not say".
    """
    raw = _str_or_none(text)
    out = Compensation()
    if not raw:
        return out

    parts = [raw]
    for sep in _COMP_SEPARATORS:
        if sep in raw:
            parts = [p.strip() for p in raw.split(sep)]
            break

    for part in parts:
        if not part:
            continue
        if _NO_EQUITY_RE.search(part):
            out.has_equity = False
            continue
        if "%" in part:
            pcts = [float(p) for p in _PERCENT_RE.findall(part)]
            if pcts:
                out.equity_min = pcts[0]
                out.equity_max = pcts[-1] if len(pcts) > 1 else None
                # A published range is equity; only a stated "No equity"
                # sets this False.
                out.has_equity = True
            continue
        ends = _RANGE_SPLIT_RE.split(part)
        amounts = [a for a in (_amount(e) for e in ends) if a is not None]
        if amounts:
            out.salary_min = amounts[0]
            out.salary_max = amounts[-1] if len(amounts) > 1 else None
            out.currency = _currency(part)

    return out


# --------------------------------------------------------------------------
# URLs
# --------------------------------------------------------------------------

def _split_url(url: str) -> Tuple[str, str, str, str]:
    """(scheme, host, path, query) from an absolute or relative URL."""
    text = (url or "").strip()
    scheme = ""
    m = re.match(r"^(https?)://", text, re.I)
    if m:
        scheme = m.group(1).lower()
        text = text[m.end():]
        host, _, rest = text.partition("/")
        host = host.lower()
        rest = "/" + rest if rest or not text.endswith(host) else "/"
    else:
        host = ""
        rest = text if text.startswith("/") else "/" + text
    rest = rest.split("#", 1)[0]
    path, _, query = rest.partition("?")
    return scheme, host, path or "/", query


def route_of(url: str) -> Optional[str]:
    """Which of this site's routes a URL is, or None."""
    _, _, path, _ = _split_url(url)
    for name, pattern in _ROUTES:
        if pattern.match(path):
            return name
    return None


def is_supported_url(url: str) -> Tuple[bool, str]:
    """(ok, reason). The reason is shown to the user, so it says WHY.

    Refusing a host with a false reason sends the reader
    hunting for a typo. `angel.co` really is Wellfound — it redirects here —
    so the refusal says that rather than "not a Wellfound URL".
    """
    if not url or not url.strip():
        return False, "no URL given"
    scheme, host, path, _ = _split_url(url)
    if scheme and scheme not in ("http", "https"):
        return False, f"{scheme}:// is not an http(s) URL"
    if host in LEGACY_HOSTS:
        return False, (
            f"{host} is AngelList's old host and redirects to "
            f"{CANONICAL_HOST}; give the wellfound.com URL instead")
    if host and host not in HOSTS:
        return False, f"{host} is not a Wellfound host"
    route = route_of(url)
    if route is None:
        return False, (
            f"{path} is not a route this scraper reads — expected "
            "/role/{role}, /role/r/{role}, /role/l/{role}/{location}, "
            "/jobs or /jobs/{id}-{slug}")
    if route == "company":
        return False, (
            "/company/ pages are served behind Cloudflare's managed "
            "challenge and this scraper has no mode for them; see the "
            "README section 'What is gated and what is not'")
    return True, "ok"


def mode_for_url(url: str) -> Optional[str]:
    """The `--mode` a URL belongs to, so a user need not pass both."""
    return {
        "role_remote": "role", "role_location": "role", "role_plain": "role",
        "jobs_feed": "jobs", "job_detail": "job",
    }.get(route_of(url) or "")


def canonical_url(url: str) -> str:
    scheme, host, path, query = _split_url(url)
    if host not in HOSTS:
        host = CANONICAL_HOST
    return f"https://{CANONICAL_HOST}{path}" + (f"?{query}" if query else "")


def _query_pairs(query: str) -> List[Tuple[str, str]]:
    pairs = []
    for chunk in query.split("&"):
        if not chunk:
            continue
        k, _, v = chunk.partition("=")
        pairs.append((k, v))
    return pairs


def page_url(url: str, page: int) -> str:
    """Replace `?page=N`, preserving every other query parameter.

    Replace rather than duplicate, and keep what was there —
    a landing URL may carry campaign parameters the user pasted and losing
    them changes what the site answers.
    """
    scheme, host, path, query = _split_url(url)
    host = host if host in HOSTS else CANONICAL_HOST
    pairs = [(k, v) for k, v in _query_pairs(query) if k.lower() != "page"]
    if page and page > 1:
        pairs.append(("page", str(int(page))))
    tail = "&".join(f"{k}={v}" if v != "" else k for k, v in pairs)
    return f"https://{CANONICAL_HOST}{path}" + (f"?{tail}" if tail else "")


def role_url(role: str, *, location: Optional[str] = None,
             remote: bool = False) -> str:
    """Build a landing URL from a role slug, the way the site spells them."""
    role = (role or "").strip().strip("/")
    if not role:
        raise ValueError("role slug is required")
    if location:
        loc = location.strip().strip("/")
        return f"{BASE_URL}/role/l/{role}/{loc}"
    if remote:
        return f"{BASE_URL}/role/r/{role}"
    return f"{BASE_URL}/role/{role}"


def job_url(job_id: Any, slug: Optional[str] = None) -> Optional[str]:
    jid = _str_or_none(str(job_id) if job_id is not None else None)
    if not jid:
        return None
    slug = _str_or_none(slug)
    return f"{BASE_URL}/jobs/{jid}-{slug}" if slug else f"{BASE_URL}/jobs/{jid}"


def company_url(slug: Any) -> Optional[str]:
    slug = _str_or_none(slug)
    return f"{BASE_URL}/company/{slug}" if slug else None


def sku_from_url(url: str) -> Optional[str]:
    m = _SKU_IN_URL_RE.search(url or "")
    return m.group(1) if m else None


def category_from_url(url: str) -> Optional[str]:
    """A human label for what this URL selects, for the run sidecar.

    `role/software-engineer`, `role/data-scientist@new-york`, `jobs`, or
    `job/4697947`. Not a site concept — the site has no category tree —
    but `diff_runs.py` and the meta sidecar want one name for "what was
    asked for", and two runs of different roles must not look comparable.
    """
    _, _, path, _ = _split_url(url)
    m = _ROLE_LOCATION_RE.match(path)
    if m:
        return f"role/{m.group('role')}@{m.group('location')}"
    m = _ROLE_REMOTE_RE.match(path)
    if m:
        return f"role/{m.group('role')}/remote"
    m = _ROLE_PLAIN_RE.match(path)
    if m:
        return f"role/{m.group('role')}"
    if _JOBS_FEED_RE.match(path):
        return "jobs"
    m = _JOB_DETAIL_RE.match(path)
    if m:
        return f"job/{m.group('id')}"
    return None


# --------------------------------------------------------------------------
# Reading the Next.js payload
# --------------------------------------------------------------------------

# Matched non-greedily and anchored on the id, because a listing page holds
# a dozen other <script> tags and one of them is 600 KB.
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(?P<json>.*?)</script>',
    re.I | re.S)


def extract_next_data(html: str) -> Optional[Dict[str, Any]]:
    """The parsed `__NEXT_DATA__` object, or None if there is not one.

    Returns None for "absent" AND for "present but not JSON", because both
    mean the same thing to every caller: this response is not a rendered
    Next.js page. Which of the two it was is a question for `--dump-html`.
    """
    if not html:
        return None
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group("json"))
    except (ValueError, TypeError):
        return None


def apollo_state(payload: Any) -> Optional[Dict[str, Any]]:
    """The normalised Apollo cache out of a `__NEXT_DATA__` object.

    The cache is nested two deep and BOTH levels are real: `apolloState` is
    a wrapper whose only key is `data`. Reading `apolloState` itself gives a
    one-entry dict whose values have no `__typename`, which looks like an
    empty page rather than like a wrong path — the exact silent-zero failure
    to avoid. Accepts either level so a caller that already unwrapped one
    gets the same answer.
    """
    if isinstance(payload, str):
        payload = extract_next_data(payload)
    if not isinstance(payload, dict):
        return None
    state = (payload.get("props") or {}).get("pageProps") or {}
    state = state.get("apolloState")
    if not isinstance(state, dict):
        return None
    data = state.get("data")
    if isinstance(data, dict):
        return data
    # Already the inner cache: a normalised Apollo cache always has a
    # ROOT_QUERY, and that is what tells the two levels apart.
    return state if "ROOT_QUERY" in state else None


_RESULTS_KEY_RE = re.compile(
    r"^seoLandingPageJobSearchResults\((?P<args>\{.*\})\)$")


def results_node(state: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The `Results` node of a landing page, or None on a feed/detail page."""
    if not isinstance(state, dict):
        return None
    talent = (state.get("ROOT_QUERY") or {}).get("talent")
    if not isinstance(talent, dict):
        return None
    for key, value in talent.items():
        if _RESULTS_KEY_RE.match(key) and isinstance(value, dict):
            return value
    for value in talent.values():
        if isinstance(value, dict) and value.get("__typename") == "Results":
            return value
    return None


def echoed_page(state: Optional[Dict[str, Any]]) -> Optional[int]:
    """The page number the SERVER says it answered with.

    This is the whole defence against trap 1 in the module docstring. The
    Apollo cache key embeds the arguments the query actually ran with, so
    `?page=48` against a 47-page listing comes back keyed `{"page":1,…}`.
    Comparing that against the page that was requested turns "the site
    silently re-served page 1" into an unambiguous end-of-listing signal,
    which is stronger than the weaker no-new-sku heuristic.
    """
    if not isinstance(state, dict):
        return None
    talent = (state.get("ROOT_QUERY") or {}).get("talent")
    if not isinstance(talent, dict):
        return None
    for key in talent:
        m = _RESULTS_KEY_RE.match(key)
        if not m:
            continue
        try:
            args = json.loads(m.group("args"))
        except ValueError:
            continue
        return _int_or_none(args.get("page"))
    return None


def _deref(state: Dict[str, Any], node: Any) -> Any:
    """Follow one Apollo `__ref`, once. Returns the node unchanged if it is
    not a reference, and None if the reference dangles."""
    if isinstance(node, dict) and "__ref" in node:
        return state.get(node["__ref"])
    return node


JOB_TYPENAMES = ("JobListingSearchResult", "JobListing")
COMPANY_TYPENAMES = ("StartupResult", "Startup")


def _badge_labels(state: Dict[str, Any], company: Dict[str, Any]) -> Optional[List[str]]:
    refs = company.get("badges")
    if not isinstance(refs, (list, tuple)):
        return None
    labels = []
    for ref in refs:
        badge = _deref(state, ref)
        if isinstance(badge, dict):
            label = _str_or_none(badge.get("label")) or _str_or_none(badge.get("name"))
            if label:
                labels.append(label)
    return labels or None


def _company_of(state: Dict[str, Any], job_key: str,
                job: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The company a job belongs to.

    Two shapes, because the two page kinds model the edge in opposite
    directions and neither is derivable from the other:

      * the /jobs feed points DOWN — `JobListing.startup` is a `__ref`.
      * a landing page points UP — `StartupResult.highlightedJobListings`
        lists its jobs and the job carries no company field at all.

    The upward case is why this takes the job's cache KEY: that key is what
    the company's list holds, and matching on it is exact. Scanning for a
    company whose list contains this job is the same "stop at the ancestor
    that covers exactly one product" discipline used for product tiles,
    done against ids instead of DOM depth.
    """
    direct = _deref(state, job.get("startup"))
    if isinstance(direct, dict):
        return direct
    for value in state.values():
        if not isinstance(value, dict) or value.get("__typename") not in COMPANY_TYPENAMES:
            continue
        refs = value.get("highlightedJobListings")
        if not isinstance(refs, (list, tuple)):
            continue
        for ref in refs:
            if isinstance(ref, dict) and ref.get("__ref") == job_key:
                return value
    return None


def parse_job_record(state: Dict[str, Any], job_key: str, job: Dict[str, Any],
                     *, page: Optional[int] = None,
                     position: Optional[int] = None,
                     scraped_at: Optional[str] = None) -> JobPosting:
    """One Apollo job node -> one row."""
    company = _company_of(state, job_key, job) or {}
    comp = parse_compensation(job.get("compensation"))
    remote_cfg = _deref(state, job.get("remoteConfig"))
    remote_cfg = remote_cfg if isinstance(remote_cfg, dict) else {}
    primary = job.get("primaryRole")
    primary_title = _str_or_none(job.get("primaryRoleTitle"))
    if not primary_title and isinstance(primary, dict):
        primary_title = _str_or_none(primary.get("slug"))

    sku = _str_or_none(job.get("id")) or (job_key.split(":", 1)[-1] if ":" in job_key else None)
    slug = _str_or_none(job.get("slug"))

    row = JobPosting(
        scraped_at=scraped_at or datetime.now(timezone.utc).isoformat(),
        url=job_url(sku, slug) or "",
        sku=sku,
        title=_str_or_none(job.get("title")),
        company_name=_str_or_none(company.get("name")),
        company_slug=_str_or_none(company.get("slug")),
        company_id=_str_or_none(company.get("id")),
        company_url=company_url(company.get("slug")),
        company_logo_url=_str_or_none(company.get("logoUrl")),
        company_size=company_size(company.get("companySize")),
        company_tagline=_str_or_none(company.get("highConcept")),
        company_badges=_badge_labels(state, company),
        job_slug=slug,
        job_type=_str_or_none(job.get("jobType")),
        primary_role=primary_title,
        years_experience_min=_int_or_none(job.get("yearsExperienceMin")),
        years_experience_max=_int_or_none(job.get("yearsExperienceMax")),
        posted_at=_epoch_to_iso(job.get("liveStartAt")),
        locations=_text_list(job.get("locationNames")),
        remote=_bool_or_none(job.get("remote")),
        remote_kind=_str_or_none(remote_cfg.get("kind")),
        wfh_flexible=_bool_or_none(remote_cfg.get("wfhFlexible")),
        remote_locations=_text_list(job.get("acceptedRemoteLocationNames")),
        compensation=_str_or_none(job.get("compensation")),
        salary_min=comp.salary_min,
        salary_max=comp.salary_max,
        salary_currency=comp.currency,
        equity_min=comp.equity_min,
        equity_max=comp.equity_max,
        has_equity=comp.has_equity,
        description=_str_or_none(job.get("description")),
        data_source="apollo",
        page=page,
        position=position,
    )
    return row


def parse_listing(source: Any, *, url: str = "", page: Optional[int] = None,
                  scraped_at: Optional[str] = None) -> List[JobPosting]:
    """Every job row on a landing page or on the /jobs feed.

    Rows come out in the cache's own iteration order, which is the order the
    server serialised them and therefore the order the page paints. That
    makes `position` meaningful; `page` is threaded in from the caller
    rather than inferred, because a parser cannot know which page it was
    handed, and guessing produced rows that all claimed page 1.
    """
    state = apollo_state(source) if not _looks_like_state(source) else source
    if not isinstance(state, dict):
        return []
    stamp = scraped_at or datetime.now(timezone.utc).isoformat()
    rows: List[JobPosting] = []
    for key, node in state.items():
        if not isinstance(node, dict) or node.get("__typename") not in JOB_TYPENAMES:
            continue
        rows.append(parse_job_record(state, key, node, page=page,
                                     position=len(rows) + 1, scraped_at=stamp))
    return rows


def _looks_like_state(source: Any) -> bool:
    return isinstance(source, dict) and "ROOT_QUERY" in source


def listing_meta(state: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The site's own pagination arithmetic, for the run sidecar.

    A sidecar that says only "complete" is lying by omission
    where the site caps what it will serve. Wellfound does not cap the way
    bbb-scraper's site does — 47 pages really is all 923 companies — but it counts COMPANIES
    per page while a consumer counts jobs, so `total_jobs` beside
    `total_companies` is what stops someone reading 940 as the job total.
    """
    node = results_node(state) or {}
    per_page = _int_or_none(node.get("perPage")) or None
    pages = _int_or_none(node.get("pageCount"))
    return {
        "per_page": per_page or (PAGE_SIZE if pages else None),
        "pages_available": pages,
        "total_companies": _int_or_none(node.get("totalStartupCount")),
        "total_jobs": _int_or_none(node.get("totalJobCount")),
    }


def pages_to_fetch(pages_requested: int, pages_available: Optional[int]) -> int:
    """How many pages it is worth asking for.

    Clamped to what the site says it has, so a `--pages 50` run of a 2-page
    listing sends 2 requests and not 50 — and, more to the point, never
    reaches the page where the server starts re-serving page 1.
    """
    wanted = max(1, int(pages_requested or 1))
    if pages_available and pages_available > 0:
        return min(wanted, int(pages_available))
    return wanted


# --------------------------------------------------------------------------
# The detail page: schema.org JobPosting
# --------------------------------------------------------------------------

_LD_RE = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(?P<json>.*?)</script>',
    re.I | re.S)

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_text(value: Any) -> Optional[str]:
    """Strip the HTML out of JSON-LD's `description`, which is a document.

    Kept deliberately crude — tags out, entities unescaped, whitespace
    collapsed. The raw markup is what `--dump-html` is for.
    """
    text = _str_or_none(value)
    if not text:
        return None
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip() or None


def json_ld_blocks(html: str) -> List[Any]:
    out = []
    for m in _LD_RE.finditer(html or ""):
        try:
            out.append(json.loads(m.group("json")))
        except ValueError:
            continue
    return out


def _job_posting_block(html: str) -> Optional[Dict[str, Any]]:
    for block in json_ld_blocks(html):
        candidates = block if isinstance(block, list) else [block]
        for node in candidates:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return node
    return None


_EMPLOYMENT_TYPE = {
    "FULL_TIME": "full-time", "PART_TIME": "part-time",
    "CONTRACTOR": "contract", "TEMPORARY": "temporary",
    "INTERN": "internship", "OTHER": None,
}


def _salary_from_jsonld(node: Dict[str, Any]) -> Compensation:
    """`baseSalary` -> the same Compensation the listing string produces.

    One structure, and every level of it is optional in real schema.org, so
    each is read defensively. Equity has no schema.org expression at all and
    stays null here — which is a real difference between the two sources
    and the reason `data_source` is a column.
    """
    out = Compensation()
    base = node.get("baseSalary")
    if not isinstance(base, dict):
        return out
    out.currency = _str_or_none(base.get("currency"))
    value = base.get("value")
    if not isinstance(value, dict):
        return out
    lo = value.get("minValue")
    hi = value.get("maxValue")
    single = value.get("value")
    out.salary_min = float(lo) if isinstance(lo, (int, float)) and not isinstance(lo, bool) else None
    out.salary_max = float(hi) if isinstance(hi, (int, float)) and not isinstance(hi, bool) else None
    if out.salary_min is None and isinstance(single, (int, float)) and not isinstance(single, bool):
        out.salary_min = float(single)
    return out


def parse_detail(html: str, url: str = "", *,
                 scraped_at: Optional[str] = None) -> Optional[JobPosting]:
    """The one row a /jobs/{id}-{slug} page publishes, or None.

    None means this page carries no `JobPosting` block — which on this
    route means the fetch did not get the page, not that the job has no
    data. The caller turns that into `parse_error`, never into "0 jobs".
    """
    node = _job_posting_block(html or "")
    if node is None:
        return None

    identifier = node.get("identifier")
    sku = None
    if isinstance(identifier, dict):
        sku = _str_or_none(identifier.get("value"))
    sku = sku or sku_from_url(url)

    org = node.get("hiringOrganization")
    org = org if isinstance(org, dict) else {}

    comp = _salary_from_jsonld(node)
    period = None
    base = node.get("baseSalary")
    if isinstance(base, dict) and isinstance(base.get("value"), dict):
        period = _str_or_none(base["value"].get("unitText"))

    months = None
    exp = node.get("experienceRequirements")
    if isinstance(exp, dict):
        months = _int_or_none(exp.get("monthsOfExperience"))

    locations = []
    for place in (node.get("jobLocation") or []) if isinstance(node.get("jobLocation"), list) else []:
        if not isinstance(place, dict):
            continue
        addr = place.get("address")
        if not isinstance(addr, dict):
            continue
        parts = [_str_or_none(addr.get(k)) for k in
                 ("addressLocality", "addressRegion", "addressCountry")]
        label = ", ".join(p for p in parts if p)
        if label:
            locations.append(label)

    remote_locations = []
    reqs = node.get("applicantLocationRequirements")
    for req in (reqs if isinstance(reqs, list) else [reqs] if reqs else []):
        if isinstance(req, dict):
            name = _str_or_none(req.get("name"))
            if name:
                remote_locations.append(name)

    posted = _str_or_none(node.get("datePosted"))
    slug = None
    m = _JOB_DETAIL_RE.match(_split_url(url)[2]) if url else None
    if m:
        slug = m.group("slug") or None

    return JobPosting(
        scraped_at=scraped_at or datetime.now(timezone.utc).isoformat(),
        url=canonical_url(url) if url else (job_url(sku, slug) or ""),
        sku=sku,
        title=_str_or_none(node.get("title")),
        company_name=_str_or_none(org.get("name")),
        company_logo_url=_str_or_none(org.get("logo")) or _str_or_none(node.get("image")),
        job_slug=slug,
        job_type=_EMPLOYMENT_TYPE.get(
            (_str_or_none(node.get("employmentType")) or "").upper(),
            _str_or_none(node.get("employmentType"))),
        years_experience_min=(months // 12) if months else None,
        posted_at=posted,
        locations=locations or None,
        # `TELECOMMUTE` is schema.org's word for remote and is the only
        # value the site sets; its ABSENCE is not evidence of onsite, so
        # this is None rather than False when the key is missing.
        remote=True if _str_or_none(node.get("jobLocationType")) == "TELECOMMUTE" else None,
        remote_locations=remote_locations or None,
        salary_min=comp.salary_min,
        salary_max=comp.salary_max,
        salary_currency=comp.currency,
        salary_period=period,
        description=_plain_text(node.get("description")),
        benefits=_plain_text(node.get("jobBenefits")),
        industry=_str_or_none(node.get("industry")),
        data_source="jsonld",
        page=1,
        position=1,
    )


# --------------------------------------------------------------------------
# Telling a served page from a refused one
# --------------------------------------------------------------------------
#
# Every marker below was counted on pages this repo KNOWS the answer for
# before it was written down — five served captures (three landing shapes,
# the /jobs feed, a job detail page) against two refusals (the branded 403
# a plain HTTP client gets, and the /company/ page a real Chromium on a
# residential exit gets). A marker that matches a good page
# is worse than no marker.
#
# The counts, 2026-09-17, as served-max vs refused-min:
#
#     _cf_chl_opt                    0   vs  7      used
#     __cf_chl                       0   vs  3      used
#     Enable JavaScript and cookies  0   vs  1      used
#     Cloudflare Ray ID              0   vs  1      used
#     challenges.cloudflare.com      1   vs  0      REJECTED — inverted
#     cf-turnstile                   0   vs  0      REJECTED — never appears
#     cdn-cgi/challenge-platform     1   vs  1      REJECTED — both
#
# The rejected three are worth naming because two of them are what this
# family's own notes recommend. Those notes promote
# `challenges.cloudflare.com` as "the one that works" on the strength of
# foodpanda-scraper and bbb-scraper measurements; on Wellfound it is exactly
# BACKWARDS.
# The site loads Cloudflare Turnstile as part of its OWN application — it
# ships `https://challenges.cloudflare.com/turnstile/v0/api.js`, publishes
# `CLOUDFLARE_TURNSTILE_SITE_KEY` in its page config, and installs a fetch
# wrapper that renders a widget into `#turnstile_widget` when one of its
# own XHRs comes back challenged. So the marker fires on every good listing
# page and is absent from the actual refusal, which carries no widget and
# no sitekey at all. Six `turnstile` substrings on a served page, zero on
# the refusal.
#
# `cdn-cgi/challenge-platform` is on both, and the difference is the PATH:
# a served page loads `/cdn-cgi/challenge-platform/scripts/jsd/main.js`
# (Cloudflare's passive JS-detections beacon), a refusal loads
# `/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1`. The
# orchestrator path is specific; the prefix is not.

BOT_CHALLENGE_MARKERS = (
    # Cloudflare's challenge bootstrap object. Present in BOTH refusal
    # variants — the branded 403 served to a plain HTTP client and the
    # "Just a moment..." interstitial a browser gets — which is why it
    # leads: one marker covers both.
    ("cloudflare", "_cf_chl_opt"),
    ("cloudflare", "__cf_chl"),
    ("cloudflare", "challenge-platform/h/"),
    ("cloudflare", "orchestrate/chl_page"),
    # Text, for a refusal whose scripts were stripped by an intermediary.
    ("cloudflare", "Enable JavaScript and cookies"),
    ("cloudflare", "Cloudflare Ray ID"),
)

# The hosts a page the site actually served is BUILT out of. The
# positive-asset test, which is the only signal that answers correctly for
# Chromium's own network-error page — that page carries the site's
# hostname in its <title> and nothing else of the site's.
SERVED_ASSET_HOSTS = ("photos.wellfound.com", "/_next/static")

# The site's own Turnstile, as distinct from Cloudflare's interstitial.
# Named here because `page_flow.py` and the README both need to talk about
# the difference and neither should re-derive it from a substring.
SITE_TURNSTILE_SITEKEY_KEY = "CLOUDFLARE_TURNSTILE_SITE_KEY"
SITE_TURNSTILE_CONTAINER = "#turnstile_widget"

_SITEKEY_RE = re.compile(
    r'"' + SITE_TURNSTILE_SITEKEY_KEY + r'"\s*:\s*"(?P<key>[^"]+)"')


def site_turnstile_sitekey(html: str) -> Optional[str]:
    """The Turnstile sitekey the site publishes in its own page config.

    This answers the real question — not "did we meet
    a captcha" but "is one configured, and would we recognise it". One is:
    the NEXT.JS routes carry this key — the landings and the /jobs feed —
    and the site renders a widget with it into `#turnstile_widget` when its
    own fetch wrapper is challenged. Counted over 17 served captures on
    2026-09-18: 14 load the Turnstile script and 12 publish the key. The
    ones that do NOT are the routes served by a different stack — the job
    page and the home page load neither, and login and signup load the
    script but publish no key in their config.
    That widget IS solvable from a static read, because the sitekey is
    published — unlike Cloudflare's own interstitial, which publishes none
    and needs the `turnstile.render` interception hook.
    """
    m = _SITEKEY_RE.search(html or "")
    return m.group("key") if m else None


def detect_bot_challenge(html: str, url: str = "") -> Optional[str]:
    """The vendor refusing this page, or None.

    Only ever called for a page the policy has already decided is not
    content — that gate is why this can never fire on a correct
    "no results" answer and turn it into exit 3.
    """
    if not html:
        return None
    for vendor, marker in BOT_CHALLENGE_MARKERS:
        if marker in html:
            return vendor
    return None


def references_own_assets(html: str) -> int:
    """How many times this page is built out of Wellfound's own assets."""
    if not html:
        return 0
    return sum(html.count(host) for host in SERVED_ASSET_HOSTS)


# The site's own copy for a landing page that matched nothing. An
# UNAMBIGUOUS positive signal, so it is checked BEFORE the asset-count
# heuristic — the classification-order trap, where a minimal
# real page with few asset references came back as "blocked".
NO_RESULTS_MARKERS = (
    "No jobs found",
    "no results found",
    "There are no jobs",
    "Try a different search",
)


def detect_page_state(html: Optional[str], status: Optional[int] = None,
                      url: str = "", mode: str = DEFAULT_MODE) -> str:
    """One of: blocked · not_found · content · empty · parse_error · unknown.

    Ordered by how much each signal PROVES, not by how cheap it is.

    1. HTTP 403 is unambiguous on this site and is the primary signal, the
       way a status is primary on any site that states one: every refusal measured
       came with 403 and every served page with 200. It is checked before
       any markup, because the branded refusal is titled "Security Check |
       Wellfound" and carries the site's name four times — a text or title
       check calls it a real page.
    2. A challenge marker, which refines WHICH vendor for the log.
    3. The parser's own answer: a page holding job records is content.
    4. The site's own "nothing matched" copy — a positive fact only the
       real page can carry.
    5. Only then the asset-reference heuristic, and only to separate
       "served but we could not read it" from "never got the site".
    """
    text = html or ""
    if status == 404:
        return "not_found"
    if status == 403 or (status is not None and status >= 500):
        return "blocked" if status == 403 else "unknown"

    if detect_bot_challenge(text, url):
        return "blocked"

    if not text.strip():
        return "unknown"

    if mode == "job":
        return "content" if _job_posting_block(text) else (
            "parse_error" if references_own_assets(text) else "unknown")

    state = apollo_state(text)
    if state is not None:
        if parse_listing(state):
            return "content"
        lowered = text.lower()
        if any(m.lower() in lowered for m in NO_RESULTS_MARKERS):
            return "empty"
        # A Next.js page the site served, whose cache holds no job nodes
        # and which does not say it found nothing, is OUR failure to read
        # it — never "0 jobs".
        return "parse_error"

    lowered = text.lower()
    if any(m.lower() in lowered for m in NO_RESULTS_MARKERS):
        return "empty"
    if references_own_assets(text):
        return "parse_error"
    return "unknown"


def parse_products(source: Any, url: str = "", page: int = 1,
                   mode: str = DEFAULT_MODE,
                   scraped_at: Optional[str] = None) -> List[JobPosting]:
    """The engines' one entry point into this module.

    Takes whatever the driver has — raw HTML, or an already-parsed cache —
    and returns rows. `mode` decides which of the site's two structured
    sources is read; passing the wrong one returns [] rather than
    half-reading the other, and the callers turn [] on a served page into
    `parse_error`.
    """
    if mode == "job":
        row = parse_detail(source if isinstance(source, str) else "",
                           url, scraped_at=scraped_at)
        return [row] if row else []
    return parse_listing(source, url=url, page=page, scraped_at=scraped_at)


# --------------------------------------------------------------------------
# One page, as the engines consume it
# --------------------------------------------------------------------------

@dataclass
class ListingPage:
    """A page's rows plus the site's own arithmetic about them.

    The engines want both in one object so the counts cannot be read from a
    different response than the rows were.

    `echoed_page` is the field that stops the silent-repeat failure: it is
    the page number the SERVER used, and `requested_page` is the one we
    asked for. They are kept separately rather than reduced to a boolean so
    the log can say what actually happened — "asked for 48, got 1" reads as
    the end of a listing, while "asked for 48, got 48" with no new rows
    reads as a genuinely empty tail.
    """

    rows: List[JobPosting]
    total_jobs: Optional[int] = None
    total_companies: Optional[int] = None
    pages_available: Optional[int] = None
    page_size: Optional[int] = None
    echoed_page: Optional[int] = None
    requested_page: Optional[int] = None

    @property
    def page_repeated(self) -> bool:
        """True when the site answered with a page other than the one asked
        for — which on this site always means it clamped back to page 1."""
        return (self.requested_page is not None
                and self.echoed_page is not None
                and self.echoed_page != self.requested_page)


def parse_listing_page(source: Any, *, url: str = "", page: Optional[int] = None,
                       scraped_at: Optional[str] = None) -> ListingPage:
    """Rows + counts for one landing or feed page."""
    state = source if _looks_like_state(source) else apollo_state(source)
    rows = parse_listing(state, url=url, page=page, scraped_at=scraped_at) if state else []
    meta = listing_meta(state)
    return ListingPage(
        rows=rows,
        total_jobs=meta.get("total_jobs"),
        total_companies=meta.get("total_companies"),
        pages_available=meta.get("pages_available"),
        page_size=meta.get("per_page"),
        echoed_page=echoed_page(state),
        requested_page=page,
    )
