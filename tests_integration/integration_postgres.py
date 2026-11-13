"""
Integration check against a REAL PostgreSQL instance.

Unlike ``tests/test_weather_pipeline.py`` (fully in-memory fakes), this
exercises the production repository class ``PostgresWeatherRepo`` end to
end: real SQL, real per-city commits and real rollback on failure. The
OpenWeatherMap HTTP layer is still faked - this script never calls the
external API and does not need an API key.

Requirements:
  * a reachable PostgreSQL with the production ``weather`` table
  * env vars POSTGRES_HOST / POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD

Usage (see the run_integration.sh helper):
  python -I tests_integration/integration_postgres.py
"""

import os
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dags"))

import psycopg2  # noqa: E402

import weather_pipeline as wp  # noqa: E402


CITIES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Manchester", "lat": 53.4808, "lon": -2.2426},
    {"name": "Glasgow", "lat": 55.8642, "lon": -4.2518},
    {"name": "Bristol", "lat": 51.4545, "lon": -2.5879},
]
RUN_DATE = date(2026, 11, 13)


def good_payload(city_name, temp=10.0, humidity=70, desc="rain"):
    return {
        "main": {"temp": temp, "humidity": humidity},
        "weather": [{"description": desc}],
        "name": city_name,
    }


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def ordered_get(*responses):
    queue = list(responses)

    def fake_get(url, timeout=None):
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return fake_get


CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS weather (
    id SERIAL PRIMARY KEY,
    city VARCHAR(50),
    temperature FLOAT,
    humidity INTEGER,
    weather_description TEXT,
    date DATE
);
"""


def connect_kwargs():
    kwargs = dict(
        host=os.environ["POSTGRES_HOST"],
        database=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )
    if os.environ.get("POSTGRES_PORT"):
        kwargs["port"] = os.environ["POSTGRES_PORT"]
    return kwargs


class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = psycopg2.connect(**connect_kwargs())
        cls.conn.autocommit = True
        with cls.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS weather;")
            cur.execute(CREATE_TABLE)

    @classmethod
    def tearDownClass(cls):
        with cls.conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS weather;")
        cls.conn.close()

    def setUp(self):
        with self.conn.cursor() as cur:
            cur.execute("TRUNCATE weather RESTART IDENTITY;")
        self.repo = wp.PostgresWeatherRepo(psycopg2.connect(**connect_kwargs()))

    def tearDown(self):
        self.repo.close()

    def _count(self, city=None, day=None):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM weather;")
            return cur.fetchone()[0]

    def test_full_success_inserts_one_row_per_city(self):
        http_get = ordered_get(*[
            FakeResponse(payload=good_payload(c["name"])) for c in CITIES
        ])
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=self.repo, api_key="fake",
            http_get=http_get, run_date=RUN_DATE,
        )
        self.assertTrue(all(r["status"] == wp.STATUS_SUCCESS for r in results))
        self.assertEqual(summary["rows_inserted"], 4)
        self.assertEqual(self._count(), 4)

        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT city, temperature, humidity, weather_description, date "
                "FROM weather ORDER BY city;"
            )
            rows = cur.fetchall()
        self.assertEqual(
            [r[0] for r in rows],
            ["Bristol", "Glasgow", "London", "Manchester"],
        )
        # No NULLs / half-written columns.
        for row in rows:
            self.assertTrue(all(v is not None for v in row))
            self.assertEqual(row[4], RUN_DATE)

    def test_rerun_same_day_skips_duplicates_and_adds_zero_rows(self):
        first = ordered_get(*[
            FakeResponse(payload=good_payload(c["name"])) for c in CITIES
        ])
        wp.run_pipeline(
            cities=CITIES, repo=self.repo, api_key="fake",
            http_get=first, run_date=RUN_DATE,
        )
        self.assertEqual(self._count(), 4)

        second = ordered_get(*[
            FakeResponse(payload=good_payload(c["name"], temp=99.0))
            for c in CITIES
        ])
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=self.repo, api_key="fake",
            http_get=second, run_date=RUN_DATE,
        )
        self.assertTrue(all(r["status"] == wp.STATUS_SKIPPED for r in results))
        self.assertTrue(all(r["reason"] == wp.REASON_DUPLICATE_DATE for r in results))
        self.assertEqual(summary["rows_inserted"], 0)
        self.assertEqual(self._count(), 4)  # still exactly four rows

    def test_http_and_invalid_payload_failures_leave_no_rows(self):
        import requests

        bad_missing_temp = good_payload("Manchester")
        del bad_missing_temp["main"]["temp"]
        http_get = ordered_get(
            FakeResponse(payload=good_payload("London")),          # ok
            FakeResponse(status_code=500, payload={}),             # http error
            FakeResponse(payload=bad_missing_temp),                # invalid
            requests.ConnectionError("boom"),                      # transport
        )
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=self.repo, api_key="fake",
            http_get=http_get, run_date=RUN_DATE,
        )
        by_city = {r["city"]: r for r in results}
        self.assertEqual(by_city["London"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["Manchester"]["reason"], wp.REASON_HTTP_ERROR)
        self.assertEqual(by_city["Glasgow"]["reason"], wp.REASON_INVALID_RESPONSE)
        self.assertEqual(by_city["Bristol"]["reason"], wp.REASON_HTTP_ERROR)
        self.assertEqual(summary["rows_inserted"], 1)
        self.assertEqual(self._count(), 1)  # only London persisted

    def test_db_error_rolls_back_and_other_cities_survive(self):
        # Force a REAL database failure (unique violation) on one city by
        # pre-seeding its row outside the repository connection, while the
        # repository's own duplicate check races against it. The production
        # code must roll the failed transaction back, categorise db_error,
        # keep prior cities committed and finish the run without raising.
        with self.conn.cursor() as cur:
            cur.execute(
                "ALTER TABLE weather ADD CONSTRAINT weather_city_date_ux "
                "UNIQUE (city, date);"
            )
            # Seed Glasgow through a different connection so the repo's
            # record_exists() check can still race / the insert is rejected.
            seed_conn = psycopg2.connect(**connect_kwargs())
            with seed_conn.cursor() as scur:
                scur.execute(
                    "INSERT INTO weather (city, temperature, humidity, "
                    "weather_description, date) VALUES (%s,%s,%s,%s,%s)",
                    ("Glasgow", 1.0, 1, "seeded", RUN_DATE),
                )
            seed_conn.commit()
            seed_conn.close()

        # Make the repo blind to the pre-seeded row: stub record_exists to
        # False so it proceeds to INSERT and hits the real constraint.
        self.repo.record_exists = lambda city_name, run_date: False

        http_get = ordered_get(*[
            FakeResponse(payload=good_payload(c["name"])) for c in CITIES
        ])
        results, summary = wp.run_pipeline(
            cities=CITIES, repo=self.repo, api_key="fake",
            http_get=http_get, run_date=RUN_DATE,
        )
        by_city = {r["city"]: r for r in results}
        self.assertEqual(by_city["London"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["Manchester"]["status"], wp.STATUS_SUCCESS)
        self.assertEqual(by_city["Glasgow"]["status"], wp.STATUS_FAILED)
        self.assertEqual(by_city["Glasgow"]["reason"], wp.REASON_DB_ERROR)
        self.assertEqual(by_city["Glasgow"]["rows_inserted"], 0)
        # Cities after the failed one still work: the rollback restored the
        # transaction to a usable state.
        self.assertEqual(by_city["Bristol"]["status"], wp.STATUS_SUCCESS)

        # Glasgow's row is exactly the seeded one (no partial duplicate).
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT weather_description FROM weather WHERE city = 'Glasgow';"
            )
            self.assertEqual(cur.fetchall(), [("seeded",)])
            cur.execute("SELECT COUNT(*) FROM weather;")
            self.assertEqual(cur.fetchone()[0], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
