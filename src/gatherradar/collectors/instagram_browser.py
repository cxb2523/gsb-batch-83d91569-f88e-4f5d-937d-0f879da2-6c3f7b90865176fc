from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse, urlunparse

from .base import (
    AuthenticationRequiredError,
    CollectorError,
    SourceAccessRestrictedError,
    SourceUnavailableError,
)
from .instagram_dom import (
    PROFILE_PRIVATE,
    PROFILE_UNAVAILABLE,
    MalformedMediaPageError,
    MediaLink,
    caption_hashtags,
    caption_mentions,
    detect_profile_state,
    discover_media_links,
    merge_media_links,
    parse_media_page,
)

# Browser-backed Instagram transport: Playwright drives the installed Google Chrome with a
# dedicated, persistent GatherRadar profile, so the logged-in Instagram web session lives
# in that profile rather than in any file GatherRadar writes. The browser is visible and
# unmodified: no stealth, fingerprint, or webdriver changes. Checkpoints are reported for
# the owner to resolve manually, never bypassed.

BROWSER_COLLECTOR_VERSION = "instagram-browser/1"
INSTAGRAM_HOME_URL = "https://www.instagram.com/"
AUTH_COMMAND = "python -m gatherradar auth instagram"
MEDIA_LINK_SELECTOR = 'a[href*="/p/"], a[href*="/reel/"]'
MEDIA_CONTENT_SELECTOR = "time[datetime]"
_SCROLL_SCRIPT = "() => window.scrollBy(0, window.innerHeight * 2)"

# Instagram lets a profile pin up to three posts to the top of its grid, so a few extra
# candidates are opened and the collector keeps the newest by publish date.
RECENCY_CANDIDATE_BUFFER = 3
MAX_CANDIDATE_POOL = 12


def candidate_limit_for(limit: int) -> int:
    """How many media pages to open for a requested limit: a small recency buffer, capped
    so a run never becomes bulk crawling (a limit above the cap gets no extra pages)."""
    return max(limit, min(limit + RECENCY_CANDIDATE_BUFFER, MAX_CANDIDATE_POOL))

NOT_AUTHENTICATED_MESSAGE = (
    f"Instagram browser session is not authenticated.\nRun:\n\n{AUTH_COMMAND}"
)
SESSION_EXPIRED_MESSAGE = (
    f"Instagram login has expired in the GatherRadar browser profile.\nRun:\n\n{AUTH_COMMAND}"
)
CHECKPOINT_MESSAGE = (
    "Instagram is showing a verification/checkpoint page.\n"
    f"Run:\n\n{AUTH_COMMAND}\n\n"
    "and complete the check manually in the opened Chrome window, then retry."
)

LOCATION_LOGIN = "login"
LOCATION_CHECKPOINT = "checkpoint"
LOCATION_OTHER = "other"


class BrowserLaunchError(CollectorError):
    """Playwright could not start Chrome with the GatherRadar browser profile."""


class ChromeUnavailableError(BrowserLaunchError):
    """The installed Google Chrome executable could not be found."""


class BrowserClosedError(CollectorError):
    """The GatherRadar Chrome window was closed while it was still needed."""


class BrowserSessionNotAuthenticatedError(AuthenticationRequiredError):
    """The GatherRadar browser profile has no Instagram login."""


class BrowserSessionExpiredError(AuthenticationRequiredError):
    """Instagram sent the profile back to its login flow."""


class InstagramCheckpointError(SourceAccessRestrictedError):
    """Instagram requires a manual verification/checkpoint step."""


class NavigationTimeoutError(SourceUnavailableError):
    """An Instagram page did not load within the navigation timeout."""


class InsufficientMediaError(SourceUnavailableError):
    """The source profile loaded but no posts or reels could be found on it."""


class BrowserHandle(Protocol):
    context: Any
    page: Any

    def close(self) -> None: ...


BrowserLauncher = Callable[[Path], BrowserHandle]


def browser_profile_path(data_dir: str | Path = "data") -> Path:
    return Path(data_dir) / "browser" / "instagram-profile"


def _first_line(exc: BaseException) -> str:
    text = str(exc).strip()
    return text.splitlines()[0] if text else type(exc).__name__


def _playwright_errors() -> tuple[type[Exception], type[Exception]]:
    from playwright.sync_api import Error, TimeoutError

    return Error, TimeoutError


