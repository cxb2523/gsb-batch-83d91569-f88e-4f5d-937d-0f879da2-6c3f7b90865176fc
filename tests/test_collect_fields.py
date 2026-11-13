"""Unit tests for Fantoma.collect_fields — field-level DOM collection.

Everything is mocked: no browser process, no network. A FakeElement routes
element.evaluate(js) to canned answers keyed by the reader script, so the
tests exercise the real Python dispatch and result contract while the page
side is deterministic.
"""
import pytest
from unittest.mock import MagicMock

from fantoma.browser_tool import (
    Fantoma, _FIELD_TEXT_JS, _FIELD_VALUE_JS, _FIELD_SELECT_JS,
)


class FakePage:
    """Minimal stand-in for a Playwright Page.

    selector_map: CSS selector -> FakeElement | None (None = no match).
    query_error: raised by query_selector when set (invalid selector etc.).
    """

    def __init__(self, selector_map=None, query_error=None):
        self.selector_map = selector_map or {}
        self.query_error = query_error
        self.url = "https://shop.example/product"

    def query_selector(self, selector):
        if self.query_error is not None:
            raise self.query_error
        return self.selector_map.get(selector)


class FakeElement:
    """Element handle whose evaluate answers depend on the reader JS sent."""

    def __init__(self, answers=None, eval_error=None):
        # answers maps the module JS constant to the value to return.
        self.answers = answers or {}
        self.eval_error = eval_error
        self.evaluate_calls = []

    def evaluate(self, js, *args, **kwargs):
        self.evaluate_calls.append(js)
        if self.eval_error is not None:
            raise self.eval_error
        if js not in self.answers:
            raise KeyError(f"FakeElement has no canned answer for reader {js[:40]!r}")
        return self.answers[js]


def _fantoma(page, page_crashed=False):
    """A Fantoma with no browser: engine and DOM extractor are mocks."""
    f = Fantoma()
    f._engine = MagicMock()
    f._engine.get_page.return_value = page
    f._engine.page_crashed.return_value = page_crashed
    f._dom = MagicMock()
    return f


def _by_name(results):
    return {r["name"]: r for r in results}


class TestAllFieldsSucceed:
    def test_text_value_native_select_and_scripted_combobox(self):
        title = FakeElement({_FIELD_TEXT_JS: "Fleece Jacket"})
        price = FakeElement({_FIELD_TEXT_JS: "$49.99"})
        email = FakeElement({_FIELD_VALUE_JS: {"ok": True, "value": "buyer@example.com"}})
        native = FakeElement({_FIELD_SELECT_JS: {"ok": True, "value": "Medium"}})
        combo = FakeElement({_FIELD_SELECT_JS: {"ok": True, "value": "Blue"}})
        listbox = FakeElement({_FIELD_SELECT_JS: {"ok": True, "value": "Express shipping"}})

        page = FakePage({
            "h1.product-title": title,
            ".price": price,
            "#email": email,
            "#size": native,
            "#color": combo,
            "#ship": listbox,
        })
        f = _fantoma(page)
        # One field located by ARIA number, the rest by CSS selector.
        f._dom.get_element_by_index.return_value = title

        results = f.collect_fields([
            {"name": "title", "type": "text", "aria": 0},
            {"name": "price", "type": "text", "selector": ".price"},
            {"name": "email", "type": "value", "selector": "#email"},
            {"name": "size", "type": "select", "selector": "#size"},
            {"name": "color", "type": "select", "selector": "#color"},
            {"name": "shipping", "type": "select", "selector": "#ship"},
        ])

        assert len(results) == 6
        assert all(r["ok"] is True for r in results)
        by = _by_name(results)
        assert by["title"]["value"] == "Fleece Jacket"
        assert by["price"]["value"] == "$49.99"
        assert by["email"]["value"] == "buyer@example.com"
        assert by["size"]["value"] == "Medium"
        assert by["color"]["value"] == "Blue"
        assert by["shipping"]["value"] == "Express shipping"
        # Every successful result carries an empty reason and keeps name/order.
        assert [r["name"] for r in results] == [
            "title", "price", "email", "size", "color", "shipping"]
        assert all(set(r) == {"name", "ok", "value", "reason"} for r in results)
        f._dom.get_element_by_index.assert_called_once_with(page, 0)

    def test_text_read_uses_visible_text_reader(self):
        el = FakeElement({_FIELD_TEXT_JS: "Some rendered text"})
        f = _fantoma(FakePage({"#x": el}))
        f.collect_fields([{"name": "x", "type": "text", "selector": "#x"}])
        assert _FIELD_TEXT_JS in el.evaluate_calls


