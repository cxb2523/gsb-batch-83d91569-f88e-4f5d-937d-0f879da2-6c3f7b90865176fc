"""Testing FastAPI endpoints.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.main import CACHE_TTL_SECONDS, app
from app.schemas import UpstreamFailureReason
from app.scraping import UpstreamRequestError

client = TestClient(app)
DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@pytest.fixture(autouse=True)
def clear_trending_cache():
    """Clears route cache before and after each test."""
    main.clear_trending_cache()
    yield
    main.clear_trending_cache()


@pytest.fixture
def frozen_clock(monkeypatch):
    """Controls ``time.monotonic`` so cache ageing/expiry is deterministic."""

    class FakeClock:
        def __init__(self) -> None:
            self.now = 1000.0

        def advance(self, seconds: float) -> None:
            self.now += seconds

        def __call__(self) -> float:
            return self.now

    clock = FakeClock()
    monkeypatch.setattr(main.time, "monotonic", clock)
    return clock


def stub_upstream_html(html_name: str, calls: list) -> object:
    """Build an async get_request stub returning a local HTML sample."""

    async def fake_get_request(*args, **kwargs):
        calls.append((args, kwargs))
        return (DATA_DIR / html_name).read_text(encoding="utf-8")

    return fake_get_request


def test_help_route():
    """Tests if the '/'-route (help-route) returns correctly data
    about repositories/developers and built-in documentation.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "repositories": "http://testserver/repositories",
        "developers": "http://testserver/developers",
        "docs": "http://testserver/docs",
        "redoc": "http://testserver/redoc",
    }


def test_health_route():
    """Tests if the health route returns application status."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metadata_route():
    """Tests if the metadata route returns API discovery data."""
    response = client.get("/metadata")

    assert response.status_code == 200
    assert response.json() == {
        "name": "GitHub Trending API",
        "version": "2.0.0",
        "docs": "http://testserver/docs",
        "redoc": "http://testserver/redoc",
        "health": "http://testserver/health",
        "repositories": "http://testserver/repositories",
        "developers": "http://testserver/developers",
        "cacheTtlSeconds": 300,
        "supportedDateRanges": ["daily", "weekly", "monthly"],
        "supportedProgrammingLanguagesCount": len(main.AllowedProgrammingLanguages),
        "supportedSpokenLanguagesCount": len(main.AllowedSpokenLanguages),
    }


def test_repositories_route_uses_query_parameters(monkeypatch):
    """Tests the repository endpoint request payload and response parsing."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    response = client.get(
        "/repositories",
        params={"since": "weekly", "spoken_language_code": "zh"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["repositoryName"] == "v"
    assert calls == [
        (
            ("https://github.com/trending",),
            {
                "compress": True,
                "params": {
                    "since": "weekly",
                    "spoken_language_code": "zh",
                },
            },
        ),
    ]


def test_repositories_route_caches_upstream_html(monkeypatch):
    """Tests repeated requests reuse cached upstream HTML."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    first_response = client.get("/repositories", params={"since": "weekly"})
    second_response = client.get("/repositories", params={"since": "weekly"})

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(calls) == 1


def test_repositories_language_route_uses_enum_value(monkeypatch):
    """Tests that language enum params are rendered as GitHub URL values."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    response = client.get("/repositories/python", params={"since": "monthly"})

    assert response.status_code == 200
    assert response.json()["data"][0]["since"] == "monthly"
    assert calls[0][0] == ("https://github.com/trending/python",)
    assert calls[0][1]["params"] == {"since": "monthly"}


def test_developers_route_uses_query_parameters(monkeypatch):
    """Tests the developer endpoint request payload and response parsing."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("devdata2.html", calls),
    )

    response = client.get("/developers", params={"since": "weekly"})

    assert response.status_code == 200
    assert response.json()["data"][0]["username"] == "nunomaduro"
    assert calls == [
        (
            ("https://github.com/trending/developers",),
            {
                "compress": True,
                "params": {"since": "weekly"},
            },
        ),
    ]


def test_developers_language_route_uses_enum_value(monkeypatch):
    """Tests that developer language params use GitHub URL values."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("devdata2.html", calls),
    )

    response = client.get("/developers/python", params={"since": "monthly"})

    assert response.status_code == 200
    assert response.json()["data"][0]["since"] == "monthly"
    assert calls[0][0] == ("https://github.com/trending/developers/python",)
    assert calls[0][1]["params"] == {"since": "monthly"}


def test_invalid_query_parameter_returns_validation_error():
    """Tests invalid enum query parameters are rejected by FastAPI."""
    response = client.get("/repositories", params={"since": "yearly"})

    assert response.status_code == 422


