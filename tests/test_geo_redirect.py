#!/usr/bin/env python3
"""Offline tests for the geo-redirect rule in `http_scraper.py`.

Self-contained: every page is synthesised here and every HTTP answer comes
from a stub session or a stubbed `subprocess.run`, so nothing touches the
network, a proxy or a real curl. Run it directly:

    python3 -I tests/test_geo_redirect.py

It is also collected by pytest as one suite of plain asserts — the repo's
`smoke_test.py` stays the single self-contained runner it is (see
CONTRIBUTING.md), and this file exists because the geo-redirect behaviour has
three end-to-end shapes worth naming in one place.

What is pinned here
-------------------
1. **Same store, followed.** A 301/302 inside www.potterybarn.com is followed
   by hand, up to MAX_REDIRECTS hops; the landing URL is kept and the product
   parses. The host is compared case-insensitively and the query string is
   ignored, so `https://WWW.POTTERYBARN.COM/products/x/?N=1` is still us.
2. **Off store, refused, rotated.** A hop to potterybarn.co.uk (or any other
   host) is returned UNFETCHED, classified `geo_redirect`, counted as a
   refused page, and rotated to another exit. When the new exit serves the
   product page the run completes, the rows are parsed, and the sidecar shows
   the rotation count and the masked exits.
3. **Off store, exhausted.** Every exit redirects away: the run is NOT
   complete (`stop_reason: geo_redirect`, exit 3), the sidecar says which
   pages and which exits, and any row read before that is kept on disk.
4. **Too many hops** inside the store raises instead of truncating.
5. **The other store's body never reaches the output** — no rows, no
   `--dump-html` file, no `unparsed_pages` entry.

`sys.path` is set to the repo root explicitly (not relied on from the cwd), so
the module runs from anywhere.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import http_scraper  # noqa: E402
import product_parser as P  # noqa: E402

STORE = "www.potterybarn.com"
PRODUCT_URL = "https://%s/products/delaney-marble-end-table/" % STORE
UK_URL = "https://www.potterybarn.co.uk/products/delaney-marble-end-table/"
YORK_URL = "https://%s/products/york-sofa/" % STORE


def _product_html(product_id="delaney-marble-end-table", title="Delaney 14\" Marble End Table",
                  skus=(("2235076", 599.0), ("4647188", 649.0)), currency="USD"):
    """A product page in the one shape the parser reads: `__INITIAL_STATE__`.

    Deliberately synthetic and tiny — real captures are 600 KB to 1.4 MB — but
    it carries a `productDetails` node with a `groupId` and a matching
    `skuCount`, which is all `detect_page_state` and `parse_product` ask for.
    """
    definitions_skus = {}
    for sku_id, price in skus:
        definitions_skus[sku_id] = {
            "id": sku_id,
            "name": "%s (%s)" % (title, sku_id),
            "price": {"sellingPrice": price, "regularPrice": price},
            "inventory": {"availability": "IN_STOCK"},
            "availability": {"displayable": True},
            "selectionValueIds": [],
            "media": {"images": []},
        }
    state = {
        "product": {
            "productDetails": {
                "groupId": product_id,
                "title": title,
                "skuCount": len(skus),
                "subsets": [{"name": "Default", "definitions": {"skus": definitions_skus}}],
            },
            "config": {"pricing": {"currencyData": {"selectedCurrency": currency}}},
        }
    }
    return ("<!doctype html><html><head><title>%s | Pottery Barn</title></head>"
            "<body><p>%s</p><script>window.__INITIAL_STATE__=%s</script></body></html>"
            % (title, "x" * 400, json.dumps(state)))


def _uk_page():
    """A UK product page that WOULD parse if anyone were careless enough to.

    Its `groupId` and SKUs are distinct from the US page's, so `assert` can
    prove none of them reached the output.
    """
    return _product_html(product_id="delaney-marble-end-table-uk",
                         title="Delaney Marble End Table (UK)",
                         skus=(("uk-sku-1", 850.0),), currency="GBP")


US_HTML = _product_html()
UK_HTML = _uk_page()
US_SKUS = ["2235076", "4647188"]


def _resp(status, text, url, offsite=False):
    return http_scraper._Response(status, text, url, offsite_redirect=offsite)


class StubSession:
    """A `CurlSession`/`requests.Session` stand-in: one scripted answer per
    `.get()`. An answer is an `_Response` or an exception to raise.

    A session outlives one page — a run reuses it across targets — so
    `answers` may be given per URL (`{url: [answer, ...]}`) or as one flat
    list that is consumed in call order.
    """

    def __init__(self, answers):
        if isinstance(answers, dict):
            self.routes = {url: list(items) for url, items in answers.items()}
            self.answers = []
        else:
            self.routes = None
            self.answers = list(answers)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        queue = self.routes[url] if self.routes is not None else self.answers
        answer = queue.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def _curl_answers(*entries):
    """`subprocess.run` answers in curl's `--write-out` shape.

    Each entry is `(status, url_effective, redirect_url_or_None, body)`; the
    return is the body and the newline-terminated trailer, exactly as curl
    prints them (`body\\n<status> <sizes> <url_effective> <redirect_url>`).
    """
    completed = []
    for status, effective, redirect, body in entries:
        trailer = "%d 100 0 200 %d %s %s" % (status, len(body), effective,
                                            redirect or "")
        completed.append(body + "\n" + trailer)
    return completed


def _install_curl(entries):
    """Patch `subprocess.run` to replay `entries` in order.

    Returns the list of URLs curl was asked for, so an assert can prove the
    UK host was never fetched.
    """
    asked = []
    answers = iter(_curl_answers(*entries))

    def fake_run(command, input=None, **kwargs):
        asked.append(command[-1])
        return subprocess.CompletedProcess(args=command, returncode=0,
                                           stdout=next(answers), stderr="")

    patcher = mock.patch.object(http_scraper.subprocess, "run", fake_run)
    patcher.start()
    return asked, patcher


class StubPool:
    """A proxy pool with N distinct exits, each masked as `gw<i>:<i>`."""

    def __init__(self, count=4):
        self.count = count
        self.index = 0

    @property
    def current(self):
        return "http://user:pw@gw%d:%d" % (self.index + 1, self.index + 1)

    def __len__(self):
        return self.count

    def advance(self, reason):
        self.index = (self.index + 1) % self.count
        return self.current


def _run(argv, sessions, pool):
    """Run `http_scraper.main` with sessions handed out in order.

    `sessions` is a list: the first is the run's session, every further one
    is what a rotation builds. Nothing here starts a browser, opens a socket
    or sleeps.
    """
    queue = list(sessions)
    built = []

    def build(session_proxy, client=None):
        built.append(client)
        return queue.pop(0)

    def rotate_limit(args):
        return pool

    with mock.patch.object(http_scraper, "build_session", build), \
            mock.patch.object(http_scraper.proxy_pool, "from_args", rotate_limit), \
            mock.patch.object(http_scraper.proxy_pool, "is_2captcha_gateway",
                              lambda url: False), \
            mock.patch.object(http_scraper.time, "sleep", lambda seconds: None):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(out):
            code = http_scraper.main(argv)
    return code, out.getvalue()


def _sidecars(out_prefix):
    with open(out_prefix + ".latest_attempt.meta.json", encoding="utf-8") as handle:
        attempt = json.load(handle)
    meta = None
    if os.path.exists(out_prefix + ".meta.json"):
        with open(out_prefix + ".meta.json", encoding="utf-8") as handle:
            meta = json.load(handle)
    rows = None
    if os.path.exists(out_prefix + ".json"):
        with open(out_prefix + ".json", encoding="utf-8") as handle:
            rows = json.load(handle)
    return meta, attempt, rows


# ---------------------------------------------------------------------------
# 1. The redirect rule itself (curl-shaped answers, the real CurlSession)
# ---------------------------------------------------------------------------

def test_same_store_redirect_is_followed():
    asked, patcher = _install_curl([
        (301, "https://%s/products/delaney/" % STORE,
         "https://%s/products/delaney-marble-end-table/" % STORE, ""),
        (200, PRODUCT_URL, None, US_HTML),
    ])
    try:
        response = http_scraper.CurlSession(None).get(PRODUCT_URL)
    finally:
        patcher.stop()
    assert len(asked) == 2, "the in-store hop must be followed"
    assert response.url == PRODUCT_URL
    assert http_scraper._same_store(response.url)
    assert not response.offsite_redirect
    assert P.detect_page_state(response.text, status=response.status_code,
                               url=response.url) == "product"


def test_same_store_host_match_ignores_case_and_query():
    """The host alone decides: `WWW.` in caps and a `?N=` facet are ours."""
    for target in ("https://WWW.POTTERYBARN.COM/products/x/?N=1",
                   "https://www.potterybarn.com/products/x/?N=1&subGroupId=z",
                   "https://potterybarn.com/products/x/"):
        assert http_scraper._same_store(target), target
    for target in ("https://www.potterybarn.co.uk/products/x/?N=1",
                   "https://WWW.POTTERYBARN.CO.UK/products/x/",
                   "https://www.potterybarnkids.com/products/x/",
                   "https://example.com/products/x/"):
        assert not http_scraper._same_store(target), target


def test_a_redirect_chain_of_exactly_five_hops_is_followed():
    entries = []
    current = PRODUCT_URL
    for hop in range(http_scraper.MAX_REDIRECTS):
        nxt = "https://%s/products/delaney-marble-end-table/?h=%d" % (STORE, hop + 1)
        entries.append((302, current, nxt, ""))
        current = nxt
    entries.append((200, current, None, US_HTML))
    asked, patcher = _install_curl(entries)
    try:
        response = http_scraper.CurlSession(None).get(PRODUCT_URL)
    finally:
        patcher.stop()
    assert len(asked) == http_scraper.MAX_REDIRECTS + 1
    assert response.status_code == 200
    assert response.url == current


def test_one_hop_over_the_limit_raises_instead_of_truncating():
    """Silently returning the 5th redirect would hand a caller a 3xx page as
    if it were the content; the sixth hop must be an error."""
    entries = []
    current = PRODUCT_URL
    for hop in range(http_scraper.MAX_REDIRECTS + 1):
        nxt = "https://%s/products/delaney-marble-end-table/?h=%d" % (STORE, hop + 1)
        entries.append((302, current, nxt, ""))
        current = nxt
    asked, patcher = _install_curl(entries)
    try:
        try:
            http_scraper.CurlSession(None).get(PRODUCT_URL)
            raised = None
        except http_scraper.CurlError as exc:
            raised = str(exc)
    finally:
        patcher.stop()
    assert raised is not None, "an over-long chain must raise, not return a 3xx"
    assert "more than %d redirects" % http_scraper.MAX_REDIRECTS in raised
    # Six requests were made: the five permitted hops plus the one that
    # revealed the sixth. It did not fetch the sixth target.
    assert len(asked) == http_scraper.MAX_REDIRECTS + 1


def test_offsite_hop_is_returned_unfetched_and_marked():
    asked, patcher = _install_curl([
        (302, PRODUCT_URL, UK_URL, ""),
    ])
    try:
        response = http_scraper.CurlSession(None).get(PRODUCT_URL)
    finally:
        patcher.stop()
    assert asked == [PRODUCT_URL], "the UK page must never be requested"
    assert response.offsite_redirect is True
    assert response.url == UK_URL
    assert response.text == "", "no body may be carried for an unfetched hop"
    assert response.status_code == 302
    state = http_scraper.FetchResult(PRODUCT_URL, final_url=response.url,
                                     status=response.status_code,
                                     html=response.text,
                                     offsite_redirect=response.offsite_redirect).state
    assert state == "geo_redirect"


def test_offsite_hop_to_any_other_host_is_the_same_state():
    """The rule is about the US store, not about the UK host by name: a hop to
    a sibling brand is refused too, and reads as `geo_redirect` with no body."""
    for target in ("https://www.potterybarnkids.com/products/x/",
                   "https://example.com/products/x/"):
        asked, patcher = _install_curl([(302, PRODUCT_URL, target, "")])
        try:
            response = http_scraper.CurlSession(None).get(PRODUCT_URL)
        finally:
            patcher.stop()
        assert len(asked) == 1, target
        assert response.offsite_redirect and response.text == ""
        assert P.detect_page_state(response.text, status=response.status_code,
                                   url=response.url,
                                   offsite_redirect=True) == "geo_redirect", target


def test_a_disabled_redirect_leaves_the_redirect_as_the_answer():
    """`allow_redirects=False` is `_once`'s contract: no hop, no mark."""
    asked, patcher = _install_curl([(302, PRODUCT_URL, UK_URL, "")])
    try:
        response = http_scraper.CurlSession(None).get(PRODUCT_URL,
                                                      allow_redirects=False)
    finally:
        patcher.stop()
    assert len(asked) == 1
    assert response.status_code == 302 and not response.offsite_redirect


