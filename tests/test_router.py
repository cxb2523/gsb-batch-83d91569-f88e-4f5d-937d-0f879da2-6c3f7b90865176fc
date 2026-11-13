"""Offline tests: no network, no keys, no money."""
import pytest

from getcheapapi import core, providers, router
from getcheapapi.core import Refused, Stop
from getcheapapi.providers import DataForSEO, GoAnyAPI, GoogleAds


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("GETCHEAPAPI_HOME", str(tmp_path))
    for k in ("ANYAPI_API_KEY", "GOANYAPI_API_KEY", "DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD",
              "TWITTERAPI_IO_KEY", "YIR_API_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_render_required_optional_default_join():
    tpl = {"q": "$query", "gl": "$gl?", "loc": "$loc=2840", "lang": "$hl=en", "k": "$kw|join", "fixed": 10}
    out = router.render(tpl, {"query": "x", "kw": ["a", "b"], "hl": "de"})
    assert out == {"q": "x", "loc": 2840, "lang": "de", "k": "a,b", "fixed": 10}
    with pytest.raises(router.NotApplicable):
        router.render(tpl, {"kw": []})


def test_each_dedupes_and_chunk_splits():
    each = {"body": {"keyword": "$item"}, "each": "keywords"}
    assert router.bodies(each, {"keywords": ["a", "b", "a"]}) == [{"keyword": "a"}, {"keyword": "b"}]
    chunk = {"body": {"keywords": "$keywords"}, "chunk": {"field": "keywords", "size": 1000}}
    calls = router.bodies(chunk, {"keywords": [f"k{i}" for i in range(2500)]})
    assert [len(c["keywords"]) for c in calls] == [1000, 1000, 500]


def test_keyword_volume_switches_provider_by_quantity(monkeypatch, tmp_path):
    monkeypatch.setenv("GOANYAPI_API_KEY", "x")
    monkeypatch.setenv("DATAFORSEO_LOGIN", "x")
    monkeypatch.setenv("DATAFORSEO_PASSWORD", "x")
    oauth_file = tmp_path / "google-ads-oauth.json"
    oauth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_ADS_OAUTH_FILE", str(oauth_file))
    cap = router.capability("keyword.volume")
    few = router.plan(cap, [{"keywords": [f"k{i}" for i in range(5)]}], {})
    many = router.plan(cap, [{"keywords": [f"k{i}" for i in range(50)]}], {})
    assert router.choose(few).provider == "goanyapi"
    assert router.choose(many).provider == "dataforseo"
    assert router.choose(many).usd == pytest.approx(0.09)
    direct = router.plan(cap, [{"keywords": ["car", "cars"]}], {}, only="googleads")
    assert router.choose(direct).usd == 0
    assert {option.provider for option in direct} == {"googleads"}


def test_keyword_volume_reports_nested_keywords_as_invalid_input():
    cap = router.capability("keyword.volume")
    options = router.plan(cap, [{"keywords": [{"term": "car"}]}], {}, only="googleads")
    with pytest.raises(Stop, match="keywords must be a flat list"):
        router.choose(options)


def test_keyless_routes_are_priced_but_never_chosen():
    options = router.plan(router.capability("serp.google"), [{"query": "x"}], {})
    assert all(o.status == "no key" and o.usd is not None for o in options)
    assert options[0].provider == "anyapi"  # bundled snapshot says it is cheapest
    with pytest.raises(Stop):
        router.choose(options)


def test_route_needing_missing_field_is_not_applicable(monkeypatch):
    monkeypatch.setenv("ANYAPI_API_KEY", "x")
    options = router.plan(router.capability("reddit.search"), [{"title": "x"}], {})
    assert options[0].status.startswith("n/a")


def test_price_per_multiplies_by_list_length(monkeypatch):
    monkeypatch.setenv("GOANYAPI_API_KEY", "x")
    options = router.plan(router.capability("google.trends"), [{"keywords": ["a", "b", "c"]}], {}, only="goanyapi")
    assert options[0].usd == pytest.approx(3 * GoAnyAPI.credits("google-trends") * 0.001)


def test_dataforseo_operators_cost_five_times():
    d = DataForSEO()
    plain = d.estimate("serp/google/organic/live/regular", {"keyword": "serp api", "depth": 10})
    ops = d.estimate("serp/google/organic/live/regular", {"keyword": "site:example.com serp", "depth": 10})
    assert ops == pytest.approx(5 * plain)


def test_media_batches_are_refused():
    with pytest.raises(Stop):
        router.plan(router.capability("image.generate"), [{"prompt": "a"}, {"prompt": "b"}], {})


def test_catalog_routes_reference_known_providers():
    from getcheapapi.providers import PROVIDERS
    for name, cap in router.load_catalog().items():
        assert cap["routes"], name
        for r in cap["routes"]:
            assert r["provider"] in PROVIDERS, (name, r)
            assert isinstance(r["body"], dict), (name, r)


def test_yir_quote_retries_transient_gateway_errors(monkeypatch):
    from getcheapapi import providers
    monkeypatch.setenv("YIR_API_KEY", "x")
    monkeypatch.setattr(providers.time, "sleep", lambda s: None)
    calls = []

    def fake_http(method, url, headers=None, body=None, timeout=0):
        calls.append(url)
        if len(calls) < 3:
            raise Stop("HTTP 525: error code: 525")
        return {"expected_amount": "0.0085", "supply": {"available": True}}

    monkeypatch.setattr(providers, "http", fake_http)
    y = providers.Yir()
    assert y.estimate("image", {"model": "a/b", "prompt": "p"}) == pytest.approx(0.0085)
    assert len(calls) == 3


def test_yir_quote_does_not_retry_client_errors(monkeypatch):
    from getcheapapi import providers
    monkeypatch.setenv("YIR_API_KEY", "x")
    calls = []

    def fake_http(*a, **k):
        calls.append(1)
        raise Stop("HTTP 400: bad model")

    monkeypatch.setattr(providers, "http", fake_http)
    with pytest.raises(Stop):
        providers.Yir().estimate("image", {"model": "a/b", "prompt": "p"})
    assert len(calls) == 1


def test_yir_balance_reads_gateway_with_the_gateway_key(monkeypatch):
    from getcheapapi import providers
    monkeypatch.setenv("YIR_API_KEY", "x")
    calls = []

    def fake_http(method, url, headers=None, body=None, timeout=0):
        calls.append((method, url, headers))
        return {"object": "balance", "available_amount": "1.5"}

    monkeypatch.setattr(providers, "http", fake_http)
    assert providers.Yir().balance()["available_amount"] == "1.5"
    assert calls == [("GET", "https://gateway.yir.ai/v1/balance", {"Authorization": "Bearer x"})]


def test_env_file_pointer_loads_keys_without_copying(tmp_path, monkeypatch):
    from getcheapapi.core import load_env
    keys = tmp_path / "elsewhere.env"
    keys.write_text("ANYAPI_API_KEY=abc\n", encoding="utf-8")
    (tmp_path / ".env").write_text(f"GETCHEAPAPI_ENV_FILE={keys}\n", encoding="utf-8")  # home .env: pointer only
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.delenv("GETCHEAPAPI_ENV_FILE", raising=False)
    load_env()
    import os
    try:
        assert os.environ["ANYAPI_API_KEY"] == "abc"
    finally:
        os.environ.pop("ANYAPI_API_KEY", None)
        os.environ.pop("GETCHEAPAPI_ENV_FILE", None)


def test_key_source_names_the_file_not_the_value(tmp_path, monkeypatch):
    from getcheapapi.core import key_source, load_env
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("ANYAPI_API_KEY=abc\n", encoding="utf-8")
    monkeypatch.chdir(work)
    monkeypatch.setenv("GETCHEAPAPI_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANYAPI_API_KEY", raising=False)
    monkeypatch.setenv("YIR_API_KEY", "xyz")
    load_env()
    import os
    try:
        assert key_source("ANYAPI_API_KEY") == str(work / ".env")
        assert key_source("YIR_API_KEY") == "environment"
        assert "abc" not in key_source("ANYAPI_API_KEY", "YIR_API_KEY")
    finally:
        os.environ.pop("ANYAPI_API_KEY", None)


def test_twitterapi_blocks_writes_and_monitoring_but_not_follower_reads():
    from getcheapapi.providers import TwitterAPI
    t = TwitterAPI()
    for path in ("twitter/create_tweet_v2", "twitter/follow_user_v2", "twitter/user_login_v2",
                 "twitter/send_dm_to_user", "oapi/tweet_filter/add_rule", "/twitter/like_tweet_v2"):
        with pytest.raises(Stop):
            t.estimate(path, {})
    for path in ("twitter/user/followers", "twitter/user/followings", "twitter/tweet/retweeters",
                 "twitter/tweet/advanced_search", "twitter/user/last_tweets"):
        assert t.estimate(path, {}) > 0
    assert t.estimate("twitter/user/followers", {}) == pytest.approx(0.006)  # 200 users x 3 credits
    assert t.estimate("twitter/tweets", {"tweet_ids": "1,2,3"}) == pytest.approx(3 * 0.00015)


def test_anyapi_unexpected_source_stops_but_keeps_the_charge(monkeypatch):
    from getcheapapi import providers
    monkeypatch.setenv("ANYAPI_API_KEY", "x")
    monkeypatch.setattr(providers, "http", lambda *a, **k: {"source": {"id": "dear"}, "costUsd": 0.01, "output": {}})
    a = providers.AnyAPI()
    body = {"query": "x"}
    a._pinned[id(body)] = ({"cheap"}, 0.0005)
    with pytest.raises(Stop) as exc:
        a.call("google.search", body)
    assert exc.value.cost == pytest.approx(0.01)


def test_anyapi_invalid_input_is_not_reported_as_pricier_sources(monkeypatch):
    from getcheapapi import providers

    def fake_http(*a, **k):
        raise Stop("HTTP 400: {\"error\":\"invalid_input: missing property 'query'\"}")

    monkeypatch.setenv("ANYAPI_API_KEY", "x")
    monkeypatch.setattr(providers, "http", fake_http)
    a = providers.AnyAPI()
    body = {"keyword": "x"}
    a._pinned[id(body)] = ({"cheap"}, 0.0005)
    with pytest.raises(Stop) as exc:
        a.call("tiktok.search_keyword", body)
    assert "--max-ratio" not in str(exc.value)


def test_anyapi_async_acceptance_is_not_a_wrong_source(monkeypatch):
    from getcheapapi import providers
    monkeypatch.setenv("ANYAPI_API_KEY", "x")
    monkeypatch.setattr(providers, "http", lambda *a, **k: {"requestId": "r1", "nextAction": {"poll": "/v1/requests/r1"}})
    a = providers.AnyAPI()
    body = {"q": "x"}
    a._pinned[id(body)] = ({"cheap"}, 0.0005)
    assert a.call("company.research", body)[3] is True


def test_summary_saves_against_dearest_priced_route(monkeypatch):
    monkeypatch.setenv("GOANYAPI_API_KEY", "x")
    cap = router.capability("keyword.volume")
    options = router.plan(cap, [{"keywords": ["a", "b", "c"]}], {})
    best = router.choose(options)
    s = router.summary(options, best)
    assert s["pick"] == best.label and s["calls"] == 3 and s["routes"] == 2
    assert s["savedUsd"] == round(s["vsUsd"] - s["usd"], 5) and 0 < s["savedPct"] < 100
    assert "savedUsd" not in router.summary([best], best)


def test_unpriced_route_with_a_key_stops_the_run(monkeypatch):
    monkeypatch.setattr(providers.AnyAPI, "configured", classmethod(lambda cls: True))
    ok = router.Option("dataforseo", "e", {}, usd=0.09)
    bad = router.Option("anyapi", "e", {}, status="error: HTTP 503")
    with pytest.raises(core.Refused, match="cheapest is unknown"):
        router.choose([ok, bad])


def test_unpriced_route_without_a_key_does_not_block(monkeypatch):
    monkeypatch.setattr(providers.AnyAPI, "configured", classmethod(lambda cls: False))
    ok = router.Option("dataforseo", "e", {}, usd=0.09)
    assert router.choose([ok, router.Option("anyapi", "e", {}, status="error: no snapshot price")]) is ok


def test_yir_failover_is_off_unless_asked():
    assert providers.Yir.request({"model": "m", "prompt": "p"})["routing"] == {"fallback": False}
    asked = providers.Yir.request({"model": "m", "prompt": "p", "routing": {"fallback": True, "preference": "speed"}})
    assert asked["routing"] == {"fallback": True, "preference": "speed"}


def test_googleads_keyword_ideas_seeds():
    ads = GoogleAds()
    body = ads.request_body("generateKeywordIdeas", {"keyword": "ai photo", "limit": 50, "location_code": 2826})
    assert body["keywordSeed"] == {"keywords": ["ai photo"]} and body["pageSize"] == 50
    assert body["geoTargetConstants"] == ["geoTargetConstants/2826"]
    assert ads.request_body("generateKeywordIdeas", {"site": "example.com"})["siteSeed"] == {"site": "example.com"}
    both = ads.request_body("generateKeywordIdeas", {"keywords": ["a", "b"], "url": "https://example.com/x"})
    assert both["keywordAndUrlSeed"] == {"url": "https://example.com/x", "keywords": ["a", "b"]}
    for bad in ({}, {"site": "example.com", "keyword": "a"}, {"site": "https://example.com"},
                {"keywords": [f"k{i}" for i in range(21)]}, {"url": "example.com"}, {"keyword": "a", "limit": 0}):
        with pytest.raises(Refused):
            ads.request_body("generateKeywordIdeas", bad)


def test_googleads_month_range_and_device_split():
    body = GoogleAds().request_body("generateKeywordHistoricalMetrics", {
        "keywords": ["car"], "start_month": "2023-01", "end_month": "2026-10"})
    assert body["historicalMetricsOptions"]["yearMonthRange"] == {
        "start": {"year": 2023, "month": "JANUARY"}, "end": {"year": 2026, "month": "OCTOBER"}}
    ideas = GoogleAds().request_body("generateKeywordIdeas", {"keyword": "car", "device": True})
    assert ideas["aggregateMetrics"] == {"aggregateMetricTypes": ["DEVICE"]}
    assert "historicalMetricsOptions" not in GoogleAds().request_body("generateKeywordHistoricalMetrics", {"keywords": ["car"]})
    for months in ({"start_month": "2023-01"}, {"start_month": "2026-10", "end_month": "2023-01"}, {"start_month": "2023-1", "end_month": "2023-02"}):
        with pytest.raises(Refused):
            GoogleAds().request_body("generateKeywordHistoricalMetrics", {"keywords": ["car"], **months})


def test_keyword_ideas_googleads_route_is_free_and_explicit(monkeypatch, tmp_path):
    oauth_file = tmp_path / "google-ads-oauth.json"
    oauth_file.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("GOOGLE_ADS_OAUTH_FILE", str(oauth_file))
    cap = router.capability("keyword.ideas")
    assert all(o.provider != "googleads" for o in router.plan(cap, [{"keyword": "car"}], {}))
    direct = router.plan(cap, [{"site": "example.com", "device": True}], {}, only="googleads")
    best = router.choose(direct)
    assert best.usd == 0 and best.bodies[0]["site"] == "example.com" and best.bodies[0]["limit"] == 100