def test_invalid_path_parameter_returns_validation_error():
    """Tests invalid enum path parameters are rejected by FastAPI."""
    response = client.get("/repositories/not-a-language")

    assert response.status_code == 422


@pytest.mark.parametrize(
    "route,html_sample",
    [
        ("/repositories", "repodata2.html"),
        ("/repositories/python", "repodata2.html"),
        ("/developers", "devdata2.html"),
        ("/developers/python", "devdata2.html"),
    ],
)
def test_all_trending_routes_expose_source_metadata(
    monkeypatch,
    route,
    html_sample,
):
    """First request on every trending route is marked freshly fetched."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html(html_sample, calls),
    )

    response = client.get(route)

    assert response.status_code == 200
    body = response.json()
    assert list(body.keys()) == ["data", "source"]
    assert body["source"] == {
        "origin": "upstream",
        "cacheAgeSeconds": 0,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
    }
    assert len(calls) == 1


def test_first_fetch_marked_upstream_with_zero_age(monkeypatch):
    """Path 1: first request fetches upstream, age is 0, entries unchanged."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata1.html", calls),
    )

    response = client.get("/repositories")

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == {
        "origin": "upstream",
        "cacheAgeSeconds": 0,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
    }
    assert len(body["data"]) == 25
    # original entry fields and their ordering remain untouched
    assert list(body["data"][0].keys()) == [
        "rank",
        "username",
        "repositoryName",
        "url",
        "description",
        "language",
        "languageColor",
        "totalStars",
        "forks",
        "starsSince",
        "since",
        "builtBy",
    ]
    assert len(calls) == 1


@pytest.mark.parametrize(
    "route,html_sample,expected_json",
    [
        ("/repositories", "repodata1.html", "repodata1.json"),
        ("/repositories/python", "repodata2.html", "repodata2.json"),
        ("/developers", "devdata1.html", "devdata1.json"),
        ("/developers/python", "devdata2.html", "devdata2.json"),
    ],
)
def test_trending_entries_keep_fields_and_order(
    monkeypatch,
    route,
    html_sample,
    expected_json,
):
    """The provenance envelope must not alter entry fields or ordering."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html(html_sample, calls),
    )

    response = client.get(route)

    assert response.status_code == 200
    expected_entries = json.loads((DATA_DIR / expected_json).read_text())
    assert response.json()["data"] == expected_entries
    assert len(calls) == 1


def test_repeated_request_served_from_cache_with_ageing(
    monkeypatch,
    frozen_clock,
):
    """Path 2: repeat hits cache once upstream is called; age never drops."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    first = client.get("/repositories", params={"since": "weekly"})
    assert first.json()["source"] == {
        "origin": "upstream",
        "cacheAgeSeconds": 0,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
    }

    frozen_clock.advance(10)
    second = client.get("/repositories", params={"since": "weekly"})
    assert second.json()["source"] == {
        "origin": "cache",
        "cacheAgeSeconds": 10,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
    }

    frozen_clock.advance(5)
    third = client.get("/repositories", params={"since": "weekly"})
    third_source = third.json()["source"]
    assert third_source["origin"] == "cache"
    assert third_source["cacheAgeSeconds"] == 15
    assert len(calls) == 1


@pytest.mark.parametrize(
    "first_params,second_params",
    [
        ({"since": "daily"}, {"since": "weekly"}),
        (
            {"spoken_language_code": "en"},
            {"spoken_language_code": "zh"},
        ),
    ],
)
def test_different_query_parameters_do_not_share_cache(
    monkeypatch,
    first_params,
    second_params,
):
    """Path 3a: distinct query params each trigger their own upstream fetch."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    first = client.get("/repositories", params=first_params)
    second = client.get("/repositories", params=second_params)

    assert first.json()["source"]["origin"] == "upstream"
    assert second.json()["source"]["origin"] == "upstream"
    assert second.json()["source"]["cacheAgeSeconds"] == 0
    assert len(calls) == 2
    assert calls[0][1]["params"] != calls[1][1]["params"]


def test_different_language_paths_do_not_share_cache(monkeypatch):
    """Path 3b: distinct programming-language paths own separate entries."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    first = client.get("/repositories/python")
    second = client.get("/repositories/typescript")

    assert first.json()["source"]["origin"] == "upstream"
    assert second.json()["source"]["origin"] == "upstream"
    assert len(calls) == 2
    assert calls[0][0] != calls[1][0]


