"""Tests for sitemap parsing and traversal (untrusted input)."""

import asyncio
import gzip

import pytest

from shopify_spy import _sitemap as sitemap
from shopify_spy._fetch import FakeFetcher, FetchTimeout
from shopify_spy._policy import IdentityPool, RetryPolicy, ThrottleSettings
from shopify_spy._session import HostRegistry, StoreSession
from shopify_spy._sitemap import SitemapOutcome, SitemapWalk, iter_locs, parse

NS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def urlset(*locs: str) -> str:
    entries = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {NS}>{entries}</urlset>'


def index(*locs: str) -> str:
    entries = "".join(f"<sitemap><loc>{loc}</loc></sitemap>" for loc in locs)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex {NS}>{entries}</sitemapindex>'


# --- parse ----------------------------------------------------------------------------


def test_parse_urlset():
    body = urlset("https://a.test/products/x", " https://a.test/products/y ").encode()
    assert parse(body) == ("urlset", ["https://a.test/products/x", "https://a.test/products/y"])


def test_parse_sitemapindex():
    body = index("https://a.test/sitemap_products_1.xml").encode()
    assert parse(body) == ("sitemapindex", ["https://a.test/sitemap_products_1.xml"])


def test_parse_gzip_detected_by_magic_bytes():
    body = gzip.compress(urlset("https://a.test/products/x").encode())
    assert parse(body) == ("urlset", ["https://a.test/products/x"])


def test_parse_corrupt_gzip():
    assert parse(b"\x1f\x8b" + b"garbage" * 10) == (None, [])


@pytest.mark.parametrize("body", [b"", b"not xml at all", b"<urlset><url><loc>a</loc>"])
def test_parse_malformed_does_not_raise(body):
    root, locs = parse(body)
    assert isinstance(locs, list)


def test_parse_non_sitemap_root():
    assert parse(b"<html><body><loc>x</loc></body></html>")[0] is None


def test_parse_rejects_entity_expansion():
    bomb = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
        b"<urlset><url><loc>&lol2;</loc></url></urlset>"
    )
    assert parse(bomb) == (None, [])


def test_parse_rejects_external_entity():
    xxe = (
        b'<?xml version="1.0"?>'
        b'<!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<urlset><url><loc>&xxe;</loc></url></urlset>"
    )
    assert parse(xxe) == (None, [])


def test_parse_oversize_body_ignored(monkeypatch):
    monkeypatch.setattr(sitemap, "MAX_SITEMAP_SIZE", 100)
    body = urlset(*(f"https://a.test/products/{i}" for i in range(10))).encode()
    assert parse(body) == (None, [])


def test_parse_oversize_gzip_ignored(monkeypatch):
    monkeypatch.setattr(sitemap, "MAX_SITEMAP_SIZE", 100)
    body = gzip.compress(urlset(*(f"https://a.test/products/{i}" for i in range(10))).encode())
    assert parse(body) == (None, [])


# --- iter_locs ------------------------------------------------------------------------


def make_session(routes) -> tuple[StoreSession, FakeFetcher]:
    fetcher = FakeFetcher(routes)
    registry = HostRegistry(
        concurrent_requests=16,
        throttle=ThrottleSettings(enabled=False),
        respect_robots_txt=False,
    )
    session = StoreSession(
        fetcher=fetcher,
        registry=registry,
        retry=RetryPolicy(retries=0, backoff=False),
        identity=IdentityPool(),
        request_timeout=5,
    )
    return session, fetcher


async def collect(session, url) -> list[str]:
    async with asyncio.timeout(2):
        return [loc async for loc in iter_locs(session, url)]


def outcomes(w: SitemapWalk) -> list[tuple[str, int, SitemapOutcome]]:
    return [(r.url, r.depth, r.outcome) for r in w.records]


async def test_iter_locs_urlset():
    session, _ = make_session({"https://a.test/sitemap.xml": (200, urlset("https://a.test/p/1"))})
    assert await collect(session, "https://a.test/sitemap.xml") == ["https://a.test/p/1"]


async def test_iter_locs_follows_same_host_children_and_skips_off_host():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://evil.test/s.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
            "https://evil.test/s.xml": (200, urlset("https://evil.test/p/x")),
        }
    )
    locs = await collect(session, "https://a.test/sitemap.xml")
    assert locs == ["https://a.test/p/1", "https://a.test/p/2"]
    assert fetcher.count("https://evil.test/s.xml") == 0


