"""API response schemas."""
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Health check response data."""

    status: str


class Metadata(BaseModel):
    """API metadata response data."""

    name: str
    version: str
    docs: str
    redoc: str
    health: str
    repositories: str
    developers: str
    cacheTtlSeconds: int
    supportedDateRanges: list[str]
    supportedProgrammingLanguagesCount: int
    supportedSpokenLanguagesCount: int


class DataOrigin(str, Enum):
    """Where the trending data of a response came from."""

    upstream = "upstream"
    cache = "cache"


class UpstreamFailureReason(str, Enum):
    """Category of an upstream GitHub Trending request failure."""

    timeout = "timeout"
    connection_error = "connection_error"


class TrendingSource(BaseModel):
    """Verifiable provenance metadata of a trending response."""

    origin: DataOrigin
    cacheAgeSeconds: int
    cacheTtlSeconds: int


class UpstreamFailure(BaseModel):
    """Structured error body for upstream fetch failures (HTTP 502)."""

    detail: str
    retryable: bool
    failureReason: UpstreamFailureReason


class Contributor(BaseModel):
    """Repository contributor data."""

    username: str
    url: str
    avatar: str


class Repository(BaseModel):
    """Trending repository response data."""

    rank: int
    username: str
    repositoryName: str
    url: str
    description: str | None
    language: str | None
    languageColor: str | None
    totalStars: int | None
    forks: int | None
    starsSince: int | None
    since: str
    builtBy: list[Contributor]


class PopularRepository(BaseModel):
    """Trending developer popular repository data."""

    repositoryName: str | None
    description: str | None
    url: str | None


class Developer(BaseModel):
    """Trending developer response data."""

    rank: int
    username: str
    name: str | None
    url: str
    avatar: str | None
    since: str
    popularRepository: PopularRepository


TrendingItem = TypeVar("TrendingItem")


class TrendingResponse(BaseModel, Generic[TrendingItem]):
    """Envelope wrapping trending entries with fetch provenance.

    The ``data`` entries keep their original fields and ordering; only the
    surrounding provenance block is added.
    """

    data: list[TrendingItem]
    source: TrendingSource
