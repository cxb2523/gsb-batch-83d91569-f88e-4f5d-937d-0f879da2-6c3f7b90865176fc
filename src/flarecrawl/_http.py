"""Shared HTTP helpers for polite GETs with bounded resource use.

The same client-ownership / origin-extraction / bounded-GET dance
repeats in :mod:`flarecrawl.robots` and :mod:`flarecrawl.sitemap`.
Factor out the building blocks:

- :func:`origin` — ``scheme://netloc`` extraction for a URL.
- :func:`ensure_client` — async context manager that yields a
  ``(client, owns)`` pair. ``owns=True`` when we created the client and
  must close it on exit; ``owns=False`` when the caller supplied one.
- :func:`polite_get_detailed` — :func:`polite_get` plus a structured
  reason when no response is returned, so callers can tell a network
  error from a response-body cap.
- :func:`polite_get` — ``httpx.AsyncClient.get`` wrapper with
  follow-redirects, UA header, optional ``max_bytes`` content-length
  cap, and ``None`` on network error.

Only these primitives are exported; callers still own the
per-module ``MAX_*`` constants and parse logic.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

__all__ = [
    "FetchFailure",
    "ensure_client",
    "origin",
    "polite_get",
    "polite_get_detailed",
]

logger = logging.getLogger(__name__)

#: ``FetchFailure.kind`` values.
REQUEST_ERROR = "request_error"
TOO_LARGE = "too_large"


@dataclass(frozen=True, slots=True)
class FetchFailure:
    """Why :func:`polite_get_detailed` returned no response.

    ``kind`` is ``"request_error"`` when the GET raised a transport
    error (connect failure, timeout, invalid URL, …) and
    ``"too_large"`` when the advertised ``content-length`` exceeded the
    caller's cap. ``detail`` is a short human-readable explanation.
    """

    kind: str
    detail: str


def origin(url: str) -> str:
    """Return ``scheme://netloc`` for ``url``.

    Example
    -------
    >>> origin("https://example.com:443/a?b=1")
    'https://example.com:443'
    """
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"


@asynccontextmanager
async def ensure_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[tuple[httpx.AsyncClient, bool]]:
    """Yield ``(client, owns)``.

    If ``client`` is ``None`` a fresh :class:`httpx.AsyncClient` is
    created; ``owns`` is ``True`` and the client is closed on exit.
    If a client is passed in, it is yielded untouched and the caller
    retains ownership.
    """
    if client is None:
        owned = httpx.AsyncClient()
        try:
            yield owned, True
        finally:
            await owned.aclose()
    else:
        yield client, False


async def polite_get_detailed(
    url: str,
    *,
    client: httpx.AsyncClient,
    user_agent: str,
    timeout: float = 10.0,
    max_bytes: int | None = None,
) -> tuple[httpx.Response | None, FetchFailure | None]:
    """GET ``url``, returning ``(response, failure)``.

    Exactly one element is non-``None``. A response (including a
    ``4xx``/``5xx``) is returned as-is — callers inspect
    ``status_code`` themselves. A :class:`FetchFailure` is returned
    when the GET raised :class:`httpx.HTTPError` /
    :class:`httpx.InvalidURL` or the response advertises a
    ``content-length`` above ``max_bytes``.
    """
    try:
        resp = await client.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=timeout,
            follow_redirects=True,
        )
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        logger.debug("polite_get(%s) failed: %r", url, exc)
        return None, FetchFailure(
            REQUEST_ERROR, f"{type(exc).__name__}: {exc}"
        )
    if max_bytes is not None:
        cl = resp.headers.get("content-length")
        if cl is not None:
            try:
                size = int(cl)
            except ValueError:
                size = None
            if size is not None and size > max_bytes:
                logger.debug(
                    "polite_get(%s) size cap tripped: %s > %d",
                    url,
                    cl,
                    max_bytes,
                )
                return None, FetchFailure(
                    TOO_LARGE,
                    f"content-length {size} exceeds cap {max_bytes}",
                )
    return resp, None


async def polite_get(
    url: str,
    *,
    client: httpx.AsyncClient,
    user_agent: str,
    timeout: float = 10.0,
    max_bytes: int | None = None,
) -> httpx.Response | None:
    """GET ``url`` with a User-Agent header and size cap.

    Returns the :class:`httpx.Response` on success, or ``None`` when
    the GET raised :class:`httpx.HTTPError` / :class:`httpx.InvalidURL`
    or the response advertises a ``content-length`` above ``max_bytes``.

    The function deliberately does NOT treat ``4xx``/``5xx`` as errors
    — callers inspect ``resp.status_code`` themselves because the
    meaningful response for (e.g.) a missing robots.txt differs from
    a missing sitemap.xml.

    Callers that need to distinguish a transport error from a size-cap
    trip should use :func:`polite_get_detailed`.
    """
    resp, _failure = await polite_get_detailed(
        url,
        client=client,
        user_agent=user_agent,
        timeout=timeout,
        max_bytes=max_bytes,
    )
    return resp
