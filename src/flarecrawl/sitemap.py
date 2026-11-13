"""Sitemap-first URL discovery (item 12).

Walk ``robots.txt`` for ``Sitemap:`` entries, then fall back to
``<base_url>/sitemap.xml``. Sitemap XML is parsed with selectolax's XML
mode for speed; output is a list of ``(url, lastmod)`` tuples, suitable
for seeding into the crawl frontier with a high priority.

Discovery is best-effort by design — a real sitemap index routinely
points at dozens of child sitemaps, and some of them time out, return
``4xx``/``5xx``, blow past :data:`MAX_SITEMAP_BYTES`, or are indexes
themselves. :func:`discover_sitemap_urls` still returns just the entry
list (unchanged shape and order) while
:func:`discover_sitemap_urls_with_report` additionally returns a
:class:`SitemapReport` with one :class:`SitemapAttempt` per child
sitemap, including those skipped because the ``max_sitemaps`` budget
ran out. Callers can therefore tell "site has no pages" apart from
"we never got to that child sitemap".
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field

import httpx
from selectolax.parser import HTMLParser

from . import DEFAULT_USER_AGENT
from ._http import (
    REQUEST_ERROR,
    TOO_LARGE,
    ensure_client,
    polite_get,
    polite_get_detailed,
)
from ._http import (
    origin as _origin_of,
)

logger = logging.getLogger(__name__)

_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_FETCH_TIMEOUT = 15.0

#: Hard cap on a single sitemap response body. The sitemap protocol
#: limits uncompressed sitemaps to 50 MiB but most are well under
#: 10 MiB. 10 MiB balances "accept realistic real-world sitemaps"
#: with "don't let a hostile origin exhaust memory".
MAX_SITEMAP_BYTES = 10 * 1024 * 1024

#: Terminal states recorded for each sitemap we tried (or skipped).
#: ``REQUEST_ERROR`` / ``TOO_LARGE`` are re-exported from
#: :mod:`flarecrawl._http` so the values match the shared fetch helper.
STATUS_OK = "ok"
STATUS_HTTP_ERROR = "http_error"
STATUS_REQUEST_ERROR = REQUEST_ERROR
STATUS_TOO_LARGE = TOO_LARGE
STATUS_PARSE_ERROR = "parse_error"
STATUS_NOT_ATTEMPTED = "not_attempted"

#: Statuses that mean the sitemap was actually fetched.
ATTEMPTED_STATUSES = frozenset(
    {
        STATUS_OK,
        STATUS_HTTP_ERROR,
        STATUS_REQUEST_ERROR,
        STATUS_TOO_LARGE,
        STATUS_PARSE_ERROR,
    }
)


@dataclass(slots=True)
class SitemapEntry:
    url: str
    lastmod: str | None = None


@dataclass(slots=True)
class SitemapAttempt:
    """Outcome for one child sitemap in a discovery run.

    A single record is produced per unique sitemap URL. ``status`` is
    one of :data:`STATUS_OK`, :data:`STATUS_HTTP_ERROR`,
    :data:`STATUS_REQUEST_ERROR`, :data:`STATUS_TOO_LARGE`,
    :data:`STATUS_PARSE_ERROR`, or :data:`STATUS_NOT_ATTEMPTED` (queued
    but the ``max_sitemaps`` budget ran out first).
    """

    url: str
    status: str
    #: HTTP status when a response was received (``None`` for transport
    #: failures and untried sitemaps).
    http_status: int | None = None
    #: Number of page entries parsed. Always ``0`` for failures, and
    #: ``0`` for sitemap indexes (their children are separate attempts).
    entry_count: int = 0
    #: Number of child sitemap URLs enqueued (index documents only).
    child_count: int = 0
    #: Short human-readable explanation for non-OK outcomes.
    detail: str | None = None

    @property
    def attempted(self) -> bool:
        """True when a fetch was actually attempted for this sitemap."""
        return self.status in ATTEMPTED_STATUSES

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class RobotsOutcome:
    """Outcome of the ``robots.txt`` fetch used to seed discovery."""

    url: str
    status: str
    http_status: int | None = None
    #: Number of ``Sitemap:`` directives advertised by robots.txt.
    sitemap_count: int = 0
    detail: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _http_error_detail(status_code: int) -> str:
    return f"HTTP {status_code}"


@dataclass(slots=True)
class SitemapReport:
    """Per-sitemap outcome log for one :func:`discover_sitemap_urls` run.

    ``entries`` is the exact list returned by
    :func:`discover_sitemap_urls` (same objects, same order).
    ``attempts`` holds one :class:`SitemapAttempt` per unique child
    sitemap URL, in discovery order, including untried URLs skipped by
    the budget.
    """

    base_url: str
    robots: RobotsOutcome
    #: True when robots.txt advertised no sitemap and
    #: ``<origin>/sitemap.xml`` was used instead.
    used_fallback: bool
    attempts: list[SitemapAttempt] = field(default_factory=list)
    entries: list[SitemapEntry] = field(default_factory=list)
    max_sitemaps: int = 50

    @property
    def attempted_count(self) -> int:
        """Number of sitemaps actually fetched (duplicates count once)."""
        return sum(1 for a in self.attempts if a.attempted)

    @property
    def not_attempted(self) -> list[SitemapAttempt]:
        """Queued sitemaps that were never fetched because of the budget."""
        return [a for a in self.attempts if a.status == STATUS_NOT_ATTEMPTED]

    @property
    def failed(self) -> list[SitemapAttempt]:
        """Attempted sitemaps that did not yield a usable document."""
        return [a for a in self.attempts if a.attempted and a.status != STATUS_OK]

    def as_dict(self) -> dict:
        return {
            "base_url": self.base_url,
            "robots": self.robots.as_dict(),
            "used_fallback": self.used_fallback,
            "max_sitemaps": self.max_sitemaps,
            "attempted_count": self.attempted_count,
            "attempts": [a.as_dict() for a in self.attempts],
            "entries": [asdict(e) for e in self.entries],
        }


async def _get(
    url: str, client: httpx.AsyncClient, user_agent: str,
    *, max_bytes: int | None = None,
) -> httpx.Response | None:
    return await polite_get(
        url,
        client=client,
        user_agent=user_agent,
        timeout=_FETCH_TIMEOUT,
        max_bytes=max_bytes,
    )


def _origin(url: str) -> str:
    return _origin_of(url)


async def sitemap_urls_from_robots(
    base_url: str,
    client: httpx.AsyncClient,
    user_agent: str = DEFAULT_USER_AGENT,
) -> list[str]:
    """Return the list of sitemap URLs advertised in robots.txt (if any)."""
    origin = _origin(base_url)
    resp = await _get(f"{origin}/robots.txt", client, user_agent)
    if resp is None or resp.status_code >= 400:
        return []
    return _SITEMAP_RE.findall(resp.text)


def parse_sitemap_xml(text: str) -> list[SitemapEntry]:
    """Parse sitemap XML (urlset or sitemapindex). Nested indexes expand to
    their child ``loc`` entries marked with ``lastmod=None`` for the caller
    to follow if desired.
    """
    # selectolax's HTMLParser handles sloppy XML well enough for sitemaps.
    tree = HTMLParser(text)
    entries: list[SitemapEntry] = []
    for url_node in tree.css("url"):
        loc = url_node.css_first("loc")
        if not loc or not loc.text(strip=True):
            continue
        lm = url_node.css_first("lastmod")
        entries.append(
            SitemapEntry(
                url=loc.text(strip=True),
                lastmod=lm.text(strip=True) if lm else None,
            )
        )
    if entries:
        return entries
    # Sitemap index: just return the child sitemap URLs.
    for sm in tree.css("sitemap"):
        loc = sm.css_first("loc")
        if loc and loc.text(strip=True):
            entries.append(SitemapEntry(url=loc.text(strip=True), lastmod=None))
    return entries


async def _fetch_robots(
    base_url: str,
    client: httpx.AsyncClient,
    user_agent: str,
) -> tuple[RobotsOutcome, list[str]]:
    """Fetch robots.txt and return (outcome, advertised sitemap URLs).

    Never raises: HTTP errors, transport errors and oversized bodies all
    become a non-``ok`` :class:`RobotsOutcome` with no sitemap URLs, so
    discovery falls back to ``<origin>/sitemap.xml`` exactly as before.
    """
    url = f"{_origin(base_url)}/robots.txt"
    resp, failure = await polite_get_detailed(
        url,
        client=client,
        user_agent=user_agent,
        timeout=_FETCH_TIMEOUT,
        max_bytes=MAX_SITEMAP_BYTES,
    )
    if failure is not None:
        return (
            RobotsOutcome(
                url=url, status=failure.kind, detail=failure.detail
            ),
            [],
        )
    assert resp is not None  # exactly one of resp/failure is set
    if resp.status_code >= 400:
        return (
            RobotsOutcome(
                url=url,
                status=STATUS_HTTP_ERROR,
                http_status=resp.status_code,
                detail=_http_error_detail(resp.status_code),
            ),
            [],
        )
    urls = _SITEMAP_RE.findall(resp.text)
    return (
        RobotsOutcome(
            url=url,
            status=STATUS_OK,
            http_status=resp.status_code,
            sitemap_count=len(urls),
        ),
        urls,
    )


async def discover_sitemap_urls_with_report(
    base_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    follow_index: bool = True,
    max_sitemaps: int = 50,
) -> SitemapReport:
    """Discover sitemap URLs and record an outcome for every child sitemap.

    Resolution order is identical to :func:`discover_sitemap_urls`:
    ``robots.txt`` ``Sitemap:`` entries first, then
    ``<origin>/sitemap.xml``. ``report.entries`` matches the list the
    plain function returns, in the same order.

    ``max_sitemaps`` caps the number of sitemaps *actually fetched*
    (duplicate URLs are deduplicated and count once). Any sitemap still
    queued when the budget is exhausted is recorded with status
    ``not_attempted`` rather than silently dropped. Fetch failures —
    ``4xx``/``5xx``, transport errors, and bodies over
    :data:`MAX_SITEMAP_BYTES` — never raise; they become failure
    attempts in the report.
    """
    async with ensure_client(client) as (c, _owns):
        robots, robots_urls = await _fetch_robots(base_url, c, user_agent)
        used_fallback = not robots_urls
        sitemap_urls = (
            list(robots_urls)
            if robots_urls
            else [f"{_origin(base_url)}/sitemap.xml"]
        )

        # ``seen`` doubles as the dedupe set and the budget counter: a
        # URL is added once, when first queued, so duplicate locs in
        # robots.txt or a sitemap index never cost a second fetch.
        seen: set[str] = set()
        queue: list[str] = []
        for sm_url in sitemap_urls:
            if sm_url not in seen:
                seen.add(sm_url)
                queue.append(sm_url)

        attempts: list[SitemapAttempt] = []
        entries: list[SitemapEntry] = []
        attempted = 0

        while queue:
            sm_url = queue.pop(0)
            if attempted >= max_sitemaps:
                attempts.append(
                    SitemapAttempt(
                        url=sm_url,
                        status=STATUS_NOT_ATTEMPTED,
                        detail=(
                            f"max_sitemaps budget ({max_sitemaps}) "
                            "exhausted before this sitemap was fetched"
                        ),
                    )
                )
                continue

            attempted += 1
            resp, failure = await polite_get_detailed(
                sm_url,
                client=c,
                user_agent=user_agent,
                timeout=_FETCH_TIMEOUT,
                max_bytes=MAX_SITEMAP_BYTES,
            )
            if failure is not None:
                attempts.append(
                    SitemapAttempt(
                        url=sm_url,
                        status=failure.kind,
                        detail=failure.detail,
                    )
                )
                continue
            assert resp is not None
            if resp.status_code >= 400:
                attempts.append(
                    SitemapAttempt(
                        url=sm_url,
                        status=STATUS_HTTP_ERROR,
                        http_status=resp.status_code,
                        detail=_http_error_detail(resp.status_code),
                    )
                )
                continue

            try:
                parsed = parse_sitemap_xml(resp.text)
            except Exception as exc:  # pragma: no cover — defensive
                logger.debug("sitemap parse failed for %s: %r", sm_url, exc)
                attempts.append(
                    SitemapAttempt(
                        url=sm_url,
                        status=STATUS_PARSE_ERROR,
                        http_status=resp.status_code,
                        detail=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            # Heuristic: if the doc tag is ``<sitemapindex>``, follow.
            if follow_index and "<sitemapindex" in resp.text[:200].lower():
                enqueued = 0
                for e in parsed:
                    if e.url not in seen:
                        seen.add(e.url)
                        queue.append(e.url)
                        enqueued += 1
                attempts.append(
                    SitemapAttempt(
                        url=sm_url,
                        status=STATUS_OK,
                        http_status=resp.status_code,
                        child_count=enqueued,
                        detail=f"sitemap index ({enqueued} child sitemaps queued)",
                    )
                )
                continue

            entries.extend(parsed)
            attempts.append(
                SitemapAttempt(
                    url=sm_url,
                    status=STATUS_OK,
                    http_status=resp.status_code,
                    entry_count=len(parsed),
                )
            )

        return SitemapReport(
            base_url=base_url,
            robots=robots,
            used_fallback=used_fallback,
            attempts=attempts,
            entries=entries,
            max_sitemaps=max_sitemaps,
        )


async def discover_sitemap_urls(
    base_url: str,
    *,
    client: httpx.AsyncClient | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    follow_index: bool = True,
    max_sitemaps: int = 50,
) -> list[SitemapEntry]:
    """Discover sitemap URLs for ``base_url``.

    Resolution order:
    1. ``robots.txt`` ``Sitemap:`` entries.
    2. ``<origin>/sitemap.xml`` fallback.

    If the response is a sitemap-index and ``follow_index`` is true,
    child sitemaps are fetched and merged (up to ``max_sitemaps``).

    Returns only the entry list, preserving the original API. Use
    :func:`discover_sitemap_urls_with_report` for a per-sitemap outcome
    log alongside the same entries.
    """
    report = await discover_sitemap_urls_with_report(
        base_url,
        client=client,
        user_agent=user_agent,
        follow_index=follow_index,
        max_sitemaps=max_sitemaps,
    )
    return report.entries
