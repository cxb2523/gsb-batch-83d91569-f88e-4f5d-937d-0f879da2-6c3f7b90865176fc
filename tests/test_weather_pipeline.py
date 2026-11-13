"""
Local verification for the weather collection pipeline.

These tests deliberately use *fake* HTTP responses and a *fake* repository:
they validate the control flow (status classification, duplicate skipping,
per-city isolation, rollback, reporting) without any network call or real
database. They do NOT prove the production path works - production still
uses OpenWeatherMap and PostgreSQL via the real env vars in docker-compose.

Run (from the repo root):

    python -I -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import date
from pathlib import Path

# Make ``dags`` importable without installing anything and without relying
# on the current working directory (which would make planted modules risky).
DAGS_DIR = Path(__file__).resolve().parent.parent / "dags"
sys.path.insert(0, str(DAGS_DIR))

import weather_pipeline as wp  # noqa: E402


CITIES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Manchester", "lat": 53.4808, "lon": -2.2426},
    {"name": "Glasgow", "lat": 55.8642, "lon": -4.2518},
]
RUN_DATE = date(2026, 11, 13)


def good_payload(city_name="London", temp=12.5, humidity=80, desc="cloudy"):
    return {
        "main": {"temp": temp, "humidity": humidity},
        "weather": [{"description": desc, "main": "Clouds"}],
        "name": city_name,
    }


class FakeResponse:
    def __init__(self, status_code=200, payload=None, raise_json=False):
        self.status_code = status_code
        self._payload = payload if payload is not None else good_payload()
        self._raise_json = raise_json

    def json(self):
        if self._raise_json:
            raise ValueError("no JSON object could be decoded")
        return self._payload


def make_http_get(mapping):
    """Build a requests.get-like callable from a {city: FakeResponse} map."""

    def fake_get(url, timeout=None):
        # The URL always carries the lat/lon; map back via the city name is
        # not in the URL, so tests pass responses in city order instead.
        response = mapping.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    return fake_get


def ordered_get(*responses):
    return make_http_get(list(responses))


class FakeWeatherRepo:
    """In-memory stand-in for PostgresWeatherRepo with failure injection."""

    def __init__(self, existing=None):
        # Set of (city, iso_date) tuples already in the "table".
        self._rows = set(existing or [])
        self.inserted = []
        self.rollback_count = 0
        self.fail_on = None  # city name whose next insert/select raises

    def record_exists(self, city_name, run_date):
        if self.fail_on == city_name:
            raise RuntimeError(f"injected SELECT failure for {city_name}")
        return (city_name, run_date.isoformat()) in self._rows

    def insert_weather(self, weather):
        city = weather["city"]
        if self.fail_on == city:
            raise RuntimeError(f"injected INSERT failure for {city}")
        self._rows.add((city, weather["date"].isoformat()))
        self.inserted.append(weather)

    def rollback(self):
        self.rollback_count += 1


class FetchWeatherTests(unittest.TestCase):
    def test_success_returns_validated_record(self):
        http_get = ordered_get(FakeResponse(payload=good_payload()))
        record = wp.fetch_weather(
            CITIES[0], api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(record["city"], "London")
        self.assertEqual(record["temperature"], 12.5)
        self.assertEqual(record["humidity"], 80)
        self.assertEqual(record["description"], "cloudy")
        self.assertEqual(record["date"], RUN_DATE)

    def test_http_500_classified_as_http_error(self):
        http_get = ordered_get(FakeResponse(status_code=500, payload={}))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_HTTP_ERROR)
        self.assertIn("non-2xx", ctx.exception.message)

    def test_http_404_classified_as_http_error(self):
        http_get = ordered_get(FakeResponse(status_code=404, payload={}))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_HTTP_ERROR)

    def test_transport_exception_classified_as_http_error(self):
        import requests

        http_get = ordered_get(
            requests.ConnectionError("network unreachable")
        )
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_HTTP_ERROR)

    def test_missing_main_temp_classified_as_invalid_response(self):
        payload = good_payload()
        del payload["main"]["temp"]
        http_get = ordered_get(FakeResponse(payload=payload))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)
        self.assertIn("main.temp", ctx.exception.message)

    def test_missing_main_block_classified_as_invalid_response(self):
        payload = good_payload()
        del payload["main"]
        http_get = ordered_get(FakeResponse(payload=payload))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)

    def test_missing_weather_description_classified_as_invalid_response(self):
        payload = good_payload()
        del payload["weather"][0]["description"]
        http_get = ordered_get(FakeResponse(payload=payload))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)
        self.assertIn("weather[0].description", ctx.exception.message)

    def test_empty_weather_array_classified_as_invalid_response(self):
        payload = good_payload()
        payload["weather"] = []
        http_get = ordered_get(FakeResponse(payload=payload))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)

    def test_non_json_body_classified_as_invalid_response(self):
        http_get = ordered_get(FakeResponse(raise_json=True))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)

    def test_null_temp_treated_as_missing(self):
        payload = good_payload()
        payload["main"]["temp"] = None
        http_get = ordered_get(FakeResponse(payload=payload))
        with self.assertRaises(wp.WeatherFetchError) as ctx:
            wp.fetch_weather(CITIES[0], api_key="k", http_get=http_get)
        self.assertEqual(ctx.exception.reason, wp.REASON_INVALID_RESPONSE)


class ProcessCityTests(unittest.TestCase):
    def test_success_inserts_one_row_and_reports_it(self):
        repo = FakeWeatherRepo()
        http_get = ordered_get(FakeResponse(payload=good_payload()))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_SUCCESS)
        self.assertIsNone(result["reason"])
        self.assertEqual(result["rows_inserted"], 1)
        self.assertEqual(len(repo.inserted), 1)
        self.assertEqual(repo.rollback_count, 0)

    def test_duplicate_same_city_same_day_is_skipped_not_inserted(self):
        repo = FakeWeatherRepo(existing=[("London", RUN_DATE.isoformat())])
        # Even though the API would return data, no second row may be added.
        http_get = ordered_get(FakeResponse(payload=good_payload()))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_SKIPPED)
        self.assertEqual(result["reason"], wp.REASON_DUPLICATE_DATE)
        self.assertEqual(result["rows_inserted"], 0)
        self.assertEqual(repo.inserted, [])

    def test_db_insert_failure_is_db_error_rolled_back_no_partial_row(self):
        repo = FakeWeatherRepo()
        repo.fail_on = "London"
        http_get = ordered_get(FakeResponse(payload=good_payload()))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_FAILED)
        self.assertEqual(result["reason"], wp.REASON_DB_ERROR)
        self.assertEqual(result["rows_inserted"], 0)
        self.assertEqual(repo.rollback_count, 1)
        # Nothing persisted for the failed city.
        self.assertEqual(repo.inserted, [])
        self.assertNotIn(("London", RUN_DATE.isoformat()), repo._rows)

    def test_db_select_failure_is_also_db_error(self):
        repo = FakeWeatherRepo()
        repo.fail_on = "London"  # raises inside record_exists as well
        http_get = ordered_get(FakeResponse(payload=good_payload()))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_FAILED)
        self.assertEqual(result["reason"], wp.REASON_DB_ERROR)

    def test_http_failure_never_touches_database(self):
        repo = FakeWeatherRepo()
        http_get = ordered_get(FakeResponse(status_code=503, payload={}))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_FAILED)
        self.assertEqual(result["reason"], wp.REASON_HTTP_ERROR)
        self.assertEqual(result["rows_inserted"], 0)
        self.assertEqual(repo.inserted, [])
        self.assertEqual(repo.rollback_count, 0)

    def test_missing_field_failure_never_touches_database(self):
        repo = FakeWeatherRepo()
        payload = good_payload()
        del payload["weather"][0]["description"]
        http_get = ordered_get(FakeResponse(payload=payload))
        result = wp.process_city(
            CITIES[0], repo, api_key="k", http_get=http_get, run_date=RUN_DATE
        )
        self.assertEqual(result["status"], wp.STATUS_FAILED)
        self.assertEqual(result["reason"], wp.REASON_INVALID_RESPONSE)
        self.assertEqual(repo.inserted, [])


class RunPipelineTests(unittest.TestCase):
    def test_mixed_run_isolates_cities_and_keeps_all_results(self):
        # London: success; Manchester: http failure; Glasgow: duplicate skip.
        repo = FakeWeatherRepo(existing=[("Glasgow", RUN_DATE.isoformat())])
        http_get = ordered_get(
            FakeResponse(payload=good_payload("London")),
            FakeResponse(status_code=500, payload={}),
            FakeResponse(payload=good_payload("Glasgow")),
        )
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=repo, api_key="k",
            http_get=http_get, run_date=RUN_DATE,
        )

        by_city = {r["city"]: r for r in results}
        self.assertEqual(by_city["London"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["London"]["rows_inserted"], 1)
        self.assertEqual(by_city["Manchester"]["status"], wp.STATUS_FAILED)
        self.assertEqual(by_city["Manchester"]["reason"], wp.REASON_HTTP_ERROR)
        self.assertEqual(by_city["Glasgow"]["status"], wp.STATUS_SKIPPED)
        self.assertEqual(by_city["Glasgow"]["reason"], wp.REASON_DUPLICATE_DATE)

        self.assertEqual(summary["total_cities"], 3)
        self.assertEqual(summary["succeeded"], 1)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["rows_inserted"], 1)

        # Every result carries the four auditable fields.
        for r in results:
            self.assertIn("city", r)
            self.assertIn("status", r)
            self.assertIn("reason", r)
            self.assertIn("rows_inserted", r)
            self.assertIn("date", r)

    def test_second_run_same_day_skips_everything_adds_no_rows(self):
        repo = FakeWeatherRepo()
        first_get = ordered_get(*[
            FakeResponse(payload=good_payload(c))
            for c in ["London", "Manchester", "Glasgow"]
        ])
        results_1, summary_1 = wp.run_pipeline(
            cities=CITIES, repo=repo, api_key="k",
            http_get=first_get, run_date=RUN_DATE,
        )
        self.assertEqual(summary_1["rows_inserted"], 3)

        second_get = ordered_get(*[
            FakeResponse(payload=good_payload(c))
            for c in ["London", "Manchester", "Glasgow"]
        ])
        results_2, summary_2 = wp.run_pipeline(
            cities=CITIES, repo=repo, api_key="k",
            http_get=second_get, run_date=RUN_DATE,
        )
        self.assertTrue(all(r["status"] == wp.STATUS_SKIPPED for r in results_2))
        self.assertEqual(summary_2["skipped"], 3)
        self.assertEqual(summary_2["rows_inserted"], 0)
        # Still exactly one stored row per city.
        self.assertEqual(len(repo.inserted), 3)

    def test_one_city_db_failure_does_not_block_other_cities(self):
        repo = FakeWeatherRepo()
        repo.fail_on = "Manchester"
        http_get = ordered_get(
            FakeResponse(payload=good_payload("London")),
            FakeResponse(payload=good_payload("Manchester")),
            FakeResponse(payload=good_payload("Glasgow")),
        )
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=repo, api_key="k",
            http_get=http_get, run_date=RUN_DATE,
        )
        by_city = {r["city"]: r for r in results}
        self.assertEqual(by_city["London"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["Manchester"]["reason"], wp.REASON_DB_ERROR)
        self.assertEqual(by_city["Glasgow"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(summary["succeeded"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["rows_inserted"], 2)

    def test_different_cities_same_day_do_not_interfere(self):
        # Only London pre-exists; Manchester and Glasgow must still insert.
        repo = FakeWeatherRepo(existing=[("London", RUN_DATE.isoformat())])
        http_get = ordered_get(
            FakeResponse(payload=good_payload("London")),
            FakeResponse(payload=good_payload("Manchester")),
            FakeResponse(payload=good_payload("Glasgow")),
        )
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=repo, api_key="k",
            http_get=http_get, run_date=RUN_DATE,
        )
        by_city = {r["city"]: r for r in results}
        self.assertEqual(by_city["London"]["status"], wp.STATUS_SKIPPED)
        self.assertEqual(by_city["Manchester"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["Glasgow"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(summary["rows_inserted"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