def _default_playwright_factory() -> Any:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BrowserLaunchError(
            "Playwright is not installed. Run: python -m pip install -e ."
        ) from exc
    return sync_playwright().start()


@dataclass(slots=True)
class _PlaywrightBrowser:
    context: Any
    page: Any
    playwright: Any

    def close(self) -> None:
        try:
            self.context.close()
        except Exception:
            # The owner may already have closed the window; Chrome has flushed the
            # profile by then, and stopping Playwright below is what still matters.
            pass
        finally:
            self.playwright.stop()


class PlaywrightChromeLauncher:
    """Launches installed Google Chrome on a persistent profile through Playwright."""

    def __init__(
        self,
        *,
        headless: bool = False,
        channel: str = "chrome",
        timeout_ms: int = 30_000,
        playwright_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.headless = headless
        self.channel = channel
        self.timeout_ms = timeout_ms
        self._playwright_factory = playwright_factory or _default_playwright_factory

    def __call__(self, profile_dir: Path) -> BrowserHandle:
        playwright = self._playwright_factory()
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                channel=self.channel,
                headless=self.headless,
                timeout=self.timeout_ms,
            )
        except Exception as exc:
            playwright.stop()
            raise _translate_launch_error(exc, profile_dir) from exc

        context.set_default_timeout(self.timeout_ms)
        page = context.pages[0] if context.pages else context.new_page()
        return _PlaywrightBrowser(context=context, page=page, playwright=playwright)


def _translate_launch_error(exc: Exception, profile_dir: Path) -> BrowserLaunchError:
    lowered = str(exc).lower()
    if "distribution 'chrome' is not found" in lowered or "executable doesn't exist" in lowered:
        return ChromeUnavailableError(
            "Google Chrome was not found. Install Google Chrome; GatherRadar launches the "
            "installed Chrome through Playwright and does not use a bundled browser."
        )
    if "processsingleton" in lowered or "already in use" in lowered or "has been closed" in lowered:
        return BrowserLaunchError(
            f"Chrome could not start with the GatherRadar profile at {profile_dir}; it is "
            "probably already in use. Close the Chrome window GatherRadar opened and retry."
        )
    return BrowserLaunchError(f"Playwright could not launch Chrome: {_first_line(exc)}")


def classify_instagram_location(url: str | None) -> str:
    segments = [segment for segment in urlparse(url or "").path.lower().split("/") if segment]
    if segments[:2] == ["accounts", "login"]:
        return LOCATION_LOGIN
    if segments[:1] in (["challenge"], ["checkpoint"], ["auth_platform"]) or segments[:2] in (
        ["accounts", "suspended"],
        ["accounts", "disabled"],
    ):
        return LOCATION_CHECKPOINT
    return LOCATION_OTHER


def has_instagram_session_cookie(context: Any) -> bool:
    cookies = context.cookies([INSTAGRAM_HOME_URL])
    return any(cookie.get("name") == "sessionid" and cookie.get("value") for cookie in cookies)


def _ensure_location_allowed(url: str | None) -> None:
    location = classify_instagram_location(url)
    if location == LOCATION_LOGIN:
        raise BrowserSessionExpiredError(SESSION_EXPIRED_MESSAGE)
    if location == LOCATION_CHECKPOINT:
        raise InstagramCheckpointError(CHECKPOINT_MESSAGE)


def _goto(page: Any, url: str, timeout_ms: int) -> Any:
    playwright_error, playwright_timeout = _playwright_errors()
    try:
        return page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except playwright_timeout as exc:
        raise NavigationTimeoutError(
            f"Timed out after {timeout_ms / 1000:.0f}s loading {url}"
        ) from exc
    except playwright_error as exc:
        if "has been closed" in str(exc).lower():
            raise BrowserClosedError("The GatherRadar Chrome window was closed during the run.") from exc
        raise SourceUnavailableError(f"Could not load {url}: {_first_line(exc)}") from exc


def _wait_for_optional(page: Any, selector: str, timeout_ms: int) -> None:
    _, playwright_timeout = _playwright_errors()
    try:
        page.wait_for_selector(selector, timeout=timeout_ms)
    except playwright_timeout:
        pass


def _without_query(url: str | None) -> str | None:
    if not url:
        return None
    return urlunparse(urlparse(url)._replace(query="", fragment=""))


