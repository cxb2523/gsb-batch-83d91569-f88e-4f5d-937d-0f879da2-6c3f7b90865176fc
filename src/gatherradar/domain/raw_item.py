from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .source import SourceType


def _require_aware(value: datetime | None, field_name: str) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RawItem:
    id: str
    source_id: str
    source_type: SourceType
    external_id: str
    content_type: str
    content_url: str
    raw_text: str
    captured_at: datetime
    published_at: datetime | None = None
    author: str | None = None
    image_url: str | None = None
    content_hash: str = ""
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("id", "source_id", "external_id", "content_type", "content_url"):
            if not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")
        _require_aware(self.captured_at, "captured_at")
        _require_aware(self.published_at, "published_at")


def compute_content_hash(
    *,
    raw_text: str,
    published_at: datetime | None,
    content_url: str,
) -> str:
    """Deterministic fingerprint of the source-supported fields that matter to event
    interpretation, so a collector can tell an edited observation from an unchanged one.

    Deliberately excludes `captured_at`, which changes on every run and would make
    every observation look "changed" even when nothing did. Also deliberately
    excludes `content_type`: it is GatherRadar's own classification of the source
    content (e.g. "video" vs. "reel"), not a property of the content itself, so a
    later fix to that classification must not by itself mark unchanged source
    content as edited.
    """
    published = published_at.astimezone(timezone.utc).isoformat() if published_at else ""
    payload = "\x1f".join([raw_text, published, content_url])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
