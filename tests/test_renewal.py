"""Offline tests for renew_python_anywhere.py.

Every test drives the renewal logic through an in-memory FakeSession backed
by self-made HTML/JSON fixtures under ``tests/fixtures``. No real network I/O
is possible: requesting a URL without a registered fake route raises
``AssertionError`` instead of opening a socket, so PythonAnywhere is never
contacted.

Run locally with:

    python -m unittest discover -s tests -v
"""

import json
import os
import pathlib
import sys
import unittest
from unittest import mock

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

import renew_python_anywhere as renew  # noqa: E402

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
BASE = renew.BASE_URL
UNSET = object()


def load_fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    """Minimal stand-in for requests.Response used by the renewal code."""

    def __init__(self, status_code=200, text="", url=None,
                 json_data=UNSET, json_error=None):
        self.status_code = status_code
        self.text = text
        self.url = url or "https://example.invalid/"
        self._json_data = json_data
        self._json_error = json_error

    @property
    def content(self):
        return self.text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} error for url {self.url}", response=self
            )

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        if self._json_data is UNSET:
            raise json.JSONDecodeError("Expecting value", self.text or "", 0)
        return self._json_data


class FakeSession:
    """Route table double for requests.Session.

    routes is a list of ``(method, url_substring, response)`` tuples. A
    response is either a FakeResponse or a callable taking
    ``(session, url, kwargs)`` and returning one. The first matching route
    wins; unmatched requests raise, guaranteeing tests stay offline.
    """

    def __init__(self, routes=None, cookies=None):
        self.routes = list(routes or [])
        self.cookies = dict(cookies or {})
        self.headers = {}
        self.requests = []

    def _resolve(self, method, url, kwargs):
        for route_method, needle, response in self.routes:
            if route_method == method and needle in url:
                if callable(response):
                    return response(self, url, kwargs)
                return response
        raise AssertionError(
            f"offline test session has no fake route for {method} {url}"
        )

    def get(self, url, **kwargs):
        self.requests.append(("GET", url, kwargs))
        return self._resolve("GET", url, kwargs)

    def post(self, url, **kwargs):
        self.requests.append(("POST", url, kwargs))
        return self._resolve("POST", url, kwargs)


def html_response(fixture_name, status_code=200, url=None):
    return FakeResponse(
        status_code=status_code, text=load_fixture(fixture_name), url=url
    )


def json_fixture_response(fixture_name, status_code=200, url=None):
    data = json.loads(load_fixture(fixture_name))
    return FakeResponse(
        status_code=status_code,
        text=load_fixture(fixture_name),
        url=url,
        json_data=data,
    )


def login_routes(username):
    return [
        (
            "GET",
            f"{BASE}/login/",
            html_response("login_page.html", url=f"{BASE}/login/"),
        ),
        (
            "POST",
            f"{BASE}/login/",
            FakeResponse(
                status_code=200,
                text="<html><body>log out</body></html>",
                url=f"{BASE}/user/{username}/",
            ),
        ),
    ]


def names_statuses(results):
    return [(item["name"], item["status"]) for item in results]


class OfflineTestCase(unittest.TestCase):
    """Base case: never sleep between simulated renewals."""

    def setUp(self):
        sleep_patcher = mock.patch.object(renew.time, "sleep")
        sleep_patcher.start()
        self.addCleanup(sleep_patcher.stop)


