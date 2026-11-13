"""Tests for sitemap-first discovery (item 12)."""

from __future__ import annotations

import pytest

pytest.importorskip("selectolax", reason="optional dep")
pytest.importorskip("aiosqlite", reason="optional dep")
import asyncio

import httpx

from flarecrawl.sitemap import (
    STATUS_HTTP_ERROR,
    STATUS_NOT_ATTEMPTED,
    STATUS_OK,
    STATUS_REQUEST_ERROR,
    STATUS_TOO_LARGE,
    SitemapEntry,
    discover_sitemap_urls,
    discover_sitemap_urls_with_report,
    parse_sitemap_xml,
    sitemap_urls_from_robots,
)

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://example.com/a</loc>
    <lastmod>2025-01-01</lastmod>
  </url>
  <url>
    <loc>https://example.com/b</loc>
  </url>
</urlset>
""".strip()

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://example.com/sm1.xml</loc></sitemap>
  <sitemap><loc>https://example.com/sm2.xml</loc></sitemap>
</sitemapindex>
""".strip()


def test_parse_urlset():
    entries = parse_sitemap_xml(SITEMAP_XML)
    assert entries == [
        SitemapEntry("https://example.com/a", "2025-01-01"),
        SitemapEntry("https://example.com/b", None),
    ]


def test_parse_sitemap_index():
    entries = parse_sitemap_xml(SITEMAP_INDEX)
    urls = {e.url for e in entries}
    assert urls == {"https://example.com/sm1.xml", "https://example.com/sm2.xml"}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_sitemap_urls_from_robots():
    robots = "User-agent: *\nSitemap: https://example.com/sitemap.xml\nSitemap: https://example.com/other.xml\n"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        return httpx.Response(404)

    async def run():
        async with _client(handler) as c:
            return await sitemap_urls_from_robots("https://example.com/", c)

    urls = asyncio.run(run())
    assert urls == [
        "https://example.com/sitemap.xml",
        "https://example.com/other.xml",
    ]


def test_discover_uses_fallback():
    """With no Sitemap: in robots, /sitemap.xml is tried."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\n")
        if request.url.path == "/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_XML)
        return httpx.Response(404)

    async def run():
        async with _client(handler) as c:
            return await discover_sitemap_urls("https://example.com/", client=c)

    entries = asyncio.run(run())
    assert {e.url for e in entries} == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_discover_follows_sitemap_index():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="Sitemap: https://example.com/index.xml\n")
        if path == "/index.xml":
            return httpx.Response(200, text=SITEMAP_INDEX)
        if path == "/sm1.xml":
            return httpx.Response(200, text=SITEMAP_XML)
        if path == "/sm2.xml":
            return httpx.Response(
                200,
                text=SITEMAP_XML.replace(
                    "https://example.com/a", "https://example.com/c"
                ).replace(
                    "https://example.com/b", "https://example.com/d"
                ),
            )
        return httpx.Response(404)

    async def run():
        async with _client(handler) as c:
            return await discover_sitemap_urls("https://example.com/", client=c)

    entries = asyncio.run(run())
    urls = {e.url for e in entries}
    assert urls == {
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
        "https://example.com/d",
    }


# ---------------------------------------------------------------------------
# Response size cap (S3)
# ---------------------------------------------------------------------------
def test_sitemap_oversize_content_length_skipped():
    from flarecrawl.sitemap import MAX_SITEMAP_BYTES

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        # Pretend the sitemap is bigger than the cap.
        return httpx.Response(
            200,
            text=SITEMAP_XML,
            headers={"content-length": str(MAX_SITEMAP_BYTES + 1)},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as c:
            entries = await discover_sitemap_urls(
                "https://example.com", client=c, follow_index=False
            )
            assert entries == []

    asyncio.run(run())


def test_sitemap_within_cap_parses_normally():
    from flarecrawl.sitemap import MAX_SITEMAP_BYTES

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200,
            text=SITEMAP_XML,
            headers={"content-length": str(MAX_SITEMAP_BYTES - 1)},
        )

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler)
        ) as c:
            entries = await discover_sitemap_urls(
                "https://example.com", client=c, follow_index=False
            )
            assert len(entries) == 2

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Per-sitemap outcome report
# ---------------------------------------------------------------------------
# Self-contained fixtures: an origin-local robots.txt advertising an
# index, plus child sitemap documents served by the same MockTransport.
# Nothing here touches the network.
ORIGIN = "https://report.example"
ROBOTS_WITH_INDEX = (
    "User-agent: *\n"
    f"Sitemap: {ORIGIN}/index.xml\n"
)


def _pages(prefix: str, count: int) -> str:
    """Build a urlset with ``count`` deterministic page URLs."""
    body = "".join(
        f"<url><loc>{ORIGIN}/{prefix}{i}</loc></url>" for i in range(count)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</urlset>"
    )


def _index(*children: str) -> str:
    body = "".join(
        f"<sitemap><loc>{child}</loc></sitemap>" for child in children
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"{body}</sitemapindex>"
    )


def _report_handler(
    routes: dict[str, httpx.Response | Exception], requests: list[str]
):
    """Return a MockTransport handler over ``routes`` keyed by URL path.

    Records every path hit in ``requests`` so tests can assert exactly
    which child sitemaps were fetched (and how often).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        route = routes.get(request.url.path)
        if route is None:
            return httpx.Response(404)
        if isinstance(route, Exception):
            raise route
        return route

    return handler


