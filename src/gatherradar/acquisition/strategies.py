"""Acquisition strategies: how one channel of a publisher is collected.

Every strategy delegates to an existing collector boundary, so all network access
keeps that boundary's policy: the fixed GatherRadar user agent, robots checks,
no proxies (`ProxyHandler({})`), no cookies for websites, and the owner's
visible, unmodified Chrome profile for Instagram. Strategies take no transport,
header, proxy or browser options, so a fallback cannot change them.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from ..collectors.website import WebsiteCollector
from ..collectors.websites.adapters import build_adapter
from ..domain import RawItem, Source, SourceType
from ..extraction.signals import URL_PATTERN, _URL_TRAILING
from ..orchestration.collection_run import run_instagram_collection
from ..orchestration.website_run import run_website_collection, website_output_path
from ..storage import JsonlRawItemStore
from .models import ChannelResult, ChannelStatus, disabled_status, failure_result

# Facts each channel states in dedicated structure (sections, labels, slots)
# rather than only in free prose. When a channel is unavailable, these are the
# fields whose absence may be caused by the channel rather than by the source.
CHANNEL_STRUCTURED_FIELDS: dict[str, frozenset[str]] = {
    'website': frozenset({'description_text', 'address', 'area_text', 'duration_text', 'organizer_name',
                          'availability_text', 'registration_url', 'source_category_text'}),
    'instagram': frozenset(),
}


class AcquisitionStrategy(Protocol):
    """Acquires one channel. Never raises for source failures: it reports them."""

    name: str
    channel: str

    def supports(self, source: Source) -> bool: ...

    def acquire(self, source: Source, *, config_path: str | Path, data_dir: str | Path,
                limit: int) -> ChannelResult: ...


class _CollectorStrategy:
    name = ''
    channel = ''
    source_type: SourceType

    def __init__(self, collect: Callable) -> None:
        self._collect = collect

    def supports(self, source: Source) -> bool:
        return source.source_type is self.source_type

    def acquire(self, source: Source, *, config_path: str | Path, data_dir: str | Path,
                limit: int) -> ChannelResult:
        if not source.enabled:
            # Configured off (for example robots): reported, never contacted.
            return ChannelResult(source.id, source.publisher_key, self.channel, self.name,
                                 disabled_status(source.disabled_reason), diagnostic=source.disabled_reason)
        try:
            summary = self._collect(source.id, config_path=config_path, data_dir=data_dir, limit=limit)
        except Exception as exc:
            return failure_result(source.id, source.publisher_key, self.channel, self.name, exc)
        items = tuple(summary.observed_items)
        if (len(items) > limit or len({i.id for i in items}) != len(items)
                or any(i.source_id != source.id or i.source_type != source.source_type for i in items)):
            return ChannelResult(source.id, source.publisher_key, self.channel, self.name,
                                 ChannelStatus.PARSE_FAILURE, diagnostic='invalid_collection_membership')
        return ChannelResult(source.id, source.publisher_key, self.channel, self.name,
                             ChannelStatus.SUCCESS if items else ChannelStatus.EMPTY, len(items),
                             'collection_item_failed' if summary.failed else (
                                 'publication_recency_unverified' if getattr(summary, 'warnings', ()) else None), items,
                             summary.new, summary.changed, summary.already_existing)


class WebsiteListingStrategy(_CollectorStrategy):
    name, channel, source_type = 'website_listing', 'website', SourceType.WEBSITE

    def __init__(self, collect: Callable = run_website_collection) -> None:
        super().__init__(collect)


class InstagramProfileStrategy(_CollectorStrategy):
    name, channel, source_type = 'instagram_profile', 'instagram', SourceType.INSTAGRAM

    def __init__(self, collect: Callable = run_instagram_collection) -> None:
        super().__init__(collect)


def default_strategies(website_collect: Callable = run_website_collection,
                       instagram_collect: Callable = run_instagram_collection) -> tuple[AcquisitionStrategy, ...]:
    return (WebsiteListingStrategy(website_collect), InstagramProfileStrategy(instagram_collect))


def strategy_for(source: Source, strategies: Iterable[AcquisitionStrategy]) -> AcquisitionStrategy | None:
    return next((s for s in strategies if s.supports(source)), None)


def referenced_urls(item: RawItem) -> tuple[str, ...]:
    """Public URLs written verbatim in an observation's own text, in order."""
    urls: list[str] = []
    for match in URL_PATTERN.finditer(item.raw_text or ''):
        url = match.group().rstrip(_URL_TRAILING)
        if url not in urls:
            urls.append(url)
    return tuple(urls)


def _origin(url: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(url)
        return (parts.scheme.lower(), (parts.hostname or '').lower(), parts.port)
    except ValueError:
        return None


class LinkedPageStrategy:
    """At most one approved linked detail page per observation, depth one.

    A URL qualifies only when its origin is a configured website channel's origin
    and that channel's adapter accepts it as a detail page. The page is collected
    through that channel's normal Website boundary; a disabled/policy-blocked
    target is reported and never contacted. No arbitrary origins, no link following.
    """

    name, channel = 'linked_page', 'website'

    def __init__(self, collector_factory: Callable[[], WebsiteCollector] = WebsiteCollector) -> None:
        self._collector_factory = collector_factory

    def plan(self, observations: Iterable[RawItem], targets: Iterable[Source],
             limit: int) -> dict[str, dict[str, tuple[str, ...]]]:
        """{target source id: {url: referring observation ids}}, bounded by `limit`."""
        candidates = [t for t in targets if t.source_type is SourceType.WEBSITE and t.website is not None]
        plan: dict[str, dict[str, list[str]]] = {}
        for item in observations:
            if item.source_type is SourceType.WEBSITE:
                continue  # website pages never seed further website fetches
            for url in referenced_urls(item):
                origin = _origin(url)
                target = next((t for t in candidates if origin and _origin(t.url) == origin
                               and build_adapter(t.website).accepts(url, t.url)), None)
                if target is None:
                    continue
                urls = plan.setdefault(target.id, {})
                if url in urls:
                    urls[url].append(item.id)
                elif len(urls) < limit:
                    urls[url] = [item.id]
                break  # one approved linked page per observation
        return {target: {url: tuple(ids) for url, ids in urls.items()} for target, urls in plan.items()}

    def acquire(self, target: Source, urls: dict[str, tuple[str, ...]], *, data_dir: str | Path,
                limit: int) -> ChannelResult:
        if not target.enabled:
            return ChannelResult(target.id, target.publisher_key, self.channel, self.name,
                                 disabled_status(target.disabled_reason), diagnostic=target.disabled_reason)
        try:
            result = self._collector_factory().collect_linked(target, tuple(urls), limit=limit, linked_from=urls)
            stored = JsonlRawItemStore(website_output_path(target, data_dir)).append_new(result.items)
        except Exception as exc:
            return failure_result(target.id, target.publisher_key, self.channel, self.name, exc)
        status = ChannelStatus.SUCCESS if result.items else ChannelStatus.EMPTY
        return ChannelResult(target.id, target.publisher_key, self.channel, self.name, status,
                             len(result.items), 'linked_item_failed' if result.failures else None, result.items,
                             stored.new, stored.changed, stored.already_existing)