def authenticate_browser_profile(
    *,
    wait_for_user: Callable[[], None],
    data_dir: str | Path = "data",
    launcher: BrowserLauncher | None = None,
    navigation_timeout_ms: int = 60_000,
) -> Path:
    """Open Instagram in a visible Chrome window on the GatherRadar profile, let the owner
    log in manually, then verify the login. The profile itself is the persisted session;
    no password or cookie passes through GatherRadar. The browser is always closed."""
    profile_dir = browser_profile_path(data_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    active_launcher = launcher or PlaywrightChromeLauncher(timeout_ms=navigation_timeout_ms)
    browser = active_launcher(profile_dir.resolve())
    try:
        try:
            _goto(browser.page, INSTAGRAM_HOME_URL, navigation_timeout_ms)
        except NavigationTimeoutError:
            pass  # a slow first load is not fatal; the owner is about to use the window anyway
        wait_for_user()
        _verify_logged_in(browser)
    finally:
        browser.close()
    return profile_dir


def _verify_logged_in(browser: BrowserHandle) -> None:
    playwright_error, _ = _playwright_errors()
    try:
        location = classify_instagram_location(browser.page.url)
        authenticated = has_instagram_session_cookie(browser.context)
    except playwright_error as exc:
        raise BrowserClosedError(
            "The GatherRadar Chrome window was closed before the Instagram session could be "
            f"verified.\nRun:\n\n{AUTH_COMMAND}\n\nand press Enter while the window is still open."
        ) from exc

    if location == LOCATION_CHECKPOINT:
        raise InstagramCheckpointError(CHECKPOINT_MESSAGE)
    if location == LOCATION_LOGIN or not authenticated:
        raise BrowserSessionNotAuthenticatedError(
            "No Instagram login was detected in the GatherRadar Chrome window.\n"
            f"Run:\n\n{AUTH_COMMAND}\n\nand press Enter only after the Instagram home page is visible."
        )


@contextmanager
def open_authenticated_browser(profile_dir: Path, launcher: BrowserLauncher) -> Iterator[BrowserHandle]:
    """Launch the GatherRadar profile only if it holds an Instagram login; always close it."""
    if not profile_dir.is_dir() or not any(profile_dir.iterdir()):
        raise BrowserSessionNotAuthenticatedError(NOT_AUTHENTICATED_MESSAGE)

    browser = launcher(profile_dir)
    try:
        if not has_instagram_session_cookie(browser.context):
            raise BrowserSessionNotAuthenticatedError(NOT_AUTHENTICATED_MESSAGE)
        yield browser
    finally:
        browser.close()


@dataclass(frozen=True, slots=True)
class BrowserMedia:
    """One post or reel read from the browser. Its attribute names match the Instaloader
    Post attributes the RawItem mapper reads, so both transports share one mapping."""

    shortcode: str
    owner_username: str
    caption: str | None = None
    date_utc: datetime | None = None
    url: str | None = None
    caption_hashtags: tuple[str, ...] = ()
    caption_mentions: tuple[str, ...] = ()
    extraction_error: str | None = None
    extra_metadata: dict[str, Any] = field(default_factory=dict)
    collector_version: str = BROWSER_COLLECTOR_VERSION

    @classmethod
    def failed(cls, link: MediaLink, username: str, reason: str) -> BrowserMedia:
        return cls(
            shortcode=link.shortcode,
            owner_username=username,
            extraction_error=reason,
            extra_metadata={"transport": "browser", "media_url": link.url},
        )


class BrowserMediaFetcher:
    """Reads a bounded number of recent posts and reels from one approved public profile
    through the persistent GatherRadar Chrome profile.

    Opens the profile page plus one page per candidate: `candidate_limit_for(limit)`
    items, slightly more than `limit`, so InstagramCollector can keep the newest by
    publish date and pinned posts cannot displace recent media. Scrolls only while fewer
    candidates are visible and never more than `max_scroll_attempts` times. Browser
    failures are raised, never retried through another transport.
    """

    def __init__(
        self,
        *,
        data_dir: str | Path = "data",
        launcher: BrowserLauncher | None = None,
        navigation_timeout_ms: int = 30_000,
        content_wait_ms: int = 10_000,
        max_scroll_attempts: int = 4,
        scroll_pause_ms: int = 1_500,
        page_pause_ms: int = 1_000,
    ) -> None:
        self.profile_dir = browser_profile_path(data_dir)
        self.launcher = launcher
        self.navigation_timeout_ms = navigation_timeout_ms
        self.content_wait_ms = content_wait_ms
        self.max_scroll_attempts = max_scroll_attempts
        self.scroll_pause_ms = scroll_pause_ms
        self.page_pause_ms = page_pause_ms

    def __call__(self, username: str, limit: int) -> Iterator[tuple[str, BrowserMedia]]:
        launcher = self.launcher or PlaywrightChromeLauncher(timeout_ms=self.navigation_timeout_ms)
        with open_authenticated_browser(self.profile_dir.resolve(), launcher) as browser:
            for link in self._discover_links(browser, username, candidate_limit_for(limit)):
                yield self._read_media(browser.page, username, link)

    def _discover_links(
        self, browser: BrowserHandle, username: str, candidate_limit: int
    ) -> list[MediaLink]:
        page = browser.page
        response = _goto(page, f"https://www.instagram.com/{username}/", self.navigation_timeout_ms)
        _ensure_location_allowed(page.url)
        if not has_instagram_session_cookie(browser.context):
            raise BrowserSessionExpiredError(SESSION_EXPIRED_MESSAGE)

        _wait_for_optional(page, MEDIA_LINK_SELECTOR, self.content_wait_ms)
        html = page.content()
        if detect_profile_state(html) == PROFILE_PRIVATE:
            raise SourceAccessRestrictedError(
                f"Instagram profile @{username} is private; GatherRadar collects public content only"
            )

        links = discover_media_links(html, username)
        scroll_attempts = 0
        while len(links) < candidate_limit and scroll_attempts < self.max_scroll_attempts:
            page.evaluate(_SCROLL_SCRIPT)
            page.wait_for_timeout(self.scroll_pause_ms)
            scroll_attempts += 1
            grown = merge_media_links(links, discover_media_links(page.content(), username))
            if len(grown) == len(links):
                break
            links = grown

        if not links:
            if getattr(response, "status", None) == 404 or detect_profile_state(html) == PROFILE_UNAVAILABLE:
                raise SourceUnavailableError(
                    f"Instagram profile @{username} was not found or is unavailable"
                )
            raise InsufficientMediaError(
                f"No posts or reels were found on @{username}'s profile page after "
                f"{scroll_attempts} scroll attempt(s). The profile may be empty, or "
                "Instagram's page layout may have changed."
            )
        return links[:candidate_limit]

    def _read_media(self, page: Any, username: str, link: MediaLink) -> tuple[str, BrowserMedia]:
        page.wait_for_timeout(self.page_pause_ms)
        try:
            _goto(page, link.url, self.navigation_timeout_ms)
        except NavigationTimeoutError as exc:
            return link.kind, BrowserMedia.failed(link, username, str(exc))
        _ensure_location_allowed(page.url)
        _wait_for_optional(page, MEDIA_CONTENT_SELECTOR, self.content_wait_ms)

        final_url = page.url
        try:
            data = parse_media_page(page.content(), link, username=username, final_url=final_url)
        except MalformedMediaPageError as exc:
            return link.kind, BrowserMedia.failed(link, username, str(exc))

        return data.kind, BrowserMedia(
            shortcode=link.shortcode,
            owner_username=username,
            caption=data.caption,
            date_utc=data.published_at,
            url=data.image_url,
            caption_hashtags=caption_hashtags(data.caption),
            caption_mentions=caption_mentions(data.caption),
            extra_metadata={
                "transport": "browser",
                "media_url": link.url,
                "final_url": _without_query(final_url),
                "caption_source": data.caption_source,
                "published_at_source": data.published_at_source,
            },
        )


__all__ = [
    "BROWSER_COLLECTOR_VERSION",
    "MAX_CANDIDATE_POOL",
    "RECENCY_CANDIDATE_BUFFER",
    "candidate_limit_for",
    "NOT_AUTHENTICATED_MESSAGE",
    "SESSION_EXPIRED_MESSAGE",
    "CHECKPOINT_MESSAGE",
    "BrowserLaunchError",
    "ChromeUnavailableError",
    "BrowserClosedError",
    "BrowserSessionNotAuthenticatedError",
    "BrowserSessionExpiredError",
    "InstagramCheckpointError",
    "NavigationTimeoutError",
    "InsufficientMediaError",
    "BrowserMedia",
    "BrowserMediaFetcher",
    "PlaywrightChromeLauncher",
    "authenticate_browser_profile",
    "browser_profile_path",
    "classify_instagram_location",
    "has_instagram_session_cookie",
    "open_authenticated_browser",
]
