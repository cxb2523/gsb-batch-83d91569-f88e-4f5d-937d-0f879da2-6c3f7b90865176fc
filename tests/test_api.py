"""Library calls: same guards as the CLI, and every call lands in the ledger. Offline."""
import http.client
import io
import json
import urllib.error

import pytest

from getcheapapi import api, core, lanes as L, providers


def lane(sid, usd):
    return {"source": {"id": sid}, "pricing": {"baseUsd": usd}}


LANES = [lane("cheap", 0.0005), lane("near", 0.0007), lane("dear", 0.01)]


@pytest.fixture
def post(tmp_path, monkeypatch):
    """Stub the network; the returned list collects POSTed bodies and `answer` is what they get back."""
    monkeypatch.setenv("GETCHEAPAPI_HOME", str(tmp_path))
    monkeypatch.setenv("ANYAPI_API_KEY", "k")
    monkeypatch.setenv("TWITTERAPI_IO_KEY", "k")
    monkeypatch.setattr(api, "load_env", lambda: [])
    monkeypatch.setattr(L, "fetch_lanes", lambda sku, key, max_age=0: LANES)
    calls = []

    def http(method, url, headers=None, body=None, timeout=180):
        calls.append(body)
        answer = http.answer
        if callable(answer):
            answer = answer(body)
        if isinstance(answer, Exception):
            raise answer
        return answer

    http.answer = {"costUsd": 0.0005, "source": {"id": "cheap"}, "output": {"data": {"items": [1, 2]}}}
    monkeypatch.setattr(providers, "http", http)
    return calls, http


def ledger():
    return [json.loads(l) for l in core.ledger_path().read_text(encoding="utf-8").splitlines()]


def item(result, keyword):
    return next(row for row in result["items"] if row["keyword"] == keyword)


def test_batch_call_collects_every_keyword_and_sums_the_costs(post):
    calls, _ = post
    result = api.batch_call("anyapi", "twitter.search", ["a", "b", "c"], project="p")
    assert [row["status"] for row in result["items"]] == ["success"] * 3
    assert [row["keyword"] for row in result["items"]] == ["a", "b", "c"]
    assert [row["costUsd"] for row in result["items"]] == [0.0005] * 3
    assert all(row["charged"] and row["result"]["output"]["data"]["items"] == [1, 2] for row in result["items"])
    assert (result["success"], result["failed"], result["refused"], result["not_run"]) == (3, 0, 0, 0)
    assert result["totalUsd"] == pytest.approx(0.0015) and result["stoppedForBalance"] is False
    assert [c["keyword"] for c in calls] == ["a", "b", "c"]  # one call per keyword, in order
    assert all(c["source"] == ["cheap"] and c["allowFallbacks"] is False for c in calls)
    rows = ledger()
    assert [r["input"]["keyword"] for r in rows] == ["a", "b", "c"] and all(r["project"] == "p" for r in rows)


def test_batch_call_goes_on_after_one_keyword_fails(post):
    _, http = post
    good = http.answer
    http.answer = lambda body: (core.Stop("HTTP 400: invalid_input") if body["keyword"] == "b" else good)
    result = api.batch_call("anyapi", "twitter.search", ["a", "b", "c"])
    assert [row["status"] for row in result["items"]] == ["success", "failed", "success"]
    assert "invalid_input" in item(result, "b")["error"]
    assert (result["success"], result["failed"], result["totalUsd"]) == (2, 1, pytest.approx(0.001))
    assert result["stoppedForBalance"] is False
    assert [r["input"]["keyword"] for r in ledger()] == ["a", "b", "c"]  # the failed call is recorded too
    assert ledger()[1]["costUsd"] == 0


def test_batch_call_stops_on_no_balance_and_keeps_what_was_done(post):
    _, http = post
    good = http.answer
    http.answer = lambda body: (core.Stop("HTTP 402: empty", core.EXIT_NO_BALANCE) if body["keyword"] == "c" else good)
    result = api.batch_call("anyapi", "twitter.search", ["a", "b", "c", "d"])
    assert [row["status"] for row in result["items"]] == ["success", "success", "failed", "not_run"]
    assert "402" in item(result, "c")["error"] and item(result, "c")["charged"] is False
    assert "out of balance" in item(result, "d")["error"] and item(result, "d")["charged"] is False
    assert item(result, "a")["result"] is not None and item(result, "b")["result"] is not None
    assert result["stoppedForBalance"] is True
    assert (result["success"], result["failed"], result["not_run"], result["totalUsd"]) == (2, 1, 1, pytest.approx(0.001))
    assert len(ledger()) == 3  # a, b and the 402 attempt; d was never sent


