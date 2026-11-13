from __future__ import annotations

from pathlib import Path

import yaml

from .domain.source import Source, SourceType
from .domain.website import WebsiteConfig


def load_sources(path: str | Path = "config/sources.yaml") -> list[Source]:
    """The effective registry: the tracked base file plus the local runtime overlay.

    Every command (CLI and Telegram bot) reads sources through this function, so
    there is exactly one effective registry. See `source_registry` for precedence.
    """
    from .source_registry import SourceRegistry
    return SourceRegistry(path).sources()


def load_base_sources(path: str | Path = "config/sources.yaml") -> list[Source]:
    """Only the tracked YAML file, without the local overlay."""
    config_path = Path(path)
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        raise ValueError('source registry is not valid YAML') from None

    if not isinstance(payload, dict):
        raise ValueError('source registry must be a mapping')

    defaults = payload.get("defaults") or {}
    if not isinstance(defaults, dict):
        raise ValueError('source defaults must be a mapping')
    raw_sources = payload.get("sources")
    if not isinstance(raw_sources, list):
        raise ValueError("sources.yaml must contain a 'sources' list")

    sources: list[Source] = []
    seen_ids: set[str] = set()

    for raw in raw_sources:
        source = source_from_mapping(raw, defaults)
        if source.id in seen_ids:
            raise ValueError(f"duplicate source id: {source.id}")
        seen_ids.add(source.id)
        sources.append(source)

    return sources


def source_from_mapping(raw: object, defaults: dict | None = None) -> Source:
    defaults = defaults or {}
    if not isinstance(raw, dict) or not {'id', 'publisher_key', 'name', 'type', 'url'} <= raw.keys():
        raise ValueError('source record requires id, publisher_key, name, type, and url')
    return Source(
        id=raw["id"],
        publisher_key=raw["publisher_key"],
        name=raw["name"],
        source_type=SourceType(raw["type"]),
        url=raw["url"],
        enabled=raw.get("enabled", True),
        username=raw.get("username"),
        city_hint=raw.get("city_hint", defaults.get("city_hint")),
        timezone=raw.get("timezone", defaults.get("timezone", "Asia/Tehran")),
        locale=raw.get("locale", defaults.get("locale", "fa-IR")),
        website=WebsiteConfig.from_mapping(raw['website']) if 'website' in raw else None,
        disabled_reason=raw.get('disabled_reason'),
        archived=raw.get('archived', False),
    )
