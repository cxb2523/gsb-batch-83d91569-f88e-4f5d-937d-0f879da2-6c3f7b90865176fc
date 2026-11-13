"""
tests/test_page_manifest.py
----------------------------
End-to-end check of the Playwright engine's per-page manifest.

Drives the REAL engine — real argparse, real Chromium, real navigation, real
classification and the real merge — against three SELF-MADE HTML documents
served from disk: a page of vendor cards, an empty page (the site's own 404
document) and a refused page (PerimeterX's widget-less stub). Every request
is answered by a Playwright route handler out of this file's own HTML, so
nothing here touches foodpanda, 2captcha or any network at all.

What it pins, and why each half exists:

  * a page that was REFUSED and never read is recorded as `blocked` /
    failed, never as a 0-row `empty` page. An empty page is the site's own
    answer that the listing ended; a refusal is the opposite, and the two
    producing the same row count is exactly the misreading the manifest
    exists to prevent.
  * the failed page does not leave the run claiming `completed`: exit 6,
    `status: partial`, and a `stop_reason` from the existing vocabulary.
  * an all-content run is `complete`, exit 0, with a full manifest.
  * a run that runs out of listing records the pages it never dispatched in
    `pages_unattempted` — not as failures and not as empty pages.
  * under `--concurrency`, rows are merged in PAGE order and a duplicated
    `sku` keeps the LOWEST page, so two runs of the same command produce the
    same rows in the same order — and a refused page in the middle of a
    concurrent run is still reported as failed rather than as an empty one.

Run directly (`python tests/test_page_manifest.py`) or under pytest. It
SKIPS — loudly, with the reason — where Playwright or its browser binary
is absent, because CI's offline jobs install neither.
"""

import json
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

try:
    import playwright_scraper as engine
except ImportError as exc:                       # pragma: no cover - CI offline
    engine = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


def _browser_available():
    """Whether Playwright can actually launch here (not merely import)."""
    if engine is None:
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            return os.path.exists(pw.chromium.executable_path)
    except Exception:
        return False


needs_browser = pytest.mark.skipif(
    engine is None or not _browser_available(),
    reason="playwright and its Chromium binary are required for this test"
    + ("" if engine is not None else f" (import failed: {_IMPORT_ERROR})"))


# ---------------------------------------------------------------------------
# Self-made HTML fixtures
# ---------------------------------------------------------------------------
# A vendor card shaped like the real one where the parser looks: the `<li>`
# class carries the tile, its `data-testid` IS the vendor code, the name is
# in a `title` attribute, the link is a /restaurant/ path, the image is on
# the site's own media host, and the cuisine row is the only info row.
_TILE = """
<li class="bds-c-vendor-tile--large" data-testid="{sku}">
  <a data-testid="bds-c-vendor-tile__link-{sku}" href="/restaurant/{sku}/{slug}">
    <div class="bds-c-vendor-tile__image-wrapper">
      <img class="bds-c-vendor-tile__vendor-image"
           data-testid="bds-c-vendor-tile__vendor-image-actual"
           src="https://foodpanda.dhmedia.io/image/fd-pk/{sku}-listing.jpg"
           alt="{title}"/>
    </div>
    <div class="bds-c-vendor-tile__info">
      <div class="bds-c-vendor-tile__name" title="{title}">{title}</div>
      <div class="bds-c-vendor-tile__info-row">
        <div class="bds-c-vendor-tile__info-row-text"
             data-testid="bds-c-vendor-tile__info-row-text">Cuisines {cuisine}</div>
      </div>
    </div>
  </a>
</li>
"""

# Three references to the site's own asset hosts, which is what
# `served_by_foodpanda` counts. Not strictly needed for a page with tiles on
# it (the tiles are the unambiguous positive) but present so the document
# looks like a served page rather than an interstitial.
_HEAD = """<!DOCTYPE html><html lang="en-PK"><head><meta charset="utf-8">
<title>{title}</title>
<link rel="preconnect" href="https://images.deliveryhero.io/">
<link rel="preconnect" href="https://foodpanda.dhmedia.io/">
<link rel="preconnect" href="https://static.fd-api.com/">
</head><body>"""


def _cards_page(skus):
    tiles = "".join(
        _TILE.format(sku=sku, slug=f"vendor-{sku}", title=f"Vendor {sku}",
                     cuisine="Fast Food")
        for sku in skus)
    return _HEAD.format(title="Vendors") + f"<ul>{tiles}</ul></body></html>"