def test_requests_client_applies_the_same_rule():
    """The two HTTP clients are twins; the rule lives in both `get`s."""
    class FakeRequestsSession:
        def __init__(self):
            self.headers = {}
            self.proxies = {}
            self.hooks = {"response": []}
            self.answers = [
                _RawResponse(301, {"location": "/products/delaney-marble-end-table/"},
                             "", PRODUCT_URL),
                _RawResponse(302, {"location": UK_URL}, UK_HTML, PRODUCT_URL),
            ]

        def get(self, url, timeout=None, allow_redirects=None):
            assert allow_redirects is False, "requests must not follow by itself"
            answer = self.answers.pop(0)
            answer.url = url if answer.url is None else answer.url
            return answer

    session = http_scraper._RequestsSession.__new__(http_scraper._RequestsSession)
    session._session = FakeRequestsSession()
    first = session.get(PRODUCT_URL)
    assert first.offsite_redirect is True, "a hop to the UK host is refused"
    assert first.text == "" and first.url == UK_URL

    session._session.answers = [
        _RawResponse(301, {"location": "https://WWW.POTTERYBARN.COM/products/x/?N=1"},
                     "", PRODUCT_URL),
        _RawResponse(200, {}, US_HTML, None),
    ]
    second = session.get(PRODUCT_URL)
    assert not second.offsite_redirect, "a case-varied in-store hop is followed"
    assert second.text == US_HTML


