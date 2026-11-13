import asyncio
import gzip
from collections.abc import Mapping
from typing import Any

import pytest

from telegram_me.cache import MemoryCache
from telegram_me.schemas.channel import SkippedChannel
from telegram_me.services.channels import ChannelService, encode
from telegram_me.services.feed import FeedRefresher, FeedService
from telegram_me.services.popularity import LocalLeaderLock, MemoryPopularity
from telegram_me.settings import Settings
from telegram_me.telegram.client import Fetcher, FetchResult, Method, TelegramClient
from telegram_me.telegram.errors import TelegramNotFoundError, TelegramUpstreamError
from tests.conftest import FIXTURES_DIR, make_settings


def _fixture(name: str) -> str:
    return gzip.decompress((FIXTURES_DIR / f"{name}.txt.gz").read_bytes()).decode()


class PageFetcher:
    """Serves one HTML page for every channel page and counts requests."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.paths: list[str] = []

    async def fetch(
        self,
        method: Method,
        path: str,
        *,
        query: Mapping[str, int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        self.paths.append(path)
        return FetchResult(200, self.html)

    async def close(self) -> None:
        return None


@pytest.fixture
def durov_html() -> str:
    return _fixture("body_durov")


def _service(fetcher: Fetcher, settings: Settings) -> ChannelService:
    client = TelegramClient(fetcher, max_concurrency=4)
    return ChannelService(client, MemoryCache(64 * 1024 * 1024), settings)


@pytest.fixture
async def feed_parts(
    durov_html: str,
) -> tuple[PageFetcher, ChannelService, FeedService, MemoryPopularity]:
    fetcher = PageFetcher(durov_html)
    settings = make_settings(feed_fresh_ttl=60, feed_stale_ttl=900, feed_diversity=0.0)
    channels = _service(fetcher, settings)
    popularity = MemoryPopularity()
    return fetcher, channels, FeedService(channels, popularity, settings), popularity


async def test_page_cache_and_coalescing(durov_html: str) -> None:
    fetcher = PageFetcher(durov_html)
    service = _service(fetcher, make_settings(cache_mode="normal"))
    first = await service.body("durov")
    second = await service.body("durov")
    assert first == second
    assert fetcher.paths == ["/s/durov"]


async def test_cache_mode_off_always_fetches(durov_html: str) -> None:
    fetcher = PageFetcher(durov_html)
    service = _service(fetcher, make_settings(cache_mode="off", enable_feed=False))
    await service.body("durov")
    await service.body("durov")
    assert fetcher.paths == ["/s/durov", "/s/durov"]


async def test_post_not_on_page_is_not_found(durov_html: str) -> None:
    service = _service(PageFetcher(durov_html), make_settings())
    with pytest.raises(TelegramNotFoundError):
        await service.post("durov", 9_999_999)


async def test_invalid_post_is_dropped_not_fatal(durov_html: str) -> None:
    fetcher = PageFetcher(durov_html)
    service = _service(fetcher, make_settings())
    page = await service.page("durov")
    broken = {**page["content"]["posts"][0], "footer": {"date": "not a date object"}}
    page = {**page, "content": {"posts": [broken, *page["content"]["posts"][1:]]}}
    # A service that has the broken page in its cache but no rendered body.
    other = _service(fetcher, make_settings())
    await other._cache.set(other.page_key("durov"), encode(page), 60)

    body = await other.body("durov")
    assert len(body.content.posts) == len(page["content"]["posts"]) - 1


class PreviewFetcher:
    """Serves scripted responses for preview landing pages and counts requests."""

    def __init__(self, script: Mapping[str, FetchResult]) -> None:
        self.script = script
        self.paths: list[str] = []

    async def fetch(
        self,
        method: Method,
        path: str,
        *,
        query: Mapping[str, int] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FetchResult:
        self.paths.append(path)
        return self.script[path]

    async def close(self) -> None:
        return None


def _preview_script(*channels: str, status: int = 200) -> dict[str, FetchResult]:
    html = _fixture("preview_durov")
    return {
        f"/{channel}": FetchResult(status, html if status == 200 else "") for channel in channels
    }


async def test_previews_all_succeed() -> None:
    fetcher = PreviewFetcher(_preview_script("durov", "telegram"))
    service = _service(fetcher, make_settings())
    result = await service.previews(["durov", "telegram"])
    assert list(result.previews) == ["durov", "telegram"]
    assert result.skipped == []


async def test_previews_skip_missing_channels() -> None:
    fetcher = PreviewFetcher(
        {
            "/durov": FetchResult(200, _fixture("preview_durov")),
            "/zzzzzznothing": FetchResult(200, _fixture("preview_missing")),
        }
    )
    service = _service(fetcher, make_settings())
    result = await service.previews(["durov", "zzzzzznothing", "durov"])
    assert list(result.previews) == ["durov"]
    assert result.skipped == [
        SkippedChannel(channel="zzzzzznothing", normalized="zzzzzznothing", reason="not_found")
    ]
    # The miss is cached briefly, so repeated lookups do not hit t.me again.
    with pytest.raises(TelegramNotFoundError):
        await service.preview("zzzzzznothing")
    assert fetcher.paths.count("/zzzzzznothing") == 1


async def test_previews_all_upstream_failures_raise() -> None:
    fetcher = PreviewFetcher(_preview_script("durov", "telegram", status=500))
    service = _service(fetcher, make_settings())
    with pytest.raises(TelegramUpstreamError):
        await service.previews(["durov", "telegram"])


async def test_previews_partial_upstream_failure_is_skipped() -> None:
    fetcher = PreviewFetcher(
        {"/durov": FetchResult(200, _fixture("preview_durov")), "/telegram": FetchResult(503, "")}
    )
    service = _service(fetcher, make_settings())
    result = await service.previews(["durov", "telegram"])
    assert list(result.previews) == ["durov"]
    assert result.skipped == [
        SkippedChannel(channel="telegram", normalized="telegram", reason="upstream_failed")
    ]


async def test_previews_missing_and_upstream_failure_does_not_raise() -> None:
    fetcher = PreviewFetcher(
        {
            "/zzzzzznothing": FetchResult(200, _fixture("preview_missing")),
            "/telegram": FetchResult(500, ""),
        }
    )
    service = _service(fetcher, make_settings())
    result = await service.previews(["zzzzzznothing", "telegram"])
    assert result.previews == {}
    # Skipped entries keep the first-appearance order and classify the reason.
    assert result.skipped == [
        SkippedChannel(channel="zzzzzznothing", normalized="zzzzzznothing", reason="not_found"),
        SkippedChannel(channel="telegram", normalized="telegram", reason="upstream_failed"),
    ]


async def test_previews_dedup_mixed_case_fetches_once() -> None:
    fetcher = PreviewFetcher(
        {
            "/durov": FetchResult(200, _fixture("preview_durov")),
            "/zzzzzznothing": FetchResult(200, _fixture("preview_missing")),
        }
    )
    service = _service(fetcher, make_settings())
    result = await service.previews(["Durov", "durov", "ZZZZZZNothing", "zzzzzznothing", "DUROV"])
    # Results and skipped entries point back to the first spelling of a channel.
    assert list(result.previews) == ["Durov"]
    assert result.skipped == [
        SkippedChannel(channel="ZZZZZZNothing", normalized="zzzzzznothing", reason="not_found")
    ]
    # Each channel is fetched from t.me once, under its normalized name.
    assert sorted(fetcher.paths) == ["/durov", "/zzzzzznothing"]


async def test_feed_fetches_missing_pages_in_parallel_and_tracks_popularity(
    feed_parts: tuple[PageFetcher, ChannelService, FeedService, MemoryPopularity],
) -> None:
    fetcher, _channels, feed, popularity = feed_parts
    posts = await feed.build(["durov", "durovtwo", "durov"])
    assert set(fetcher.paths) == {"/s/durov", "/s/durovtwo"}
    # Both pages contain the same posts of @durov; duplicates are removed.
    assert len(posts) == len({(p["channel"]["username"], p["id"]) for p in posts})
    assert posts == sorted(posts, key=lambda p: p["_score"], reverse=True)
    assert dict(await popularity.top(10)) == {"durov": 1.0, "durovtwo": 1.0}


async def test_feed_serves_stale_pages_and_refreshes_in_background(
    feed_parts: tuple[PageFetcher, ChannelService, FeedService, MemoryPopularity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher, channels, feed, _popularity = feed_parts
    await feed.build(["durov"])
    assert fetcher.paths == ["/s/durov"]

    entry = await channels.cached_page("durov")
    assert entry is not None
    monkeypatch.setattr(type(entry), "age", property(lambda _self: 120.0))

    refreshes: list[str] = []
    monkeypatch.setattr(channels, "refresh_page_in_background", refreshes.append)
    assert await feed.build(["durov"])
    assert fetcher.paths == ["/s/durov"]  # answered from the stale page
    assert refreshes == ["durov"]

    monkeypatch.setattr(type(entry), "age", property(lambda _self: 1000.0))
    await feed.build(["durov"])
    assert fetcher.paths == ["/s/durov", "/s/durov"]  # too old: fetched inline


def test_refresher_interval_follows_popularity() -> None:
    settings = make_settings(feed_refresh_min_interval=30, feed_refresh_max_interval=600)
    refresher = FeedRefresher(None, MemoryPopularity(), LocalLeaderLock(), settings)  # type: ignore[arg-type]
    assert refresher.interval(0) == 600
    assert refresher.interval(1) == 300
    assert refresher.interval(1000) == 30


async def test_refresher_refreshes_popular_channels_when_due(durov_html: str) -> None:
    fetcher = PageFetcher(durov_html)
    settings = make_settings()
    channels = _service(fetcher, settings)
    popularity = MemoryPopularity()
    await popularity.hit(["durov"])
    refresher = FeedRefresher(channels, popularity, LocalLeaderLock(), settings)

    assert await refresher.tick() == 1
    assert await refresher.tick() == 0  # not due again yet
    assert fetcher.paths == ["/s/durov"]
    assert await channels.cached_page("durov") is not None


async def test_refresher_bounds_concurrent_refreshes() -> None:
    class Channels:
        in_flight = peak = 0

        async def refresh_page(self, channel: str, fresh_for: float = 0) -> dict[str, Any]:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            await asyncio.sleep(0.001)
            self.in_flight -= 1
            return {}

    channels = Channels()
    popularity = MemoryPopularity()
    await popularity.hit([f"channel{i}" for i in range(30)])
    refresher = FeedRefresher(channels, popularity, LocalLeaderLock(), make_settings())  # type: ignore[arg-type]

    assert await refresher.tick() == 30
    assert channels.peak == FeedRefresher.concurrency


async def test_rendered_body_cache_is_identical_to_fresh_render(durov_html: str) -> None:
    fetcher = PageFetcher(durov_html)
    service = _service(fetcher, make_settings(cache_mode="normal"))
    first = await service.body_json("durov")
    cached = await service.body_json("durov")
    assert cached == first
    assert cached == (await service.body("durov")).model_dump_json().encode()
    assert fetcher.paths == ["/s/durov"]
