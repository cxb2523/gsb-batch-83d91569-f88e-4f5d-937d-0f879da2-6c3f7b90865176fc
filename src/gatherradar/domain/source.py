from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from .website import WebsiteConfig


# Why an automatic channel is switched off. `robots`/`terms`: the publisher's
# access policy excludes GatherRadar; `owner`: the owner paused it;
# `unsupported`: an owner-registered website no existing adapter supports yet.
DISABLED_REASONS = frozenset({"robots", "terms", "owner", "unsupported"})
# Reasons the owner cannot clear from a UI: only a changed policy or a new
# adapter (a reviewed code/config change) can make such a source runnable.
LOCKED_REASONS = frozenset({"robots", "terms", "unsupported"})


class SourceType(StrEnum):
    INSTAGRAM = "instagram"
    WEBSITE = "website"


@dataclass(frozen=True, slots=True)
class Source:
    id: str
    publisher_key: str
    name: str
    source_type: SourceType
    url: str
    enabled: bool = True
    username: str | None = None
    city_hint: str | None = None
    timezone: str = "Asia/Tehran"
    locale: str = "fa-IR"
    website: WebsiteConfig | None = None
    disabled_reason: str | None = None
    # Archived ("removed from the list"): reversible, never crawled, history kept.
    archived: bool = False

    def __post_init__(self) -> None:
        for field_name in ("id", "publisher_key", "name", "url"):
            if not isinstance(getattr(self, field_name), str) or not getattr(self, field_name).strip():
                raise ValueError(f"{field_name} must not be empty")

        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        if parsed.username or parsed.password or not parsed.hostname or any(c.isspace() for c in self.url):
            raise ValueError('url must not contain credentials or whitespace')
        try:
            parsed.port
        except ValueError:
            raise ValueError('invalid URL port') from None
        if not re.fullmatch(r'[A-Za-z0-9_-]+', self.id):
            raise ValueError('source id must be safe for a storage filename')
        if not isinstance(self.enabled, bool):
            raise ValueError('enabled must be a boolean')
        if self.disabled_reason is not None and (self.enabled or self.disabled_reason not in DISABLED_REASONS):
            raise ValueError('disabled_reason requires a disabled source and one of robots, terms, owner, unsupported')
        if not isinstance(self.archived, bool) or (self.archived and self.enabled):
            raise ValueError('an archived source must be disabled')
        if self.website is not None and (
            self.source_type is not SourceType.WEBSITE or not isinstance(self.website, WebsiteConfig)
        ):
            raise ValueError('website configuration requires a website Source')

        if self.source_type is SourceType.INSTAGRAM and not self.username:
            raise ValueError("Instagram sources require a username")