def test_batch_call_refuses_one_keyword_over_the_cap_without_calling_it(post, monkeypatch):
    _, http = post
    good = http.answer
    big = {"source": {"id": "cheap"}, "pricing": {"model": "linear", "baseUsd": 0.0, "perUnitUsd": 0.001,
                                                   "maxUsd": 1.0}}
    monkeypatch.setattr(L, "fetch_lanes", lambda sku, key, max_age=0: [big])  # $0.005 at limit 5, $0.06 at 60
    http.answer = lambda body: ({"costUsd": 0.06, "source": {"id": "cheap"}, "output": {"data": [1]}}
                                if body["limit"] == 60 else good)
    result = api.batch_call("anyapi", "twitter.search", ["small", "big", "small2"],
                            body_for=lambda term: {"keyword": term} | ({"limit": 60} if term == "big" else {"limit": 5}),
                            max_usd=0.01)
    assert [row["status"] for row in result["items"]] == ["success", "refused", "success"]
    assert "exceeds the $0.01 cap" in item(result, "big")["error"]
    assert item(result, "big")["charged"] is False and item(result, "big")["costUsd"] == 0
    assert result["refused"] == 1 and result["totalUsd"] == pytest.approx(0.001)
    assert [r["input"]["keyword"] for r in ledger()] == ["small", "small2"]  # big never reached the network


def test_batch_call_reports_a_waited_out_source_as_one_failed_keyword(post, monkeypatch):
    _, http = post
    good = http.answer
    slept = []
    monkeypatch.setattr(api.time, "sleep", slept.append)
    http.answer = lambda body: (core.Stop("HTTP 503: no capacity") if body["keyword"] == "b" else good)
    result = api.batch_call("anyapi", "twitter.search", ["a", "b", "c"], wait=10, retries=0)
    assert [row["status"] for row in result["items"]] == ["success", "failed", "success"]
    assert slept == [5, 5]  # both tries of b waited; c was still called after it
    assert result["stoppedForBalance"] is False


def test_batch_call_keeps_the_charge_of_a_keyword_that_failed_after_being_served(post):
    _, http = post
    good = http.answer
    http.answer = lambda body: ({"costUsd": 0.01, "source": {"id": "dear"}, "output": {}}
                                if body["keyword"] == "b" else good)
    result = api.batch_call("anyapi", "twitter.search", ["a", "b", "c"])
    assert [row["status"] for row in result["items"]] == ["success", "failed", "success"]
    assert item(result, "b")["charged"] is True and item(result, "b")["costUsd"] == pytest.approx(0.01)
    assert "served by dear" in item(result, "b")["error"]
    assert result["totalUsd"] == pytest.approx(0.011)  # the failed keyword's charge is counted, not lost
    assert [r["costUsd"] for r in ledger()] == [0.0005, 0.01, 0.0005]


def test_batch_call_rejects_a_keyword_list_that_is_not_plain_strings(post):
    calls, _ = post
    with pytest.raises(api.Stop, match="non-empty strings"):
        api.batch_call("anyapi", "twitter.search", ["a", {"term": "b"}])
    with pytest.raises(api.Stop):
        api.batch_call("anyapi", "twitter.search", "a")
    assert calls == [] and not core.ledger_path().exists()


