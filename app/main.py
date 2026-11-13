"""Github-Trending-API
===================
API serving data about trending github repositories/developers.
"""
# Copyright (c) 2021, Niklas Tiede.
# All rights reserved. Distributed under the MIT License.
import time
from typing import Any, Dict, NamedTuple

import fastapi
import uvicorn

from app.allowed_parameters import (
    AllowedDateRanges,
    AllowedProgrammingLanguages,
    AllowedSpokenLanguages,
)
from app.schemas import (
    DataOrigin,
    Developer,
    HealthStatus,
    Metadata,
    Repository,
    TrendingResponse,
    TrendingSource,
    UpstreamFailure,
)
from app.scraping import (
    UpstreamRequestError,
    get_request,
    make_soup,
    scraping_developers,
    scraping_repositories,
)

app = fastapi.FastAPI()
APP_NAME = "GitHub Trending API"
APP_VERSION = "2.0.0"
CACHE_TTL_SECONDS = 300
UPSTREAM_FAILURE_DETAIL = "Unable to fetch GitHub Trending data"
UPSTREAM_FAILURE_RESPONSES: dict[int | str, dict[str, Any]] = {
    502: {"model": UpstreamFailure},
}
CacheKey = tuple[str, tuple[tuple[str, str], ...]]
_trending_html_cache: dict[CacheKey, tuple[float, str]] = {}


class FetchResult(NamedTuple):
    """Fetched trending HTML together with its provenance."""

    html: str
    origin: DataOrigin
    cache_age_seconds: int


@app.exception_handler(UpstreamRequestError)
async def handle_upstream_request_error(
    request: fastapi.Request,
    request_error: UpstreamRequestError,
) -> fastapi.responses.JSONResponse:
    """Translate upstream fetch failures into structured 502 responses."""
    failure = UpstreamFailure(
        detail=UPSTREAM_FAILURE_DETAIL,
        retryable=True,
        failureReason=request_error.failure_reason,
    )
    return fastapi.responses.JSONResponse(
        status_code=502,
        content=failure.model_dump(),
    )


def build_payload(
    since: AllowedDateRanges | None = None,
    spoken_language_code: AllowedSpokenLanguages | None = None,
) -> Dict[str, str]:
    """Build GitHub Trending query parameters."""
    payload = {"since": "daily"}
    if since:
        payload["since"] = since.value
    if spoken_language_code:
        payload["spoken_language_code"] = spoken_language_code.value
    return payload


def _cache_age_seconds(cached_at: float, now: float) -> int:
    """Whole seconds elapsed since a cache entry was written (never negative)."""
    return max(0, int(now - cached_at))


async def fetch_trending_html(url: str, payload: Dict[str, str]) -> FetchResult:
    """Fetch GitHub Trending HTML, reporting origin and cache age.

    Fresh upstream data is marked ``upstream`` with an age of 0. Data served
    from the in-memory cache is marked ``cache`` with the age in whole
    seconds. Each distinct ``(url, payload)`` combination owns its cache
    entry. Upstream failures propagate as ``UpstreamRequestError`` and are
    translated into a structured 502 by the registered exception handler.
    """
    cache_key = (url, tuple(sorted(payload.items())))
    now = time.monotonic()
    cached_at, cached_html = _trending_html_cache.get(cache_key, (0.0, ""))
    if cached_html and now - cached_at < CACHE_TTL_SECONDS:
        return FetchResult(
            html=cached_html,
            origin=DataOrigin.cache,
            cache_age_seconds=_cache_age_seconds(cached_at, now),
        )

    raw_html = await get_request(url, compress=True, params=payload)

    fetched_at = time.monotonic()
    _trending_html_cache[cache_key] = (fetched_at, raw_html)
    return FetchResult(
        html=raw_html,
        origin=DataOrigin.upstream,
        cache_age_seconds=0,
    )


def clear_trending_cache() -> None:
    """Clear cached GitHub Trending HTML responses."""
    _trending_html_cache.clear()


def _build_source(fetch_result: FetchResult) -> TrendingSource:
    """Build the provenance block attached to every trending response."""
    return TrendingSource(
        origin=fetch_result.origin,
        cacheAgeSeconds=fetch_result.cache_age_seconds,
        cacheTtlSeconds=CACHE_TTL_SECONDS,
    )