async def test_iter_locs_accepts_children_on_redirected_host():
    session, _ = make_session(
        {
            "https://a.test/sitemap.xml": (301, "", {"Location": "https://www.a.test/sitemap.xml"}),
            "https://www.a.test/sitemap.xml": (
                200,
                index("https://www.a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://www.a.test/s1.xml": (200, urlset("https://www.a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs = await collect(session, "https://a.test/sitemap.xml")
    assert locs == ["https://www.a.test/p/1", "https://a.test/p/2"]


async def test_iter_locs_depth_limit():
    def chain(last_body):
        return {
            "https://a.test/s0.xml": (200, index("https://a.test/s1.xml")),
            "https://a.test/s1.xml": (200, index("https://a.test/s2.xml")),
            "https://a.test/s2.xml": (200, index("https://a.test/s3.xml")),
            "https://a.test/s3.xml": (200, last_body),
            "https://a.test/s4.xml": (200, urlset("https://a.test/p/deep")),
        }

    # A urlset at depth 3 is read
    session, _ = make_session(chain(urlset("https://a.test/p/3")))
    assert await collect(session, "https://a.test/s0.xml") == ["https://a.test/p/3"]

    # An index at depth 3 pointing to depth 4 is not followed
    session, fetcher = make_session(chain(index("https://a.test/s4.xml")))
    assert await collect(session, "https://a.test/s0.xml") == []
    assert fetcher.count("https://a.test/s4.xml") == 0


async def test_iter_locs_cycle_protection():
    session, fetcher = make_session(
        {
            "https://a.test/a.xml": (200, index("https://a.test/b.xml")),
            "https://a.test/b.xml": (200, index("https://a.test/a.xml", "https://a.test/c.xml")),
            "https://a.test/c.xml": (200, urlset("https://a.test/p/1")),
        }
    )
    assert await collect(session, "https://a.test/a.xml") == ["https://a.test/p/1"]
    assert fetcher.count("https://a.test/a.xml") == 1
    assert session.stats.duplicates == 0  # stopped by the visited set, not session dedupe


@pytest.mark.parametrize("status", [404, 500])
async def test_iter_locs_non_2xx_yields_nothing(status):
    session, _ = make_session({"https://a.test/sitemap.xml": (status, urlset("https://a.test/p"))})
    assert await collect(session, "https://a.test/sitemap.xml") == []


async def test_iter_locs_request_failure_yields_nothing():
    session, _ = make_session({"https://a.test/sitemap.xml": FetchTimeout("slow")})
    assert await collect(session, "https://a.test/sitemap.xml") == []


# --- per-sitemap records --------------------------------------------------------------


async def _run_walk(session, url, follow=None) -> tuple[list[str], SitemapWalk]:
    w = iter_locs(session, url, follow)
    async with asyncio.timeout(2):
        locs = [loc async for loc in w]
    return locs, w


async def test_records_are_a_copy_and_keep_visit_order():
    session, _ = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    snapshot = w.records
    snapshot.clear()  # mutating the snapshot must not touch the walk's own list
    assert [r.url for r in w.records] == [
        "https://a.test/sitemap.xml",
        "https://a.test/s1.xml",
        "https://a.test/s2.xml",
    ]
    assert locs == ["https://a.test/p/1", "https://a.test/p/2"]


async def test_records_normal_index_expansion():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1", "https://a.test/p/2")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/3")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/1", "https://a.test/p/2", "https://a.test/p/3"]
    assert w.root_ok is True
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.urlset),
        ("https://a.test/s2.xml", 1, SitemapOutcome.urlset),
    ]
    records = {r.url: r for r in w.records}
    assert records["https://a.test/sitemap.xml"].reason == "sitemapindex listing 2 child sitemap(s)"
    assert records["https://a.test/s1.xml"].reason == "urlset yielding 2 page URL(s)"
    assert records["https://a.test/s2.xml"].reason == "urlset yielding 1 page URL(s)"
    # every fetched sitemap was requested exactly once
    for url in records:
        assert fetcher.count(url) == 1


async def test_records_child_500_is_http_error_not_request_failure():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (500, urlset("https://a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    # the failing child yields nothing, but its sibling is still walked
    assert locs == ["https://a.test/p/2"]
    assert w.root_ok is True
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.http_error),
        ("https://a.test/s2.xml", 1, SitemapOutcome.urlset),
    ]
    failed = next(r for r in w.records if r.url == "https://a.test/s1.xml")
    assert failed.reason == "HTTP 500 response"
    assert fetcher.count("https://a.test/s1.xml") == 1


async def test_records_top_level_500_leaves_root_not_ok():
    session, _ = make_session(
        {"https://a.test/sitemap.xml": (404, urlset("https://a.test/p/1"))}
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == []
    assert w.root_ok is False
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.http_error),
    ]
    assert w.records[0].reason == "HTTP 404 response"


async def test_records_child_returning_non_sitemap_content():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (200, "<html><body>not a sitemap</body></html>"),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/2"]
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.not_sitemap),
        ("https://a.test/s2.xml", 1, SitemapOutcome.urlset),
    ]
    bad = next(r for r in w.records if r.url == "https://a.test/s1.xml")
    assert bad.reason == "response body is not a sitemap"
    assert fetcher.count("https://a.test/s1.xml") == 1


async def test_records_off_host_child_skipped_without_a_request():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://evil.test/s.xml"),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
            "https://evil.test/s.xml": (200, urlset("https://evil.test/p/x")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/1"]
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.urlset),
        ("https://evil.test/s.xml", 1, SitemapOutcome.off_host),
    ]
    skipped = next(r for r in w.records if r.url == "https://evil.test/s.xml")
    assert skipped.reason.startswith("host 'evil.test'")
    assert fetcher.count("https://evil.test/s.xml") == 0