def test_expired_cache_is_refetched_and_age_resets(monkeypatch, frozen_clock):
    """Path 4: after the TTL elapses the same params are fetched upstream."""
    calls = []
    monkeypatch.setattr(
        main,
        "get_request",
        stub_upstream_html("repodata2.html", calls),
    )

    first = client.get("/repositories", params={"since": "weekly"})
    assert first.json()["source"]["origin"] == "upstream"

    frozen_clock.advance(CACHE_TTL_SECONDS)  # exactly at expiry boundary
    refetched = client.get("/repositories", params={"since": "weekly"})
    assert refetched.json()["source"] == {
        "origin": "upstream",
        "cacheAgeSeconds": 0,
        "cacheTtlSeconds": CACHE_TTL_SECONDS,
    }
    assert len(calls) == 2

    frozen_clock.advance(1)
    cached_again = client.get("/repositories", params={"since": "weekly"})
    assert cached_again.json()["source"]["origin"] == "cache"
    assert cached_again.json()["source"]["cacheAgeSeconds"] == 1
    assert len(calls) == 2


@pytest.mark.parametrize(
    "reason",
    [
        UpstreamFailureReason.timeout,
        UpstreamFailureReason.connection_error,
    ],
)
def test_upstream_failure_returns_retryable_502_with_reason(monkeypatch, reason):
    """Path 5: upstream failures keep the detail and add retry + category."""

    async def failing_get_request(*args, **kwargs):
        raise UpstreamRequestError("upstream unavailable", failure_reason=reason)

    monkeypatch.setattr(main, "get_request", failing_get_request)

    response = client.get("/repositories")

    assert response.status_code == 502
    assert response.json() == {
        "detail": "Unable to fetch GitHub Trending data",
        "retryable": True,
        "failureReason": reason.value,
    }


def test_upstream_failure_does_not_populate_cache(monkeypatch):
    """A failed fetch must not poison the cache for the next request."""
    responses = []

    async def failing_get_request(*args, **kwargs):
        raise UpstreamRequestError(
            "timeout",
            failure_reason=UpstreamFailureReason.timeout,
        )

    async def recovering_get_request(*args, **kwargs):
        responses.append((args, kwargs))
        return (DATA_DIR / "repodata2.html").read_text(encoding="utf-8")

    monkeypatch.setattr(main, "get_request", failing_get_request)
    failed = client.get("/repositories")
    assert failed.status_code == 502

    monkeypatch.setattr(main, "get_request", recovering_get_request)
    recovered = client.get("/repositories")
    assert recovered.status_code == 200
    assert recovered.json()["source"]["origin"] == "upstream"
    assert len(responses) == 1


def test_empty_upstream_html_returns_empty_list(monkeypatch):
    """Tests empty upstream HTML returns an empty successful result."""

    async def fake_get_request(*args, **kwargs):
        return ""

    monkeypatch.setattr(main, "get_request", fake_get_request)

    response = client.get("/developers")

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == []
    assert body["source"]["origin"] == "upstream"


def test_openapi_documents_repository_response_model():
    """Tests repository routes expose a typed response schema."""
    response = client.get("/openapi.json")

    repository_response = response.json()["paths"]["/repositories"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert repository_response == {
        "$ref": "#/components/schemas/TrendingResponse_Repository_",
    }
    trending_schema = response.json()["components"]["schemas"][
        "TrendingResponse_Repository_"
    ]
    assert trending_schema["properties"]["data"] == {
        "items": {"$ref": "#/components/schemas/Repository"},
        "type": "array",
        "title": "Data",
    }
    assert trending_schema["properties"]["source"] == {
        "$ref": "#/components/schemas/TrendingSource",
    }


def test_openapi_documents_developer_response_model():
    """Tests developer routes expose a typed response schema."""
    response = client.get("/openapi.json")

    developer_response = response.json()["paths"]["/developers"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert developer_response == {
        "$ref": "#/components/schemas/TrendingResponse_Developer_",
    }
    trending_schema = response.json()["components"]["schemas"][
        "TrendingResponse_Developer_"
    ]
    assert trending_schema["properties"]["data"] == {
        "items": {"$ref": "#/components/schemas/Developer"},
        "type": "array",
        "title": "Data",
    }
    assert trending_schema["properties"]["source"] == {
        "$ref": "#/components/schemas/TrendingSource",
    }


@pytest.mark.parametrize(
    "route",
    [
        "/repositories",
        "/repositories/{prog_lang}",
        "/developers",
        "/developers/{prog_lang}",
    ],
)
def test_openapi_documents_structured_502(route):
    """All trending routes document the structured upstream failure body."""
    spec = client.get("/openapi.json").json()

    bad_gateway = spec["paths"][route]["get"]["responses"]["502"]
    assert bad_gateway["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/UpstreamFailure",
    }
    failure_schema = spec["components"]["schemas"]["UpstreamFailure"]
    assert set(failure_schema["required"]) == {
        "detail",
        "retryable",
        "failureReason",
    }
    reason_enum = spec["components"]["schemas"]["UpstreamFailureReason"]
    assert reason_enum["enum"] == ["timeout", "connection_error"]