class _RawResponse:
    """The slice of `requests.Response` the wrapper reads."""

    def __init__(self, status_code, headers, text, url):
        self.status_code = status_code
        self.headers = headers
        self.text = text
        self.url = url


# ---------------------------------------------------------------------------
# 2. End to end: geo-redirect, rotate, success
# ---------------------------------------------------------------------------

def test_geo_redirect_rotates_and_the_new_exit_parses_the_product():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    first = StubSession([_resp(302, "", UK_URL, offsite=True)])
    second = StubSession([_resp(200, US_HTML, PRODUCT_URL)])
    pool = StubPool(count=4)
    code, text = _run(["--url", PRODUCT_URL, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "2",
                       "--retry-delay", "0", "--delay", "0"], [first, second], pool)
    meta, attempt, rows = _sidecars(out)

    assert code == 0, text
    assert [row["sku"] for row in rows] == US_SKUS, "the US product's SKUs, in order"
    assert {row["product_id"] for row in rows} == {"delaney-marble-end-table"}
    assert {row["currency"] for row in rows} == {"USD"}

    facts = meta["transport_facts"]
    assert meta["status"] == "complete" and meta["stop_reason"] == "completed"
    assert facts["geo_redirect_pages"] == [1], "page 1 WAS geo-redirected"
    assert facts["rotations"] == 1, "exactly one exit change"
    # Refused ONCE (the first exit), then answered: the refusal cost an exit
    # and is visible in `refused_pages`, but the page itself did not fail.
    assert facts["refused_pages"] == [1]
    assert facts["failed_pages"] == [], "the page was read in the end"
    assert len(facts["exits_used"]) == 2, "both exits are named"
    assert facts["exits_used"][0] == "http://***:***@gw1:1"
    assert facts["exits_used"][1] == "http://***:***@gw2:2"
    assert facts["exit"] == facts["exits_used"][-1]
    assert "gw2:2" in facts["exits_used"][-1]
    for label in facts["exits_used"]:
        assert "pw" not in label and "user" not in label, "exits are masked"
    assert meta["transport_facts"]["attempt_states"] == ["geo_redirect", "product"]
    assert attempt["transport_facts"]["rotations"] == 1

    # The hop is recorded with the exit that made it, and nothing fetched.
    hops = facts["offsite_targets"]
    assert len(hops) == 1
    assert hops[0]["page"] == 1 and hops[0]["target"] == UK_URL
    assert hops[0]["exit"] == "http://***:***@gw1:1"
    assert hops[0]["status"] == 302


