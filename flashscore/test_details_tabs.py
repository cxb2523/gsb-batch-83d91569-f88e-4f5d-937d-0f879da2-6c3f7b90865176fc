"""Offline tests for the per-tab orchestration `/matches/details` uses —
no network.

Two layers are covered:

  * fetch.gather_tabs: a mixed batch (one success, one NotFound, one
    Blocked, one empty body, one transport failure) keeps every tab's own
    outcome, and an all-failing batch still returns a record per tab instead
    of raising.
  * matches.get_details: the base match card survives a mixed tab batch, the
    failures name their category, and an all-failed batch still returns the
    card with no usable tabs.

The transport is replaced with locally constructed callables, so nothing here
touches curl_cffi or flashscore.com.

    python -m pytest flashscore/test_details_tabs.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flashscore import matches     # noqa: E402
from flashscore.fetch import (FAILURE_BLOCKED, FAILURE_UPSTREAM,  # noqa: E402
                              TAB_FAILED, TAB_NO_DATA, TAB_OK,
                              FlashscoreBlocked, FlashscoreNotFound,
                              FlashscoreUpstreamError, gather_tabs)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


# ---- gather_tabs: the orchestration primitive ---------------------------------------

def test_gather_tabs_keeps_each_tabs_own_outcome():
    def blocked():
        raise FlashscoreBlocked("HTTP 403 on feed df_hh")

    def missing():
        raise FlashscoreNotFound("df_st not found")

    def failed():
        raise FlashscoreUpstreamError("HTTP 502 on feed df_scr")

    results = gather_tabs({
        "lineups": lambda: {"home": {"groups": []}},
        "statistics": missing,
        "h2h": blocked,
        "commentary": lambda: "",
        "missing_players": failed,
    })

    assert results["lineups"]["status"] == TAB_OK
    assert results["lineups"]["data"] == {"home": {"groups": []}}

    # NotFound means the match has nothing for that tab — not a failure.
    assert results["statistics"]["status"] == TAB_NO_DATA
    assert results["statistics"]["data"] is None

    # A block is reported with its category, never swallowed as no-data.
    assert results["h2h"]["status"] == TAB_FAILED
    assert results["h2h"]["category"] == FAILURE_BLOCKED
    assert "403" in results["h2h"]["error"]

    assert results["commentary"]["status"] == TAB_NO_DATA
    assert results["missing_players"]["status"] == TAB_FAILED
    assert results["missing_players"]["category"] == FAILURE_UPSTREAM


def test_gather_tabs_reports_every_key_when_all_fail():
    def boom():
        raise FlashscoreBlocked("HTTP 429")

    results = gather_tabs({"lineups": boom, "statistics": boom, "h2h": boom})
    assert set(results) == {"lineups", "statistics", "h2h"}
    assert all(r["status"] == TAB_FAILED and r["category"] == FAILURE_BLOCKED
               for r in results.values())
    assert all(r["data"] is None for r in results.values())


def test_gather_tabs_does_not_let_one_exception_cancel_its_siblings():
    def noisy():
        raise RuntimeError("parser bug")

    results = gather_tabs({"statistics": lambda: {"periods": [1]},
                           "lineups": noisy})
    assert results["statistics"]["status"] == TAB_OK
    assert results["lineups"]["status"] == TAB_FAILED
    assert results["lineups"]["category"] == "error"


# ---- get_details: the endpoint contract ----------------------------------------------

def _environment_html(match_id, dx):
    """A page carrying just the `window.environment` blob get_details reads."""
    environment = {
        "sport_id": 1,
        "common_feed": [{
            "DA": "3", "DB": "3", "DC": "1789673400", "DD": "1789674466",
            "DG": "0", "DH": "2", "DJ": "A", "DV": "1", "DX": dx,
        }],
        "header": {
            "country_id": "176", "country_name": "Spain",
            "tournament": {"tournament": "LaLiga - Round 37",
                           "link": "/football/spain/laliga/"},
        },
        "participantsData": {
            "home": [{"id": "h8oAv4Ts", "name": "Sevilla", "three_char_name": "SEV",
                      "country_id": "176", "is_team": True,
                      "detail_link": "/team/sevilla/h8oAv4Ts/"}],
            "away": [{"id": "W8mj7MDD", "name": "Real Madrid", "three_char_name": "RMA",
                      "country_id": "176", "is_team": True,
                      "detail_link": "/team/real-madrid/W8mj7MDD/"}],
            "is_national": False,
        },
        "event_info": {"hasStats": True, "hasPlayerStats": True,
                       "hasMissingPlayers": True},
    }
    return ("<html><script>window.environment = "
            + json.dumps(environment) + ";</script></html>")


_DEFAULT_FEEDS = {
    "df_li": "match_lineups.txt",
    "df_st": "match_statistics.txt",
    "df_hh": "match_h2h.txt",
    "df_lc": "match_commentary.txt",
    "df_scr": "match_missing_players.txt",
}


def _patch_transport(monkeypatch, feed_handlers):
    """get_page returns the environment page; every feed request is routed
    to `feed_handlers[name]`, a callable returning text or raising. A prefix
    with no explicit handler serves its captured fixture, so a test only
    states the tabs it means to break."""
    match_id = "GCxZ2uHc"
    monkeypatch.setattr(matches, "get_page",
                        lambda path, **kwargs: _environment_html(
                            match_id, "LI,ST,HH,LC,SCR,OD,LT,NF,OD"))

    def fake_feed(name, *, optional=True):
        for prefix, handler in feed_handlers.items():
            if name.startswith(prefix):
                return handler()
        fixture = next((f for p, f in _DEFAULT_FEEDS.items() if name.startswith(p)), None)
        return load(fixture) if fixture else ""

    monkeypatch.setattr(matches, "get_feed", fake_feed)


def _tabs_of(details):
    return details["tabs"]


def test_details_returns_successes_and_classifies_failures(monkeypatch):
    def not_found():
        raise FlashscoreNotFound("df_st not found")

    def blocked():
        raise FlashscoreBlocked("HTTP 403 on feed df_hh")

    _patch_transport(monkeypatch, {
        "df_li": lambda: load("match_lineups.txt"),       # success
        "df_st": not_found,                                # no data
        "df_hh": blocked,                                  # blocked
        "df_lc": lambda: "",                               # empty body
        "df_scr": lambda: load("match_missing_players.txt"),  # success
    })

    details = matches.get_details("GCxZ2uHc")
    tabs = _tabs_of(details)

    # The base card is untouched by tab failures.
    assert details["id"] == "GCxZ2uHc"
    assert details["status"] == "finished"
    assert details["home"]["name"] == "Sevilla"
    assert details["away"]["name"] == "Real Madrid"
    assert details["competition"]["name"] == "LaLiga"
    assert details["round"] == "Round 37"
    assert details["home_score"] == 0 and details["away_score"] == 2

    # Successes carry their payload; failures and no-data are separate lists.
    assert set(tabs["data"]) == {"lineups", "missing_players"}
    assert tabs["data"]["lineups"]["home"]["groups"]
    assert tabs["data"]["missing_players"]["count"] >= 1

    assert tabs["no_data"] == ["statistics", "commentary"]
    assert [f["name"] for f in tabs["failed"]] == ["h2h"]
    assert tabs["failed"][0]["category"] == "blocked"
    assert tabs["has_tabs"] is True
    assert tabs["count"] == 2

    # Tabs with no feed mapping are surfaced by name, not silently dropped.
    assert set(tabs["unmapped"]) == {"odds", "standings", "news"}
    assert tabs["available"] == ["lineups", "statistics", "h2h", "commentary",
                                 "missing_players"]


def test_details_still_returns_the_card_when_every_tab_fails(monkeypatch):
    def blocked():
        raise FlashscoreBlocked("HTTP 429")

    _patch_transport(monkeypatch, {"df_": blocked, "dc_": lambda: ""})

    details = matches.get_details("GCxZ2uHc")
    tabs = _tabs_of(details)

    assert details["id"] == "GCxZ2uHc"
    assert details["available_tabs"]
    assert tabs["data"] == {}
    assert tabs["count"] == 0 and tabs["has_tabs"] is False
    assert len(tabs["failed"]) == 5
    assert all(f["category"] == "blocked" for f in tabs["failed"])
    assert tabs["no_data"] == []


def test_details_marks_upstream_failures_with_their_own_category(monkeypatch):
    def flaky():
        raise FlashscoreUpstreamError("request failed: ConnectionError")

    _patch_transport(monkeypatch, {"df_st": flaky})

    details = matches.get_details("GCxZ2uHc")
    failed = {f["name"]: f["category"] for f in details["tabs"]["failed"]}
    assert failed == {"statistics": "upstream"}
    # The other tabs still ran and succeeded.
    assert set(details["tabs"]["data"]) == {"lineups", "h2h", "commentary",
                                            "missing_players"}