async def get_repository_trends(
    url: str,
    payload: Dict[str, str],
) -> TrendingResponse[Repository]:
    """Fetch and parse GitHub Trending repository data."""
    fetch_result = await fetch_trending_html(url, payload)
    soup = make_soup(fetch_result.html)
    repositories = scraping_repositories(soup, since=payload["since"])
    items = [Repository.model_validate(repository) for repository in repositories]
    return TrendingResponse[Repository](
        data=items,
        source=_build_source(fetch_result),
    )


async def get_developer_trends(
    url: str,
    payload: Dict[str, str],
) -> TrendingResponse[Developer]:
    """Fetch and parse GitHub Trending developer data."""
    fetch_result = await fetch_trending_html(url, payload)
    soup = make_soup(fetch_result.html)
    developers = scraping_developers(soup, since=payload["since"])
    items = [Developer.model_validate(developer) for developer in developers]
    return TrendingResponse[Developer](
        data=items,
        source=_build_source(fetch_result),
    )


@app.get("/")
def help_routes(request: fastapi.Request) -> Dict[str, str]:
    """ API endpoints and documentation. """
    base_url = str(request.base_url).rstrip("/")
    return {
        "repositories": f"{base_url}/repositories",
        "developers": f"{base_url}/developers",
        "docs": f"{base_url}/docs",
        "redoc": f"{base_url}/redoc",
    }


@app.get("/health", response_model=HealthStatus)
def health() -> HealthStatus:
    """Return application health status."""
    return HealthStatus(status="ok")


@app.get("/metadata", response_model=Metadata)
def metadata(request: fastapi.Request) -> Metadata:
    """Return API metadata for clients."""
    base_url = str(request.base_url).rstrip("/")
    return Metadata(
        name=APP_NAME,
        version=APP_VERSION,
        docs=f"{base_url}/docs",
        redoc=f"{base_url}/redoc",
        health=f"{base_url}/health",
        repositories=f"{base_url}/repositories",
        developers=f"{base_url}/developers",
        cacheTtlSeconds=CACHE_TTL_SECONDS,
        supportedDateRanges=[date_range.value for date_range in AllowedDateRanges],
        supportedProgrammingLanguagesCount=len(AllowedProgrammingLanguages),
        supportedSpokenLanguagesCount=len(AllowedSpokenLanguages),
    )


@app.get(
    "/repositories",
    response_model=TrendingResponse[Repository],
    responses=UPSTREAM_FAILURE_RESPONSES,
)
async def trending_repositories(
    since: AllowedDateRanges | None = None,
    spoken_language_code: AllowedSpokenLanguages | None = None,
) -> TrendingResponse[Repository]:
    """Returns data about trending repositories (all programming
    languages, cannot be specified on this endpoint).
    """
    payload = build_payload(since, spoken_language_code)
    return await get_repository_trends("https://github.com/trending", payload)


@app.get(
    "/repositories/{prog_lang}",
    response_model=TrendingResponse[Repository],
    responses=UPSTREAM_FAILURE_RESPONSES,
)
async def trending_repositories_by_progr_language(
    prog_lang: AllowedProgrammingLanguages,
    since: AllowedDateRanges | None = None,
    spoken_language_code: AllowedSpokenLanguages | None = None,
) -> TrendingResponse[Repository]:
    """Returns data about trending repositories. A specific programming
    language can be added as path parameter to specify search.
    """
    payload = build_payload(since, spoken_language_code)
    url = f"https://github.com/trending/{prog_lang.value}"
    return await get_repository_trends(url, payload)


@app.get(
    "/developers",
    response_model=TrendingResponse[Developer],
    responses=UPSTREAM_FAILURE_RESPONSES,
)
async def trending_developers(
    since: AllowedDateRanges | None = None,
) -> TrendingResponse[Developer]:
    """Returns data about trending developers (all programming languages,
    cannot be specified on this endpoint).
    """
    payload = build_payload(since)
    return await get_developer_trends(
        "https://github.com/trending/developers",
        payload,
    )


@app.get(
    "/developers/{prog_lang}",
    response_model=TrendingResponse[Developer],
    responses=UPSTREAM_FAILURE_RESPONSES,
)
async def trending_developers_by_progr_language(
    prog_lang: AllowedProgrammingLanguages,
    since: AllowedDateRanges | None = None,
) -> TrendingResponse[Developer]:
    """Returns data about trending developers. A specific programming
    language can be added as path parameter to specify search.
    """
    payload = build_payload(since)
    url = f"https://github.com/trending/developers/{prog_lang.value}"
    return await get_developer_trends(url, payload)


if __name__ == "__main__":
    uvicorn.run(app, port=8000, host="0.0.0.0")
