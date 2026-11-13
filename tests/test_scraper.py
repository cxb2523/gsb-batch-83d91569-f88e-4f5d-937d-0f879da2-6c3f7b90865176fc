import scraper
from config import COL_ICON, COL_INSTALLS, COL_RATING, COL_REVIEWS, COL_TITLE


def _deterministic_sampling(monkeypatch):
    monkeypatch.setattr(scraper.random, "sample", lambda values, k: list(values)[:k])


def test_parse_installs_supports_localized_separators():
    assert scraper._parse_installs("100,000+") == 100_000
    assert scraper._parse_installs("10\u202f000+") == 10_000
    assert scraper._parse_installs(-10) == 0
    assert scraper._parse_installs(True) == 0
    assert scraper._parse_installs("1.5M") == 0


def test_normalize_row_handles_untrusted_metadata():
    row = scraper._normalize_row(
        "com.example.app",
        {
            "title": "  Example  ",
            "score": "not-a-number",
            "ratings": "invalid",
            "icon": "javascript:alert(1)",
        },
        12_500,
    )

    assert row[COL_TITLE] == "Example"
    assert row[COL_INSTALLS] == "12 500"
    assert row[COL_RATING] == "0.0"
    assert row[COL_REVIEWS] == 0
    assert row[COL_ICON] == ""


def test_collect_candidates_prioritizes_custom_queries(monkeypatch):
    monkeypatch.setattr(scraper, "MAX_LOCALES_PER_RUN", 1)
    monkeypatch.setattr(scraper, "_fetch_search", lambda *args: [])
    monkeypatch.setattr(scraper.random, "sample", lambda values, k: list(values)[:k])

    _, queries = scraper.collect_candidates(2, 20, set(), ["offline notes", "habits"])

    assert queries == ["offline notes", "habits"]


def test_fetch_details_uses_cache_and_batches_new_writes(monkeypatch):
    cached = {
        "cached": {
            "title": "Cached",
            "minInstalls": 20_000,
            "score": 4.5,
            "ratings": 100,
        }
    }
    fetched = {
        "fetched": {
            "title": "Fetched",
            "minInstalls": 30_000,
            "score": 4.7,
            "ratings": 200,
        }
    }
    writes = []
    monkeypatch.setattr(scraper.random, "sample", lambda values, k: list(values)[:k])
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: cached)
    monkeypatch.setattr(scraper, "_fetch_details", lambda app_id: fetched[app_id])
    monkeypatch.setattr(scraper, "set_cached_details_many", writes.append)

    rows = scraper.fetch_details_batch(["cached", "fetched"], 10_000, 0, 1)

    assert len(rows) == 2
    assert writes == [fetched]


def test_fetch_details_enforces_install_range(monkeypatch):
    details = {"app": {"title": "App", "minInstalls": 5_000}}
    monkeypatch.setattr(scraper.random, "sample", lambda values, k: list(values)[:k])
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: details)

    assert scraper.fetch_details_batch(["app"], 10_000, 0, 1) == []
    assert scraper.fetch_details_batch(["app"], 0, 1_000, 1) == []


def test_failed_search_combination_is_recorded_and_run_continues(monkeypatch):
    monkeypatch.setattr(scraper, "MAX_LOCALES_PER_RUN", 1)
    _deterministic_sampling(monkeypatch)

    def fake_search(query, lang, country, limit):
        if query == "boom":
            raise RuntimeError("search exploded")
        return [{"appId": f"app-{query}"}]

    monkeypatch.setattr(scraper, "_fetch_search", fake_search)
    summary = scraper.RunSummary()

    candidates, queries = scraper.collect_candidates(2, 20, set(), ["ok", "boom"], summary=summary)

    assert candidates == ["app-ok"]
    assert queries == ["ok", "boom"]
    assert summary.combinations_total == 2
    assert summary.combinations_succeeded == 1
    assert summary.failed_combinations == [{"query": "boom", "lang": "ru", "country": "ru"}]
    assert summary.candidates == 1


def test_missing_details_are_counted_as_skipped(monkeypatch):
    _deterministic_sampling(monkeypatch)
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: {})
    monkeypatch.setattr(scraper, "_fetch_details", lambda app_id: None)
    monkeypatch.setattr(scraper, "set_cached_details_many", lambda data: None)
    summary = scraper.RunSummary()

    rows = scraper.fetch_details_batch(["a", "b", "c"], 0, 0, 5, summary=summary)

    assert rows == []
    assert summary.details_missing == 3
    assert summary.details_cache_hits == 0
    assert summary.details_network == 0


def test_install_bounds_are_counted_separately(monkeypatch):
    details = {
        "low": {"title": "Low", "minInstalls": 100},
        "mid": {"title": "Mid", "minInstalls": 5_000},
        "high": {"title": "High", "minInstalls": 500_000},
    }
    _deterministic_sampling(monkeypatch)
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: details)

    summary = scraper.RunSummary()
    rows = scraper.fetch_details_batch(["low", "mid", "high"], 1_000, 10_000, 5, summary=summary)

    assert [row["appId"] for row in rows] == ["mid"]
    assert summary.excluded_below_min == 1
    assert summary.excluded_above_max == 1


def test_zero_max_installs_disables_upper_bound_exclusions(monkeypatch):
    details = {
        "low": {"title": "Low", "minInstalls": 100},
        "high": {"title": "High", "minInstalls": 500_000},
    }
    _deterministic_sampling(monkeypatch)
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: details)

    summary = scraper.RunSummary()
    rows = scraper.fetch_details_batch(["low", "high"], 0, 0, 5, summary=summary)

    assert len(rows) == 2
    assert summary.excluded_below_min == 0
    assert summary.excluded_above_max == 0


def test_duplicate_candidate_ids_are_counted_once(monkeypatch):
    monkeypatch.setattr(scraper, "MAX_LOCALES_PER_RUN", 2)
    _deterministic_sampling(monkeypatch)
    monkeypatch.setattr(
        scraper, "_fetch_search", lambda *args: [{"appId": "dup"}, {"appId": "dup"}]
    )
    summary = scraper.RunSummary()

    candidates, _ = scraper.collect_candidates(1, 20, set(), ["solo"], summary=summary)

    assert candidates == ["dup"]
    assert summary.candidates == 1

    # The details stage collapses repeats as well, so a duplicated input list
    # is only sampled and counted once.
    details = {"dup": {"title": "Dup", "minInstalls": 5_000}}
    monkeypatch.setattr(scraper, "get_cached_details_many", lambda ids: details)
    details_summary = scraper.RunSummary()
    rows = scraper.fetch_details_batch(["dup", "dup"], 0, 0, 5, summary=details_summary)

    assert len(rows) == 1
    assert details_summary.details_cache_hits == 1
