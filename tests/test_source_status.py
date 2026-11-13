"""Per-source status records: success, HTTP failure and empty window.

The three registered collectors (Google News RSS, ge.globo and the official
Flamengo site) must each produce a SourceStatus record, and one source failing
must never prevent the other sources' articles from reaching the result.
"""

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flanews import pipeline
from flanews.collectors.base import SourceStatus
from flanews.collectors.flamengo_oficial import FLAMENGO_OFICIAL_URL
from flanews.collectors.ge import GE_FLAMENGO_URL
from flanews.collectors.google_news import GOOGLE_NEWS_RSS_URL, GoogleNewsCollector
from flanews.models import Edition

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("America/Sao_Paulo")

# The fixtures carry items dated October 2026, so this window contains them.
EDITION = Edition(
    kind="news",
    start=datetime(2026, 10, 9, 0, 0, tzinfo=TZ),
    end=datetime(2026, 10, 15, 23, 59, tzinfo=TZ),
    label="Notícias — 15/10/2026",
)
# A window years away from every fixture date: the sources respond 200 but have
# no in-window items, which must be reported as "empty", not "failed".
EMPTY_EDITION = Edition(
    kind="news",
    start=datetime(2025, 1, 1, 0, 0, tzinfo=TZ),
    end=datetime(2025, 1, 31, 23, 59, tzinfo=TZ),
    label="Notícias — 31/01/2025",
)


@pytest.fixture
def skip_extraction(monkeypatch: pytest.MonkeyPatch):
    """Keep these tests focused on collection: extraction is covered elsewhere."""

    def passthrough(articles, client, limiter=None):
        return articles

    monkeypatch.setattr(pipeline, "extract_articles", passthrough)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def by_name(statuses: list[SourceStatus]) -> dict[str, SourceStatus]:
    return {status.name: status for status in statuses}


@respx.mock
def test_all_sources_succeed(skip_extraction) -> None:
    respx.get(GOOGLE_NEWS_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("google_news.xml"))
    )
    respx.get(GE_FLAMENGO_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_flamengo.html"))
    )
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=fixture("flamengo_oficial.html"))
    )

    articles, statuses = pipeline.collect_with_sources(EDITION)

    assert [status.name for status in statuses] == [
        "google_news",
        "ge",
        "flamengo_oficial",
    ]
    records = by_name(statuses)
    for name in records:
        assert records[name].status == "success"
        assert records[name].articles > 0
        assert records[name].reason is None

    # Articles from every source survive into the final, still-deduped result.
    source_kinds = {article.source.split(":", 1)[0] for article in articles}
    assert {"google_news", "ge", "flamengo_oficial"} <= source_kinds
    assert len(articles) == len({article.url for article in articles})
    # Newest first ordering is preserved.
    assert articles == sorted(articles, key=lambda a: a.published_at, reverse=True)


@respx.mock
def test_failing_source_is_reported_and_others_keep_collecting(skip_extraction) -> None:
    respx.get(GOOGLE_NEWS_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("google_news.xml"))
    )
    respx.get(GE_FLAMENGO_URL).mock(return_value=httpx.Response(500))
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=fixture("flamengo_oficial.html"))
    )

    articles, statuses = pipeline.collect_with_sources(EDITION)

    records = by_name(statuses)
    assert records["ge"].status == "failed"
    assert records["ge"].articles == 0
    assert records["ge"].reason and "500" in records["ge"].reason
    assert records["google_news"].status == "success"
    assert records["google_news"].articles > 0
    assert records["flamengo_oficial"].status == "success"
    assert records["flamengo_oficial"].articles > 0

    # The failed source contributes nothing while the other sources still flow through.
    source_kinds = {article.source.split(":", 1)[0] for article in articles}
    assert "ge" not in source_kinds
    assert {"google_news", "flamengo_oficial"} <= source_kinds
    assert articles == sorted(articles, key=lambda a: a.published_at, reverse=True)


@respx.mock
def test_source_with_200_but_no_in_window_items_is_empty_not_failed(skip_extraction) -> None:
    # Google News answers normally but none of its fixture items fit the 2025 window.
    respx.get(GOOGLE_NEWS_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("google_news.xml"))
    )
    respx.get(GE_FLAMENGO_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_flamengo.html"))
    )
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=fixture("flamengo_oficial.html"))
    )

    articles, statuses = pipeline.collect_with_sources(EMPTY_EDITION)

    records = by_name(statuses)
    assert records["google_news"].status == "empty"
    assert records["google_news"].articles == 0
    assert records["google_news"].reason is None
    # Every source answered fine; the whole run simply has nothing in this window.
    assert all(status.status == "empty" for status in statuses)
    assert articles == []


@respx.mock
def test_network_error_is_reported_as_failure(skip_extraction) -> None:
    respx.get(GOOGLE_NEWS_RSS_URL).mock(side_effect=httpx.ConnectError("dns failure"))
    respx.get(GE_FLAMENGO_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_flamengo.html"))
    )
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=fixture("flamengo_oficial.html"))
    )

    _, statuses = pipeline.collect_with_sources(EDITION)

    google = by_name(statuses)["google_news"]
    assert google.status == "failed"
    assert google.articles == 0
    assert google.reason and "ConnectError" in google.reason
    assert "dns failure" in google.reason


@respx.mock
def test_parse_failure_is_reported_as_failure(
    skip_extraction, monkeypatch: pytest.MonkeyPatch
) -> None:
    respx.get(GOOGLE_NEWS_RSS_URL).mock(
        return_value=httpx.Response(200, text=fixture("google_news.xml"))
    )
    respx.get(GE_FLAMENGO_URL).mock(
        return_value=httpx.Response(200, text=fixture("ge_flamengo.html"))
    )
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=fixture("flamengo_oficial.html"))
    )

    def broken_parse(self, feed, start, end):
        raise ValueError("malformed feed entry")

    monkeypatch.setattr(GoogleNewsCollector, "_parse_feed", broken_parse)

    _, statuses = pipeline.collect_with_sources(EDITION)

    google = by_name(statuses)["google_news"]
    assert google.status == "failed"
    assert google.reason and "ValueError" in google.reason
    assert "malformed feed entry" in google.reason
    # The other two sources were still attempted.
    assert by_name(statuses)["ge"].status == "success"
    assert by_name(statuses)["flamengo_oficial"].status == "success"