async def test_records_duplicate_child_read_only_once():
    # The same child loc is listed twice in the index; it must be read once and the
    # second encounter recorded as a duplicate (no second request).
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index(
                    "https://a.test/s1.xml",
                    "https://a.test/s2.xml",
                    "https://a.test/s1.xml",
                ),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/1", "https://a.test/p/2"]
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.urlset),
        ("https://a.test/s2.xml", 1, SitemapOutcome.urlset),
        ("https://a.test/s1.xml", 1, SitemapOutcome.duplicate),
    ]
    dup = w.records[-1]
    assert dup.reason == "sitemap already visited"
    assert fetcher.count("https://a.test/s1.xml") == 1


async def test_records_request_failure_is_distinct_from_skips():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": FetchTimeout("slow"),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/2"]
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.request_failed),
        ("https://a.test/s2.xml", 1, SitemapOutcome.urlset),
    ]
    failed = next(r for r in w.records if r.url == "https://a.test/s1.xml")
    assert "FetchTimeout" in failed.reason and "slow" in failed.reason
    assert fetcher.count("https://a.test/s1.xml") == 1


async def test_records_follow_rejected_child_is_not_requested():
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (
                200,
                index("https://a.test/s1.xml", "https://a.test/s2.xml"),
            ),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
            "https://a.test/s2.xml": (200, urlset("https://a.test/p/2")),
        }
    )

    def follow(child: str) -> bool:
        return child.endswith("s1.xml")

    locs, w = await _run_walk(session, "https://a.test/sitemap.xml", follow)

    assert locs == ["https://a.test/p/1"]
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.urlset),
        ("https://a.test/s2.xml", 1, SitemapOutcome.follow_rejected),
    ]
    rejected = next(r for r in w.records if r.url == "https://a.test/s2.xml")
    assert rejected.reason == "rejected by the follow callback"
    assert fetcher.count("https://a.test/s2.xml") == 0


async def test_records_depth_limited_child_is_not_requested():
    routes = {
        "https://a.test/s0.xml": (200, index("https://a.test/s1.xml")),
        "https://a.test/s1.xml": (200, index("https://a.test/s2.xml")),
        "https://a.test/s2.xml": (200, index("https://a.test/s3.xml")),
        # An index at depth 3 points one level beyond MAX_DEPTH
        "https://a.test/s3.xml": (200, index("https://a.test/s4.xml")),
        "https://a.test/s4.xml": (200, urlset("https://a.test/p/deep")),
    }
    session, fetcher = make_session(routes)
    locs, w = await _run_walk(session, "https://a.test/s0.xml")

    assert locs == []
    assert outcomes(w) == [
        ("https://a.test/s0.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml", 1, SitemapOutcome.index),
        ("https://a.test/s2.xml", 2, SitemapOutcome.index),
        ("https://a.test/s3.xml", 3, SitemapOutcome.index),
        ("https://a.test/s4.xml", 4, SitemapOutcome.depth_limited),
    ]
    limited = w.records[-1]
    assert "maximum of 3" in limited.reason
    assert fetcher.count("https://a.test/s4.xml") == 0


async def test_records_session_skip_is_not_requested_not_a_failure():
    # The session's own dedupe refuses a URL it already requested (canonicalized),
    # so get() returns None without sending. The walk must not call it a failure.
    # A fragment is dropped by canonicalization but legal in the index's XML, so the
    # loc and the pre-requested URL differ as strings yet share a canonical key.
    session, fetcher = make_session(
        {
            "https://a.test/sitemap.xml": (200, index("https://a.test/s1.xml#top")),
            "https://a.test/s1.xml": (200, urlset("https://a.test/p/1")),
        }
    )
    # Same canonical URL as the index loc, requested before the walk reaches it
    pre_seen = await session.get("https://a.test/s1.xml")
    assert pre_seen is not None

    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == []
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.index),
        ("https://a.test/s1.xml#top", 1, SitemapOutcome.not_requested),
    ]
    skipped = w.records[-1]
    assert skipped.reason == "request not sent: skipped by the session"
    # Only the pre-walk request ever went out
    assert fetcher.count("https://a.test/s1.xml") == 1


async def test_records_top_level_request_failure():
    session, _ = make_session({"https://a.test/sitemap.xml": FetchTimeout("slow")})
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == []
    assert w.root_ok is False
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.request_failed),
    ]
    assert "FetchTimeout" in w.records[0].reason


async def test_records_urlset_top_level():
    session, _ = make_session(
        {"https://a.test/sitemap.xml": (200, urlset("https://a.test/p/1"))}
    )
    locs, w = await _run_walk(session, "https://a.test/sitemap.xml")

    assert locs == ["https://a.test/p/1"]
    assert w.root_ok is True
    assert outcomes(w) == [
        ("https://a.test/sitemap.xml", 0, SitemapOutcome.urlset),
    ]
