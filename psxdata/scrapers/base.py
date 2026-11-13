"""BaseScraper — foundation class for all psxdata scrapers.

Scraping mode:
  - requests + BeautifulSoup: via _get() / _post()

All PSX endpoints are accessible via plain HTTP requests to AJAX endpoints.
Playwright is not used — all scrapers use requests only.

All Phase 3 scrapers inherit from BaseScraper.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from psxdata.constants import (
    BASE_URL,
    ENDPOINTS,
    MAX_REQUESTS_PER_SECOND,
    MAX_RETRIES,
    REQUEST_HEADERS,
    REQUEST_TIMEOUT,
    RETRY_DELAYS,
    TOKEN_HEADER,
)
from psxdata.exceptions import (
    PSXAuthError,
    PSXConnectionError,
    PSXParseError,
    PSXRateLimitError,
    PSXServerError,
)
from psxdata.proxy import ProxyConfig, describe_proxies, normalize_proxy, redact_text
from psxdata.scrapers.token import TokenProvider, get_default_provider
from psxdata.utils import RateLimiter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestAttempt:
    """One HTTP attempt made by :meth:`BaseScraper._request`.

    Passed to an ``on_attempt`` observer after every attempt — successful or
    not — so callers can tell a clean first-try fetch from one that needed
    retries, and can salvage a response body from an earlier attempt.

    Attributes:
        number: 1-based attempt number (an ``X-Req-Id`` refresh retry keeps
            the same number — it is not a 5xx/network retry).
        succeeded: Whether this attempt produced a 2xx response.
        status_code: HTTP status if a response was received, else ``None``.
        error: Exception raised for this attempt, if any.
        response: The response object, when one was received.
    """

    number: int
    succeeded: bool
    status_code: int | None = None
    error: Exception | None = None
    response: requests.Response | None = None


AttemptObserver = Callable[[RequestAttempt], None]


class BaseScraper:
    """Foundation class for all psxdata scrapers.

    Provides:
    - Persistent requests.Session with standard PSX headers
    - Exponential backoff retry (MAX_RETRIES attempts, RETRY_DELAYS seconds)
    - Thread-safe rate limiter (MAX_REQUESTS_PER_SECOND)
    - PSX ``X-Req-Id`` request token on every request (process-wide TokenProvider),
      with one refresh-and-retry on 403
    - Optional explicit proxy for every request, including the token fetch

    Args:
        token_provider: Token provider to use. ``None`` uses the process-wide
            provider for this scraper's proxy configuration.
        proxy: Proxy URL (``"http://user:pass@host:8080"``, ``"socks5://..."``)
            applied to all traffic, or a ``requests``-style dict mapping scheme
            to URL. Takes precedence over ``HTTP_PROXY``/``HTTPS_PROXY``. ``None``
            (default) keeps plain ``requests`` behaviour, env vars included.

    Raises:
        ValueError, TypeError, ImportError: Invalid *proxy*; see
            :func:`psxdata.proxy.normalize_proxy`.
    """

    def __init__(
        self,
        token_provider: TokenProvider | None = None,
        proxy: ProxyConfig = None,
    ) -> None:
        self._proxies = normalize_proxy(proxy)
        self._session = requests.Session()
        self._session.headers.update(REQUEST_HEADERS)
        if self._proxies:
            self._session.proxies.update(self._proxies)
        self._via = f" via proxy {describe_proxies(self._proxies)}" if self._proxies else ""
        self._rate_limiter = RateLimiter(max_per_second=MAX_REQUESTS_PER_SECOND)
        # None -> process-wide default, looked up per request (see _get_token_provider)
        self._token_provider = token_provider

    def _get_token_provider(self) -> TokenProvider:
        return self._token_provider or get_default_provider(self._proxies)

    def _build_url(self, endpoint: str) -> str:
        return BASE_URL + ENDPOINTS[endpoint]

    def _request(
        self,
        method: str,
        url: str,
        on_attempt: AttemptObserver | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """Execute an HTTP request with retry, rate limiting, and error mapping.

        Every request carries the PSX ``X-Req-Id`` token when one can be
        obtained (see :mod:`psxdata.scrapers.token`). On 403 the token is
        refreshed and the request retried once; this retry does not consume a
        5xx/network attempt. Retries on 5xx and network errors up to
        MAX_RETRIES times with exponential backoff. Other 4xx raise immediately.

        Args:
            method: HTTP method ("GET" or "POST").
            url: Full URL to request.
            on_attempt: Optional observer called with a :class:`RequestAttempt`
                after every attempt, including failed ones. Exceptions raised by
                the observer propagate — keep it cheap and non-throwing.
            **kwargs: Passed directly to requests.Session.request. A ``headers``
                dict is merged with the token header (the caller's dict is not
                modified).

        Returns:
            requests.Response with 2xx status.

        Raises:
            PSXConnectionError: Network-level failure after all retries.
            PSXServerError: 5xx response after all retries.
            PSXRateLimitError: 429 response (no retry).
            PSXAuthError: 401 response (no retry), or 403 after one token
                refresh-and-retry (or when no token could be obtained).
            PSXParseError: Other 4xx response (no retry).
        """
        caller_headers: dict[str, str] = dict(kwargs.pop("headers", None) or {})
        if self._proxies:
            # Per-request proxies take precedence over HTTP(S)_PROXY env vars;
            # session.proxies alone would not (requests merges env settings over it).
            kwargs.setdefault("proxies", self._proxies)
        provider = self._get_token_provider()
        auth_retry_used = False
        last_exc: Exception | None = None
        attempt = 1

        def notify(
            *,
            succeeded: bool,
            status_code: int | None = None,
            error: Exception | None = None,
            response: requests.Response | None = None,
        ) -> None:
            if on_attempt is not None:
                on_attempt(
                    RequestAttempt(
                        number=attempt,
                        succeeded=succeeded,
                        status_code=status_code,
                        error=error,
                        response=response,
                    )
                )

        while attempt <= MAX_RETRIES:
            token = provider.get_token()
            headers = {**caller_headers, TOKEN_HEADER: token} if token else dict(caller_headers)
            try:
                with self._rate_limiter:
                    logger.debug(
                        "attempt %d/%d %s %s%s", attempt, MAX_RETRIES, method, url, self._via
                    )
                    resp = self._session.request(
                        method, url, timeout=REQUEST_TIMEOUT, headers=headers, **kwargs
                    )

                if resp.status_code == 429:
                    exc: Exception = PSXRateLimitError(
                        f"PSX rate limit exceeded (429) on {url}"
                    )
                    notify(succeeded=False, status_code=429, error=exc, response=resp)
                    raise exc
                if resp.status_code == 403 and token is not None and not auth_retry_used:
                    provider.invalidate(token)
                    if provider.get_token() is not None:
                        auth_retry_used = True
                        logger.debug("403 on %s; refreshed %s, retrying once", url, TOKEN_HEADER)
                        continue  # same attempt number — auth retry is not a 5xx retry
                    exc = PSXAuthError(
                        f"PSX auth error (403) on {url}; {TOKEN_HEADER} token was "
                        "rejected and could not be refreshed"
                    )
                    notify(succeeded=False, status_code=403, error=exc, response=resp)
                    raise exc
                if resp.status_code == 403:
                    detail = (
                        f"{TOKEN_HEADER} token was sent and refreshed once"
                        if token is not None
                        else f"no {TOKEN_HEADER} token could be obtained"
                    )
                    exc = PSXAuthError(f"PSX auth error (403) on {url}; {detail}")
                    notify(succeeded=False, status_code=403, error=exc, response=resp)
                    raise exc
                if resp.status_code == 401:
                    exc = PSXAuthError(f"PSX auth error ({resp.status_code}) on {url}")
                    notify(succeeded=False, status_code=401, error=exc, response=resp)
                    raise exc
                if resp.status_code >= 500:
                    last_exc = PSXServerError(
                        f"PSX server error ({resp.status_code}) on {url}, "
                        f"attempt {attempt}/{MAX_RETRIES}"
                    )
                    notify(succeeded=False, status_code=resp.status_code,
                           error=last_exc, response=resp)
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAYS[attempt - 1])  # delays[0]=1s, delays[1]=2s
                        attempt += 1
                        continue
                    raise last_exc  # final attempt — raise immediately, no sleep
                if 400 <= resp.status_code < 500:
                    exc = PSXParseError(f"Unexpected {resp.status_code} from {url}")
                    notify(succeeded=False, status_code=resp.status_code, error=exc, response=resp)
                    raise exc
                notify(succeeded=True, status_code=resp.status_code, response=resp)
                return resp

            except requests.RequestException as exc:
                # Catches ConnectionError, Timeout, SSLError, ChunkedEncodingError, etc.
                last_exc = exc
                logger.debug(
                    "Network error on attempt %d/%d%s: %s",
                    attempt,
                    MAX_RETRIES,
                    self._via,
                    redact_text(str(exc), self._proxies),
                )
                notify(succeeded=False, error=exc)
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAYS[attempt - 1])
                    attempt += 1
                    continue
                raise PSXConnectionError(
                    f"PSX unreachable after {MAX_RETRIES} attempts{self._via}: {url}"
                ) from exc
            except (PSXRateLimitError, PSXAuthError, PSXParseError):
                raise  # no retry

        # Safety net — loop always returns or raises above
        raise PSXServerError(f"Exhausted retries for {url}")

    def _get(
        self,
        endpoint: str,
        on_attempt: AttemptObserver | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """GET request to a named PSX endpoint."""
        return self._request("GET", self._build_url(endpoint), on_attempt=on_attempt, **kwargs)

    def _post(
        self,
        endpoint: str,
        data: dict[str, Any],
        on_attempt: AttemptObserver | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        """POST request to a named PSX endpoint."""
        return self._request(
            "POST", self._build_url(endpoint), data=data, on_attempt=on_attempt, **kwargs
        )