class TestPartialLocatorFailures:
    def test_missing_aria_number_and_missing_selector_do_not_abort_batch(self):
        ok_el = FakeElement({_FIELD_TEXT_JS: "Visible heading"})
        page = FakePage({".present": ok_el})
        f = _fantoma(page)
        # ARIA number 7 is stale — the element is gone.
        f._dom.get_element_by_index.return_value = None

        results = f.collect_fields([
            {"name": "gone_aria", "type": "text", "aria": 7},
            {"name": "present", "type": "text", "selector": ".present"},
            {"name": "gone_css", "type": "text", "selector": ".does-not-exist"},
        ])

        assert len(results) == 3
        by = _by_name(results)
        assert by["gone_aria"]["ok"] is False
        assert by["gone_aria"]["value"] == ""
        assert "7" in by["gone_aria"]["reason"] and "not found" in by["gone_aria"]["reason"]
        assert by["gone_css"]["ok"] is False
        assert by["gone_css"]["value"] == ""
        assert ".does-not-exist" in by["gone_css"]["reason"]
        # The good field still succeeds and is untouched by the failures.
        assert by["present"]["ok"] is True
        assert by["present"]["value"] == "Visible heading"

    def test_selector_that_throws_is_reported_not_raised(self):
        def query_selector(selector):
            if selector == ">>>":
                raise SyntaxError("not a valid selector: >>>")
            return None  # the other selector simply matches nothing

        page = MagicMock()
        page.url = "https://shop.example/product"
        page.query_selector.side_effect = query_selector
        f = _fantoma(page)
        results = f.collect_fields([
            {"name": "bad", "type": "text", "selector": ">>>"},
            {"name": "ok", "type": "text", "selector": "#fine"},
        ])
        by = _by_name(results)
        assert by["bad"]["ok"] is False
        assert "SyntaxError" in by["bad"]["reason"]
        # The second selector is attempted even though the first threw.
        assert by["ok"]["ok"] is False
        assert "no element matches" in by["ok"]["reason"]


