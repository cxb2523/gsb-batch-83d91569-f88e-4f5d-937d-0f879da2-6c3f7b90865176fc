"""Protocols and lightweight model types."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any, Protocol


class FetchStatus(enum.Enum):
    """Per-URL fetch outcome categories written to the fetch report."""

    SUCCESS = "success"
    ROBOTS_BLOCKED = "robots_blocked"
    FETCH_FAILED = "fetch_failed"
    UNSUPPORTED_URL = "unsupported_url"


@dataclass(frozen=True)
class FetchOutcome:
    """The fetch ending of a single candidate URL."""

    url: str
    status: FetchStatus
    detail: str = ""
    content: str = ""


class SearchBackend(Protocol):
    """Contract for search providers."""

    def search(self, query: str, num: int, min_delay: float, max_delay: float) -> list[str]:
        """Return candidate URLs for a query."""


class Fetcher(Protocol):
    """Contract for HTML fetchers."""

    def fetch(self, url: str) -> str:
        """Return HTML content for a URL or an empty string."""


class DetailedFetcher(Fetcher, Protocol):
    """Fetcher contract that also explains why a fetch did not yield content."""

    def fetch_detailed(self, url: str) -> FetchOutcome:
        """Return a structured outcome, distinguishing blocks, failures, and empties."""


class Closable(Protocol):
    """Optional close contract for resources."""

    def close(self) -> None:
        """Release associated resources."""


class HunterClientProtocol(Protocol):
    """Contract for Hunter API integration."""

    def domain_search(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return discovered emails for a domain."""

    def verify_email(self, email: str, poll: bool = True, timeout: int = 20) -> dict[str, Any]:
        """Verify one email address."""


@dataclass(frozen=True)
class EmailObservation:
    """An observed email with source metadata."""

    email: str
    source: str
    note: str