def test_the_uk_page_body_never_reaches_output_or_dump():
    """A careless follow would parse the UK page's 1 SKU and 850 GBP row."""
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    dump = os.path.join(tmp, "pages.html")
    first = StubSession([_resp(302, UK_HTML, UK_URL, offsite=True)])
    second = StubSession([_resp(200, US_HTML, PRODUCT_URL)])
    pool = StubPool(count=2)
    code, text = _run(["--url", PRODUCT_URL, "--out", out, "--format", "json",
                       "--dump-html", dump, "--proxy", pool.current,
                       "--retries", "1", "--retry-delay", "0", "--delay", "0"],
                      [first, second], pool)
    meta, attempt, rows = _sidecars(out)
    assert code == 0

    dumped = [name for name in os.listdir(tmp) if name.startswith("pages")]
    assert dumped == ["pages_p1.html"], "only the US page is dumped (%s)" % dumped
    with open(os.path.join(tmp, "pages_p1.html"), encoding="utf-8") as handle:
        assert handle.read() == US_HTML

    assert "uk-sku-1" not in json.dumps(rows), "no UK SKU in the output"
    assert "GBP" not in json.dumps(rows)
    assert "uk-sku-1" not in json.dumps(meta), "no UK SKU in the sidecar"
    # The off-site target is a URL in the sidecar, never a body.
    assert UK_HTML[:40] not in json.dumps(meta)
    assert "unparsed_pages" not in meta["transport_facts"], \
        "an unfetched hop has no page shape to record"


