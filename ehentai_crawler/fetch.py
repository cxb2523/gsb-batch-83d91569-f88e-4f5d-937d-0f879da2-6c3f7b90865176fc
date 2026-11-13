"""Network access.

* :class:`HostRateLimiter` spaces requests to each host, shared by all threads.
* :class:`HttpTransport` loads pages and downloads files with ``requests``.
* :class:`BrowserTransport` loads pages with Chrome through Selenium (optional).
* :class:`Fetcher` turns the site's error pages into exceptions and retries
  temporary failures with exponential backoff.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar
from urllib.parse import urlsplit

import requests

from . import parse
from .errors import (
    AccessDeniedError,
    BannedError,
    FetchError,
    GalleryUnavailableError,
    SettingsError,
    TransientError,
)
from .settings import Settings

log = logging.getLogger(__name__)

#: HTTP statuses worth retrying.
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
#: First retry waits this many seconds; each further retry doubles it, up to the cap.
BACKOFF_BASE = 5.0
BACKOFF_CAP = 300.0
DOWNLOAD_CHUNK = 64 * 1024
PARTIAL_SUFFIX = ".part"

#: Chrome content the browser fetcher never needs (same list as the 2019 version).
BLOCKED_CHROME_CONTENT = {
    "profile.managed_default_content_settings.images": 2,
    "profile.managed_default_content_settings.media_stream": 2,
    "profile.managed_default_content_settings.popups": 2,
    "profile.managed_default_content_settings.javascript": 2,
    "profile.default_content_setting_values.notifications": 2,
    "profile.managed_default_content_settings.geolocation": 2,
}
CHROME_WINDOW_SIZE = "512,384"

T = TypeVar("T")
C = TypeVar("C")


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


@dataclass(frozen=True)
class Page:
    url: str
    #: HTTP status; ``None`` when the browser fetcher loaded the page.
    status: int | None
    text: str
    content_type: str | None = None


class Transport(Protocol):
    def fetch(self, url: str) -> Page: ...

    def close(self) -> None: ...


class HostRateLimiter:
    """Keep at least ``interval`` (plus random jitter) between requests to the same host."""

    def __init__(
        self,
        interval: float,
        *,
        jitter: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self.interval = interval
        self.jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._rng = rng
        self._next: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str) -> None:
        if self.interval <= 0:
            return
        host = host_of(url)
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(host, now))
            self._next[host] = start + self.interval * (1 + self._rng() * self.jitter)
        if start > now:
            self._sleep(start - now)


class _PerThread(Generic[C]):
    """One client object per thread (sessions and web drivers are not thread-safe)."""

    def __init__(self, make: Callable[[], C]) -> None:
        self._make = make
        self._local = threading.local()
        self._all: list[C] = []
        self._lock = threading.Lock()

    def get(self) -> C:
        client: C | None = getattr(self._local, "client", None)
        if client is None:
            client = self._make()
            self._local.client = client
            with self._lock:
                self._all.append(client)
        return client

    def drain(self) -> list[C]:
        with self._lock:
            clients, self._all = self._all, []
        self._local = threading.local()
        return clients


class HttpTransport:
    def __init__(
        self,
        settings: Settings,
        limiter: HostRateLimiter,
        session_factory: Callable[[], requests.Session] = requests.Session,
    ) -> None:
        self.settings = settings
        self.limiter = limiter
        self._session_factory = session_factory
        self._sessions = _PerThread(self._new_session)

    def _new_session(self) -> requests.Session:
        session = self._session_factory()
        session.headers["User-Agent"] = self.settings.user_agent
        for host, cookies in self.settings.cookies_by_host().items():
            for name, value in cookies.items():
                session.cookies.set(name, value, domain=host, path="/")
        return session

    def _get(self, url: str, *, stream: bool = False) -> requests.Response:
        self.limiter.wait(url)
        log.debug("GET %s", url)
        try:
            return self._sessions.get().get(url, timeout=self.settings.timeout, stream=stream)
        except (requests.Timeout, requests.ConnectionError) as exc:
            raise TransientError(f"{url}: {type(exc).__name__}") from exc
        except requests.RequestException as exc:
            raise FetchError(f"{url}: {exc}") from exc

    def fetch(self, url: str) -> Page:
        response = self._get(url)
        return Page(url, response.status_code, response.text, response.headers.get("Content-Type"))

    def download(self, url: str, dest: Path) -> int:
        """Save ``url`` to ``dest`` through a ``.part`` file, so a crash never leaves a
        truncated image under the real name. Return the number of bytes written."""
        partial = dest.with_name(dest.name + PARTIAL_SUFFIX)
        with self._get(url, stream=True) as response:
            if response.status_code in RETRY_STATUSES:
                raise TransientError(f"{url}: HTTP {response.status_code}")
            if response.status_code >= 400:
                raise FetchError(f"{url}: HTTP {response.status_code}")
            size = 0
            try:
                with partial.open("wb") as handle:
                    for chunk in response.iter_content(DOWNLOAD_CHUNK):
                        handle.write(chunk)
                        size += len(chunk)
            except requests.RequestException as exc:
                raise TransientError(f"{url}: download interrupted ({type(exc).__name__})") from exc
        partial.replace(dest)
        return size

    def close(self) -> None:
        for session in self._sessions.drain():
            session.close()


@dataclass
class _Browser:
    driver: Any  # selenium.webdriver.Chrome, or a stand-in in tests
    hosts_with_cookies: set[str] = field(default_factory=set)


class BrowserTransport:
    """Load pages in Chrome. Selenium finds or downloads a matching ChromeDriver itself."""

    def __init__(
        self,
        settings: Settings,
        limiter: HostRateLimiter,
        driver_factory: Callable[[], Any] | None = None,
    ) -> None:
        try:
            from selenium.common.exceptions import TimeoutException, WebDriverException
        except ImportError:
            raise SettingsError("FETCHER=browser needs Selenium: pip install 'ehentai-crawler[browser]'") from None
        self._timeout_error = TimeoutException
        self._driver_error = WebDriverException
        self.settings = settings
        self.limiter = limiter
        self._factory = driver_factory or self._chrome
        self._drivers = _PerThread(self._new_driver)
        self._cookies = settings.cookies_by_host()

    def _chrome(self) -> Any:
        from selenium import webdriver

        options = webdriver.ChromeOptions()
        options.add_experimental_option("excludeSwitches", ["enable-logging"])
        options.add_experimental_option("prefs", BLOCKED_CHROME_CONTENT)
        options.add_argument(f"--window-size={CHROME_WINDOW_SIZE}")
        if self.settings.headless:
            options.add_argument("--headless=new")
        return webdriver.Chrome(options=options)

    def _new_driver(self) -> _Browser:
        driver = self._factory()
        driver.set_page_load_timeout(self.settings.timeout)
        return _Browser(driver)

    def _load(self, driver: Any, url: str) -> None:
        self.limiter.wait(url)
        log.debug("browser GET %s", url)
        try:
            driver.get(url)
        except self._timeout_error as exc:
            driver.execute_script("window.stop()")
            raise TransientError(f"{url}: page load timed out") from exc
        except self._driver_error as exc:
            raise TransientError(f"{url}: {exc.msg or type(exc).__name__}") from exc

    def fetch(self, url: str) -> Page:
        browser = self._drivers.get()
        driver = browser.driver
        host = host_of(url)
        if host in self._cookies and host not in browser.hosts_with_cookies:
            # Chrome only accepts cookies for the site it is showing, so open it first.
            parts = urlsplit(url)
            self._load(driver, f"{parts.scheme}://{parts.netloc}/")
            for name, value in self._cookies[host].items():
                driver.add_cookie({"name": name, "value": value})
            browser.hosts_with_cookies.add(host)
        self._load(driver, url)
        return Page(url, None, str(driver.page_source))

    def close(self) -> None:
        for browser in self._drivers.drain():
            browser.driver.quit()


def check_page(page: Page) -> str:
    """Return the page text, or raise for the site's error and placeholder pages."""
    text = page.text
    if parse.BAN_MARKER in text:
        expires = parse.ban_expires_in(text)
        detail = f"; it ends in about {expires / 60:.0f} min" if expires else ""
        raise BannedError(f"the site banned this IP for too many page loads{detail}", expires)
    if page.status in RETRY_STATUSES:
        raise TransientError(f"{page.url}: HTTP {page.status}")
    if parse.SERVICE_UNAVAILABLE_MARKER in text:
        raise TransientError(f"{page.url}: the site answered '{parse.SERVICE_UNAVAILABLE_MARKER}'")
    if page.status == 404 or any(marker in text for marker in parse.UNAVAILABLE_MARKERS):
        raise GalleryUnavailableError(f"{page.url} was removed or does not exist")
    if page.status is not None and page.status >= 400:
        raise FetchError(f"{page.url}: HTTP {page.status}")
    if not text.strip() or (page.content_type and "html" not in page.content_type.lower()):
        raise AccessDeniedError(
            f"{page.url} returned no HTML page; for ExHentai this usually means the login cookies are wrong"
        )
    return text


