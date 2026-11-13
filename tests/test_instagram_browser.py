import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from gatherradar.collectors.base import SourceAccessRestrictedError, SourceUnavailableError
from gatherradar.collectors.instagram import InstagramCollector, map_post_to_raw_item
from gatherradar.collectors.instagram_browser import (
    AUTH_COMMAND,
    BROWSER_COLLECTOR_VERSION,
    MAX_CANDIDATE_POOL,
    INSTAGRAM_HOME_URL,
    NOT_AUTHENTICATED_MESSAGE,
    BrowserClosedError,
    BrowserLaunchError,
    BrowserMedia,
    BrowserMediaFetcher,
    BrowserSessionExpiredError,
    BrowserSessionNotAuthenticatedError,
    ChromeUnavailableError,
    InstagramCheckpointError,
    InsufficientMediaError,
    NavigationTimeoutError,
    PlaywrightChromeLauncher,
    authenticate_browser_profile,
    browser_profile_path,
    candidate_limit_for,
    classify_instagram_location,
    has_instagram_session_cookie,
)
from gatherradar.collectors.instagram_dom import ORIGIN_POST
from gatherradar.domain import Source, SourceType, compute_content_hash
from gatherradar.orchestration.collection_run import run_instagram_collection

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "sources.yaml"
FIXTURES = Path(__file__).parent / "fixtures" / "instagram_browser"
CAPTURED_AT = datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc)
PROFILE_URL = "https://www.instagram.com/davvvat/"
SESSION_COOKIE = {"name": "sessionid", "value": "fake-session-value", "domain": ".instagram.com"}


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def media_url(shortcode: str, segment: str = "p") -> str:
    return f"https://www.instagram.com/{segment}/{shortcode}/"


def profile_page(*hrefs: str) -> str:
    links = "".join(f'<a href="{href}">media</a>' for href in hrefs)
    return f"<html><body><main>{links}</main></body></html>"


def media_page(
    shortcode: str,
    caption: str = "Event on Friday",
    published: str | None = "2026-09-09T14:30:00.000Z",
    segment: str = "p",
) -> str:
    timestamp = (
        f'<a href="/davvvat/{segment}/{shortcode}/"><time datetime="{published}"></time></a>'
        if published
        else ""
    )
    return (
        "<html><head>"
        f'<meta property="og:url" content="https://www.instagram.com/davvvat/{segment}/{shortcode}/">'
        f'<meta property="og:image" content="https://cdn.example.test/{shortcode}.jpg">'
        "</head><body><main><article>"
        f"<h1>{caption}</h1>{timestamp}"
        "</article></main></body></html>"
    )


def dated_profile(entries, caption_for=None) -> dict:
    """A profile grid in the given order; each entry is (shortcode, published or None)."""
    routes = {PROFILE_URL: profile_page(*[f"/davvvat/p/{code}/" for code, _ in entries])}
    for code, published in entries:
        caption = caption_for(code) if caption_for else f"Caption {code}"
        routes[media_url(code)] = media_page(code, caption, published=published)
    return routes


PINNED_GRID = [
    ("PINA", "2026-06-12T10:00:00.000Z"),
    ("PINB", "2026-08-10T10:00:00.000Z"),
    ("C", "2026-09-13T10:00:00.000Z"),
    ("D", "2026-09-12T10:00:00.000Z"),
    ("E", "2026-09-11T10:00:00.000Z"),
    ("F", "2026-09-10T10:00:00.000Z"),
    ("G", "2026-09-09T10:00:00.000Z"),
]


def fixture_routes() -> dict:
    return {
        PROFILE_URL: fixture("profile_davvvat.html"),
        media_url("POST1"): fixture("post_page.html"),
        media_url("REEL1", "reel"): fixture("reel_page_og_only.html"),
        media_url("POST2"): media_page("POST2", "Second post"),
        media_url("POST3"): media_page("POST3", "Third post", published="2026-09-01T10:00:00.000Z"),
    }


def make_source() -> Source:
    return Source(
        id="davvvat_instagram",
        publisher_key="davvvat",
        name="Davvvat Instagram",
        source_type=SourceType.INSTAGRAM,
        url=PROFILE_URL,
        username="davvvat",
    )


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class FakePage:
    """Stand-in for a Playwright Page. `routes` maps a final URL to its HTML, or to a list
    of HTML snapshots returned after successive scrolls."""

    def __init__(self, routes=None, *, redirects=None, timeouts=(), statuses=None) -> None:
        self.routes = {
            url: html if isinstance(html, list) else [html] for url, html in (routes or {}).items()
        }
        self.redirects = redirects or {}
        self.timeouts = set(timeouts)
        self.statuses = statuses or {}
        self.url = "about:blank"
        self.visited: list[str] = []
        self.scrolls = 0
        self._scrolls_at_load = 0
        self.pauses: list[int] = []

    def goto(self, url, *, wait_until=None, timeout=None):
        self.visited.append(url)
        if url in self.timeouts:
            raise PlaywrightTimeoutError(f"Timeout {timeout}ms exceeded.")
        self.url = self.redirects.get(url, url)
        self._scrolls_at_load = self.scrolls
        return FakeResponse(self.statuses.get(url, 200))

    def content(self) -> str:
        snapshots = self.routes.get(self.url, ["<html><body></body></html>"])
        return snapshots[min(self.scrolls - self._scrolls_at_load, len(snapshots) - 1)]

    def evaluate(self, script):
        self.scrolls += 1

    def wait_for_timeout(self, timeout) -> None:
        self.pauses.append(timeout)

    def wait_for_selector(self, selector, *, timeout=None):
        return None


