"""
Airflow DAG: daily OpenWeatherMap collection for ten UK cities.

The dag_id (``weather_etl``), the daily schedule and the ``weather`` table
schema are unchanged. What changed is the task's per-city reliability:

* every city produces an auditable result (city / status / reason /
  rows_inserted) that is logged and pushed to XCom;
* one city failing never blocks the others and never leaves a partial row;
* a re-run for the same city on the same day is detected and skipped
  instead of inserting a duplicate row.

The task is marked failed when at least one city fails, but only *after*
the full per-city report has been logged and archived to XCom, so operators
always see which cities succeeded / failed / skipped and how many rows were
actually added.
"""

import logging
from datetime import datetime, timezone

from airflow import DAG
from airflow.operators.python import PythonOperator

from weather_pipeline import (
    UK_CITIES,
    PostgresWeatherRepo,
    run_pipeline,
    utc_today,
)

logger = logging.getLogger(__name__)


def store_weather(**context):
    """Collect weather for every UK city and archive the per-city report."""
    repo = None
    try:
        # Production connection: env vars supplied by docker-compose, same
        # host/db/user/password as the previous implementation.
        repo = PostgresWeatherRepo.from_env()

        # A single run date for the whole run makes "same city, same day"
        # duplicate detection deterministic across cities.
        run_date = utc_today()
        results, summary = run_pipeline(
            cities=UK_CITIES, repo=repo, run_date=run_date
        )

        # Archive the auditable per-city outcome so downstream tasks and
        # operators can read it from the Airflow UI (XCom) as well as logs.
        ti = context.get("ti")
        if ti is not None:
            ti.xcom_push(key="city_results", value=results)
            ti.xcom_push(key="run_summary", value=summary)

        if summary["failed"]:
            # Surface the failure to Airflow (red task, retries) without
            # losing the report that was just logged / pushed to XCom.
            failed = [
                f"{r['city']}({r['reason']})"
                for r in results
                if r["status"] == "failed"
            ]
            raise RuntimeError(
                f"Weather collection failed for {summary['failed']} city/cities: "
                f"{', '.join(failed)}. See task log / XCom 'city_results' "
                f"for the full per-city report."
            )

        return {"city_results": results, "run_summary": summary}
    finally:
        if repo is not None:
            repo.close()


# Define Airflow DAG
default_args = {
    "start_date": datetime(2024, 1, 1),
}

# DAG definition: runs daily and triggers weather fetch/store task
with DAG(
    dag_id="weather_etl",
    schedule_interval="@daily",
    default_args=default_args,
    catchup=False,
) as dag:

    store_weather_task = PythonOperator(
        task_id="store_weather",
        python_callable=store_weather,
    )

    store_weather_task
