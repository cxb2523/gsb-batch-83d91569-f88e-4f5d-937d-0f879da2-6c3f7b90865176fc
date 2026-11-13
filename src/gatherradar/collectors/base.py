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


def failure_category(exc: Exception) -> str:
    """Map any exception onto the fixed failure vocabulary; never its message.

    The returned words are the only safe values allowed in per-page outcomes:
    timeout, network, redirect, content_type, layout or collection_failure.
    Transport-level categories outside that set collapse to collection_failure.
    """
    categories = {'dns', 'timeout', 'network', 'tls', 'robots', 'http_status', 'redirect',
                  'encoding', 'content_type', 'layout', 'collection_failure'}
    category = getattr(exc, 'category', 'collection_failure')
    if category not in categories:
        category = 'collection_failure'
    return {
        'dns': 'network',
        'tls': 'network',
        'robots': 'collection_failure',
        'http_status': 'collection_failure',
        'encoding': 'content_type',
    }.get(category, category)


def safe_failure(exc: Exception) -> str:
    """Fixed vocabulary only; never serialize exception messages or payloads."""
    category = getattr(exc, 'category', 'collection_failure')
    categories = {'dns', 'timeout', 'network', 'tls', 'robots', 'http_status', 'redirect',
                  'encoding', 'content_type', 'layout', 'collection_failure'}
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


# Per-page outcome vocabulary. Statuses are fixed words; failure categories come
# from failure_category() only. Nothing here carries exception text, query
# parameters from a failed request, or page content.
PAGE_SUCCESS = 'success'
PAGE_FAILED = 'failed'
PAGE_NOT_ATTEMPTED = 'not_attempted'
PAGE_STATUSES = frozenset({PAGE_SUCCESS, PAGE_FAILED, PAGE_NOT_ATTEMPTED})
PAGE_FAILURE_CATEGORIES = frozenset(
    {'timeout', 'network', 'redirect', 'content_type', 'layout', 'collection_failure'})


@dataclass(frozen=True, slots=True)
class PageOutcome:
    """The ending of one attempted (or skipped) detail link in a single run.

    `candidate_index` is the 1-based position in the bounded candidate list.
    `final_url` is the verified end URL when it could be determined, else None.
    Failed and not-attempted records never embed exception messages or content;
    `failure_category` holds a fixed vocabulary word and is None on success or
    when the page was never tried after an access-restricted stop.
    """

    candidate_index: int
    candidate_url: str
    status: str
    final_url: str | None = None
    failure_category: str | None = None

    def __post_init__(self) -> None:
        if self.status not in PAGE_STATUSES:
            raise ValueError('unknown page outcome status')
        if self.status == PAGE_FAILED:
            if self.failure_category not in PAGE_FAILURE_CATEGORIES:
                raise ValueError('failed page outcome requires a fixed failure category')
        elif self.failure_category is not None:
            raise ValueError('only failed page outcomes carry a failure category')


@dataclass(frozen=True, slots=True)
class CollectionResult:
    source_id: str
    items: tuple[RawItem, ...] = ()
    failures: tuple[ItemFailure, ...] = ()
    warnings: tuple[str, ...] = ()
    # Additive per-page manifest of the website detail phase; other collectors
    # leave it empty. One record per candidate in the bounded list, in order.
    page_outcomes: tuple[PageOutcome, ...] = ()

    @property
    def observed(self) -> int:
        return len(self.items) + len(self.failures)

    @property
    def not_attempted_count(self) -> int:
        """Candidates never fetched because an access refusal stopped the source."""
        return sum(1 for outcome in self.page_outcomes if outcome.status == PAGE_NOT_ATTEMPTED)

    @property
    def interrupted(self) -> bool:
        """Whether an access-restricted response halted the remaining candidates."""
        return any(outcome.status == PAGE_NOT_ATTEMPTED for outcome in self.page_outcomes)


class Collector(Protocol):
    """Fetches a bounded number of recent items and returns domain records."""

    def collect(self, source: Source, *, limit: int) -> CollectionResult: ...