async def _collect_report(routes, requests, **kwargs):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_report_handler(routes, requests))
    ) as c:
        return await discover_sitemap_urls_with_report(
            ORIGIN + "/", client=c, **kwargs
        )


def _run_report(routes, requests, **kwargs):
    return asyncio.run(_collect_report(routes, requests, **kwargs))


async def _legacy_entries(routes):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_report_handler(routes, []))
    ) as c:
        return await discover_sitemap_urls(ORIGIN + "/", client=c)


def _statuses(report) -> dict[str, str]:
    return {a.url: a.status for a in report.attempts}


def test_report_normal_expansion():
    """robots -> index -> two child urlset files, all parsed."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/sm2.xml")
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 2)),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 3)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    # Entry list is flat, in traversal order, and identical to the
    # legacy API's return value.
    assert [e.url for e in report.entries] == [
        f"{ORIGIN}/a0",
        f"{ORIGIN}/a1",
        f"{ORIGIN}/b0",
        f"{ORIGIN}/b1",
        f"{ORIGIN}/b2",
    ]
    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
        f"{ORIGIN}/sm2.xml": STATUS_OK,
    }
    # Budget accounting: 3 fetches, none skipped.
    assert report.attempted_count == 3
    assert report.not_attempted == []
    assert report.used_fallback is False
    assert report.robots.status == STATUS_OK
    assert report.robots.sitemap_count == 1
    # Index vs urlset bookkeeping.
    by_url = {a.url: a for a in report.attempts}
    assert by_url[f"{ORIGIN}/index.xml"].child_count == 2
    assert by_url[f"{ORIGIN}/index.xml"].entry_count == 0
    assert by_url[f"{ORIGIN}/sm1.xml"].entry_count == 2
    assert by_url[f"{ORIGIN}/sm2.xml"].entry_count == 3

    # The plain API returns exactly those entries in the same order.
    legacy = asyncio.run(_legacy_entries(routes))
    assert legacy == report.entries


def test_report_child_sitemap_404():
    """A missing child is recorded as http_error and skipped; no raise."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/missing.xml")
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 2)),
        "/missing.xml": httpx.Response(404, text="not found"),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [
        f"{ORIGIN}/a0",
        f"{ORIGIN}/a1",
    ]
    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
        f"{ORIGIN}/missing.xml": STATUS_HTTP_ERROR,
    }
    failed = report.failed
    assert [a.url for a in failed] == [f"{ORIGIN}/missing.xml"]
    assert failed[0].http_status == 404
    assert failed[0].entry_count == 0
    assert failed[0].detail == "HTTP 404"