def _empty_page():
    # The site's own 404 furniture, which is how `detect_page_state` reaches
    # `empty`: a served document whose title says 404 with no grid on it.
    return _HEAD.format(title="404 Ooops!") + "</body></html>"


def _refused_page():
    # PerimeterX's widget-less denial stub: `px-captcha` and `_pxUuid` are
    # the markers, and there is no `g-recaptcha`/enterprise loader on it —
    # so it is `blocked`, not a solvable `challenge`.
    return """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="description" content="px-captcha">
<title>Access to this page has been denied</title></head><body>
<script>window._pxUuid = '00000000-0000-0000-0000-000000000000';
window._pxAppId = 'PXtest';</script>
<div id="px-captcha"></div>
<p>Access to this page has been denied.</p>
</body></html>"""


# ---------------------------------------------------------------------------
# The local server: a Playwright route that answers out of the fixtures above
# ---------------------------------------------------------------------------
class _LocalSite:
    """Serves `pages` (1-based index) for one listing, 403 on the refused set.

    Answers every request from disk with no network at all. Only the main
    document is fulfilled; fonts, images and anything else are aborted, so
    the run cannot accidentally reach the real site through a subresource.
    """

    def __init__(self, pages, refused=(), empty=()):
        self.pages = dict(pages)          # page number -> html
        self.refused = set(refused)       # page numbers answered 403
        self.empty = set(empty)           # page numbers answered with the 404
        self.requests = []                # page numbers actually requested

    def handler(self, route):
        request = route.request
        if request.resource_type != "document":
            route.abort()
            return
        page_num = _page_of(request.url)
        self.requests.append(page_num)
        if page_num in self.refused:
            route.fulfill(status=403, content_type="text/html",
                          body=_refused_page())
        elif page_num in self.empty or page_num not in self.pages:
            route.fulfill(status=200, content_type="text/html",
                          body=_empty_page())
        else:
            route.fulfill(status=200, content_type="text/html",
                          body=self.pages[page_num])

    def install(self, browser, context, page):
        # `**` matches every URL including the document itself.
        context.route("**/*", self.handler)


def _page_of(url):
    from urllib.parse import parse_qsl, urlsplit
    for key, value in parse_qsl(urlsplit(url).query):
        if key == "page":
            try:
                return int(value)
            except ValueError:
                return 1
    return 1


# ---------------------------------------------------------------------------
# Driving the real engine
# ---------------------------------------------------------------------------
AREA_URL = "https://www.foodpanda.pk/city/lahore/area/gulberg"


def _run(tmp_prefix, site, pages=3, concurrency=1, extra_argv=()):
    """Run the real `scrape()` with a local route answering every navigation.

    Only three things are reached into: the route is attached to the real
    browser context (and re-attached on every relaunch), the Turnstile render
    wait is short-circuited (it would otherwise poll for six seconds per
    navigation on pages carrying no Turnstile), and the block-retry budget is
    held at one re-fetch so a deliberately refused page does not relaunch the
    family default of five browsers. Everything else — argparse, Chromium,
    navigation, classification, parsing, retries, merging and exit codes —
    is the shipped path.
    """
    import sys as _sys

    def _launch_local_with_route(pw, args, pool):
        browser, context, page = _original_launch(pw, args, pool)
        site.install(browser, context, page)
        return browser, context, page

    saved = {
        "wait_for_turnstile": engine.wait_for_turnstile,
        "_launch_local": engine._launch_local,
        "RETRY_ON_BLOCKED": engine.page_flow.RETRY_ON_BLOCKED,
        "BLOCK_RETRIES_WITHOUT_POOL":
            engine.page_flow.BLOCK_RETRIES_WITHOUT_POOL,
        "argv": _sys.argv,
    }
    _original_launch = saved["_launch_local"]
    try:
        engine.wait_for_turnstile = lambda *a, **k: None
        engine._launch_local = _launch_local_with_route
        engine.page_flow.RETRY_ON_BLOCKED = True
        engine.page_flow.BLOCK_RETRIES_WITHOUT_POOL = 1
        _sys.argv = [
            "playwright_scraper.py",
            "--url", AREA_URL,
            "--pages", str(pages),
            "--concurrency", str(concurrency),
            "--format", "json",
            "--out", tmp_prefix,
            "--headless",
            "--delay", "0",
            "--retries", "1",
            "--retry-delay", "0",
        ] + list(extra_argv)
        args = engine.parse_args()
        return engine.scrape(args)
    finally:
        engine.wait_for_turnstile = saved["wait_for_turnstile"]
        engine._launch_local = saved["_launch_local"]
        engine.page_flow.RETRY_ON_BLOCKED = saved["RETRY_ON_BLOCKED"]
        engine.page_flow.BLOCK_RETRIES_WITHOUT_POOL = \
            saved["BLOCK_RETRIES_WITHOUT_POOL"]
        _sys.argv = saved["argv"]