def test_cli_batch_reports_each_keyword_without_real_calls(post, tmp_path, capsys):
    calls, http = post
    from getcheapapi import cli
    http.answer = lambda body: (core.Stop("HTTP 402: empty", core.EXIT_NO_BALANCE) if body["keyword"] == "c" else
                                {"costUsd": 0.0005, "source": {"id": "cheap"}, "output": {"data": {"items": [1]}}})
    argv = ["batch", "anyapi", "twitter.search", "--input", json.dumps(["a", "b", "c", "d"]),
            "--max-usd", "0.01", "--output", str(tmp_path / "batch.json")]
    import sys
    old = sys.argv
    sys.argv = ["getcheapapi", *argv]
    try:
        with pytest.raises(SystemExit) as stop:
            cli.main()
    finally:
        sys.argv = old
    assert stop.value.code == core.EXIT_NO_BALANCE  # scripts stop the loop on it
    saved = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    assert [row["status"] for row in saved["items"]] == ["success", "success", "failed", "not_run"]
    assert saved["totalUsd"] == pytest.approx(0.001) and saved["stoppedForBalance"] is True
    assert len(calls) == 3
    summary = json.loads(capsys.readouterr().out)
    assert (summary["success"], summary["failed"], summary["not_run"]) == (2, 1, 1)


def test_cli_batch_reads_a_keywords_object_and_leaves_clean_when_all_work(post, tmp_path, capsys):
    _, http = post
    from getcheapapi import cli
    import sys
    argv = ["batch", "anyapi", "twitter.search", "--input", json.dumps({"keywords": ["a", "b"]}),
            "--output", str(tmp_path / "batch.json")]
    old = sys.argv
    sys.argv = ["getcheapapi", *argv]
    try:
        with pytest.raises(SystemExit) as stop:
            cli.main()
    finally:
        sys.argv = old
    assert stop.value.code == 0
    saved = json.loads((tmp_path / "batch.json").read_text(encoding="utf-8"))
    assert [row["keyword"] for row in saved["items"]] == ["a", "b"] and saved["success"] == 2


def test_call_pins_sources_and_writes_ledger(post):
    calls, _ = post
    result, cost = api.call("anyapi", "twitter.search", {"query": "x"}, project="p")
    assert cost == 0.0005 and result["output"]["data"]["items"] == [1, 2]
    assert calls[0]["source"] == ["cheap"] and calls[0]["allowFallbacks"] is False
    row = ledger()[0]
    assert (row["project"], row["costUsd"], row["source"], row["input"]) == ("p", 0.0005, "cheap", {"query": "x"})


def test_googleads_token_error_keeps_credentials_out_of_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("GETCHEAPAPI_HOME", str(tmp_path))
    monkeypatch.delenv("GOOGLE_ADS_OAUTH_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_ADS_CUSTOMER_ID", "1234567890")
    monkeypatch.delenv("GOOGLE_ADS_LOGIN_CUSTOMER_ID", raising=False)
    monkeypatch.setattr(api, "load_env", lambda: [])
    credentials = {"client_id": "test-client", "client_secret": "local-secret", "refresh_token": "local-token"}
    (tmp_path / "google-ads-oauth.json").write_text(json.dumps(credentials), encoding="utf-8")

    def expired_token(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 400, "invalid_grant", {}, io.BytesIO(request.data))

    monkeypatch.setattr(providers.urllib.request, "urlopen", expired_token)
    with pytest.raises(api.NotServed, match=r"OAuth token refresh failed \(HTTP 400\)") as exc:
        api.call("googleads", "generateKeywordHistoricalMetrics", {"keywords": ["car"]}, max_usd=0)
    row = ledger()[0]
    assert row["costUsd"] == 0
    for secret in credentials.values():
        assert secret not in str(exc.value) and secret not in json.dumps(row)


def test_refused_past_cap_spends_nothing(post):
    calls, _ = post
    with pytest.raises(api.Refused):
        api.call("anyapi", "twitter.search", {"query": "x"}, max_usd=0.0001)
    assert calls == [] and not core.ledger_path().exists()


def test_refused_when_price_rose(post, monkeypatch):
    calls, _ = post
    api.quote("anyapi", "sku", {})
    monkeypatch.setattr(L, "fetch_lanes", lambda sku, key, max_age=0: [lane("near", 0.0009)])
    with pytest.raises(api.Refused, match="rose"):
        api.call("anyapi", "sku", {})
    assert calls == []


