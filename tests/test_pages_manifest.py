"""
tests/test_pages_manifest.py
-----------------------------
The per-page manifest a CONCURRENT run writes into `<out>.meta.json`.

Everything here is offline and deterministic:

  * the HTML is built in-process, in the shapes page_flow/product_parser
    already understand (listing cards, the site's own "Show N results" count);
  * the browser is a stub whose `goto()` serves that HTML and records which
    pages were asked for, so no socket is opened;
  * for the dispatcher's own edge cases (a worker dying mid-page, workers not
    finishing in page order) `_fetch_one_page` is replaced with a stub worker,
    which is what makes "page 4 came back empty while page 3 was still queued"
    reproducible instead of a race.

Three scenarios, one per acceptance case in the brief:

  all pages succeed                       -> every page success, complete
  a page in the middle fails              -> that page failed, run partial
  an empty page in the middle, with
  lower pages never attempted             -> those are `gap`, run partial

And the negative case: a sequential run and a 1-2 page run must write exactly
the metadata they wrote before, with no manifest key at all.
"""

import json
import threading
import types

import pytest

import playwright_scraper
import output_writer

URL = "https://flippa.com/search?filter%5Bproperty_type%5D=saas"

CARD_TEMPLATE = """
<div id="listing-{sku}" class="listing-card">
  <div><img alt="Broker {sku}">Marketplace · Listed by Owner</div>
  <a href="/{sku}-business"><h4>SaaS | Business {sku}</h4></a>
  <p>Listing {sku}.</p>
  <hr>
  <div>Asking price | USD ${price}</div>
</div>
"""


def page_html(page_num: int, cards: int = 3, total: int = 500) -> str:
    """A search page holding `cards` listing cards, in the served-HTML shape.

    `total` is Flippa's own match count, which is what page_flow reads to
    classify a card-less page as `exhausted` rather than `blocked`.
    """
    body = "".join(
        CARD_TEMPLATE.format(sku=page_num * 1000 + i, price=10000 + page_num * 100 + i)
        for i in range(1, cards + 1))
    # Enough references to the site's own asset hosts for page_flow's
    # interstitial heuristic not to fire on a card-less page.
    assets = "".join('<script src="https://static.flippa.com/assets/a.js"></script>'
                     for _ in range(6))
    return (f"<html><head>{assets}</head><body>"
            f'<div id="filters-show-results-count">{total} results</div>'
            f"{body}</body></html>")


class StubResponse:
    def __init__(self, status=200):
        self.status = status


class StubPage:
    """Serves `pages[page_num]` HTML; `goto` records every URL, like a browser."""

    def __init__(self, pages):
        self.pages = pages
        self.visited = []
        self.url = URL

    def goto(self, url, wait_until=None, timeout=None):
        page_num = 1
        if "page=" in url:
            page_num = int(url.rsplit("page=", 1)[1].split("&", 1)[0])
        self.visited.append(page_num)
        self.url = url
        if page_num not in self.pages:
            raise RuntimeError(f"stub has no page {page_num}")
        return StubResponse()

    def content(self):
        return self.pages[self._current_page()]

    def _current_page(self):
        return self.visited[-1]

    def wait_for_timeout(self, *_args, **_kwargs):
        return None

    def locator(self, _selector):
        # Above MIN_CARD_MATCHES, so the readiness wait returns at once
        # instead of spinning for RENDER_WAIT_MS of real time.
        return types.SimpleNamespace(count=lambda: 6)

    def evaluate(self, _js):
        # The live-page captcha detector: nothing found.
        return {"found": False}

    def screenshot(self, **_kwargs):
        return None


class StubSession:
    def __init__(self, pages, visited=None):
        self.page = StubPage(pages)
        self.pool = None
        self.closed = False
        if visited is not None:
            self.page.visited = visited

    def close(self):
        self.closed = True

    def open(self):
        return self

    def relaunch(self):
        pass


def make_args(tmp_path, pages: int, concurrency: int = 1):
    args = types.SimpleNamespace(
        url=URL, category="saas", pages=pages, delay=0,
        concurrency=concurrency, retries=1, retry_delay=0,
        proxy=None, proxy_file=None, proxy_rotate="per-run", proxy_shuffle=False,
        proxy_block_retries=0, twocaptcha_key=None, captcha_api="v2",
        solve_captcha="when-blocked", min_score=0.7,
        allow_empty=True, fingerprint=False, fp_tags="Windows",
        fp_country=None, cdp_endpoint=None, dump_html=None, headless=True,
        out=str(tmp_path / "run"), format="both",
    )
    return args