# ---------------------------------------------------------------------------
# 3. End to end: every exit redirects away
# ---------------------------------------------------------------------------

def test_exhausted_geo_redirects_stop_the_run():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    # One session that always redirects; every rotation hands out a fresh
    # one that does the same.
    sessions = [StubSession([_resp(302, "", UK_URL, offsite=True)]) for _ in range(5)]
    pool = StubPool(count=5)
    code, text = _run(["--url", PRODUCT_URL, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "2",
                       "--retry-delay", "0", "--delay", "0"], sessions, pool)
    meta, attempt, rows = _sidecars(out)

    assert code == http_scraper.output_writer.EXIT_BLOCKED, text
    assert rows is None, "zero rows writes nothing"
    assert meta is None, "a failed run leaves .meta.json (the dataset sidecar) alone"
    assert attempt["status"] == "failed"
    assert attempt["stop_reason"] == "geo_redirect", \
        "a geo-redirect-burned run says so, not just 'blocked'"
    assert attempt["pages_failed"] == [1]
    facts = attempt["transport_facts"]
    assert facts["states"] == ["geo_redirect"]
    assert facts["geo_redirect_pages"] == [1]
    assert facts["blocked"] is True
    # retries=2 -> three attempts, so three exits ISSUED a request. The third
    # retry rotates once more before it gives up, but nothing is ever sent
    # through that fourth exit, so it is not counted as used.
    assert facts["rotations"] == 2, facts["exits_used"]
    assert len(facts["exits_used"]) == 3, facts["exits_used"]
    assert facts["offsite_targets"] and len(facts["offsite_targets"]) == 3
    assert {hop["page"] for hop in facts["offsite_targets"]} == {1}
    assert [hop["exit"] for hop in facts["offsite_targets"]] == facts["exits_used"]
    assert all(hop["target"] == UK_URL for hop in facts["offsite_targets"])
    assert facts["attempt_states"] == ["geo_redirect"] * 3
    assert "geo_redirect" in text