def test_refusal_from_cheap_sources_is_not_served(post):
    _, http = post
    http.answer = core.Stop("HTTP 503: no capacity")
    with pytest.raises(api.NotServed):
        api.call("anyapi", "twitter.search", {"query": "x"})
    assert "503" in ledger()[0]["error"]


def test_unavailable_source_is_waited_for_not_replaced(post, monkeypatch):
    calls, http = post
    http.answer = core.Stop("HTTP 503: no capacity")
    slept = []
    monkeypatch.setattr(api.time, "sleep", slept.append)
    with pytest.raises(api.Unavailable) as err:
        api.call("anyapi", "twitter.search", {"query": "x"}, wait=90)
    assert err.value.code == core.EXIT_UNAVAILABLE and err.value.cost == 0
    assert slept == [5, 10, 20, 40, 15] and len(calls) == 6
    assert all(c["source"] == ["cheap"] for c in calls)
    assert all(r["costUsd"] == 0 for r in ledger())


def test_wait_ends_when_the_source_comes_back(post, monkeypatch):
    calls, http = post
    good = http.answer
    http.answer = core.Stop("HTTP 503: no capacity")
    monkeypatch.setattr(api.time, "sleep", lambda _: setattr(http, "answer", good))
    result, cost = api.call("anyapi", "twitter.search", {"query": "x"}, wait=90)
    assert cost == 0.0005 and len(calls) == 2


def test_bad_input_is_not_waited_for(post, monkeypatch):
    calls, http = post
    http.answer = core.Stop("HTTP 400: invalid_input")
    monkeypatch.setattr(api.time, "sleep", lambda _: pytest.fail("waited"))
    with pytest.raises(api.NotServed) as err:
        api.call("anyapi", "twitter.search", {"query": "x"}, wait=90)
    assert not isinstance(err.value, api.Unavailable) and len(calls) == 1


def test_no_balance_ends_the_batch(post):
    _, http = post
    http.answer = core.Stop("HTTP 402: empty", core.EXIT_NO_BALANCE)
    with pytest.raises(core.Stop) as err:
        api.call("anyapi", "twitter.search", {"query": "x"})
    assert err.value.code == core.EXIT_NO_BALANCE and not isinstance(err.value, api.NotServed)


def test_unexpected_source_stops_and_records_the_charge(post):
    _, http = post
    http.answer = {"costUsd": 0.01, "source": {"id": "dear"}, "output": {}}
    with pytest.raises(core.Stop, match="served by dear") as err:
        api.call("anyapi", "twitter.search", {"query": "x"})
    assert err.value.cost == 0.01 and ledger()[0]["costUsd"] == 0.01


def test_retries_a_dropped_connection_then_gives_up(post):
    calls, http = post
    http.answer = urllib.error.URLError("reset")
    with pytest.raises(api.NotServed, match="connection failed"):
        api.call("anyapi", "twitter.search", {"query": "x"}, retries=2)
    assert len(calls) == 3 and len(ledger()) == 1


def test_response_cut_off_midway_counts_as_a_dropped_connection(post):
    calls, http_stub = post
    http_stub.answer = http.client.IncompleteRead(b"{")
    with pytest.raises(api.NotServed, match="connection failed"):
        api.call("anyapi", "twitter.search", {"query": "x"}, retries=1)
    assert len(calls) == 2 and "connection" in ledger()[0]["error"]


def test_twitterapi_read_is_priced_and_recorded(post):
    _, http = post
    http.answer = {"tweets": [{"id": "1"}], "status": "success"}
    result, cost = api.call("twitterapi", "/twitter/tweets", {"tweet_ids": "1"})
    assert result["tweets"] and cost == pytest.approx(0.00015) and ledger()[0]["provider"] == "twitterapi"


def test_fetch_lanes_retries_dropped_connections(tmp_path, monkeypatch):
    monkeypatch.setenv("GETCHEAPAPI_HOME", str(tmp_path))
    monkeypatch.setattr(L.time, "sleep", lambda s: None)
    tries = []

    def http(*a, **k):
        tries.append(1)
        if len(tries) < 3:
            raise urllib.error.URLError("reset")
        return {"lanes": LANES}

    monkeypatch.setattr(L, "http", http)
    assert L.fetch_lanes("sku", "k") == LANES and len(tries) == 3