@pytest.fixture
def no_network(monkeypatch):
    """No real proxy preflight, no real browser launch, no resync of sleeps."""
    monkeypatch.setattr(playwright_scraper, "check_exit_or_raise",
                        lambda *a, **k: None)
    monkeypatch.setattr(playwright_scraper.time, "sleep", lambda _s: None)


def _patch_single_session(monkeypatch, pages):
    """One stub browser for the sequential stages (pages 1 and 2)."""
    session = StubSession(pages)

    class _Ctx:
        def __enter__(self):
            return object()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(playwright_scraper, "sync_playwright", lambda: _Ctx())
    monkeypatch.setattr(playwright_scraper._BrowserSession, "open",
                        lambda self: session)
    return session


def _patch_concurrent_workers(monkeypatch, pages, behaviours, order=None):
    """Drive the real dispatcher with stub workers.

    `behaviours` maps page_num -> a callable returning either a live outcome
    (parsed from `pages`) or a failure marker. `order` controls the sequence
    pages are completed in, which is how "the empty page finished while a
    lower page was still queued" is made deterministic.
    """
    monkeypatch.setattr(
        playwright_scraper, "_BrowserSession",
        lambda *a, **k: StubSession(pages))

    def fake_fetch(session, args, pool, page_num, url):
        outcome = playwright_scraper.PageOutcome(page_num=page_num, url=url)
        behaviour = behaviours.get(page_num)
        if behaviour is None:
            html = pages[page_num]
            import page_flow
            outcome.state = page_flow.classify(html)
            outcome.products = playwright_scraper.parse_products(
                html, url, category=args.category, page=page_num) \
                if outcome.state.state == page_flow.CONTENT else []
            return outcome
        return behaviour(outcome)

    monkeypatch.setattr(playwright_scraper, "_fetch_one_page", fake_fetch)


def _read_meta(tmp_path):
    path = tmp_path / "run.meta.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.mark.parametrize("pages,expected", [(3, 3), (4, 4), (5, 5)])
def test_concurrent_run_writes_manifest(tmp_path, monkeypatch, no_network,
                                        pages, expected):
    """Every requested page appears once, ascending, all success."""
    html = {n: page_html(n) for n in range(1, pages + 1)}
    _patch_single_session(monkeypatch, html)
    _patch_concurrent_workers(monkeypatch, html, {})

    args = make_args(tmp_path, pages, concurrency=3)
    rc = playwright_scraper.scrape(args)

    meta = _read_meta(tmp_path)
    assert rc == 0
    assert meta["status"] == "complete"
    assert meta["stop_reason"] == "completed"
    manifest = meta["pages_manifest"]
    assert [e["page"] for e in manifest] == list(range(1, expected + 1))
    assert all(e["status"] == "success" for e in manifest)
    assert all(isinstance(e["products"], int) and e["products"] == 3
               for e in manifest)


def test_middle_page_failure_is_recorded_and_run_is_partial(tmp_path,
                                                            monkeypatch,
                                                            no_network):
    """Page 4 fails; the rest succeed; the manifest names the failure."""
    pages = 6
    html = {n: page_html(n) for n in range(1, pages + 1)}

    def failing(outcome):
        outcome.load_failed = True
        return outcome

    _patch_single_session(monkeypatch, html)
    _patch_concurrent_workers(monkeypatch, html, {4: failing})
    args = make_args(tmp_path, pages, concurrency=3)

    rc = playwright_scraper.scrape(args)
    meta = _read_meta(tmp_path)

    assert rc == output_writer.EXIT_PARTIAL
    assert meta["status"] == "partial"
    assert meta["stop_reason"] == "page_load_timeout"
    manifest = meta["pages_manifest"]
    assert [e["page"] for e in manifest] == [1, 2, 3, 4, 5, 6]
    by_page = {e["page"]: e for e in manifest}
    assert by_page[4]["status"] == "failed"
    assert by_page[4]["stop_reason"] == "page_load_timeout"
    assert all(by_page[n]["status"] == "success" for n in (1, 2, 3, 5, 6))
    assert meta["pages_failed"] == [4]