def _meta(prefix):
    with open(prefix + ".meta.json", encoding="utf-8") as f:
        return json.load(f)


def _rows(prefix):
    with open(prefix + ".json", encoding="utf-8") as f:
        return json.load(f)


def _pages(meta):
    return {r["page"]: r for r in meta["pages"]}


SKUS = ("c48s", "pedb", "yqcc", "abcd", "efgh", "ijkl")


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------
@needs_browser
def test_all_pages_succeed():
    site = _LocalSite({1: _cards_page(SKUS),
                       2: _cards_page(("m1n2", "o3p4", "q5r6",
                                       "s7t8", "u9v0", "w1x2")),
                       3: _cards_page(("a1b2", "c3d4", "e5f6",
                                       "g7h8", "i9j0", "k1l2"))})
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "ok")
        code = _run(prefix, site)
        meta = _meta(prefix)
        pages = _pages(meta)
        assert code == 0, f"exit {code}, stop_reason {meta['stop_reason']}"
        assert meta["status"] == "complete"
        assert meta["stop_reason"] == "completed"
        assert sorted(pages) == [1, 2, 3]
        assert all(r["status"] == "content" and not r["failed"]
                   for r in pages.values()), pages
        assert [pages[n]["rows"] for n in (1, 2, 3)] == [6, 6, 6]
        assert meta["pages_attempted"] == [1, 2, 3]
        assert meta["pages_succeeded"] == [1, 2, 3]
        assert meta["pages_failed"] == []
        assert meta["pages_unattempted"] == []
        assert meta["pages_completed"] == 3
        assert meta["products"] == len(_rows(prefix)) == 18


@needs_browser
def test_refused_page_is_failed_not_empty():
    site = _LocalSite({1: _cards_page(SKUS),
                       3: _cards_page(("a1b2", "c3d4", "e5f6",
                                       "g7h8", "i9j0", "k1l2"))},
                      refused=(2,))
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "blocked")
        code = _run(prefix, site)
        meta = _meta(prefix)
        pages = _pages(meta)
        assert code == 6, (code, meta["stop_reason"])
        assert meta["status"] == "partial"
        assert meta["stop_reason"] != "completed"
        assert pages[2]["status"] == "blocked", pages[2]
        assert pages[2]["failed"] is True
        # NOT a zero-row empty page: this page was never read.
        assert pages[2]["rows"] == 0
        assert pages[1]["status"] == "content" and pages[1]["rows"] == 6
        assert pages[3]["status"] == "content" and pages[3]["rows"] == 6
        assert pages[1]["failed"] is False and pages[3]["failed"] is False
        assert meta["pages_attempted"] == [1, 2, 3]
        assert meta["pages_succeeded"] == [1, 3]
        assert meta["pages_failed"] == [2]
        assert meta["pages_unattempted"] == []
        assert meta["pages_completed"] == 2
        assert meta["products"] == 12


@needs_browser
def test_empty_page_ends_the_listing_and_the_rest_are_unattempted():
    site = _LocalSite({1: _cards_page(SKUS),
                       2: _cards_page(("m1n2", "o3p4", "q5r6",
                                       "s7t8", "u9v0", "w1x2"))},
                      empty=(3,))
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "ranout")
        code = _run(prefix, site, pages=5)
        meta = _meta(prefix)
        pages = _pages(meta)
        assert code == 0, (code, meta["stop_reason"])
        assert meta["status"] == "complete"
        assert meta["stop_reason"] == "no_new_products"
        assert pages[3]["status"] == "empty"
        assert pages[3]["failed"] is False          # empty is a real answer
        assert pages[3]["rows"] == 0
        assert meta["pages_failed"] == []
        assert meta["pages_unattempted"] == [4, 5]
        assert meta["pages_attempted"] == [1, 2, 3]
        # The distinction this test exists for: an empty page (rows 0,
        # failed False) is not a refused page (rows 0, failed True).
        assert pages[3]["failed"] is False


