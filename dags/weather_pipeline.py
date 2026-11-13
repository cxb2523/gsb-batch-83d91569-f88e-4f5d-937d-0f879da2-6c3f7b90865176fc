"""
Weather collection pipeline core logic.

This module is intentionally Airflow-free: it only uses ``requests`` /
``psycopg2`` so the same code can be exercised locally with fakes (see
``tests/test_weather_pipeline.py``) and imported by the Airflow DAG in
``dags/weather_etl.py``.

Per-city outcome model
----------------------
Every city produces one result dict::

    {
        "city": str,
        "status": "success" | "failed" | "skipped",
        "reason": str | None,          # None when success, populated otherwise
        "rows_inserted": int,          # rows actually added this run (0 or 1)
        "date": "YYYY-MM-DD",
    }

Failure reasons fall into three explicit categories:

* ``http_error``       - the HTTP call failed or returned a non-2xx status
* ``invalid_response`` - HTTP 2xx but a required field
                         (``main.temp`` / ``main.humidity`` /
                         ``weather[0].description``) is missing
* ``db_error``         - PostgreSQL read/write raised an exception

A duplicate (city, date) already present in the ``weather`` table is
reported as ``skipped`` / ``duplicate_date`` and no row is inserted.
"""

import logging
import os
from datetime import date, datetime, timezone

import requests

logger = logging.getLogger(__name__)


def utc_today():
    """Current calendar date in UTC (timezone-aware, no deprecation path)."""
    return datetime.now(timezone.utc).date()

# List of major UK cities with coordinates for accurate weather data
UK_CITIES = [
    {"name": "London", "lat": 51.5074, "lon": -0.1278},
    {"name": "Birmingham", "lat": 52.4862, "lon": -1.8904},
    {"name": "Manchester", "lat": 53.4808, "lon": -2.2426},
    {"name": "Glasgow", "lat": 55.8642, "lon": -4.2518},
    {"name": "Liverpool", "lat": 53.4084, "lon": -2.9916},
    {"name": "Leeds", "lat": 53.8008, "lon": -1.5491},
    {"name": "Sheffield", "lat": 53.3811, "lon": -1.4701},
    {"name": "Bristol", "lat": 51.4545, "lon": -2.5879},
    {"name": "Newcastle", "lat": 54.9784, "lon": -1.6174},
    {"name": "Nottingham", "lat": 52.9548, "lon": -1.1581},
]

# Status / reason vocabulary (kept as constants so tests and the DAG can
# rely on the exact strings).
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

REASON_HTTP_ERROR = "http_error"
REASON_INVALID_RESPONSE = "invalid_response"
REASON_DB_ERROR = "db_error"
REASON_DUPLICATE_DATE = "duplicate_date"

OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
HTTP_TIMEOUT_SECONDS = 30


class WeatherFetchError(Exception):
    """Raised when the upstream API cannot provide a usable payload.

    ``reason`` is one of ``REASON_HTTP_ERROR`` / ``REASON_INVALID_RESPONSE``
    so callers can categorise the failure without parsing the message.
    """

    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason
        self.message = message


def _build_url(lat, lon, api_key):
    return (
        f"{OPENWEATHER_URL}?lat={lat}&lon={lon}"
        f"&appid={api_key}&units=metric"
    )