class Fetcher:
    """Pages and files with retries. ``pages`` may be the browser; files always use HTTP."""

    def __init__(
        self,
        pages: Transport,
        files: HttpTransport,
        *,
        max_retries: int,
        sleep: Callable[[float], None] = time.sleep,
        backoff_base: float = BACKOFF_BASE,
        backoff_cap: float = BACKOFF_CAP,
    ) -> None:
        self.pages = pages
        self.files = files
        self.max_retries = max_retries
        self._sleep = sleep
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap

    def page(self, url: str) -> str:
        return self._retry(url, lambda: check_page(self.pages.fetch(url)))

    def download(self, url: str, dest: Path) -> int:
        return self._retry(url, lambda: self.files.download(url, dest))

    def _retry(self, url: str, attempt: Callable[[], T]) -> T:
        for tries in range(self.max_retries + 1):
            try:
                return attempt()
            except TransientError as exc:
                if tries == self.max_retries:
                    attempts = f"{tries + 1} attempt" + ("s" if tries else "")
                    raise FetchError(f"gave up on {url} after {attempts} ({exc})") from exc
                wait = min(self._backoff_cap, self._backoff_base * 2**tries)
                log.warning("%s; retry %d/%d in %.0f s", exc, tries + 1, self.max_retries, wait)
                self._sleep(wait)
        raise AssertionError("unreachable")

    def close(self) -> None:
        if self.pages is not self.files:
            self.pages.close()
        self.files.close()


@contextmanager
def open_fetcher(settings: Settings) -> Iterator[Fetcher]:
    limiter = HostRateLimiter(settings.request_delay)
    files = HttpTransport(settings, limiter)
    pages: Transport = BrowserTransport(settings, limiter) if settings.fetcher == "browser" else files
    fetcher = Fetcher(pages, files, max_retries=settings.max_retries)
    try:
        yield fetcher
    finally:
        fetcher.close()