class FakeContext:
    def __init__(self, cookies=()) -> None:
        self._cookies = list(cookies)
        self.cookie_requests: list = []

    def cookies(self, urls=None):
        self.cookie_requests.append(urls)
        return list(self._cookies)


class ExpiringContext(FakeContext):
    """Has a session cookie at launch that Instagram clears on the first page load."""

    def cookies(self, urls=None):
        self.cookie_requests.append(urls)
        return [SESSION_COOKIE] if len(self.cookie_requests) == 1 else []


class ClosedWindowContext(FakeContext):
    def cookies(self, urls=None):
        raise PlaywrightError("Target page, context or browser has been closed")


class FakeBrowser:
    def __init__(self, page: FakePage, context: FakeContext) -> None:
        self.page = page
        self.context = context
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeLauncher:
    def __init__(self, browser: FakeBrowser | None = None, error: Exception | None = None) -> None:
        self.browser = browser
        self.error = error
        self.profile_dirs: list[Path] = []

    def __call__(self, profile_dir: Path) -> FakeBrowser:
        self.profile_dirs.append(profile_dir)
        if self.error is not None:
            raise self.error
        return self.browser


class BrowserTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = Path(self._tmp.name)

    def authenticate_profile(self) -> Path:
        profile = browser_profile_path(self.data_dir)
        (profile / "Default").mkdir(parents=True, exist_ok=True)
        (profile / "Default" / "Preferences").write_text("{}", encoding="utf-8")
        return profile

    def browser_for(self, routes, *, cookies=(SESSION_COOKIE,), context=None, **page_options) -> FakeBrowser:
        return FakeBrowser(FakePage(routes, **page_options), context or FakeContext(cookies))

    def fetcher_for(self, browser: FakeBrowser, **options) -> tuple[BrowserMediaFetcher, FakeLauncher]:
        self.authenticate_profile()
        launcher = FakeLauncher(browser)
        options.setdefault("scroll_pause_ms", 0)
        options.setdefault("page_pause_ms", 0)
        return BrowserMediaFetcher(data_dir=self.data_dir, launcher=launcher, **options), launcher

    def collect(self, browser: FakeBrowser, *, limit: int = 5, **options):
        fetcher, _ = self.fetcher_for(browser, **options)
        return InstagramCollector(fetch_posts=fetcher, now=lambda: CAPTURED_AT).collect(
            make_source(), limit=limit
        )


class PlaywrightLauncherWiringTests(unittest.TestCase):
    def fake_playwright(self, *, existing_page=True, launch_error=None):
        context = mock.MagicMock()
        context.pages = [mock.sentinel.existing_page] if existing_page else []
        context.new_page.return_value = mock.sentinel.new_page
        playwright = mock.MagicMock()
        if launch_error is not None:
            playwright.chromium.launch_persistent_context.side_effect = launch_error
        else:
            playwright.chromium.launch_persistent_context.return_value = context
        return playwright, context

    def test_launches_installed_chrome_visibly_on_the_persistent_profile(self) -> None:
        playwright, context = self.fake_playwright()
        profile = Path("data") / "browser" / "instagram-profile"

        browser = PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(profile)

        playwright.chromium.launch_persistent_context.assert_called_once_with(
            str(profile), channel="chrome", headless=False, timeout=30_000
        )
        self.assertIs(browser.page, mock.sentinel.existing_page)
        browser.close()
        context.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()

    def test_opens_a_page_when_chrome_starts_without_one(self) -> None:
        playwright, _ = self.fake_playwright(existing_page=False)
        browser = PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(Path("profile"))
        self.assertIs(browser.page, mock.sentinel.new_page)

    def test_missing_chrome_is_reported_without_playwright_call_log(self) -> None:
        error = PlaywrightError(
            "BrowserType.launch_persistent_context: Chromium distribution 'chrome' is not found at "
            "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe\nCall log:\n  - details"
        )
        playwright, _ = self.fake_playwright(launch_error=error)

        with self.assertRaises(ChromeUnavailableError) as ctx:
            PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(Path("profile"))

        self.assertNotIn("Call log", str(ctx.exception))
        playwright.stop.assert_called_once_with()

    def test_profile_already_in_use_is_reported_clearly(self) -> None:
        error = PlaywrightError("Failed to create a ProcessSingleton for your profile directory.")
        playwright, _ = self.fake_playwright(launch_error=error)

        with self.assertRaises(BrowserLaunchError) as ctx:
            PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(Path("profile"))

        self.assertNotIsInstance(ctx.exception, ChromeUnavailableError)
        self.assertIn("already in use", str(ctx.exception))

    def test_other_launch_failures_keep_only_the_first_line(self) -> None:
        playwright, _ = self.fake_playwright(launch_error=PlaywrightError("spawn failed\nCall log:\n  - x"))

        with self.assertRaises(BrowserLaunchError) as ctx:
            PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(Path("profile"))

        self.assertEqual(str(ctx.exception), "Playwright could not launch Chrome: spawn failed")

    def test_close_still_stops_playwright_when_the_window_was_already_closed(self) -> None:
        playwright, context = self.fake_playwright()
        context.close.side_effect = PlaywrightError("Target page, context or browser has been closed")
        browser = PlaywrightChromeLauncher(playwright_factory=lambda: playwright)(Path("profile"))

        browser.close()

        playwright.stop.assert_called_once_with()

    def test_default_launcher_is_visible_installed_chrome(self) -> None:
        launcher = PlaywrightChromeLauncher()
        self.assertFalse(launcher.headless)
        self.assertEqual(launcher.channel, "chrome")


