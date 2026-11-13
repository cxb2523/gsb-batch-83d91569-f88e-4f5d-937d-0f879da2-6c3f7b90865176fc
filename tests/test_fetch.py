from __future__ import annotations

import pytest
import requests

from ehentai_crawler.errors import (
    AccessDeniedError,
    BannedError,
    FetchError,
    GalleryUnavailableError,
    SettingsError,
    TransientError,
)
from ehentai_crawler.fetch import (
    BrowserTransport,
    Fetcher,
    HostRateLimiter,
    HttpTransport,
    Page,
    check_page,
    open_fetcher,
)
from ehentai_crawler.settings import Settings

from .fake_site import image_bytes, render


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_rate_limiter_spaces_requests_per_host():
    clock = FakeClock()
    limiter = HostRateLimiter(2.0, jitter=1.0, clock=clock, sleep=clock.sleep, rng=lambda: 0.5)

    limiter.wait("https://a.test/1")  # first request to a host goes right away
    limiter.wait("https://b.test/1")  # other hosts are independent
    limiter.wait("https://a.test/2")
    limiter.wait("https://a.test/3")

    assert clock.slept == [3.0, 3.0]  # 2 s plus half of the 100 % jitter, each time


def test_rate_limiter_disabled_with_zero_delay():
    clock = FakeClock()
    limiter = HostRateLimiter(0, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        limiter.wait("https://a.test/")
    assert clock.slept == []


@pytest.mark.parametrize(
    ("page", "error", "message"),
    [
        (Page("u", 200, render("banned.html", EXPIRES="10 minutes")), BannedError, "about 10 min"),
        (Page("u", 503, "busy"), TransientError, "HTTP 503"),
        (Page("u", 200, "<p>Error 503 Service Unavailable</p>"), TransientError, "503"),
        (Page("u", 429, "slow down"), TransientError, "HTTP 429"),
        (Page("u", 404, "<p>Gallery not found.</p>"), GalleryUnavailableError, "removed"),
        (Page("u", 200, render("removed.html")), GalleryUnavailableError, "removed"),
        (Page("u", 403, "<p>no</p>"), FetchError, "HTTP 403"),
        (Page("u", 200, "", "text/html"), AccessDeniedError, "cookies"),
        (Page("u", 200, "GIF89a", "image/gif"), AccessDeniedError, "cookies"),
    ],
)
def test_check_page_recognises_error_pages(page, error, message):
    with pytest.raises(error, match=message):
        check_page(page)


def test_check_page_passes_normal_pages():
    assert check_page(Page("u", 200, "<html>ok</html>", "text/html; charset=UTF-8")) == "<html>ok</html>"
    assert check_page(Page("u", None, "<html>ok</html>")) == "<html>ok</html>"  # browser: no status


def test_banned_error_carries_the_wait():
    with pytest.raises(BannedError) as caught:
        check_page(Page("u", 200, render("banned.html", EXPIRES="1 hours and 5 minutes")))
    assert caught.value.expires_in == 3900


class ScriptedTransport:
    """Answers with the given pages or exceptions, in order."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def close(self):
        pass


def test_fetcher_retries_with_exponential_backoff():
    slept = []
    pages = ScriptedTransport(TransientError("timeout"), Page("u", 503, "busy"), Page("u", 200, "<p>ok</p>"))
    fetcher = Fetcher(pages, None, max_retries=3, sleep=slept.append, backoff_base=5)
    assert fetcher.page("u") == "<p>ok</p>"
    assert slept == [5, 10]


def test_fetcher_gives_up_with_a_clear_message():
    pages = ScriptedTransport(*[Page("u", 503, "busy")] * 3)
    fetcher = Fetcher(pages, None, max_retries=2, sleep=lambda _: None)
    with pytest.raises(FetchError, match=r"gave up on u after 3 attempts \(u: HTTP 503\)"):
        fetcher.page("u")


def test_fetcher_caps_the_backoff():
    slept = []
    pages = ScriptedTransport(*[Page("u", 503, "busy")] * 4, Page("u", 200, "<p>ok</p>"))
    Fetcher(pages, None, max_retries=4, sleep=slept.append, backoff_base=100, backoff_cap=250).page("u")
    assert slept == [100, 200, 250, 250]


def test_fetcher_does_not_retry_permanent_errors():
    pages = ScriptedTransport(Page("u", 404, "Gallery not found"))
    with pytest.raises(GalleryUnavailableError):
        Fetcher(pages, None, max_retries=5, sleep=lambda _: None).page("u")
    assert pages.calls == 1


def cookie_header(transport: HttpTransport, url: str) -> str:
    session = transport._sessions.get()
    return session.prepare_request(requests.Request("GET", url)).headers.get("Cookie", "")


def test_http_transport_sends_login_cookies_to_exhentai_only():
    transport = HttpTransport(Settings(ipb_member_id="m1", ipb_pass_hash="h1"), HostRateLimiter(0))
    assert cookie_header(transport, "https://e-hentai.org/g/1/ab/") == "nw=1"
    ex = cookie_header(transport, "https://exhentai.org/g/1/ab/")
    assert sorted(ex.split("; ")) == ["ipb_member_id=m1", "ipb_pass_hash=h1", "nw=1"]
    assert cookie_header(transport, "https://elsewhere.test/") == ""


def test_http_transport_talks_to_the_site(site, settings):
    transport = HttpTransport(settings, HostRateLimiter(0))
    page = transport.fetch(site.base)
    assert page.status == 200 and "itg gltc" in page.text
    assert site.requests[0][1] == "nw=1"


def test_download_goes_through_a_part_file(site, settings, tmp_path):
    transport = HttpTransport(settings, HostRateLimiter(0))
    dest = tmp_path / "out.jpg"
    (tmp_path / "out.jpg.part").write_bytes(b"left over from a crash")
    assert transport.download(site.base + "img/1005-1.jpg", dest) == len(image_bytes(1005, 1))
    assert dest.read_bytes() == image_bytes(1005, 1)
    assert not (tmp_path / "out.jpg.part").exists()


def test_download_errors(site, settings, tmp_path):
    transport = HttpTransport(settings, HostRateLimiter(0))
    site.fail["/img/1005-1.jpg"] = 1
    with pytest.raises(TransientError, match="HTTP 503"):
        transport.download(site.base + "img/1005-1.jpg", tmp_path / "a.jpg")
    with pytest.raises(FetchError, match="HTTP 404"):
        transport.download(site.base + "nothing.jpg", tmp_path / "b.jpg")
    assert not (tmp_path / "a.jpg").exists() and not (tmp_path / "b.jpg").exists()


def test_connection_refused_is_transient(settings):
    transport = HttpTransport(settings, HostRateLimiter(0))
    with pytest.raises(TransientError, match="ConnectionError"):
        transport.fetch("http://127.0.0.1:9/")


class FakeDriver:
    def __init__(self, pages=None, fail_with=None):
        self.visited: list[str] = []
        self.cookies: list[tuple[str, dict]] = []
        self.pages = pages or {}
        self.fail_with = fail_with
        self.page_source = ""
        self.quit_called = False
        self.scripts: list[str] = []

    def set_page_load_timeout(self, seconds):
        self.timeout = seconds

    def get(self, url):
        self.visited.append(url)
        if self.fail_with is not None and url in self.pages:
            raise self.fail_with
        self.page_source = self.pages.get(url, "<html>home</html>")

    def add_cookie(self, cookie):
        self.cookies.append((self.visited[-1], cookie))

    def execute_script(self, script):
        self.scripts.append(script)

    def quit(self):
        self.quit_called = True


def test_browser_transport_sets_cookies_once_per_host():
    pytest.importorskip("selenium")
    driver = FakeDriver({"https://exhentai.org/g/1/ab/": "<html>gallery</html>"})
    settings = Settings(ipb_member_id="m1", ipb_pass_hash="h1", timeout=30)
    transport = BrowserTransport(settings, HostRateLimiter(0), driver_factory=lambda: driver)

    page = transport.fetch("https://exhentai.org/g/1/ab/")
    transport.fetch("https://exhentai.org/g/1/ab/")

    assert page == Page("https://exhentai.org/g/1/ab/", None, "<html>gallery</html>")
    assert driver.visited == ["https://exhentai.org/", "https://exhentai.org/g/1/ab/", "https://exhentai.org/g/1/ab/"]
    assert [(where, c["name"]) for where, c in driver.cookies] == [
        ("https://exhentai.org/", "nw"),
        ("https://exhentai.org/", "ipb_member_id"),
        ("https://exhentai.org/", "ipb_pass_hash"),
    ]
    assert driver.timeout == 30
    transport.close()
    assert driver.quit_called


def test_browser_timeout_is_transient():
    selenium_exceptions = pytest.importorskip("selenium.common.exceptions")
    url = "https://e-hentai.org/"
    driver = FakeDriver({url: ""}, fail_with=selenium_exceptions.TimeoutException("slow"))
    transport = BrowserTransport(Settings(ex_mode=False), HostRateLimiter(0), driver_factory=lambda: driver)
    with pytest.raises(TransientError, match="timed out"):
        transport.fetch(url)
    assert driver.scripts == ["window.stop()"]


def test_browser_fetcher_without_selenium_explains_what_to_install(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_selenium(name, *args, **kwargs):
        if name.startswith("selenium"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_selenium)
    with pytest.raises(SettingsError, match=r"ehentai-crawler\[browser\]"), open_fetcher(Settings(fetcher="browser")):
        pass
