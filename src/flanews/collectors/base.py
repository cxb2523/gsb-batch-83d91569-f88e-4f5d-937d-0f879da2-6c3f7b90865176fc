from datetime import datetime
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel

from flanews.config import Settings, get_settings
from flanews.models import Article

USER_AGENT = "flanews/0.1 (+contato@flanews.local)"
DEFAULT_TIMEOUT = 15.0

SourceStatusValue = Literal["success", "empty", "failed"]


class CollectorError(RuntimeError):
    """A collector could not fetch or parse its source.

    Raised instead of silently returning an empty list, so the pipeline can
    distinguish a failing source from a window with genuinely no articles.
    """


class SourceStatus(BaseModel):
    """Outcome of running one registered collector for an edition window."""

    name: str
    status: SourceStatusValue
    articles: int = 0
    reason: str | None = None


def describe_error(error: Exception) -> str:
    """Short, single-line description of a fetch/parse failure for reports.

    CollectorError wraps the original network/parse problem, so the message
    leads with the concrete cause rather than the wrapper type.
    """
    cause = error.__cause__ or error
    text = str(cause).strip()
    detail = text.splitlines()[0] if text else cause.__class__.__name__
    return f"{cause.__class__.__name__}: {detail}"[:200]


def create_http_client() -> httpx.Client:
    """Create a configured HTTP client for collectors."""
    return httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    )


class Collector(Protocol):
    """Protocol defining news collector interface."""

    name: str

    def collect(self, start: datetime, end: datetime) -> list[Article]:
        """Collect articles within the given time window.

        Raises CollectorError when the request or the response parsing fails;
        an empty list means the source responded but had nothing in the window.
        """
        ...


def get_collectors(settings: Settings | None = None) -> list[Collector]:
    """Return all registered collectors."""
    if settings is None:
        settings = get_settings()

    from flanews.collectors.flamengo_oficial import FlamengoOficialCollector
    from flanews.collectors.ge import GECollector
    from flanews.collectors.google_news import GoogleNewsCollector

    return [
        GoogleNewsCollector(),
        GECollector(),
        FlamengoOficialCollector(),
    ]
