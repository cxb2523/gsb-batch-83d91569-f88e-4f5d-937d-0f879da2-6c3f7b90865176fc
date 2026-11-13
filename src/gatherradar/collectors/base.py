from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..domain import RawItem, Source


class CollectorError(Exception):
    """Base class for collection failures that can be reported to a human."""

    def __init__(self, message: str, *, category: str = 'collection_failure', operation: str = 'collect',
                 http_status: int | None = None) -> None:
        super().__init__(message)
        self.category, self.operation, self.http_status = category, operation, http_status


def safe_failure(exc: Exception) -> str:
    """Fixed vocabulary only; never serialize exception messages or payloads."""
    categories = {'dns', 'timeout', 'network', 'tls', 'robots', 'http_status', 'redirect',
                  'encoding', 'content_type', 'layout', 'collection_failure'}
    category = getattr(exc, 'category', 'collection_failure')
    if category not in categories:
        category = 'collection_failure'
    operation = getattr(exc, 'operation', 'collect')
    if operation not in {'collect', 'request', 'robots', 'listing', 'detail'}:
        operation = 'collect'
    status = getattr(exc, 'http_status', None)
    suffix = f':http_{status}' if type(status) is int and 100 <= status <= 599 else ''
    return f'{operation}:{category}{suffix}'


class SourceNotFoundError(CollectorError):
    """The requested source id is not present in the registry."""


class SourceDisabledError(CollectorError):
    """The source exists but is disabled in the registry."""


class SourceTypeMismatchError(CollectorError):
    """The source was handed to a collector that does not serve its type."""


class SourceConfigurationError(CollectorError):
    """The source is missing configuration the collector needs."""


class SourceUnavailableError(CollectorError):
    """The source could not be reached or does not exist upstream."""


class SourceAccessRestrictedError(SourceUnavailableError):
    """The platform refused access, required a login, or rate-limited the run."""


class AuthenticationRequiredError(SourceAccessRestrictedError):
    """Authenticated access is required but no valid local session is available.

    Raised instead of attempting an anonymous request, since anonymous Instagram
    access is known to be blocked (see PROJECT_CONTEXT.md open decisions).
    """


@dataclass(frozen=True, slots=True)
class ItemFailure:
    """One source item that could not be mapped onto the RawItem contract."""

    reason: str
    external_id: str | None = None


@dataclass(frozen=True, slots=True)
class CollectionResult:
    source_id: str
    items: tuple[RawItem, ...] = ()
    failures: tuple[ItemFailure, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def observed(self) -> int:
        return len(self.items) + len(self.failures)


class Collector(Protocol):
    """Fetches a bounded number of recent items and returns domain records."""

    def collect(self, source: Source, *, limit: int) -> CollectionResult: ...