def test_report_budget_truncation_marks_unattempted():
    """Exhausted budget surfaces the queued children as not_attempted."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200,
            text=_index(
                f"{ORIGIN}/sm1.xml",
                f"{ORIGIN}/sm2.xml",
                f"{ORIGIN}/sm3.xml",
            ),
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 1)),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 1)),
        "/sm3.xml": httpx.Response(200, text=_pages("c", 1)),
    }
    requests: list[str] = []
    # Budget of 2: index.xml + sm1.xml fetched, sm2/sm3 queued but untried.
    report = _run_report(routes, requests, max_sitemaps=2)

    assert [e.url for e in report.entries] == [f"{ORIGIN}/a0"]
    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
        f"{ORIGIN}/sm2.xml": STATUS_NOT_ATTEMPTED,
        f"{ORIGIN}/sm3.xml": STATUS_NOT_ATTEMPTED,
    }
    assert report.attempted_count == 2
    assert [a.url for a in report.not_attempted] == [
        f"{ORIGIN}/sm2.xml",
        f"{ORIGIN}/sm3.xml",
    ]
    for attempt in report.not_attempted:
        assert attempt.http_status is None
        assert attempt.detail is not None
        assert not attempt.attempted
    # sm2/sm3 were never requested.
    assert requests == ["/robots.txt", "/index.xml", "/sm1.xml"]


def test_report_duplicate_sitemap_urls_fetched_once():
    """Duplicate locs in robots.txt and the index cost one fetch/record."""
    routes = {
        "/robots.txt": httpx.Response(
            200,
            text=(
                "User-agent: *\n"
                f"Sitemap: {ORIGIN}/index.xml\n"
                f"Sitemap: {ORIGIN}/sm1.xml\n"  # duplicate of an index child
            ),
        ),
        "/index.xml": httpx.Response(
            200,
            text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/sm1.xml"),
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 2)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [
        f"{ORIGIN}/a0",
        f"{ORIGIN}/a1",
    ]
    attempt_urls = [a.url for a in report.attempts]
    assert attempt_urls == [f"{ORIGIN}/index.xml", f"{ORIGIN}/sm1.xml"]
    assert len(attempt_urls) == len(set(attempt_urls))
    assert report.attempted_count == 2
    # One request per unique sitemap, plus the robots.txt fetch.
    assert requests.count("/sm1.xml") == 1
    assert requests == ["/robots.txt", "/index.xml", "/sm1.xml"]


def test_report_duplicate_child_not_counted_against_budget():
    """Duplicates don't consume budget: 1 unique child fits in 2 fetches."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200,
            text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/sm1.xml"),
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 3)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests, max_sitemaps=2)

    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
    }
    assert report.not_attempted == []
    assert len(report.entries) == 3
    assert requests == ["/robots.txt", "/index.xml", "/sm1.xml"]