def test_empty_page_mid_run_leaves_lower_pages_as_gaps(tmp_path, monkeypatch,
                                                       no_network):
    """Page 5 comes back empty while pages 4 and 6 were never dispatched.

    The listing really ends at 5 (it is empty), so page 6 — past it — is
    legitimately 'listing_exhausted'. Page 4 is BELOW the empty page: it was
    skipped although rows may exist there, so it is a `gap` and the run must
    not report complete.
    """
    pages = 6
    html = {n: page_html(n) for n in range(1, pages + 1)}
    # Page 5 carries no cards but keeps the site's count: classified exhausted.
    html[5] = page_html(5, cards=0)

    page3_done = threading.Event()

    def page3(outcome):
        import page_flow
        outcome.state = page_flow.classify(html[3])
        outcome.products = playwright_scraper.parse_products(
            html[3], outcome.url, category="saas", page=3)
        page3_done.set()
        return outcome

    def empty_page(outcome):
        # Fetching pages is concurrent; page 5 is made to finish AFTER page 3
        # so "the empty page stopped dispatch while lower pages were still
        # queued" is deterministic here instead of a race.
        page3_done.wait(timeout=5)
        import page_flow
        outcome.state = page_flow.classify(html[5])
        outcome.products = []
        return outcome

    _patch_single_session(monkeypatch, html)
    _patch_concurrent_workers(monkeypatch, html, {3: page3, 5: empty_page})
    # Pages 4 and 6 stay in the queue when page 5 empties — exactly what the
    # dispatcher does with pages it never reached.
    monkeypatch.setattr(
        playwright_scraper, "_fetch_pages_concurrently",
        _wrap_real_dispatcher_with_skipped({4, 6}))
    args = make_args(tmp_path, pages, concurrency=2)

    rc = playwright_scraper.scrape(args)
    meta = _read_meta(tmp_path)

    assert rc == output_writer.EXIT_PARTIAL
    assert meta["status"] == "partial"
    assert meta["stop_reason"] == "pages_unattempted"
    manifest = meta["pages_manifest"]
    assert [e["page"] for e in manifest] == [1, 2, 3, 4, 5, 6]
    by_page = {e["page"]: e for e in manifest}
    assert by_page[4] == {"page": 4, "status": "not_attempted", "reason": "gap"}
    assert by_page[5]["status"] == "success"
    assert by_page[5]["products"] == 0
    assert by_page[6] == {"page": 6, "status": "not_attempted",
                          "reason": "listing_exhausted"}


def _wrap_real_dispatcher_with_skipped(skipped):
    """Run the real dispatcher, but with `skipped` left in the queue.

    A worker that reaches the empty page at the same moment as another pulls a
    lower page is a race in production; here it is imposed, so the manifest's
    gap rule is tested rather than a coin flip.
    """
    real = playwright_scraper._fetch_pages_concurrently

    def wrapped(args, pool, specs, concurrency):
        specs = [s for s in specs if s[0] not in skipped]
        results, unattempted, ran_out, empty_at = real(
            args, pool, specs, concurrency)
        return (results, sorted(set(unattempted) | set(skipped)),
                ran_out, empty_at)

    return wrapped


def test_empty_page_past_the_end_keeps_the_run_complete(tmp_path, monkeypatch,
                                                        no_network):
    """Page 4 is genuinely the last one; page 5 was skipped legitimately."""
    pages = 5
    html = {n: page_html(n) for n in range(1, pages + 1)}
    html[4] = page_html(4, cards=0)

    def empty_page(outcome):
        import page_flow
        outcome.state = page_flow.classify(html[4])
        outcome.products = []
        return outcome

    _patch_single_session(monkeypatch, html)
    _patch_concurrent_workers(monkeypatch, html, {4: empty_page})
    monkeypatch.setattr(
        playwright_scraper, "_fetch_pages_concurrently",
        _wrap_real_dispatcher_with_skipped({5}))
    args = make_args(tmp_path, pages, concurrency=2)

    rc = playwright_scraper.scrape(args)
    meta = _read_meta(tmp_path)

    assert rc == 0
    assert meta["status"] == "complete"
    assert meta["stop_reason"] == "listing_exhausted"
    assert meta["coverage"] == "exhaustive"
    manifest = meta["pages_manifest"]
    by_page = {e["page"]: e for e in manifest}
    assert [e["page"] for e in manifest] == [1, 2, 3, 4, 5]
    assert by_page[4] == {"page": 4, "status": "success", "products": 0}
    assert by_page[5] == {"page": 5, "status": "not_attempted",
                          "reason": "listing_exhausted"}


