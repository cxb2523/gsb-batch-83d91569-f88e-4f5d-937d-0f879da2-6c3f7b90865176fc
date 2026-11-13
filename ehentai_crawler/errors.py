"""Exceptions shared by the crawler.

Every error a user can hit derives from :class:`CrawlerError`, so the CLI can
print one clear line instead of a traceback.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .crawl import GalleryCrawlResult


class CrawlerError(Exception):
    """Base class for errors the CLI reports as a single message."""


class SettingsError(CrawlerError):
    """A setting is missing, malformed or contradicts another one."""


class LayoutError(CrawlerError):
    """A page no longer has the structure the parser relies on."""


class FetchError(CrawlerError):
    """A request kept failing after all retries."""


class TransientError(CrawlerError):
    """A failure worth retrying (timeouts, 5xx, the site's 503 page)."""


class AccessDeniedError(CrawlerError):
    """The site answered with an empty or non-HTML page (bad or missing cookies)."""


class BannedError(CrawlerError):
    """The site banned this IP for too many page loads."""

    def __init__(self, message: str, expires_in: float | None = None) -> None:
        super().__init__(message)
        #: Seconds until the ban ends, if the page said so.
        self.expires_in = expires_in
        #: Filled in by ``crawl_galleries`` when a ban aborts a run: what had
        #: been recorded up to the abort, including the control-stopped ids.
        self.partial_result: GalleryCrawlResult | None = None


class GalleryUnavailableError(CrawlerError):
    """The gallery was removed or does not exist."""


class QuotaExceededError(CrawlerError):
    """The image quota is used up; the site serves its 509 placeholder instead."""