def test_report_transport_error_recorded_not_raised():
    """A raising child fetch becomes request_error; later children still run."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/boom.xml", f"{ORIGIN}/sm2.xml")
        ),
        "/boom.xml": httpx.ConnectError(
            "connection refused", request=httpx.Request("GET", ORIGIN)
        ),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 1)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [f"{ORIGIN}/b0"]
    assert _statuses(report)[f"{ORIGIN}/boom.xml"] == STATUS_REQUEST_ERROR
    assert [a.url for a in report.failed] == [f"{ORIGIN}/boom.xml"]


def test_report_oversize_child_recorded_as_too_large():
    from flarecrawl.sitemap import MAX_SITEMAP_BYTES

    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/huge.xml", f"{ORIGIN}/sm2.xml")
        ),
        "/huge.xml": httpx.Response(
            200,
            text=_pages("a", 1),
            headers={"content-length": str(MAX_SITEMAP_BYTES + 1)},
        ),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 1)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [f"{ORIGIN}/b0"]
    huge = {a.url: a for a in report.attempts}[f"{ORIGIN}/huge.xml"]
    assert huge.status == STATUS_TOO_LARGE
    assert huge.http_status is None
    assert huge.detail is not None and "content-length" in huge.detail


def test_report_robots_500_falls_back_without_raising():
    """robots.txt 5xx -> fallback to /sitemap.xml, still readable."""
    routes = {
        "/robots.txt": httpx.Response(500, text="boom"),
        "/sitemap.xml": httpx.Response(200, text=_pages("a", 1)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [f"{ORIGIN}/a0"]
    assert report.used_fallback is True
    assert report.robots.status == STATUS_HTTP_ERROR
    assert report.robots.http_status == 500
    assert _statuses(report) == {f"{ORIGIN}/sitemap.xml": STATUS_OK}
    assert report.attempted_count == 1


def test_report_robots_unreachable_falls_back_without_raising():
    """robots.txt transport failure -> fallback, recorded as request_error."""
    routes = {
        "/robots.txt": httpx.ConnectError(
            "connection refused", request=httpx.Request("GET", ORIGIN)
        ),
        "/sitemap.xml": httpx.Response(200, text=_pages("a", 2)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [
        f"{ORIGIN}/a0",
        f"{ORIGIN}/a1",
    ]
    assert report.used_fallback is True
    assert report.robots.status == STATUS_REQUEST_ERROR
    assert _statuses(report) == {f"{ORIGIN}/sitemap.xml": STATUS_OK}


def test_report_fallback_sitemap_itself_404_is_recorded():
    """No Sitemap: in robots and /sitemap.xml 404 -> attempt logged, no raise."""
    routes = {
        "/robots.txt": httpx.Response(200, text="User-agent: *\n"),
        "/sitemap.xml": httpx.Response(404),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert report.entries == []
    assert report.used_fallback is True
    assert _statuses(report) == {f"{ORIGIN}/sitemap.xml": STATUS_HTTP_ERROR}
    assert requests == ["/robots.txt", "/sitemap.xml"]


def test_report_nested_index_child_is_accounted_for():
    """An index whose child is itself an index: both get their own record."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/nested.xml")
        ),
        "/nested.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/sm2.xml")
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 1)),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 2)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests)

    assert [e.url for e in report.entries] == [
        f"{ORIGIN}/a0",
        f"{ORIGIN}/b0",
        f"{ORIGIN}/b1",
    ]
    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/nested.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
        f"{ORIGIN}/sm2.xml": STATUS_OK,
    }
    by_url = {a.url: a for a in report.attempts}
    assert by_url[f"{ORIGIN}/index.xml"].child_count == 1
    assert by_url[f"{ORIGIN}/nested.xml"].child_count == 2
    assert report.attempted_count == 4


def test_report_nested_index_truncation():
    """Budget stops inside the nested expansion; remaining children logged."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/nested.xml")
        ),
        "/nested.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/sm2.xml")
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 1)),
        "/sm2.xml": httpx.Response(200, text=_pages("b", 1)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests, max_sitemaps=3)

    assert _statuses(report) == {
        f"{ORIGIN}/index.xml": STATUS_OK,
        f"{ORIGIN}/nested.xml": STATUS_OK,
        f"{ORIGIN}/sm1.xml": STATUS_OK,
        f"{ORIGIN}/sm2.xml": STATUS_NOT_ATTEMPTED,
    }
    assert [a.url for a in report.not_attempted] == [f"{ORIGIN}/sm2.xml"]
    assert requests == ["/robots.txt", "/index.xml", "/nested.xml", "/sm1.xml"]


def test_report_zero_budget_marks_all_queued_as_unattempted():
    """max_sitemaps=0: nothing fetched, every seeded URL is not_attempted."""
    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(200, text=_pages("a", 1)),
    }
    requests: list[str] = []
    report = _run_report(routes, requests, max_sitemaps=0)

    assert report.entries == []
    assert _statuses(report) == {f"{ORIGIN}/index.xml": STATUS_NOT_ATTEMPTED}
    assert report.attempted_count == 0
    assert requests == ["/robots.txt"]


def test_report_as_dict_is_json_ready():
    import json

    routes = {
        "/robots.txt": httpx.Response(200, text=ROBOTS_WITH_INDEX),
        "/index.xml": httpx.Response(
            200, text=_index(f"{ORIGIN}/sm1.xml", f"{ORIGIN}/missing.xml")
        ),
        "/sm1.xml": httpx.Response(200, text=_pages("a", 1)),
        "/missing.xml": httpx.Response(404),
    }
    report = _run_report(routes, [])
    payload = report.as_dict()
    # Round-trips through JSON (no dataclass/enum objects leak out).
    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["attempted_count"] == 3
    assert [a["status"] for a in round_tripped["attempts"]] == [
        STATUS_OK,
        STATUS_OK,
        STATUS_HTTP_ERROR,
    ]
    assert [e["url"] for e in round_tripped["entries"]] == [
        f"{ORIGIN}/a0"
    ]