def test_exhaustion_keeps_the_rows_already_read():
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    urls = os.path.join(tmp, "urls.txt")
    with open(urls, "w", encoding="utf-8") as handle:
        handle.write(PRODUCT_URL + "\n" + YORK_URL + "\n")
    # Page 1 is served; page 2 redirects away on this exit and on each of the
    # two exits a rotation hands out. One session spans both pages.
    first = StubSession({PRODUCT_URL: [_resp(200, US_HTML, PRODUCT_URL)],
                         YORK_URL: [_resp(302, "", UK_URL, offsite=True)]})
    rotated = [StubSession({YORK_URL: [_resp(302, "", UK_URL, offsite=True)]})
               for _ in range(2)]
    pool = StubPool(count=3)
    code, text = _run(["--urls-file", urls, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "1",
                       "--retry-delay", "0", "--delay", "0"], [first] + rotated, pool)
    meta, attempt, rows = _sidecars(out)

    assert code == http_scraper.output_writer.EXIT_PARTIAL, text
    assert [row["sku"] for row in rows] == US_SKUS, "the first page's rows survive"
    assert meta["status"] == "partial"
    assert meta["stop_reason"] == "geo_redirect"
    assert meta["pages_completed"] == 1 and meta["pages_failed"] == [2]
    assert meta["products"] == len(US_SKUS)
    assert meta["transport_facts"]["geo_redirect_pages"] == [2]
    assert meta["transport_facts"]["rotations"] == 1, "page 2 was retried once"


def test_a_geo_redirect_answered_by_a_rotation_is_not_a_refusal_of_the_run():
    """The page was finally read: the run is complete. The refusal shows up
    only where it belongs — `geo_redirect_pages` and the attempt states —
    and never in the keys that describe the run's OUTCOME."""
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    first = StubSession([_resp(302, "", UK_URL, offsite=True)])
    second = StubSession([_resp(200, US_HTML, PRODUCT_URL)])
    pool = StubPool(count=3)
    code, text = _run(["--url", PRODUCT_URL, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "2",
                       "--retry-delay", "0", "--delay", "0"], [first, second], pool)
    meta, _, _ = _sidecars(out)
    assert code == 0, text
    assert meta["blocked"] is False
    facts = meta["transport_facts"]
    assert facts["geo_redirect_pages"] == [1]
    assert facts["geo_redirect_failures"] == [], "the page was not finally refused"
    assert facts["failed_pages"] == []
    assert facts["refused_pages"] == [1], "it was refused once, by the first exit"
    assert facts["states"] == ["product"]


