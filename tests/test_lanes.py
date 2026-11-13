"""AnyAPI source pinning and the price baseline, offline."""
import pytest

from getcheapapi import lanes as L


def lane(sid, usd, fields=None):
    return {"source": {"id": sid}, "pricing": {"baseUsd": usd}, **({"fields": fields} if fields else {})}


LANES = [lane("cheap", 0.0005, ["items"]), lane("near", 0.0007, ["items", "nextCursor"]),
         lane("dear", 0.01, ["items", "nextCursor"])]


def test_pin_keeps_sources_within_ratio_and_disables_fallback(tmp_path):
    body, allowed, price = L.pin("sku", {"query": "x"}, LANES, 1.5, tmp_path / "b.json")
    assert body["source"] == ["cheap", "near"] and body["allowFallbacks"] is False
    assert allowed == {"cheap", "near"} and price == pytest.approx(0.0007)


def test_pin_defaults_to_the_cheapest_source_only(tmp_path):
    body, allowed, price = L.pin("sku", {"query": "x"}, LANES, baseline=tmp_path / "b.json")
    assert body["source"] == ["cheap"] and body["allowFallbacks"] is False
    assert allowed == {"cheap"} and price == pytest.approx(0.0005)


def test_pin_names_one_source_even_when_tied(tmp_path):
    body, allowed, _ = L.pin("sku", {}, LANES + [lane("tied", 0.0005)], baseline=tmp_path / "b.json")
    assert body["source"] == ["cheap"] and allowed == {"cheap"}


def test_explicit_source_gets_no_fallback_unless_asked(tmp_path):
    body, allowed, price = L.pin("sku", {"source": ["near"]}, LANES, baseline=tmp_path / "b.json")
    assert body["allowFallbacks"] is False and allowed == {"near"} and price == pytest.approx(0.0007)
    body, allowed, _ = L.pin("sku", {"source": ["near"], "allowFallbacks": True}, LANES, baseline=tmp_path / "b.json")
    assert body["allowFallbacks"] is True and allowed == {"cheap", "near", "dear"}


def test_pin_refuses_when_only_dear_sources_return_required_field(tmp_path):
    with pytest.raises(L.PricierOnly):
        L.pin("sku", {"requireFields": ["nextCursor"]}, [LANES[0], LANES[2]], 1.5, tmp_path / "b.json")


def test_baseline_tracks_lowest_and_stops_on_rise(tmp_path):
    path = tmp_path / "b.json"
    L.pin("sku", {}, LANES, 1.5, path)
    assert L.load_baseline(path)["sku"]["usd"] == pytest.approx(0.0005)
    L.pin("sku", {}, [lane("cheaper", 0.0004)] + LANES, 1.5, path)  # a price drop lowers the baseline
    assert L.load_baseline(path)["sku"]["usd"] == pytest.approx(0.0004)
    with pytest.raises(L.PriceRose):
        L.pin("sku", {}, LANES[1:], 1.5, path)  # cheapest now 0.0007 > 1.5 x 0.0004
    L.accept_price("sku", LANES[1:], path)
    L.pin("sku", {}, LANES[1:], 1.5, path)  # accepted: runs again


def test_served_ok_flags_wrong_source_or_overcharge():
    assert L.served_ok({"source": {"id": "cheap"}, "costUsd": 0.0005}, {"cheap"}, 0.0007) is None
    assert L.served_ok({"source": {"id": "dear"}, "costUsd": 0.0005}, {"cheap"}, 0.0007)
    assert L.served_ok({"source": {"id": "cheap"}, "costUsd": 0.01}, {"cheap"}, 0.0007)


def test_cheapest_respects_require_fields():
    assert L.cheapest(LANES, {}) == pytest.approx(0.0005)
    assert L.cheapest(LANES, {"requireFields": ["nextCursor"]}) == pytest.approx(0.0007)