class FetcherWiringTests(BrowserTestCase):
    def test_default_collector_uses_the_browser_fetcher_on_the_data_dir_profile(self) -> None:
        collector = InstagramCollector(data_dir=self.data_dir)

        self.assertIsInstance(collector._fetch_posts, BrowserMediaFetcher)
        self.assertEqual(collector._fetch_posts.profile_dir, browser_profile_path(self.data_dir))

    def test_constructing_the_default_collector_does_not_start_a_browser(self) -> None:
        with mock.patch("playwright.sync_api.sync_playwright", side_effect=AssertionError("started")):
            InstagramCollector(data_dir=self.data_dir)

    def test_fetcher_launches_the_resolved_persistent_profile(self) -> None:
        browser = self.browser_for(fixture_routes())
        fetcher, launcher = self.fetcher_for(browser)

        list(fetcher("davvvat", 1))

        self.assertEqual(launcher.profile_dirs, [browser_profile_path(self.data_dir).resolve()])


class ProfilePathTests(unittest.TestCase):
    def test_default_profile_lives_under_local_runtime_data(self) -> None:
        self.assertEqual(browser_profile_path(), Path("data") / "browser" / "instagram-profile")

    def test_profile_follows_the_data_dir(self) -> None:
        self.assertEqual(
            browser_profile_path("custom-data"), Path("custom-data") / "browser" / "instagram-profile"
        )


