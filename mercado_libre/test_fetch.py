"""Offline tests for fetch_product_result: the verifiable conclusion of a
product / item / user-product fetch (final shape, catalog->item fallback,
failure reason category).

    python -m pytest mercado_libre/test_fetch.py -q

No network: the new fetch_product_result entry takes an injected fake page
getter (the same shape as get_page: (url, label) -> (html, final_url), or it
raises one of the fetch.py transport errors). The four required scenarios
plus the retry/non-retry policy and an end-to-end smoke over the real
captured pages in mercado_libre/fixtures/ are covered.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mercado_libre import parsers as P  # noqa: E402
from mercado_libre import refs  # noqa: E402
from mercado_libre.fetch import (  # noqa: E402
    FAILURE_REASONS,
    PRODUCT_KINDS,
    MercadoLibreBadRequest,
    MercadoLibreBlocked,
    MercadoLibreNotFound,
    MercadoLibreUpstreamError,
    fetch_product,
    fetch_product_result,
)

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
ID = "MLA1932888020"
SITE = "MLA"
PRODUCT_URL = refs.product_link(SITE, ID)
ITEM_URL = refs.item_link(SITE, ID)


def fixture(name):
    with open(os.path.join(FX, name), encoding="utf-8") as f:
        return json.load(f) if name.endswith(".json") else f.read()


def state_html(name):
    """A state-only fixture rendered as a skipWebview page: the state object
    inlined exactly the way the mobile site carries it (`_n.ctx.r={...}`)."""
    return "<html><script>_n.ctx.r=" + json.dumps(fixture(name), ensure_ascii=False) + ";</script></html>"


PRODUCT_HTML = fixture("product_moto_g04s_mla.html")
PRODUCT_FINAL = refs.product_link(SITE, ID) + "?skipWebview=true"
ITEM_HTML = state_html("item_necklace_variations_mla.state.json")
ITEM_FINAL = refs.item_link(SITE, ID) + "?skipWebview=true"
NOT_FOUND_HTML = state_html("product_not_found_mla.state.json")


def ref(kind="unknown", ident=ID):
    return {"id": ident, "kind": kind, "site": SITE}


class FakePager:
    """A stand-in for get_page: routes by URL shape, returns scripted
    (html, final_url) results or raises scripted transport errors, and
    records every call so the request sequence is assertable."""

    def __init__(self, product=None, item=None, user_product=None):
        # None means "no script for that URL": raise loudly instead of
        # silently returning something that could hide a wrong request.
        self._script = {"product": product, "item": item, "user_product": user_product}
        self.calls = []

    def _shape(self, url):
        if "/up/" in url:
            return "user_product"
        if "/p/" in url:
            return "product"
        return "item"

    def __call__(self, url, label):
        shape = self._shape(url)
        self.calls.append((shape, url, label))
        scripted = self._script[shape]
        if scripted is None:
            raise AssertionError(f"unexpected {shape} request: {url}")
        if isinstance(scripted, Exception):
            raise scripted
        return scripted


def not_found(shape):
    return MercadoLibreNotFound(f"{shape} not found")


# ---- the four required scenarios -----------------------------------------------------------

def test_catalog_product_succeeds_directly():
    pager = FakePager(product=(PRODUCT_HTML, PRODUCT_FINAL))
    result = fetch_product_result(ref(), page_getter=pager)

    assert result.ok is True
    assert result.kind == "product"
    assert result.fell_back is False
    assert result.reason is None
    assert result.html is PRODUCT_HTML and result.final_url == PRODUCT_FINAL
    assert result.error is None
    assert [call[0] for call in pager.calls] == ["product"]


def test_catalog_not_found_falls_back_to_item_and_succeeds():
    pager = FakePager(product=not_found("product"), item=(ITEM_HTML, ITEM_FINAL))
    result = fetch_product_result(ref(), page_getter=pager)

    assert result.ok is True
    assert result.kind == "item"
    assert result.fell_back is True
    assert result.reason is None
    assert result.html == ITEM_HTML and result.final_url == ITEM_FINAL
    assert [call[0] for call in pager.calls] == ["product", "item"]
    # the fallback only fires on a catalog NotFound; labels keep shape
    assert pager.calls[0][2] == f"product {ID}" and pager.calls[1][2] == f"item {ID}"


def test_both_shapes_missing_is_one_not_found_conclusion():
    pager = FakePager(product=not_found("product"), item=not_found("item"))
    result = fetch_product_result(ref(), page_getter=pager)

    assert result.ok is False
    assert result.kind is None
    assert result.fell_back is True
    assert result.reason == "not_found"
    assert isinstance(result.error, MercadoLibreNotFound)
    assert result.html is None and result.final_url is None
    assert [call[0] for call in pager.calls] == ["product", "item"]
    # the conclusion never raises itself; the original error is re-raised on demand
    with pytest.raises(MercadoLibreNotFound):
        result.raise_on_error()


def test_catalog_blocked_does_not_fall_back_and_reports_blocked():
    blocked = MercadoLibreBlocked("HTTP 403 for product")
    pager = FakePager(product=blocked)
    result = fetch_product_result(ref(), page_getter=pager)

    assert result.ok is False
    assert result.kind is None
    assert result.fell_back is False
    assert result.reason == "blocked"
    assert result.error is blocked
    # a blocked catalog request must never be retried against the item URL
    assert [call[0] for call in pager.calls] == ["product"]
    with pytest.raises(MercadoLibreBlocked):
        result.raise_on_error()


# ---- reason categories cover the whole taxonomy --------------------------------------------

def test_upstream_and_bad_request_categories_never_fall_back():
    upstream = FakePager(product=MercadoLibreUpstreamError("HTTP 502 for product"))
    result = fetch_product_result(ref(), page_getter=upstream)
    assert result.ok is False and result.reason == "upstream"
    assert result.fell_back is False and result.kind is None
    assert isinstance(result.error, MercadoLibreUpstreamError)
    assert [call[0] for call in upstream.calls] == ["product"]

    bad = FakePager(product=MercadoLibreBadRequest("400"))
    result = fetch_product_result(ref(), page_getter=bad)
    assert result.ok is False and result.reason == "bad_request"
    assert result.fell_back is False and result.kind is None
    assert isinstance(result.error, MercadoLibreBadRequest)
    assert [call[0] for call in bad.calls] == ["product"]


def test_item_failure_after_fallback_keeps_its_own_reason():
    pager = FakePager(product=not_found("product"),
                      item=MercadoLibreBlocked("HTTP 429 for item"))
    result = fetch_product_result(ref(), page_getter=pager)
    assert result.ok is False
    assert result.kind is None and result.fell_back is True
    assert result.reason == "blocked"
    assert isinstance(result.error, MercadoLibreBlocked)
    assert [call[0] for call in pager.calls] == ["product", "item"]


def test_explicit_refs_skip_the_catalog_probe():
    # an explicit item ref goes straight to the item URL
    item_pager = FakePager(item=(ITEM_HTML, ITEM_FINAL))
    result = fetch_product_result(ref("item"), page_getter=item_pager)
    assert result.ok and result.kind == "item" and result.fell_back is False
    assert [call[0] for call in item_pager.calls] == ["item"]

    # an explicit user-product ref goes straight to the /up/ URL
    up_pager = FakePager(user_product=(ITEM_HTML, ITEM_FINAL))
    result = fetch_product_result(ref("user_product", "MLAU3735180826"), page_getter=up_pager)
    assert result.ok and result.kind == "user_product" and result.fell_back is False
    assert [call[0] for call in up_pager.calls] == ["user_product"]

    # an explicit product (/p/) ref has no item shape to fall back to
    missing = FakePager(product=not_found("product"), item=(ITEM_HTML, ITEM_FINAL))
    result = fetch_product_result(ref("product"), page_getter=missing)
    assert not result.ok and result.reason == "not_found" and result.fell_back is False
    assert [call[0] for call in missing.calls] == ["product"]


def test_explicit_item_and_user_product_failures_keep_their_reasons():
    for kind, shape in (("item", "item"), ("user_product", "user_product")):
        pager = FakePager(**{shape: MercadoLibreUpstreamError("transport down")})
        result = fetch_product_result(ref(kind, "MLAU3735180826" if kind == "user_product" else ID),
                                      page_getter=pager)
        assert not result.ok and result.reason == "upstream"
        assert result.kind is None and result.fell_back is False
        assert [call[0] for call in pager.calls] == [shape]


# ---- backward-compatible fetch_product wrapper ----------------------------------------------

def test_fetch_product_returns_the_old_tuple_and_raises_the_old_error():
    ok = FakePager(product=(PRODUCT_HTML, PRODUCT_FINAL))
    html, final, kind = fetch_product(ref(), page_getter=ok)
    assert kind == "product" and html is PRODUCT_HTML and final == PRODUCT_FINAL

    fallback = FakePager(product=not_found("product"), item=(ITEM_HTML, ITEM_FINAL))
    html, final, kind = fetch_product(ref(), page_getter=fallback)
    assert kind == "item" and html == ITEM_HTML and final == ITEM_FINAL

    blocked = FakePager(product=MercadoLibreBlocked("HTTP 403"))
    with pytest.raises(MercadoLibreBlocked):
        fetch_product(ref(), page_getter=blocked)
    missing = FakePager(product=not_found("product"), item=not_found("item"))
    with pytest.raises(MercadoLibreNotFound):
        fetch_product(ref(), page_getter=missing)


def test_reason_and_kind_vocabularies_are_stable():
    assert set(FAILURE_REASONS) == {"not_found", "blocked", "upstream", "bad_request"}
    assert set(PRODUCT_KINDS) == {"product", "item", "user_product"}


# ---- get_page retry policy stays unchanged --------------------------------------------------

class FakeResponse:
    def __init__(self, status_code, text="<html>shell</html>", url=None):
        self.status_code = status_code
        self.text = text
        self.url = url or (PRODUCT_URL + "?skipWebview=true")


def _patched_session(monkeypatch, response=None, exc=None):
    """Point fetch._session() at a session whose .get() returns the fake
    response or raises the fake transport exception."""
    class FakeSession:
        def __init__(self):
            self.gets = 0

        def get(self, *args, **kwargs):
            self.gets += 1
            if exc is not None:
                raise exc
            return response

        def close(self):
            pass

    session = FakeSession()
    monkeypatch.setattr("mercado_libre.fetch._session", lambda lane="main": session)
    monkeypatch.setattr("mercado_libre.fetch.time.sleep", lambda *_: None)
    return session


def test_blocked_and_upstream_still_retry_to_max_retries(monkeypatch):
    blocked_session = _patched_session(monkeypatch, response=FakeResponse(403))
    # get_page itself must still apply MAX_RETRIES to a block
    import config
    from mercado_libre.fetch import get_page
    with pytest.raises(MercadoLibreBlocked):
        get_page(PRODUCT_URL, "product")
    assert blocked_session.gets == config.MAX_RETRIES

    failed_session = _patched_session(monkeypatch, exc=ConnectionError("exit gone"))
    with pytest.raises(MercadoLibreUpstreamError):
        get_page(PRODUCT_URL, "product")
    assert failed_session.gets == config.MAX_RETRIES


def test_not_found_and_bad_request_are_not_retried(monkeypatch):
    not_found_session = _patched_session(monkeypatch, response=FakeResponse(404))
    from mercado_libre.fetch import get_page
    with pytest.raises(MercadoLibreNotFound):
        get_page(PRODUCT_URL, "product")
    assert not_found_session.gets == 1

    bad_session = _patched_session(monkeypatch, response=FakeResponse(400))
    with pytest.raises(MercadoLibreBadRequest):
        get_page(PRODUCT_URL, "product")
    assert bad_session.gets == 1


# ---- end-to-end smoke over the real captured pages ------------------------------------------

def test_smoke_real_catalog_product_page_parses_a_title():
    """The whole fetch_product_result -> parser chain against the real
    captured catalog page (product_moto_g04s_mla.html): no network, but the
    exact bytes get_page would have returned."""
    pager = FakePager(product=(PRODUCT_HTML, PRODUCT_FINAL))
    result = fetch_product_result(ref("unknown", "MLA39328824"), page_getter=pager)

    assert result.ok and result.kind == "product" and result.fell_back is False
    state = P.extract_state(result.html)
    record = P.parse_product(state, page_url=result.final_url.split("?")[0], site=SITE)
    assert record is not None
    assert record["title"] == "Motorola Moto G04s Sunrise Orange 64gb 4gb"


def test_smoke_real_404_then_real_item_page_falls_back_and_parses():
    """Both product-not-found and item pages are real fixtures: the catalog
    404 shell drives the fallback, the captured item state then parses."""
    item_html = state_html("item_necklace_variations_mla.state.json")
    pager = FakePager(
        product=MercadoLibreNotFound("product not found"),
        item=(item_html, ITEM_FINAL),
    )
    result = fetch_product_result(ref(), page_getter=pager)
    assert result.ok and result.kind == "item" and result.fell_back is True

    record = P.parse_product(P.extract_state(result.html),
                             page_url=result.final_url.split("?")[0], site=SITE)
    assert record is not None and record["title"]