def fetch_weather(city, api_key=None, http_get=None, run_date=None):
    """Fetch and validate current weather for one city.

    Parameters
    ----------
    city:
        City mapping with ``name`` / ``lat`` / ``lon``.
    api_key:
        OpenWeatherMap API key. Defaults to the ``OPENWEATHER_API_KEY``
        environment variable (the production path).
    http_get:
        Callable with the ``requests.get`` signature. Injected by tests;
        production code uses the real ``requests.get``.
    run_date:
        Date stamped on the record. Defaults to today (UTC).

    Returns
    -------
    dict
        Validated weather record ready for insertion.

    Raises
    ------
    WeatherFetchError
        With ``reason`` ``http_error`` for transport failures / non-2xx
        responses or ``invalid_response`` for malformed 2xx payloads.
    """
    if api_key is None:
        api_key = os.getenv("OPENWEATHER_API_KEY")
    if http_get is None:
        http_get = requests.get
    if run_date is None:
        run_date = utc_today()

    city_name = city["name"]
    url = _build_url(city["lat"], city["lon"], api_key)

    try:
        response = http_get(url, timeout=HTTP_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        # DNS failure, timeout, connection reset, ...
        raise WeatherFetchError(
            REASON_HTTP_ERROR,
            f"HTTP request failed for {city_name}: {exc}",
        ) from exc

    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int) or not 200 <= status_code < 300:
        raise WeatherFetchError(
            REASON_HTTP_ERROR,
            f"HTTP non-2xx response for {city_name}: status={status_code}",
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} is not valid JSON: {exc}",
        ) from exc

    if not isinstance(data, dict):
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} is not a JSON object",
        )

    # Explicit required-field validation. A missing field must never become
    # a NULL / half-written row: we fail the city before touching the DB.
    main = data.get("main")
    weather_list = data.get("weather")

    if not isinstance(main, dict):
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} missing required field 'main.temp'",
        )
    if main.get("temp") is None:
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} missing required field 'main.temp'",
        )
    if main.get("humidity") is None:
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} is missing required field 'main.humidity'",
        )
    if (
        not isinstance(weather_list, list)
        or not weather_list
        or not isinstance(weather_list[0], dict)
        or weather_list[0].get("description") is None
    ):
        raise WeatherFetchError(
            REASON_INVALID_RESPONSE,
            f"Response for {city_name} missing required field "
            f"'weather[0].description'",
        )

    return {
        "city": city_name,
        "temperature": main["temp"],
        "humidity": main["humidity"],
        "description": weather_list[0]["description"],
        "date": run_date,
    }


def _new_result(city_name, run_date, status, reason, rows_inserted):
    return {
        "city": city_name,
        "status": status,
        "reason": reason,
        "rows_inserted": rows_inserted,
        "date": run_date.isoformat() if isinstance(run_date, date) else str(run_date),
    }


def process_city(city, repo, api_key=None, http_get=None, run_date=None):
    """Process a single city end to end and return its result dict.

    A failure for this city is contained here: it never propagates and
    never leaves a partial row behind.
    """
    if run_date is None:
        run_date = utc_today()
    city_name = city["name"]

    try:
        weather = fetch_weather(
            city, api_key=api_key, http_get=http_get, run_date=run_date
        )
    except WeatherFetchError as exc:
        logger.error("Fetch failed for %s: %s", city_name, exc.message)
        return _new_result(city_name, run_date, STATUS_FAILED, exc.reason, 0)
    except Exception as exc:  # defensive: never let one city kill the run
        logger.exception("Unexpected fetch error for %s", city_name)
        return _new_result(
            city_name, run_date, STATUS_FAILED, REASON_INVALID_RESPONSE, 0
        )

    try:
        if repo.record_exists(city_name, run_date):
            logger.info(
                "Skipping %s: a record already exists for %s",
                city_name,
                run_date,
            )
            return _new_result(
                city_name, run_date, STATUS_SKIPPED, REASON_DUPLICATE_DATE, 0
            )

        repo.insert_weather(weather)
        logger.info(
            "Inserted 1 row for %s (temp=%s, humidity=%s, '%s')",
            city_name,
            weather["temperature"],
            weather["humidity"],
            weather["description"],
        )
        return _new_result(city_name, run_date, STATUS_SUCCESS, None, 1)
    except Exception as exc:
        # Roll back anything this city's attempt may have written so no
        # NULL / half record survives, then categorise as a DB failure.
        try:
            repo.rollback()
        except Exception:
            logger.exception("Rollback failed for %s", city_name)
        logger.error("Database error for %s: %s", city_name, exc)
        return _new_result(
            city_name, run_date, STATUS_FAILED, REASON_DB_ERROR, 0
        )


