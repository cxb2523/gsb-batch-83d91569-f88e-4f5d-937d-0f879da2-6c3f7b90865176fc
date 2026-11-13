"""Batch text extraction: per-target status, failure classification, skip policy.

All URLs and IPs are fake/local; proxy-looking strings use IANA documentation
ranges. No real browser is started: a FakeLauncher plays the control channel.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.api.app import create_app
from src.core.container import Container
from src.services.browser.batch import (
    FAILED,
    INVALID_PARAMS,
    PROXY_OR_NETWORK_UNREACHABLE,
    SCRIPT_ERROR,
    SKIPPED,
    SUCCESS,
    WAIT_TIMEOUT,
    BatchExtractService,
)
from src.services.browser.launcher import BrowserControlError

FIXED_TEXT = "fixed batch text"


class FakeLauncher:
    """Stands in for BrowserLauncher.control against a real runner."""

    def __init__(self):
        self.running = True
        self.calls: list[tuple[str, dict]] = []

    def is_running(self, name):
        return self.running

    def control(self, name, action, params=None, timeout=60):
        params = params or {}
        self.calls.append((action, params))
        if action == "tab_new":
            return {
                "tabs": [
                    {"index": 0, "url": "about:blank", "title": "", "active": False},
                    {"index": 1, "url": "about:blank", "title": "", "active": True},
                ]
            }
        if action == "tab_close":
            return {"tabs": [{"index": 0, "url": "about:blank", "title": "", "active": True}]}
        if action == "navigate":
            url = params["url"]
            if "://" not in url:
                raise BrowserControlError(f"URL scheme of '{url}' is not allowed", status=400)
            if url.startswith("file:"):
                raise BrowserControlError("URL scheme 'file' is not allowed", status=400)
            if "unreachable" in url:
                raise BrowserControlError("Error: NS_ERROR_PROXY_CONNECTION_REFUSED", status=422)
            return {"url": url, "title": "T"}
        if action == "wait_for":
            if params["selector"] == "#never":
                raise BrowserControlError(
                    f"TimeoutError: Page.wait_for: Timeout {params['timeout']}ms exceeded",
                    status=422,
                )
            if params["selector"] == "???":
                raise BrowserControlError(
                    "Error: Unexpected token while parsing selector", status=422
                )
            return {"url": "https://x/", "title": "T"}
        if action == "text":
            if params["selector"] == "#explode":
                raise BrowserControlError("Error: element detached", status=422)
            if params["selector"] == "#long":
                return {"text": "x" * params["max_chars"], "truncated": True}
            return {"text": FIXED_TEXT, "truncated": False}
        raise AssertionError(f"unexpected action {action}")


def make_service():
    launcher = FakeLauncher()
    return BatchExtractService(launcher), launcher


def request(*targets, **overrides):
    body = {
        "targets": list(targets),
        "selector": "#target",
        "timeout": 3000,
        "max_chars": 40_000,
        "skip_succeeded": False,
    }
    body.update(overrides)
    return body


FOUR_TARGETS = [
    {"id": "ok", "url": "http://127.0.0.1:9000/ok"},
    {"id": "missing", "url": "http://127.0.0.1:9000/missing", "selector": "#never"},
    {"id": "dead-proxy", "url": "http://unreachable.invalid:8080/"},
    {"id": "bad-url", "url": "file:///C:/Windows/win.ini"},
]


def test_statuses_and_failure_kinds():
    service, _ = make_service()
    record = service.run("p1", request(*FOUR_TARGETS))
    by_id = {r["id"]: r for r in record["results"]}

    ok = by_id["ok"]
    assert ok["status"] == SUCCESS
    assert ok["text"] == FIXED_TEXT
    assert ok["truncated"] is False
    assert ok["error_kind"] is None

    assert by_id["missing"]["status"] == FAILED
    assert by_id["missing"]["error_kind"] == WAIT_TIMEOUT
    assert by_id["dead-proxy"]["status"] == FAILED
    assert by_id["dead-proxy"]["error_kind"] == PROXY_OR_NETWORK_UNREACHABLE
    assert by_id["bad-url"]["status"] == FAILED
    assert by_id["bad-url"]["error_kind"] == INVALID_PARAMS

    assert (record["total"], record["succeeded"], record["failed"], record["skipped"]) == (
        4,
        1,
        3,
        0,
    )
    assert record["finished_at"] is not None


def test_one_failure_does_not_stop_the_batch():
    service, launcher = make_service()
    record = service.run("p1", request(*FOUR_TARGETS))
    assert len(record["results"]) == 4
    # Every target, including the ones after a failure, got its own tab.
    opened = [c for c in launcher.calls if c[0] == "tab_new"]
    closed = [c for c in launcher.calls if c[0] == "tab_close"]
    assert len(opened) == len(closed) == 4


def test_failed_target_closes_its_tab_before_the_next_one():
    service, launcher = make_service()
    service.run("p1", request(*FOUR_TARGETS))
    actions = [a for a, _ in launcher.calls]
    # Strict per-target cycle: open, work, close, then the next target.
    assert actions == ["tab_new", "navigate", "wait_for", "text", "tab_close"] * 1 + [
        "tab_new",
        "navigate",
        "wait_for",
        "tab_close",
        "tab_new",
        "navigate",
        "tab_close",
        "tab_new",
        "navigate",
        "tab_close",
    ]


def test_script_error_and_invalid_selector_classification():
    service, _ = make_service()
    record = service.run(
        "p1",
        request(
            {"id": "js", "url": "http://127.0.0.1:9000/ok", "selector": "#explode"},
            {"id": "bad-sel", "url": "http://127.0.0.1:9000/ok", "selector": "???"},
        ),
    )
    kinds = {r["id"]: r["error_kind"] for r in record["results"]}
    assert kinds == {"js": SCRIPT_ERROR, "bad-sel": INVALID_PARAMS}


def test_truncation_is_reported():
    service, _ = make_service()
    record = service.run(
        "p1",
        request({"id": "long", "url": "http://127.0.0.1:9000/long", "selector": "#long"}),
    )
    result = record["results"][0]
    assert result["status"] == SUCCESS
    assert result["truncated"] is True
    assert len(result["text"]) == 40_000


def test_skip_succeeded_marks_previous_successes():
    service, launcher = make_service()
    first = service.run("p1", request(*FOUR_TARGETS))
    launcher.calls.clear()

    second = service.run("p1", request(*FOUR_TARGETS, skip_succeeded=True))
    by_id = {r["id"]: r for r in second["results"]}
    skipped = by_id["ok"]
    assert skipped["status"] == SKIPPED
    assert first["batch_id"] in skipped["reason"]
    # Skipped targets are not fetched again; failures are retried.
    assert not any(
        c[0] == "navigate" and c[1].get("url", "").endswith("/ok") for c in launcher.calls
    )
    assert by_id["missing"]["status"] == FAILED
    assert by_id["missing"]["error_kind"] == WAIT_TIMEOUT
    assert (second["succeeded"], second["failed"], second["skipped"]) == (0, 3, 1)

    # Without the policy everything runs again.
    third = service.run("p1", request(*FOUR_TARGETS))
    assert third["skipped"] == 0
    assert third["succeeded"] == 1


def test_empty_targets_and_stopped_browser_fail_before_anything_runs():
    service, launcher = make_service()
    with pytest.raises(BrowserControlError) as empty:
        service.run("p1", request())
    assert empty.value.status == 400

    launcher.running = False
    with pytest.raises(BrowserControlError) as stopped:
        service.run("p1", request(*FOUR_TARGETS))
    assert stopped.value.status == 409

    assert launcher.calls == []  # no half-run batch
    assert service.latest("p1") is None


def test_duplicate_target_ids_rejected():
    service, _ = make_service()
    target = {"id": "dup", "url": "http://127.0.0.1:9000/ok"}
    with pytest.raises(BrowserControlError) as e:
        service.run("p1", request(target, dict(target)))
    assert e.value.status == 400


def test_results_are_stored_and_retrievable():
    service, _ = make_service()
    record = service.run("p1", request(*FOUR_TARGETS))
    assert service.latest("p1")["batch_id"] == record["batch_id"]
    assert service.get("p1", record["batch_id"])["total"] == 4
    assert service.get("p1", "nope") is None
    assert service.latest("other") is None


# ---------------------------------------------------------------------------
# REST API surface
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    container = Container()
    client = TestClient(create_app(container), base_url="http://127.0.0.1")
    assert client.post("/api/v1/profiles", json={"name": "p1"}).status_code == 201
    fake = FakeLauncher()
    monkeypatch.setattr(container.browser_launcher, "is_running", fake.is_running)
    monkeypatch.setattr(container.browser_launcher, "control", fake.control)
    return client, fake


def api_body(**overrides):
    body = {
        "targets": FOUR_TARGETS,
        "selector": "#target",
        "timeout": 3000,
    }
    body.update(overrides)
    return body


def test_api_batch_extract_end_to_end(client):
    http, fake = client
    r = http.post("/api/v1/browser/p1/page/batch-extract", json=api_body())
    assert r.status_code == 200
    record = r.json()
    by_id = {t["id"]: t for t in record["results"]}
    assert by_id["ok"]["status"] == "success"
    assert by_id["ok"]["text"] == FIXED_TEXT
    assert by_id["missing"]["error_kind"] == "wait_timeout"
    assert by_id["dead-proxy"]["error_kind"] == "proxy_or_network_unreachable"
    assert by_id["bad-url"]["error_kind"] == "invalid_params"

    # The batch is retrievable afterwards, latest and by id.
    assert (
        http.get("/api/v1/browser/p1/page/batch-extract").json()["batch_id"] == record["batch_id"]
    )
    got = http.get(f"/api/v1/browser/p1/page/batch-extract/{record['batch_id']}")
    assert got.status_code == 200
    assert got.json()["total"] == 4
    assert http.get("/api/v1/browser/p1/page/batch-extract/nope").status_code == 404

    # Re-run with the skip policy: the earlier success is skipped, not dropped.
    again = http.post(
        "/api/v1/browser/p1/page/batch-extract", json=api_body(skip_succeeded=True)
    ).json()
    skipped = {t["id"]: t for t in again["results"]}["ok"]
    assert skipped["status"] == "skipped"
    assert record["batch_id"] in skipped["reason"]
    assert again["skipped"] == 1 and again["failed"] == 3


def test_api_rejects_empty_target_list(client):
    http, fake = client
    r = http.post("/api/v1/browser/p1/page/batch-extract", json=api_body(targets=[]))
    assert r.status_code == 422
    assert fake.calls == []
    assert http.get("/api/v1/browser/p1/page/batch-extract").status_code == 404


def test_api_requires_a_running_browser(client):
    http, fake = client
    fake.running = False
    r = http.post("/api/v1/browser/p1/page/batch-extract", json=api_body())
    assert r.status_code == 409
    assert http.get("/api/v1/browser/p1/page/batch-extract").status_code == 404


def test_api_unknown_profile_is_404(client):
    http, _ = client
    r = http.post("/api/v1/browser/ghost/page/batch-extract", json=api_body())
    assert r.status_code == 404
    assert http.get("/api/v1/browser/ghost/page/batch-extract").status_code == 404


def test_mcp_exposes_the_batch_tools():
    from src.mcp_server.server import mcp

    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert {"browser_batch_extract", "browser_batch_results"} <= names