def test_rotations_count_changes_not_distinct_exits():
    """A two-exit pool rotated three times goes back through the first exit;
    a run that burned exits must report three, not "two distinct - 1"."""
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    sessions = [StubSession([_resp(302, "", UK_URL, offsite=True)]) for _ in range(4)]
    pool = StubPool(count=2)
    code, text = _run(["--url", PRODUCT_URL, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "3",
                       "--retry-delay", "0", "--delay", "0"], sessions, pool)
    meta, attempt, _ = _sidecars(out)
    assert code == http_scraper.output_writer.EXIT_BLOCKED, text
    facts = attempt["transport_facts"]
    assert facts["rotations"] == 3, facts["exit_sequence"]
    assert len(facts["exits_used"]) == 2, "only two distinct exits exist"
    assert facts["exit_sequence"] == [
        "http://***:***@gw1:1", "http://***:***@gw2:2",
        "http://***:***@gw1:1", "http://***:***@gw2:2",
    ]


def test_a_real_403_after_a_recovered_geo_redirect_is_still_a_block():
    """A page that hopped off once and was READ must not relabel a later 403
    as a geo-redirect: the two refusals want different operator responses."""
    tmp = tempfile.mkdtemp()
    out = os.path.join(tmp, "run")
    urls = os.path.join(tmp, "urls.txt")
    with open(urls, "w", encoding="utf-8") as handle:
        handle.write(PRODUCT_URL + "\n" + YORK_URL + "\n")
    first = StubSession({PRODUCT_URL: [_resp(302, "", UK_URL, offsite=True)]})
    second = StubSession({PRODUCT_URL: [_resp(200, US_HTML, PRODUCT_URL)],
                          YORK_URL: [_resp(403, "<html>refused</html>", YORK_URL)]})
    # Page 2's 403 is retried once and rotated once; the third exit answers
    # with the same refusal, so the run ends blocked on a plain 403.
    third = StubSession({YORK_URL: [_resp(403, "<html>refused</html>", YORK_URL)]})
    pool = StubPool(count=3)
    code, text = _run(["--urls-file", urls, "--out", out, "--format", "json",
                       "--proxy", pool.current, "--retries", "1",
                       "--retry-delay", "0", "--delay", "0"],
                      [first, second, third], pool)
    meta, _, _ = _sidecars(out)
    assert code == http_scraper.output_writer.EXIT_PARTIAL, text
    facts = meta["transport_facts"]
    assert facts["geo_redirect_pages"] == [1], "page 1 did hop off"
    assert facts["geo_redirect_failures"] == [], "but it was read in the end"
    assert facts["states"] == ["product", "blocked"]
    assert meta["stop_reason"] == "blocked", "the 403 is the reason, not the hop"


# ---------------------------------------------------------------------------
# 4. The classifier's own contract
# ---------------------------------------------------------------------------

def test_detect_page_state_takes_the_offsite_mark():
    assert P.detect_page_state("", status=302, url=UK_URL) == "geo_redirect"
    assert P.detect_page_state("", status=302, url=PRODUCT_URL,
                               offsite_redirect=True) == "geo_redirect"
    # The mark wins over a product-shaped body: an unfetched hop has none,
    # but a stray body must never turn it back into a product.
    assert P.detect_page_state(US_HTML, status=200, url=PRODUCT_URL,
                               offsite_redirect=True) == "geo_redirect"
    # And with no mark, a redirect status with no body is not a refusal.
    assert P.detect_page_state("", status=302, url=PRODUCT_URL) == "transport_error"


def test_page_flow_treats_geo_redirect_as_a_rotating_refusal():
    import page_flow
    assert page_flow.should_retry("geo_redirect") is True
    assert page_flow.should_rotate_exit("geo_redirect") is True
    assert page_flow.counts_as_blocked("geo_redirect") is True


# ---------------------------------------------------------------------------
# Entry point (no pytest needed)
# ---------------------------------------------------------------------------

def main():
    failures = []
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith("test_") and callable(fn)]
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failures.append((name, str(exc)))
            print("FAIL %s: %s" % (name, exc))
        else:
            print("PASS %s" % name)
    print("\n%d passed, %d failed" % (len(tests) - len(failures), len(failures)))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