def summarise_results(results):
    """Aggregate per-city results into a run-level summary."""
    return {
        "total_cities": len(results),
        "succeeded": sum(1 for r in results if r["status"] == STATUS_SUCCESS),
        "failed": sum(1 for r in results if r["status"] == STATUS_FAILED),
        "skipped": sum(1 for r in results if r["status"] == STATUS_SKIPPED),
        "rows_inserted": sum(r["rows_inserted"] for r in results),
    }


def log_run_report(run_date, results):
    """Emit the operator-facing per-city report into the Airflow task log."""
    summary = summarise_results(results)
    logger.info("=" * 72)
    logger.info("Weather collection report for %s", run_date)
    logger.info("-" * 72)
    logger.info(
        "%-12s | %-8s | %-16s | %s", "city", "status", "reason", "rows_inserted"
    )
    for r in results:
        logger.info(
            "%-12s | %-8s | %-16s | %d",
            r["city"],
            r["status"],
            r["reason"] or "-",
            r["rows_inserted"],
        )
    logger.info("-" * 72)
    logger.info(
        "Summary: %d cities | success=%d failed=%d skipped=%d | rows inserted=%d",
        summary["total_cities"],
        summary["succeeded"],
        summary["failed"],
        summary["skipped"],
        summary["rows_inserted"],
    )
    logger.info("=" * 72)
    return summary


def run_pipeline(cities=None, repo=None, api_key=None, http_get=None,
                 run_date=None):
    """Run the full collection for every city and return the results.

    Each city is processed independently. One city's failure never blocks
    the others and never corrupts the table. The connection is owned by the
    caller-provided ``repo``; this function does not close it.
    """
    if cities is None:
        cities = UK_CITIES
    if run_date is None:
        run_date = utc_today()

    results = []
    for city in cities:
        results.append(
            process_city(
                city,
                repo,
                api_key=api_key,
                http_get=http_get,
                run_date=run_date,
            )
        )

    summary = log_run_report(run_date, results)
    return results, summary


# ---------------------------------------------------------------------------
# Production repository (PostgreSQL via psycopg2)
# ---------------------------------------------------------------------------

class PostgresWeatherRepo:
    """Repository backed by the existing ``weather`` table (schema unchanged).

    Each city is committed independently so a failure rolls back only that
    city's work while successful cities remain durably stored.
    """

    DUPLICATE_QUERY = "SELECT 1 FROM weather WHERE city = %s AND date = %s LIMIT 1"
    INSERT_QUERY = """
        INSERT INTO weather (city, temperature, humidity,
                             weather_description, date)
        VALUES (%s, %s, %s, %s, %s)
    """

    def __init__(self, connection):
        self._conn = connection

    @classmethod
    def from_env(cls):
        """Open a connection using the same env vars as the original DAG."""
        import psycopg2

        kwargs = dict(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            database=os.getenv("POSTGRES_DB"),
            user=os.getenv("POSTGRES_USER"),
            password=os.getenv("POSTGRES_PASSWORD"),
        )
        # Optional override; inside the compose network the default 5432
        # applies, so existing deployments are unaffected.
        port = os.getenv("POSTGRES_PORT")
        if port:
            kwargs["port"] = port
        conn = psycopg2.connect(**kwargs)
        return cls(conn)

    def record_exists(self, city_name, run_date):
        cur = self._conn.cursor()
        try:
            cur.execute(self.DUPLICATE_QUERY, (city_name, run_date))
            return cur.fetchone() is not None
        finally:
            cur.close()

    def insert_weather(self, weather):
        cur = self._conn.cursor()
        try:
            cur.execute(
                self.INSERT_QUERY,
                (
                    weather["city"],
                    weather["temperature"],
                    weather["humidity"],
                    weather["description"],
                    weather["date"],
                ),
            )
        finally:
            cur.close()
        # Per-city commit: isolate each city's transaction.
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()