class TestScriptedDropdownWithoutSelection:
    def test_combobox_without_selected_option_fails(self):
        combo = FakeElement({_FIELD_SELECT_JS: {
            "ok": False,
            "reason": "scripted dropdown (role=combobox) has no selected option",
        }})
        f = _fantoma(FakePage({"#color": combo}))
        results = f.collect_fields([
            {"name": "color", "type": "select", "selector": "#color"}])
        r = results[0]
        assert r == {"name": "color", "ok": False, "value": "",
                     "reason": "scripted dropdown (role=combobox) has no selected option"}

    def test_listbox_without_selection_fails_too(self):
        listbox = FakeElement({_FIELD_SELECT_JS: {
            "ok": False,
            "reason": "scripted dropdown (role=listbox) has no selected option",
        }})
        f = _fantoma(FakePage({"#ship": listbox}))
        r = f.collect_fields([{"name": "ship", "type": "select", "selector": "#ship"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "no selected option" in r["reason"]

    def test_native_select_without_selection_fails(self):
        native = FakeElement({_FIELD_SELECT_JS: {
            "ok": False,
            "reason": "native <select> has no selected option",
        }})
        f = _fantoma(FakePage({"#size": native}))
        r = f.collect_fields([{"name": "size", "type": "select", "selector": "#size"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "no selected option" in r["reason"]

    def test_dropdown_reader_is_used_for_select_type(self):
        combo = FakeElement({_FIELD_SELECT_JS: {"ok": True, "value": "Red"}})
        f = _fantoma(FakePage({"#c": combo}))
        f.collect_fields([{"name": "c", "type": "select", "selector": "#c"}])
        assert _FIELD_SELECT_JS in combo.evaluate_calls


class TestPageCrashAndClosure:
    def test_crashed_page_fails_every_field_with_readable_reason(self):
        f = _fantoma(FakePage(), page_crashed=True)
        results = f.collect_fields([
            {"name": "a", "type": "text", "selector": "#a"},
            {"name": "b", "type": "value", "aria": 2},
            {"name": "c", "type": "select", "selector": "#c"},
        ])
        assert len(results) == 3
        for r in results:
            assert r["ok"] is False
            assert r["value"] == ""
            assert "crashed" in r["reason"] or "closed" in r["reason"]
        # Nothing on the dead page is ever touched.
        f._dom.get_element_by_index.assert_not_called()

    def test_closed_tab_surfacing_from_get_page_does_not_raise(self):
        f = Fantoma()
        f._engine = MagicMock()
        f._engine.get_page.side_effect = RuntimeError("Target page, context or browser has been closed")
        f._dom = MagicMock()

        results = f.collect_fields([
            {"name": "a", "type": "text", "selector": "#a"},
            {"name": "b", "type": "text", "selector": "#b"},
        ])
        assert len(results) == 2
        assert all(r["ok"] is False and r["value"] == "" for r in results)
        assert all("unavailable" in r["reason"] or "closed" in r["reason"]
                   for r in results)

    def test_no_engine_yet_reports_not_open(self):
        f = Fantoma()
        f._engine = None
        results = f.collect_fields([{"name": "a", "type": "text", "selector": "#a"}])
        assert results[0]["ok"] is False
        assert "not open" in results[0]["reason"]

    def test_crash_mid_batch_keeps_collecting_remaining_fields(self):
        good = FakeElement({_FIELD_TEXT_JS: "still here"})
        exploding = FakeElement(eval_error=RuntimeError("Target closed"))
        page = FakePage({"#good": good, "#dead": exploding})
        f = _fantoma(page)

        results = f.collect_fields([
            {"name": "dead", "type": "text", "selector": "#dead"},
            {"name": "good", "type": "text", "selector": "#good"},
        ])
        by = _by_name(results)
        assert by["dead"]["ok"] is False
        assert "Target closed" in by["dead"]["reason"]
        assert by["good"]["ok"] is True and by["good"]["value"] == "still here"


class TestTypeMismatchesAndEmptyValues:
    def test_value_on_non_input_is_type_mismatch(self):
        div = FakeElement({_FIELD_VALUE_JS: {
            "ok": False, "reason": "not an input element (got <div>)"}})
        f = _fantoma(FakePage({"#note": div}))
        r = f.collect_fields([{"name": "note", "type": "value", "selector": "#note"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "not an input" in r["reason"]

    def test_select_on_plain_element_is_type_mismatch(self):
        span = FakeElement({_FIELD_SELECT_JS: {
            "ok": False,
            "reason": "not a dropdown: expected <select> or role=combobox/listbox (got <span>)"}})
        f = _fantoma(FakePage({"#s": span}))
        r = f.collect_fields([{"name": "s", "type": "select", "selector": "#s"}])[0]
        assert r["ok"] is False
        assert "dropdown" in r["reason"]

    def test_empty_text_is_not_a_success(self):
        el = FakeElement({_FIELD_TEXT_JS: "   "})
        f = _fantoma(FakePage({"#blank": el}))
        r = f.collect_fields([{"name": "blank", "type": "text", "selector": "#blank"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "no visible text" in r["reason"]

    def test_empty_input_value_is_not_a_success(self):
        el = FakeElement({_FIELD_VALUE_JS: {"ok": True, "value": ""}})
        f = _fantoma(FakePage({"#empty": el}))
        r = f.collect_fields([{"name": "empty", "type": "value", "selector": "#empty"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "no current value" in r["reason"]

    def test_unknown_type_fails_the_field(self):
        f = _fantoma(FakePage())
        r = f.collect_fields([{"name": "x", "type": "html", "selector": "#x"}])[0]
        assert r["ok"] is False and r["value"] == ""
        assert "html" in r["reason"]

    def test_no_locator_fails_the_field(self):
        f = _fantoma(FakePage())
        r = f.collect_fields([{"name": "x", "type": "text"}])[0]
        assert r["ok"] is False and "locator" in r["reason"]


class TestFieldDefinitionIsolation:
    def test_malformed_definitions_are_reported_per_field(self):
        good = FakeElement({_FIELD_TEXT_JS: "fine"})
        f = _fantoma(FakePage({"#g": good}))
        results = f.collect_fields([
            "not-a-dict",
            {"name": "no-type", "selector": "#g"},
            {"name": "", "type": "text", "selector": "#g"},       # empty name still collected
            {"name": "good", "type": "text", "selector": "#g"},
            {"name": "bad-aria", "type": "text", "aria": "3"},
        ])
        assert len(results) == 5
        assert results[0]["ok"] is False and "dict" in results[0]["reason"]
        assert results[1]["ok"] is False and "type" in results[1]["reason"]
        # An empty name is a valid key; the read itself succeeds.
        assert results[2]["name"] == "" and results[2]["ok"] is True
        assert results[3]["ok"] is True and results[3]["value"] == "fine"
        # aria given as a string is rejected rather than silently mis-resolved
        assert results[4]["ok"] is False and "int" in results[4]["reason"]

    def test_one_field_exception_never_poisons_another(self):
        boom = FakeElement(eval_error=ValueError("execution context destroyed"))
        calm = FakeElement({_FIELD_TEXT_JS: "calm"})
        page = FakePage({"#boom": boom, "#calm": calm})
        f = _fantoma(page)
        results = f.collect_fields([
            {"name": "boom", "type": "text", "selector": "#boom"},
            {"name": "calm", "type": "text", "selector": "#calm"},
        ])
        by = _by_name(results)
        assert by["boom"]["ok"] is False
        assert "ValueError" in by["boom"]["reason"]
        assert by["calm"]["ok"] is True and by["calm"]["value"] == "calm"

    def test_non_list_input_is_a_programming_error(self):
        f = _fantoma(FakePage())
        with pytest.raises(TypeError):
            f.collect_fields({"name": "x", "type": "text", "selector": "#x"})

    def test_empty_batch_returns_empty_results(self):
        f = _fantoma(FakePage())
        assert f.collect_fields([]) == []
