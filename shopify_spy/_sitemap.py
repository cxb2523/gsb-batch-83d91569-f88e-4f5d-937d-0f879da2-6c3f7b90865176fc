"""Sitemap parsing for untrusted input.

Sitemaps come from arbitrary servers, so parsing uses defusedxml, decompressed size
is capped, index nesting is limited, and child sitemaps must stay on the store's
host.
"""

from __future__ import annotations

import io
import logging
import zlib
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from enum import StrEnum

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from shopify_spy._fetch import FetchTooLarge, decompress
from shopify_spy._session import STORE, RequestFailed, RequestKind, StoreSession
from shopify_spy._utils import hostname

logger = logging.getLogger("shopify_spy")

MAX_SITEMAP_SIZE = 50 * 1024 * 1024  # sitemaps.org limit, uncompressed
MAX_DEPTH = 3


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse(body: bytes) -> tuple[str | None, list[str]]:
    """Parse a sitemap document; return (root type, [loc, ...]).

    The root type is "sitemapindex", "urlset" or None if the body isn't a sitemap.
    Gzipped bodies are detected by their magic bytes.
    """
    if body[:2] == b"\x1f\x8b":
        try:
            body = decompress(body, zlib.MAX_WBITS | 16, MAX_SITEMAP_SIZE)
        except (zlib.error, FetchTooLarge) as exc:
            logger.warning("Bad gzipped sitemap: %s", exc)
            return None, []
    if len(body) > MAX_SITEMAP_SIZE:
        logger.warning("Sitemap larger than %d bytes ignored", MAX_SITEMAP_SIZE)
        return None, []
    root_type: str | None = None
    locs: list[str] = []
    path: list[str] = []  # local names of the open elements
    try:
        for event, elem in ElementTree.iterparse(io.BytesIO(body), events=("start", "end")):
            name = _local(elem.tag)
            if event == "start":
                if root_type is None:
                    root_type = name if name in ("sitemapindex", "urlset") else ""
                path.append(name)
                continue
            path.pop()
            # Only a <loc> directly under <url>/<sitemap> is a page; extensions such
            # as <image:image><image:loc> nest deeper
            if name == "loc" and elem.text and path[-1:] in (["url"], ["sitemap"]):
                locs.append(elem.text.strip())
    except (ElementTree.ParseError, DefusedXmlException) as exc:
        logger.warning("Unparseable sitemap: %s", exc)
    return root_type or None, locs


class SitemapOutcome(StrEnum):
    """How one attempt to read a sitemap ended.

    ``not_requested`` and the other skip outcomes mean no HTTP request was sent,
    unlike ``request_failed`` and ``http_error``.
    """

    urlset = "urlset"  # read a urlset; its page URLs were yielded
    index = "index"  # read a sitemapindex; its children were considered
    request_failed = "request_failed"  # the request raised RequestFailed
    http_error = "http_error"  # a response arrived, but its status was not 2xx
    not_sitemap = "not_sitemap"  # a 2xx body whose content is not a sitemap
    off_host = "off_host"  # child on another host; not requested
    follow_rejected = "follow_rejected"  # follow() returned False; not requested
    depth_limited = "depth_limited"  # nesting past MAX_DEPTH; not requested
    duplicate = "duplicate"  # the sitemap was already visited; not requested
    not_requested = "not_requested"  # the session sent no request (dedupe/robots)


@dataclass(frozen=True)
class SitemapRecord:
    """One sitemap read attempt, in the order the walk reached it."""

    url: str
    depth: int  # 0 for the top-level sitemap, 1 for its children, ...
    outcome: SitemapOutcome
    reason: str