class TaskListFailureTests(OfflineTestCase):
    """The task list endpoint must never abort the account with one error."""

    def test_non_json_response_is_task_level_failure(self):
        session = FakeSession(
            routes=[
                (
                    "GET",
                    "/schedule/",
                    FakeResponse(
                        status_code=200,
                        text=load_fixture("tasks_not_json.txt"),
                        url=f"{BASE}/api/v0/user/alpha/schedule/",
                    ),
                )
            ]
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertEqual(results[0]["name"], "task list")
        self.assertIn("not valid JSON", results[0]["detail"])

    def test_http_error_records_status_code(self):
        session = FakeSession(
            routes=[
                (
                    "GET",
                    "/schedule/",
                    FakeResponse(status_code=503, text="", json_data={}),
                )
            ]
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("HTTP 503", results[0]["detail"])

    def test_results_not_a_list_is_task_level_failure(self):
        session = FakeSession(
            routes=[
                (
                    "GET",
                    "/schedule/",
                    json_fixture_response("tasks_results_not_list.json"),
                )
            ]
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("results list", results[0]["detail"])

    def test_request_exception_is_recorded_not_raised(self):
        class ExplodingSession(FakeSession):
            def get(self, url, **kwargs):
                self.requests.append(("GET", url, kwargs))
                raise requests.ConnectionError("simulated offline failure")

        ok, results = renew.renew_scheduled_tasks(ExplodingSession(), "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("list request failed", results[0]["detail"])
        self.assertIn("simulated offline failure", results[0]["detail"])


class ScheduledTaskTests(OfflineTestCase):
    def _tasks_route(self, payloads):
        calls = {"count": 0}

        def schedule_get(session, url, kwargs):
            payload = payloads[min(calls["count"], len(payloads) - 1)]
            calls["count"] += 1
            if isinstance(payload, FakeResponse):
                return payload
            return FakeResponse(
                status_code=200,
                text=json.dumps(payload),
                json_data=payload,
                url=url,
            )

        return ("GET", "/schedule/", schedule_get), calls

    def test_missing_extend_url_is_skipped_not_failed(self):
        payload = json.loads(load_fixture("tasks_list.json"))
        schedule_route, _ = self._tasks_route([payload])
        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertTrue(ok)
        self.assertEqual(
            names_statuses(results),
            [
                ("python3 /home/alpha/sync_logs.py", renew.STATUS_SUCCESS),
                ("python3 /home/alpha/cleanup.py", renew.STATUS_SKIPPED),
            ],
        )
        skipped = results[1]
        self.assertIn("no extend URL", skipped["detail"])
        # Only the task with an extend_url may be POSTed to.
        post_urls = [url for method, url, _ in session.requests if method == "POST"]
        self.assertEqual(len(post_urls), 1)
        self.assertIn("/schedule/101/extend/", post_urls[0])

    def test_expiry_unchanged_is_maxed_out_success(self):
        schedule_route, _ = self._tasks_route(
            [json.loads(load_fixture("tasks_same_expiry.json"))]
        )
        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertTrue(ok)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["status"], renew.STATUS_SUCCESS)
        self.assertIn("Already maxed out", results[0]["detail"])
        self.assertIn("2026-11-10", results[0]["detail"])

    def test_expiry_change_is_logged_as_renewal(self):
        schedule_route, _ = self._tasks_route(
            [
                json.loads(load_fixture("tasks_same_expiry.json")),
                json.loads(load_fixture("tasks_new_expiry.json")),
            ]
        )
        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertTrue(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_SUCCESS)
        self.assertEqual(results[0]["detail"], "2026-11-10 → 2026-11-20")

    def test_extend_post_failure_does_not_stop_other_tasks(self):
        two_tasks = {
            "results": [
                {
                    "id": 1,
                    "command": "python3 first.py",
                    "expiry": "2026-11-10",
                    "extend_url": "/api/v0/user/alpha/schedule/1/extend/",
                },
                {
                    "id": 2,
                    "command": "python3 second.py",
                    "expiry": "2026-11-11",
                    "extend_url": "/api/v0/user/alpha/schedule/2/extend/",
                },
            ]
        }
        refreshed = {
            "results": [
                {
                    "id": 1,
                    "command": "python3 first.py",
                    "expiry": "2026-11-10",
                    "extend_url": "/api/v0/user/alpha/schedule/1/extend/",
                },
                {
                    "id": 2,
                    "command": "python3 second.py",
                    "expiry": "2026-11-25",
                    "extend_url": "/api/v0/user/alpha/schedule/2/extend/",
                },
            ]
        }
        schedule_route, _ = self._tasks_route([two_tasks, refreshed, refreshed])
        post_calls = {"count": 0}

        def extend_post(session, url, kwargs):
            post_calls["count"] += 1
            status = 500 if post_calls["count"] == 1 else 200
            return FakeResponse(status, text="", json_data={})

        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", extend_post),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(
            names_statuses(results),
            [
                ("python3 first.py", renew.STATUS_FAILED),
                ("python3 second.py", renew.STATUS_SUCCESS),
            ],
        )
        self.assertIn("HTTP 500", results[0]["detail"])
        self.assertIn("2026-11-11 → 2026-11-25", results[1]["detail"])

    def test_refresh_failure_fails_only_that_task(self):
        good_list = {
            "results": [
                {
                    "id": 1,
                    "command": "python3 first.py",
                    "expiry": "2026-11-10",
                    "extend_url": "/api/v0/user/alpha/schedule/1/extend/",
                },
                {
                    "id": 2,
                    "command": "python3 second.py",
                    "expiry": "2026-11-11",
                    "extend_url": "/api/v0/user/alpha/schedule/2/extend/",
                },
            ]
        }
        second_refreshed = {
            "results": [
                {
                    "id": 2,
                    "command": "python3 second.py",
                    "expiry": "2026-11-24",
                    "extend_url": "/api/v0/user/alpha/schedule/2/extend/",
                }
            ]
        }
        schedule_route, _ = self._tasks_route(
            [
                good_list,
                FakeResponse(status_code=500, text="", json_data={}),
                second_refreshed,
            ]
        )
        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("refresh failed", results[0]["detail"])
        self.assertIn("HTTP 500", results[0]["detail"])
        self.assertEqual(results[1]["status"], renew.STATUS_SUCCESS)

    def test_refresh_invalid_json_fails_only_that_task(self):
        good_list = {
            "results": [
                {
                    "id": 1,
                    "command": "python3 first.py",
                    "expiry": "2026-11-10",
                    "extend_url": "/api/v0/user/alpha/schedule/1/extend/",
                },
                {
                    "id": 2,
                    "command": "python3 second.py",
                    "expiry": "2026-11-11",
                    "extend_url": "/api/v0/user/alpha/schedule/2/extend/",
                },
            ]
        }
        schedule_route, _ = self._tasks_route(
            [
                good_list,
                FakeResponse(
                    status_code=200, text=load_fixture("tasks_not_json.txt")
                ),
                good_list,
            ]
        )
        session = FakeSession(
            routes=[
                schedule_route,
                ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
            ],
            cookies={"csrftoken": "task-csrf"},
        )

        ok, results = renew.renew_scheduled_tasks(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("not valid JSON", results[0]["detail"])
        self.assertEqual(results[1]["status"], renew.STATUS_SUCCESS)


class WebAppTests(OfflineTestCase):
    def test_missing_csrf_fails_item_but_next_form_still_processed(self):
        def dashboard_get(session, url, kwargs):
            return html_response(
                "dashboard_two_webapps.html",
                url=f"{BASE}/user/alpha/webapps/",
            )

        session = FakeSession(
            routes=[
                ("GET", "/webapps/", dashboard_get),
                (
                    "POST",
                    "/webapps/",
                    FakeResponse(
                        200,
                        text="",
                        url=f"{BASE}/user/alpha/webapps/",
                    ),
                ),
            ]
        )

        ok, results = renew.renew_webapps(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(
            names_statuses(results),
            [
                ("alpha.pythonanywhere.com", renew.STATUS_SUCCESS),
                ("beta.pythonanywhere.com", renew.STATUS_FAILED),
            ],
        )
        self.assertIn("missing CSRF token", results[1]["detail"])
        post_urls = [url for method, url, _ in session.requests if method == "POST"]
        self.assertEqual(len(post_urls), 1)
        self.assertIn("alpha.pythonanywhere.com", post_urls[0])

    def test_post_non_200_fails_item_and_continues(self):
        dashboard = load_fixture("dashboard_refreshed.html")
        post_calls = {"count": 0}

        def extend_post(session, url, kwargs):
            post_calls["count"] += 1
            status = 403 if post_calls["count"] == 1 else 200
            return FakeResponse(
                status, text="", url=f"{BASE}/user/alpha/webapps/"
            )

        session = FakeSession(
            routes=[
                (
                    "GET",
                    "/webapps/",
                    FakeResponse(
                        200, text=dashboard, url=f"{BASE}/user/alpha/webapps/"
                    ),
                ),
                ("POST", "/webapps/", extend_post),
            ]
        )

        ok, results = renew.renew_webapps(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("HTTP 403", results[0]["detail"])
        self.assertEqual(results[1]["status"], renew.STATUS_SUCCESS)
        self.assertEqual(post_calls["count"], 2)

    def test_unexpected_redirect_is_item_failure(self):
        dashboard = load_fixture("dashboard_refreshed.html")
        session = FakeSession(
            routes=[
                (
                    "GET",
                    "/webapps/",
                    FakeResponse(
                        200, text=dashboard, url=f"{BASE}/user/alpha/webapps/"
                    ),
                ),
                (
                    "POST",
                    "/webapps/",
                    FakeResponse(200, text="", url=f"{BASE}/login/?next=/extend"),
                ),
            ]
        )

        ok, results = renew.renew_webapps(session, "alpha")

        self.assertFalse(ok)
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("unexpected redirect", results[0]["detail"])

    def test_refresh_failure_is_item_failure_not_account_abort(self):
        def dashboard_get(session, url, kwargs):
            count = sum(
                1 for method, _, _ in session.requests if method == "GET"
            )
            if count == 1:
                return html_response(
                    "dashboard_two_webapps.html",
                    url=f"{BASE}/user/alpha/webapps/",
                )
            return FakeResponse(status_code=502, text="bad gateway")

        session = FakeSession(
            routes=[
                ("GET", "/webapps/", dashboard_get),
                (
                    "POST",
                    "/webapps/",
                    FakeResponse(
                        200, text="", url=f"{BASE}/user/alpha/webapps/"
                    ),
                ),
            ]
        )

        ok, results = renew.renew_webapps(session, "alpha")

        self.assertFalse(ok)
        # First form renewed but its refresh failed; the second form (missing
        # CSRF) is still evaluated afterwards.
        self.assertEqual(results[0]["status"], renew.STATUS_FAILED)
        self.assertIn("refresh failed", results[0]["detail"])
        self.assertIn("HTTP 502", results[0]["detail"])
        self.assertEqual(results[1]["status"], renew.STATUS_FAILED)
        self.assertIn("missing CSRF token", results[1]["detail"])


class AccountAndRunTests(OfflineTestCase):
    def _full_account_session(self, username):
        def dashboard_route(session, url, kwargs):
            # Both forms in this fixture carry a CSRF token, so the whole
            # account renews successfully.
            return html_response("dashboard_refreshed.html", url=url)

        task_gets = {"count": 0}

        def schedule_route(session, url, kwargs):
            task_gets["count"] += 1
            if task_gets["count"] == 1:
                return json_fixture_response("tasks_list.json", url=url)
            return json_fixture_response("tasks_new_expiry.json", url=url)

        routes = login_routes(username) + [
            ("GET", "/webapps/", dashboard_route),
            (
                "POST",
                "/webapps/",
                FakeResponse(
                    200, text="", url=f"{BASE}/user/{username}/webapps/"
                ),
            ),
            ("GET", "/schedule/", schedule_route),
            ("POST", "/schedule/", FakeResponse(200, text="{}", json_data={})),
        ]
        return FakeSession(routes=routes, cookies={"csrftoken": "task-csrf"})

    def test_task_list_failure_still_runs_webapps(self):
        routes = login_routes("alpha") + [
            (
                "GET",
                "/webapps/",
                lambda s, url, kw: html_response(
                    "dashboard_refreshed.html", url=url
                ),
            ),
            (
                "POST",
                "/webapps/",
                FakeResponse(
                    200, text="", url=f"{BASE}/user/alpha/webapps/"
                ),
            ),
            (
                "GET",
                "/schedule/",
                FakeResponse(
                    status_code=200, text=load_fixture("tasks_not_json.txt")
                ),
            ),
        ]
        session = FakeSession(routes=routes, cookies={"csrftoken": "task-csrf"})

        with mock.patch.object(
            renew.requests, "Session", return_value=session
        ):
            ok, details = renew.renew_account("ACCOUNT_1", "alpha", "secret")

        self.assertFalse(ok)
        joined = "\n".join(details)
        self.assertIn(
            "Web App: alpha.pythonanywhere.com — SUCCESS", joined
        )
        self.assertIn("Task: task list — FAILED", joined)
        self.assertIn("not valid JSON", joined)

    def test_multi_account_one_failure_does_not_affect_other(self):
        good_session = self._full_account_session("alpha")

        bad_routes = [
            (
                "GET",
                f"{BASE}/login/",
                html_response("login_page.html", url=f"{BASE}/login/"),
            ),
            (
                "POST",
                f"{BASE}/login/",
                FakeResponse(
                    status_code=200,
                    text="<html><body>wrong password</body></html>",
                    url=f"{BASE}/login/?next=/dashboard",
                ),
            ),
        ]
        bad_session = FakeSession(routes=bad_routes)

        env = {
            "ACCOUNT_CREDENTIALS_JSON": json.dumps(
                [
                    {"username": "alpha", "password": "alpha-pass"},
                    {"username": "gamma", "password": "gamma-pass"},
                ]
            )
        }
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ACCOUNT_")
            and key not in ("PA_USERNAME", "PA_PASSWORD")
        }
        clean_env.update(env)

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = pathlib.Path(tmpdir) / "workflow_runs.log"
            with mock.patch.dict(os.environ, clean_env, clear=True), mock.patch.object(
                renew.requests, "Session", side_effect=[good_session, bad_session]
            ), mock.patch.object(
                renew, "LOG_FILE", str(log_path)
            ):
                exit_code = renew.run()

            self.assertEqual(exit_code, 1)
            log_text = log_path.read_text(encoding="utf-8")

        self.assertIn("- ACCOUNT_CREDENTIALS_JSON item 1: SUCCESS", log_text)
        self.assertIn("- ACCOUNT_CREDENTIALS_JSON item 2: FAILED", log_text)
        self.assertIn("Login failed", log_text)
        # The good account still recorded checkable per-item outcomes.
        self.assertIn(
            "Web App: alpha.pythonanywhere.com — SUCCESS", log_text
        )
        self.assertIn(
            "Task: python3 /home/alpha/sync_logs.py — SUCCESS", log_text
        )

    def test_partial_status_when_credentials_incomplete(self):
        good_session = self._full_account_session("alpha")
        env = {
            "ACCOUNT_CREDENTIALS_JSON": json.dumps(
                [
                    {"username": "alpha", "password": "alpha-pass"},
                    {"username": "", "password": "ghost-pass"},
                ]
            )
        }
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ACCOUNT_")
            and key not in ("PA_USERNAME", "PA_PASSWORD")
        }
        clean_env.update(env)

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = pathlib.Path(tmpdir) / "workflow_runs.log"
            with mock.patch.dict(os.environ, clean_env, clear=True), mock.patch.object(
                renew.requests, "Session", return_value=good_session
            ), mock.patch.object(
                renew, "LOG_FILE", str(log_path)
            ):
                exit_code = renew.run()

            self.assertEqual(exit_code, 0)
            log_text = log_path.read_text(encoding="utf-8")

        self.assertIn("Status: PARTIAL", log_text)
        self.assertIn("Incomplete or skipped credentials", log_text)
        self.assertIn(
            "- ACCOUNT_CREDENTIALS_JSON item 1: SUCCESS", log_text
        )

    def test_no_complete_accounts_is_failed(self):
        clean_env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith("ACCOUNT_")
            and key not in ("PA_USERNAME", "PA_PASSWORD")
        }

        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = pathlib.Path(tmpdir) / "workflow_runs.log"
            with mock.patch.dict(os.environ, clean_env, clear=True), mock.patch.object(
                renew, "LOG_FILE", str(log_path)
            ):
                exit_code = renew.run()

            self.assertEqual(exit_code, 1)
            log_text = log_path.read_text(encoding="utf-8")

        self.assertIn("Status: FAILED", log_text)
        self.assertIn("No complete accounts were configured.", log_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