def test_manifest_pages_are_unique_and_ascending(tmp_path, monkeypatch,
                                                 no_network):
    """The brief's invariant, asserted directly on a mixed run."""
    pages = 7
    html = {n: page_html(n) for n in range(1, pages + 1)}

    def failing(outcome):
        outcome.parse_failed = True
        return outcome

    _patch_single_session(monkeypatch, html)
    _patch_concurrent_workers(monkeypatch, html, {3: failing, 6: failing})
    args = make_args(tmp_path, pages, concurrency=3)

    playwright_scraper.scrape(args)
    manifest = _read_meta(tmp_path)["pages_manifest"]
    numbers = [e["page"] for e in manifest]
    assert numbers == sorted(numbers)
    assert len(numbers) == len(set(numbers)) == pages
    assert {e["status"] for e in manifest} == {"success", "failed"}


def test_sequential_run_has_no_manifest(tmp_path, monkeypatch, no_network):
    """--concurrency 1 writes exactly the metadata it wrote before."""
    pages = 4
    html = {n: page_html(n) for n in range(1, pages + 1)}
    _patch_single_session(monkeypatch, html)

    args = make_args(tmp_path, pages, concurrency=1)
    playwright_scraper.scrape(args)

    meta = _read_meta(tmp_path)
    assert "pages_manifest" not in meta
    # The pre-existing fields are untouched.
    for key in ("status", "stop_reason", "pages_requested", "pages_completed",
                "pages_failed", "pages_missing", "coverage"):
        assert key in meta


@pytest.mark.parametrize("pages", [1, 2])
def test_short_run_has_no_manifest(tmp_path, monkeypatch, no_network, pages):
    """1-2 page runs never enter the concurrent stage."""
    html = {n: page_html(n) for n in range(1, pages + 1)}
    _patch_single_session(monkeypatch, html)

    args = make_args(tmp_path, pages, concurrency=3)
    playwright_scraper.scrape(args)

    assert "pages_manifest" not in _read_meta(tmp_path)


def test_page_manifest_is_pure_and_ordered():
    """Unit-level check of the builder, independent of the scrape path."""
    import page_flow

    ok = playwright_scraper.PageOutcome(page_num=1, url=URL)
    ok.state = page_flow.PageState(page_flow.CONTENT, "3 listing card(s)")
    bad = playwright_scraper.PageOutcome(page_num=2, url=URL)
    bad.load_failed = True
    empty = playwright_scraper.PageOutcome(page_num=4, url=URL)
    empty.state = page_flow.PageState(page_flow.EXHAUSTED,
                                      "no listings on this page")

    entries = playwright_scraper._page_manifest(
        pages_requested=5, outcomes=[ok, bad, empty], unattempted=[3, 5],
        empty_at=4)
    assert entries == [
        {"page": 1, "status": "success", "products": 0},
        {"page": 2, "status": "failed", "stop_reason": "page_load_timeout"},
        {"page": 3, "status": "not_attempted", "reason": "gap"},
        {"page": 4, "status": "success", "products": 0},
        {"page": 5, "status": "not_attempted", "reason": "listing_exhausted"},
    ]


def test_finish_run_refuses_complete_alongside_a_gap(tmp_path):
    """finish_run's independent guard: a gap outranks a complete stop reason."""
    manifest = [
        {"page": 1, "status": "success", "products": 3},
        {"page": 2, "status": "not_attempted", "reason": "gap"},
    ]
    products = [output_writer.Product(sku="1", url="https://flippa.com/1",
                                      title="t", price=1.0, currency="USD")]
    rc = output_writer.finish_run(
        products, str(tmp_path / "run"), "json", False,
        blocked=False, stop_reason="completed", pages_requested=2,
        pages_completed=2, start_url=URL, final_url=URL,
        pages_manifest=manifest)

    meta = _read_meta(tmp_path)
    assert rc == output_writer.EXIT_PARTIAL
    assert meta["status"] == "partial"
    assert meta["stop_reason"] == "pages_unattempted"
    assert meta["pages_manifest"] == manifest