class SitemapWalk:
    """Async-iterable page URLs from a sitemap, following indexes on the same host.

    The store's hosts are the sitemap URL's host plus wherever it redirected to.
    ``root_ok`` becomes True once the top-level sitemap has been read.
    ``follow(child_url)`` decides which child sitemaps of an index are read.
    ``kind`` is the request kind for every sitemap fetched.

    Every sitemap the walk reaches -- the top-level map and each index child,
    including ones that are skipped without a request -- gets one entry in
    :attr:`records`, appended in visit order. Iterating still yields only page URLs.
    """

    def __init__(
        self,
        session: StoreSession,
        sitemap_url: str,
        follow: Callable[[str], bool] | None = None,
        kind: RequestKind = STORE,
    ) -> None:
        self.session = session
        self.kind = kind
        self.sitemap_url = sitemap_url
        self.follow = follow or (lambda url: True)
        self.root_ok = False
        self.hosts = {hostname(sitemap_url)}
        self._visited: set[str] = set()
        self._records: list[SitemapRecord] = []

    @property
    def records(self) -> list[SitemapRecord]:
        """A read-only snapshot of every sitemap read attempt, in visit order."""
        return list(self._records)

    def _record(self, url: str, depth: int, outcome: SitemapOutcome, reason: str) -> None:
        self._records.append(SitemapRecord(url, depth, outcome, reason))

    def __aiter__(self) -> AsyncIterator[str]:
        return self._walk(self.sitemap_url, 0)

    async def _walk(self, url: str, depth: int) -> AsyncIterator[str]:
        if url in self._visited:
            self._record(url, depth, SitemapOutcome.duplicate, "sitemap already visited")
            return
        if depth > MAX_DEPTH:
            self._record(
                url,
                depth,
                SitemapOutcome.depth_limited,
                f"depth {depth} exceeds the maximum of {MAX_DEPTH}",
            )
            return
        self._visited.add(url)
        try:
            response = await self.session.get(url, kind=self.kind)
        except RequestFailed as exc:
            logger.info("Sitemap request failed: %s", exc)
            if isinstance(exc.cause, BaseException):
                reason = f"{type(exc.cause).__name__}: {exc}"
            else:
                reason = str(exc)
            self._record(url, depth, SitemapOutcome.request_failed, reason)
            return
        if response is None:
            # The session skipped the request itself (its own dedupe or robots.txt);
            # nothing was sent, so this is not a request failure.
            self._record(
                url,
                depth,
                SitemapOutcome.not_requested,
                "request not sent: skipped by the session",
            )
            return
        if not response.ok:
            self._record(
                url, depth, SitemapOutcome.http_error, f"HTTP {response.status} response"
            )
            return
        root, locs = parse(response.body)
        if depth == 0:
            self.hosts.add(hostname(response.url))
            self.root_ok = root is not None
        if root is None:
            self._record(
                url, depth, SitemapOutcome.not_sitemap, "response body is not a sitemap"
            )
            return
        if root == "sitemapindex":
            self._record(
                url,
                depth,
                SitemapOutcome.index,
                f"sitemapindex listing {len(locs)} child sitemap(s)",
            )
            for loc in locs:
                child_depth = depth + 1
                if hostname(loc) not in self.hosts:
                    logger.info("Skipping off-host child sitemap %s", loc)
                    self._record(
                        loc,
                        child_depth,
                        SitemapOutcome.off_host,
                        f"host {hostname(loc)!r} is not one of the top-level sitemap's hosts",
                    )
                elif not self.follow(loc):
                    self._record(
                        loc,
                        child_depth,
                        SitemapOutcome.follow_rejected,
                        "rejected by the follow callback",
                    )
                else:
                    async for page in self._walk(loc, child_depth):
                        yield page
        else:  # urlset
            self._record(
                url,
                depth,
                SitemapOutcome.urlset,
                f"urlset yielding {len(locs)} page URL(s)",
            )
            for loc in locs:
                yield loc


def iter_locs(
    session: StoreSession,
    sitemap_url: str,
    follow: Callable[[str], bool] | None = None,
    kind: RequestKind = STORE,
) -> SitemapWalk:
    """Walk a sitemap: ``async for loc in iter_locs(session, url)``."""
    return SitemapWalk(session, sitemap_url, follow, kind)
