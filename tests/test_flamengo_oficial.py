from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from flanews.collectors.base import CollectorError, get_collectors
from flanews.collectors.flamengo_oficial import (
    FLAMENGO_OFICIAL_URL,
    FlamengoOficialCollector,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "flamengo_oficial.html"


@pytest.fixture
def oficial_html_fixture() -> str:
    return FIXTURE_PATH.read_text(encoding="utf-8")


def test_flamengo_oficial_parse_html(oficial_html_fixture: str) -> None:
    collector = FlamengoOficialCollector()
    tz = ZoneInfo("America/Sao_Paulo")

    start = datetime(2026, 10, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 23, 59, 59, tzinfo=tz)

    articles = collector.parse_html(oficial_html_fixture, start, end)

    assert len(articles) >= 5
    for article in articles:
        assert article.source == "flamengo_oficial"
        assert article.title
        assert article.url.startswith("https://www.flamengo.com.br/")
        assert article.published_at.tzinfo is not None


@respx.mock
def test_flamengo_oficial_network_success(oficial_html_fixture: str) -> None:
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=oficial_html_fixture)
    )

    collector = FlamengoOficialCollector()
    tz = ZoneInfo("America/Sao_Paulo")

    start = datetime(2026, 10, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 23, 59, 59, tzinfo=tz)

    articles = collector.collect(start, end)
    assert len(articles) >= 5


@respx.mock
def test_flamengo_oficial_network_error_raises() -> None:
    respx.get(FLAMENGO_OFICIAL_URL).mock(return_value=httpx.Response(500))

    collector = FlamengoOficialCollector()
    tz = ZoneInfo("America/Sao_Paulo")
    start = datetime(2026, 10, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(2026, 10, 15, 0, 0, 0, tzinfo=tz)

    with pytest.raises(CollectorError, match="request failed"):
        collector.collect(start, end)


@respx.mock
def test_flamengo_oficial_empty_window_returns_list_without_error(
    oficial_html_fixture: str,
) -> None:
    respx.get(FLAMENGO_OFICIAL_URL).mock(
        return_value=httpx.Response(200, text=oficial_html_fixture)
    )

    collector = FlamengoOficialCollector()
    tz = ZoneInfo("America/Sao_Paulo")
    # Fixture articles are dated 2026; a 2025 window means "responded, nothing in window".
    start = datetime(2025, 10, 1, 0, 0, 0, tzinfo=tz)
    end = datetime(2025, 10, 15, 0, 0, 0, tzinfo=tz)

    assert collector.collect(start, end) == []


def test_flamengo_oficial_registry() -> None:
    collectors = get_collectors()
    assert any(c.name == "flamengo_oficial" for c in collectors)