@needs_browser
def test_concurrency_refusal_still_merges_in_page_order():
    """Page 2 refused under --concurrency: 1 and 3 are still read, and the
    run is partial for the same reason it would be sequentially."""
    site = _LocalSite({1: _cards_page(SKUS),
                       3: _cards_page(("a1b2", "c3d4", "e5f6",
                                       "g7h8", "i9j0", "k1l2"))},
                      refused=(2,))
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "conc_blocked")
        code = _run(prefix, site, pages=3, concurrency=2)
        meta = _meta(prefix)
        pages = _pages(meta)
        assert code == 6, (code, meta["stop_reason"])
        assert meta["status"] == "partial"
        assert meta["stop_reason"] != "completed"
        assert pages[1]["status"] == "content" and pages[1]["rows"] == 6
        assert pages[2]["status"] == "blocked" and pages[2]["failed"] is True
        assert pages[3]["status"] == "content" and pages[3]["rows"] == 6
        assert meta["pages_attempted"] == [1, 2, 3]
        assert meta["pages_succeeded"] == [1, 3]
        assert meta["pages_failed"] == [2]
        assert meta["pages_unattempted"] == []
        assert meta["products"] == 12
        # And the manifest is in page order, not arrival order.
        assert [r["page"] for r in meta["pages"]] == [1, 2, 3]


@needs_browser
def test_concurrency_merges_in_page_order_and_keeps_the_lowest_page():
    # Page 2 repeats one of page 1's vendors, which is the duplicate the
    # merge must resolve in favour of page 1 whatever order the workers
    # happened to finish in.
    site = _LocalSite({1: _cards_page(SKUS),
                       2: _cards_page((SKUS[0], "o3p4", "q5r6",
                                       "s7t8", "u9v0", "w1x2")),
                       3: _cards_page(("a1b2", "c3d4", "e5f6",
                                       "g7h8", "i9j0", "k1l2"))})
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "conc")
        code = _run(prefix, site, pages=3, concurrency=2)
        meta = _meta(prefix)
        rows = _rows(prefix)
        pages = _pages(meta)
        assert code == 0, (code, meta["stop_reason"])
        assert meta["status"] == "complete"
        assert sorted(pages) == [1, 2, 3]
        assert meta["pages_attempted"] == [1, 2, 3]
        # Rows come out in page order, not in arrival order.
        seen_pages = [r["page"] for r in rows]
        assert seen_pages == sorted(seen_pages), seen_pages
        # The repeated sku keeps page 1.
        dup = [r for r in rows if r["sku"] == SKUS[0]]
        assert len(dup) == 1 and dup[0]["page"] == 1
        # And the sidecar is in page order too.
        assert [r["page"] for r in meta["pages"]] == [1, 2, 3]
        # Same command twice: the manifest and the row order agree.
        prefix2 = os.path.join(tmp, "conc2")
        code2 = _run(prefix2, _LocalSite(
            {1: _cards_page(SKUS),
             2: _cards_page((SKUS[0], "o3p4", "q5r6",
                             "s7t8", "u9v0", "w1x2")),
             3: _cards_page(("a1b2", "c3d4", "e5f6",
                             "g7h8", "i9j0", "k1l2"))}))
        meta2 = _meta(prefix2)
        rows2 = _rows(prefix2)
        assert code2 == code
        assert [r["page"] for r in meta2["pages"]] == [1, 2, 3]
        strip = lambda rs: [{k: v for k, v in r.items()
                             if k != "scraped_at"} for r in rs]
        assert strip(rows) == strip(rows2)


if __name__ == "__main__":
    # Direct run: the two required scenarios print PASS/FAIL, and the exit
    # code says whether every check passed. `pytest -q` runs the same
    # functions.
    if engine is None or not _browser_available():
        print("SKIP: playwright and its Chromium binary are required.")
        sys.exit(0)
    failing = 0
    for check in (test_all_pages_succeed,
                  test_refused_page_is_failed_not_empty,
                  test_empty_page_ends_the_listing_and_the_rest_are_unattempted,
                  test_concurrency_refusal_still_merges_in_page_order,
                  test_concurrency_merges_in_page_order_and_keeps_the_lowest_page):
        try:
            check()
        except AssertionError as exc:
            failing += 1
            print(f"FAIL  {check.__name__}: {exc}")
        else:
            print(f"PASS  {check.__name__}")
    print("page manifest: " + ("OK" if not failing else "FAILED"))
    sys.exit(0 if not failing else 1)