class BrowserAuthenticationTests(BrowserTestCase):
    def authenticate(self, browser: FakeBrowser, wait_for_user=lambda: None) -> Path:
        return authenticate_browser_profile(
            data_dir=self.data_dir, wait_for_user=wait_for_user, launcher=FakeLauncher(browser)
        )

    def test_successful_manual_login_is_verified_and_the_browser_closed(self) -> None:
        browser = self.browser_for({})
        launcher = FakeLauncher(browser)
        closes_while_waiting: list[int] = []

        path = authenticate_browser_profile(
            data_dir=self.data_dir,
            wait_for_user=lambda: closes_while_waiting.append(browser.close_calls),
            launcher=launcher,
        )

        self.assertEqual(path, browser_profile_path(self.data_dir))
        self.assertTrue(path.is_dir())
        self.assertEqual(launcher.profile_dirs, [path.resolve()])
        self.assertEqual(browser.page.visited, [INSTAGRAM_HOME_URL])
        self.assertEqual(closes_while_waiting, [0])
        self.assertEqual(browser.close_calls, 1)

    def test_window_still_on_the_login_page_is_not_authenticated(self) -> None:
        browser = self.browser_for({}, cookies=())

        def wait() -> None:
            browser.page.url = "https://www.instagram.com/accounts/login/?next=%2F"

        with self.assertRaises(BrowserSessionNotAuthenticatedError) as ctx:
            self.authenticate(browser, wait)

        self.assertIn(AUTH_COMMAND, str(ctx.exception))
        self.assertEqual(browser.close_calls, 1)

    def test_missing_session_cookie_is_not_authenticated(self) -> None:
        browser = self.browser_for({}, cookies=())
        with self.assertRaises(BrowserSessionNotAuthenticatedError):
            self.authenticate(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_checkpoint_page_is_reported_for_manual_completion(self) -> None:
        browser = self.browser_for({}, redirects={INSTAGRAM_HOME_URL: "https://www.instagram.com/challenge/AbC/"})
        with self.assertRaises(InstagramCheckpointError):
            self.authenticate(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_window_closed_before_verification_is_reported(self) -> None:
        browser = self.browser_for({}, context=ClosedWindowContext())
        with self.assertRaises(BrowserClosedError):
            self.authenticate(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_cancelled_confirmation_still_closes_the_browser(self) -> None:
        browser = self.browser_for({})

        def cancel() -> None:
            raise KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            self.authenticate(browser, cancel)
        self.assertEqual(browser.close_calls, 1)

    def test_slow_first_load_does_not_abort_manual_login(self) -> None:
        browser = self.browser_for({}, timeouts={INSTAGRAM_HOME_URL})
        self.assertEqual(self.authenticate(browser), browser_profile_path(self.data_dir))

    def test_session_cookie_requires_a_non_empty_value(self) -> None:
        self.assertTrue(has_instagram_session_cookie(FakeContext([SESSION_COOKIE])))
        self.assertFalse(has_instagram_session_cookie(FakeContext([{"name": "sessionid", "value": ""}])))
        self.assertFalse(has_instagram_session_cookie(FakeContext([{"name": "csrftoken", "value": "x"}])))

    def test_instagram_locations_are_classified_by_path_segment(self) -> None:
        cases = {
            "https://www.instagram.com/accounts/login/?next=/": "login",
            "https://www.instagram.com/challenge/AbC/": "checkpoint",
            "https://www.instagram.com/checkpoint/": "checkpoint",
            "https://www.instagram.com/accounts/suspended/": "checkpoint",
            "https://www.instagram.com/challenge_accepted/": "other",
            "https://www.instagram.com/": "other",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(classify_instagram_location(url), expected)


class MissingAuthenticationTests(BrowserTestCase):
    def test_missing_profile_fails_before_launching_chrome(self) -> None:
        launcher = FakeLauncher(self.browser_for(fixture_routes()))
        fetcher = BrowserMediaFetcher(data_dir=self.data_dir, launcher=launcher)

        with self.assertRaises(BrowserSessionNotAuthenticatedError) as ctx:
            InstagramCollector(fetch_posts=fetcher).collect(make_source(), limit=5)

        self.assertEqual(str(ctx.exception), NOT_AUTHENTICATED_MESSAGE)
        self.assertEqual(launcher.profile_dirs, [])

    def test_empty_profile_directory_is_not_authenticated(self) -> None:
        browser_profile_path(self.data_dir).mkdir(parents=True)
        launcher = FakeLauncher(self.browser_for(fixture_routes()))
        fetcher = BrowserMediaFetcher(data_dir=self.data_dir, launcher=launcher)

        with self.assertRaises(BrowserSessionNotAuthenticatedError):
            list(fetcher("davvvat", 5))
        self.assertEqual(launcher.profile_dirs, [])

    def test_not_authenticated_message_names_the_auth_command(self) -> None:
        self.assertEqual(
            NOT_AUTHENTICATED_MESSAGE,
            "Instagram browser session is not authenticated.\nRun:\n\npython -m gatherradar auth instagram",
        )


class ExpiredSessionTests(BrowserTestCase):
    def test_profile_without_session_cookie_is_not_authenticated_and_closed(self) -> None:
        browser = self.browser_for(fixture_routes(), cookies=())

        with self.assertRaises(BrowserSessionNotAuthenticatedError):
            self.collect(browser)

        self.assertEqual(browser.page.visited, [])
        self.assertEqual(browser.close_calls, 1)

    def test_redirect_to_login_reports_expired_session(self) -> None:
        browser = self.browser_for(
            fixture_routes(),
            redirects={PROFILE_URL: "https://www.instagram.com/accounts/login/?next=%2Fdavvvat%2F"},
        )

        with self.assertRaises(BrowserSessionExpiredError) as ctx:
            self.collect(browser)

        self.assertIn(AUTH_COMMAND, str(ctx.exception))
        self.assertEqual(browser.close_calls, 1)

    def test_session_cookie_cleared_by_instagram_reports_expired_session(self) -> None:
        browser = self.browser_for(fixture_routes(), context=ExpiringContext())
        with self.assertRaises(BrowserSessionExpiredError):
            self.collect(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_login_redirect_on_a_media_page_stops_the_run(self) -> None:
        browser = self.browser_for(
            fixture_routes(),
            redirects={media_url("POST1"): "https://www.instagram.com/accounts/login/"},
        )
        with self.assertRaises(BrowserSessionExpiredError):
            self.collect(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_checkpoint_on_the_profile_page_is_reported(self) -> None:
        browser = self.browser_for(
            fixture_routes(), redirects={PROFILE_URL: "https://www.instagram.com/challenge/?next=/davvvat/"}
        )
        with self.assertRaises(InstagramCheckpointError):
            self.collect(browser)
        self.assertEqual(browser.close_calls, 1)


class DiscoveryTests(BrowserTestCase):
    def test_post_and_reel_urls_are_discovered_and_opened_in_page_order(self) -> None:
        browser = self.browser_for(fixture_routes())

        result = self.collect(browser)

        self.assertEqual(
            browser.page.visited,
            [PROFILE_URL, media_url("POST1"), media_url("REEL1", "reel"), media_url("POST2"), media_url("POST3")],
        )
        self.assertEqual({item.external_id for item in result.items}, {"POST1", "REEL1", "POST2", "POST3"})
        self.assertEqual(result.failures, ())

    def test_reels_are_classified_from_their_url_and_posts_stay_unknown(self) -> None:
        result = self.collect(self.browser_for(fixture_routes()))
        types = {item.external_id: item.content_type for item in result.items}

        self.assertEqual(types["REEL1"], "reel")
        self.assertEqual(types["POST1"], "unknown")

    def test_same_media_linked_as_post_and_reel_is_collected_once_as_a_reel(self) -> None:
        routes = {
            PROFILE_URL: profile_page("/davvvat/p/DUP/", "/davvvat/reel/DUP/"),
            media_url("DUP", "reel"): media_page("DUP", segment="reel"),
        }
        browser = self.browser_for(routes)

        result = self.collect(browser)

        self.assertEqual([item.external_id for item in result.items], ["DUP"])
        self.assertEqual(result.items[0].content_type, "reel")
        self.assertEqual(browser.page.visited, [PROFILE_URL, media_url("DUP", "reel")])

    def test_media_pages_opened_are_bounded_by_the_candidate_pool(self) -> None:
        # Previously exactly `limit` pages (the first grid positions) were opened; a small
        # recency buffer is now opened so pinned posts cannot take recent slots.
        codes = [f"S{index}" for index in range(1, 7)]
        routes = {PROFILE_URL: profile_page(*[f"/davvvat/p/{code}/" for code in codes])}
        routes.update({media_url(code): media_page(code) for code in codes})
        browser = self.browser_for(routes)

        result = self.collect(browser, limit=2)

        self.assertEqual(result.observed, 2)
        self.assertEqual(browser.page.visited, [PROFILE_URL] + [media_url(code) for code in codes[:5]])
        self.assertEqual(browser.page.scrolls, 0)


class ScrollingTests(BrowserTestCase):
    def growing_profile(self, counts: list[int]) -> dict:
        snapshots = [profile_page(*[f"/davvvat/p/S{index}/" for index in range(1, count + 1)]) for count in counts]
        routes = {PROFILE_URL: snapshots}
        routes.update({media_url(f"S{index}"): media_page(f"S{index}") for index in range(1, max(counts) + 1)})
        return routes

    def test_scrolling_is_bounded_by_max_scroll_attempts(self) -> None:
        browser = self.browser_for(self.growing_profile([1, 2, 3, 4, 5, 6, 7]))

        result = self.collect(browser, limit=10, max_scroll_attempts=3)

        self.assertEqual(browser.page.scrolls, 3)
        self.assertEqual(result.observed, 4)

    def test_scrolling_stops_once_enough_media_is_visible(self) -> None:
        browser = self.browser_for(self.growing_profile([1, 3, 6]))

        result = self.collect(browser, limit=2)

        # Scrolling now continues until the candidate pool (5 for limit 2) is visible,
        # not just `limit` items: 1 -> 3 -> 6 visible links takes two scrolls.
        self.assertEqual(browser.page.scrolls, 2)
        self.assertEqual(result.observed, 2)

    def test_scrolling_stops_when_a_scroll_reveals_nothing_new(self) -> None:
        browser = self.browser_for(self.growing_profile([1, 1, 2]))

        result = self.collect(browser, limit=5)

        self.assertEqual(browser.page.scrolls, 1)
        self.assertEqual(result.observed, 1)

    def test_no_scrolling_when_the_first_screen_is_enough(self) -> None:
        # The fixture grid has 4 links: exactly the candidate pool for limit 1 (was limit 2
        # when only `limit` links had to be visible).
        browser = self.browser_for(fixture_routes())
        self.collect(browser, limit=1)
        self.assertEqual(browser.page.scrolls, 0)


class ExtractionThroughCollectorTests(BrowserTestCase):
    def item(self, shortcode: str):
        result = self.collect(self.browser_for(fixture_routes()))
        return next(item for item in result.items if item.external_id == shortcode)

    def test_caption_is_extracted_verbatim(self) -> None:
        self.assertEqual(
            self.item("POST1").raw_text, "کارگاه طراحی شهری\nجمعه ساعت ۱۷ #رویداد با @venue.tehran"
        )

    def test_published_at_is_extracted_as_utc(self) -> None:
        self.assertEqual(
            self.item("POST1").published_at, datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)
        )

    def test_missing_publish_time_stays_null(self) -> None:
        self.assertIsNone(self.item("REEL1").published_at)

    def test_caption_hashtags_and_mentions_are_kept_in_metadata(self) -> None:
        metadata = self.item("POST1").raw_metadata
        self.assertEqual(metadata["hashtags"], ["رویداد"])
        self.assertEqual(metadata["mentions"], ["venue.tehran"])

    def test_source_username_remains_the_target_account(self) -> None:
        item = self.item("POST1")

        self.assertEqual(item.id, "instagram:davvvat:POST1")
        self.assertEqual(item.author, "davvvat")
        self.assertEqual(item.source_id, "davvvat_instagram")

    def test_raw_item_mapping_stays_compatible(self) -> None:
        reel = self.item("REEL1")

        self.assertEqual(reel.content_url, "https://www.instagram.com/p/REEL1/")
        self.assertEqual(reel.image_url, "https://cdn.example.test/reel1-thumb.jpg")
        self.assertEqual(
            reel.content_hash,
            compute_content_hash(
                raw_text=reel.raw_text, published_at=reel.published_at, content_url=reel.content_url
            ),
        )
        self.assertEqual(reel.raw_metadata["collector_version"], BROWSER_COLLECTOR_VERSION)
        self.assertEqual(reel.raw_metadata["transport"], "browser")
        self.assertEqual(reel.raw_metadata["media_url"], "https://www.instagram.com/reel/REEL1/")
        self.assertEqual(reel.raw_metadata["caption_source"], "og:description")
        self.assertIsNone(reel.raw_metadata["typename"])

    def test_transport_metadata_cannot_override_core_metadata(self) -> None:
        media = BrowserMedia(
            shortcode="A1", owner_username="davvvat", extra_metadata={"origin": "spoofed", "transport": "browser"}
        )
        item = map_post_to_raw_item(media, make_source(), CAPTURED_AT, origin=ORIGIN_POST)

        self.assertEqual(item.raw_metadata["origin"], ORIGIN_POST)
        self.assertEqual(item.raw_metadata["transport"], "browser")


class ProfileAndMediaFailureTests(BrowserTestCase):
    def test_private_profile_is_refused(self) -> None:
        browser = self.browser_for({PROFILE_URL: fixture("private_profile.html")})

        with self.assertRaises(SourceAccessRestrictedError) as ctx:
            self.collect(browser)

        self.assertIn("private", str(ctx.exception))
        self.assertEqual(browser.page.visited, [PROFILE_URL])
        self.assertEqual(browser.close_calls, 1)

    def test_unavailable_profile_is_reported(self) -> None:
        browser = self.browser_for({PROFILE_URL: fixture("unavailable_profile.html")})

        with self.assertRaises(SourceUnavailableError) as ctx:
            self.collect(browser)

        self.assertNotIsInstance(ctx.exception, InsufficientMediaError)
        self.assertEqual(browser.close_calls, 1)

    def test_not_found_status_is_reported_as_unavailable(self) -> None:
        browser = self.browser_for({PROFILE_URL: profile_page()}, statuses={PROFILE_URL: 404})
        with self.assertRaises(SourceUnavailableError) as ctx:
            self.collect(browser)
        self.assertNotIsInstance(ctx.exception, InsufficientMediaError)

    def test_profile_without_media_reports_insufficient_media(self) -> None:
        browser = self.browser_for({PROFILE_URL: profile_page()})
        with self.assertRaises(InsufficientMediaError):
            self.collect(browser, max_scroll_attempts=2)
        self.assertLessEqual(browser.page.scrolls, 2)

    def test_profile_navigation_timeout_is_reported(self) -> None:
        browser = self.browser_for(fixture_routes(), timeouts={PROFILE_URL})
        with self.assertRaises(NavigationTimeoutError):
            self.collect(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_media_page_timeout_fails_only_that_item(self) -> None:
        browser = self.browser_for(fixture_routes(), timeouts={media_url("POST2")})

        result = self.collect(browser)

        self.assertEqual({item.external_id for item in result.items}, {"POST1", "REEL1", "POST3"})
        self.assertEqual([failure.external_id for failure in result.failures], ["POST2"])
        self.assertIn("Timed out", result.failures[0].reason)
        self.assertEqual(browser.close_calls, 1)

    def test_malformed_media_page_fails_only_that_item(self) -> None:
        routes = fixture_routes()
        routes[media_url("POST2")] = fixture("malformed_media_page.html")

        result = self.collect(self.browser_for(routes))

        self.assertEqual(len(result.items), 3)
        self.assertEqual([failure.external_id for failure in result.failures], ["POST2"])
        self.assertIn("no recognizable caption", result.failures[0].reason)


class NewChangedExistingTests(BrowserTestCase):
    def run_once(self, caption: str):
        routes = {
            PROFILE_URL: profile_page("/davvvat/p/A1/", "/davvvat/reel/R1/"),
            media_url("A1"): media_page("A1", caption),
            media_url("R1", "reel"): media_page("R1", "Reel caption", segment="reel"),
        }
        fetcher, _ = self.fetcher_for(self.browser_for(routes))
        return run_instagram_collection(
            "davvvat_instagram",
            config_path=CONFIG,
            data_dir=self.data_dir,
            limit=5,
            collector=InstagramCollector(fetch_posts=fetcher, now=lambda: CAPTURED_AT),
        )

    def test_new_existing_and_changed_behavior_is_preserved(self) -> None:
        first = self.run_once("Event Friday 17:00")
        self.assertEqual((first.new, first.changed, first.already_existing), (2, 0, 0))

        second = self.run_once("Event Friday 17:00")
        self.assertEqual((second.new, second.changed, second.already_existing), (0, 0, 2))

        third = self.run_once("Event cancelled")
        self.assertEqual((third.new, third.changed, third.already_existing), (0, 1, 1))
        self.assertEqual(len(third.output_path.read_text(encoding="utf-8").splitlines()), 3)


class BrowserClosingTests(BrowserTestCase):
    def test_browser_closes_once_after_successful_collection(self) -> None:
        browser = self.browser_for(fixture_routes())
        self.collect(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_browser_closes_after_a_failure_mid_run(self) -> None:
        browser = self.browser_for(
            fixture_routes(), redirects={media_url("POST2"): "https://www.instagram.com/challenge/"}
        )
        with self.assertRaises(InstagramCheckpointError):
            self.collect(browser)
        self.assertEqual(browser.close_calls, 1)

    def test_browser_closes_when_the_consumer_stops_early(self) -> None:
        browser = self.browser_for(fixture_routes())
        fetcher, _ = self.fetcher_for(browser)

        media = fetcher("davvvat", 5)
        next(media)
        media.close()

        self.assertEqual(browser.close_calls, 1)


class CandidatePoolTests(BrowserTestCase):
    def test_candidate_pool_adds_a_small_recency_buffer_with_a_hard_cap(self) -> None:
        self.assertEqual(MAX_CANDIDATE_POOL, 12)
        for limit, expected in {1: 4, 5: 8, 9: 12, 10: 12, 12: 12, 20: 20}.items():
            with self.subTest(limit=limit):
                self.assertEqual(candidate_limit_for(limit), expected)

    def test_fetcher_opens_more_candidates_than_the_final_limit(self) -> None:
        codes = [f"S{index}" for index in range(1, 11)]
        browser = self.browser_for(dated_profile([(code, "2026-09-01T10:00:00.000Z") for code in codes]))
        fetcher, _ = self.fetcher_for(browser)

        media = list(fetcher("davvvat", 5))

        self.assertEqual(len(media), 8)
        self.assertEqual(browser.page.visited, [PROFILE_URL] + [media_url(code) for code in codes[:8]])

    def test_candidate_pool_is_strictly_bounded(self) -> None:
        codes = [f"S{index}" for index in range(1, 31)]
        browser = self.browser_for(dated_profile([(code, "2026-09-01T10:00:00.000Z") for code in codes]))
        fetcher, _ = self.fetcher_for(browser)

        media = list(fetcher("davvvat", 10))

        self.assertEqual(len(media), MAX_CANDIDATE_POOL)
        self.assertEqual(len(browser.page.visited), 1 + MAX_CANDIDATE_POOL)

    def test_scroll_hard_limit_still_applies_to_the_candidate_pool(self) -> None:
        snapshots = [profile_page(*[f"/davvvat/p/S{index}/" for index in range(1, count + 1)]) for count in range(1, 11)]
        routes = {PROFILE_URL: snapshots}
        routes.update({media_url(f"S{index}"): media_page(f"S{index}") for index in range(1, 11)})
        browser = self.browser_for(routes)

        result = self.collect(browser, limit=5, max_scroll_attempts=2)

        self.assertEqual(browser.page.scrolls, 2)
        self.assertEqual(result.observed, 3)


class RecencySelectionTests(BrowserTestCase):
    def test_old_pinned_posts_do_not_displace_newer_media(self) -> None:
        result = self.collect(self.browser_for(dated_profile(PINNED_GRID)), limit=5)
        self.assertEqual([item.external_id for item in result.items], ["C", "D", "E", "F", "G"])

    def test_final_items_are_sorted_newest_first(self) -> None:
        result = self.collect(self.browser_for(dated_profile(PINNED_GRID)), limit=5)
        published = [item.published_at for item in result.items]

        self.assertEqual(published, sorted(published, reverse=True))
        self.assertEqual(published[0], datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc))

    def test_items_without_a_publish_date_sort_after_dated_items(self) -> None:
        entries = [("NODATE", None), ("OLDER", "2026-09-01T10:00:00.000Z"), ("NEWER", "2026-09-05T10:00:00.000Z")]

        result = self.collect(self.browser_for(dated_profile(entries)), limit=3)

        self.assertEqual([item.external_id for item in result.items], ["NEWER", "OLDER", "NODATE"])
        self.assertIsNone(result.items[-1].published_at)

    def test_undated_items_are_dropped_first_when_bounding(self) -> None:
        entries = [("NODATE", None), ("OLDER", "2026-09-01T10:00:00.000Z"), ("NEWER", "2026-09-05T10:00:00.000Z")]
        result = self.collect(self.browser_for(dated_profile(entries)), limit=2)
        self.assertEqual([item.external_id for item in result.items], ["NEWER", "OLDER"])

    def test_equal_publish_dates_keep_grid_order(self) -> None:
        same = "2026-09-01T10:00:00.000Z"
        result = self.collect(self.browser_for(dated_profile([("FIRST", same), ("SECOND", same), ("THIRD", same)])), limit=3)
        self.assertEqual([item.external_id for item in result.items], ["FIRST", "SECOND", "THIRD"])

    def test_same_shortcode_is_still_collected_once_as_a_reel(self) -> None:
        routes = {
            PROFILE_URL: profile_page("/davvvat/p/DUP/", "/davvvat/p/OTHER/", "/davvvat/reel/DUP/"),
            media_url("DUP", "reel"): media_page("DUP", segment="reel", published="2026-09-02T10:00:00.000Z"),
            media_url("OTHER"): media_page("OTHER", published="2026-09-01T10:00:00.000Z"),
        }
        browser = self.browser_for(routes)

        result = self.collect(browser, limit=5)

        self.assertEqual([item.external_id for item in result.items], ["DUP", "OTHER"])
        self.assertEqual(result.items[0].content_type, "reel")
        self.assertEqual(browser.page.visited.count(media_url("DUP", "reel")), 1)
        self.assertNotIn(media_url("DUP"), browser.page.visited)

    def test_final_count_never_exceeds_the_requested_limit(self) -> None:
        entries = [(f"S{index}", f"2026-09-{index:02d}T10:00:00.000Z") for index in range(1, 13)]
        for limit in (1, 3, 5):
            with self.subTest(limit=limit):
                result = self.collect(self.browser_for(dated_profile(entries)), limit=limit)
                self.assertEqual(len(result.items), limit)
                self.assertLessEqual(result.observed, limit)


class RecencyStorageTests(BrowserTestCase):
    def run_once(self, caption_for):
        fetcher, _ = self.fetcher_for(self.browser_for(dated_profile(PINNED_GRID, caption_for)))
        return run_instagram_collection(
            "davvvat_instagram",
            config_path=CONFIG,
            data_dir=self.data_dir,
            limit=5,
            collector=InstagramCollector(fetch_posts=fetcher, now=lambda: CAPTURED_AT),
        )

    def test_new_and_existing_behavior_is_unchanged_with_the_candidate_pool(self) -> None:
        first = self.run_once(lambda code: f"Caption {code}")
        self.assertEqual((first.observed, first.new, first.changed, first.already_existing), (5, 5, 0, 0))

        second = self.run_once(lambda code: f"Caption {code}")
        self.assertEqual((second.observed, second.new, second.changed, second.already_existing), (5, 0, 0, 5))

    def test_captions_found_after_empty_observations_are_changed_then_existing(self) -> None:
        first = self.run_once(lambda code: "")
        self.assertEqual((first.new, first.changed, first.already_existing), (5, 0, 0))

        second = self.run_once(lambda code: f"Caption {code}")
        self.assertEqual((second.new, second.changed, second.already_existing), (0, 5, 0))

        third = self.run_once(lambda code: f"Caption {code}")
        self.assertEqual((third.new, third.changed, third.already_existing), (0, 0, 5))
        self.assertEqual(len(third.output_path.read_text(encoding="utf-8").splitlines()), 10)


class CaptionThroughCollectorTests(BrowserTestCase):
    def test_author_caption_is_collected_without_comments(self) -> None:
        routes = {
            PROFILE_URL: profile_page("/davvvat/p/LIST1/"),
            media_url("LIST1"): fixture("caption_author_list.html"),
        }

        item = self.collect(self.browser_for(routes), limit=1).items[0]

        self.assertEqual(
            item.raw_text, "جمعه ۲۱ شهریور دورهمی دعوت داریم 🎉\nبرای ثبت نام به @venue پیام بدید\n#رویداد #تهران"
        )
        self.assertEqual(item.raw_metadata["caption_source"], "main:author-block")
        self.assertEqual(item.raw_metadata["hashtags"], ["رویداد", "تهران"])
        self.assertEqual(item.raw_metadata["mentions"], ["venue"])
        self.assertNotIn("commenter.one", item.raw_text)


class NoInstaloaderFallbackTests(BrowserTestCase):
    def test_browser_launch_failure_is_raised_without_trying_instaloader(self) -> None:
        self.authenticate_profile()
        launcher = FakeLauncher(error=ChromeUnavailableError("Google Chrome was not found."))
        fetcher = BrowserMediaFetcher(data_dir=self.data_dir, launcher=launcher)

        with (
            mock.patch("instaloader.Profile.from_username") as from_username,
            mock.patch(
                "gatherradar.collectors.instagram_instaloader.load_active_authenticated_loader"
            ) as load_session,
        ):
            with self.assertRaises(ChromeUnavailableError):
                InstagramCollector(fetch_posts=fetcher).collect(make_source(), limit=5)

        from_username.assert_not_called()
        load_session.assert_not_called()

    def test_default_collection_path_needs_the_browser_session_not_instaloader(self) -> None:
        with (
            mock.patch("instaloader.Profile.from_username") as from_username,
            mock.patch("playwright.sync_api.sync_playwright", side_effect=AssertionError("started")),
        ):
            with self.assertRaises(BrowserSessionNotAuthenticatedError):
                run_instagram_collection("davvvat_instagram", config_path=CONFIG, data_dir=self.data_dir)

        from_username.assert_not_called()


class NoLiveInstagramCallTests(BrowserTestCase):
    def test_full_collection_runs_without_a_real_browser_or_network(self) -> None:
        with (
            mock.patch("playwright.sync_api.sync_playwright", side_effect=AssertionError("real browser")),
            mock.patch("socket.socket.connect", side_effect=AssertionError("network used")),
        ):
            result = self.collect(self.browser_for(fixture_routes()))

        self.assertEqual(result.observed, 4)


if __name__ == "__main__":
    unittest.main()
