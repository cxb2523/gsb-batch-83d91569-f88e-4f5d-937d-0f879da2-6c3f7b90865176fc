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
        if isinstance(answer, Exception):
            raise answer
        return answer

    http.answer = {"costUsd": 0.0005, "source": {"id": "cheap"}, "output": {"data": {"items": [1, 2]}}}
    monkeypatch.setattr(providers, "http", http)
    return calls, http


def ledger():
    return [json.loads(l) for l in core.ledger_path().read_text(encoding="utf-8").splitlines()]


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
