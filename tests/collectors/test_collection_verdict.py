"""The collector's round verdict and per-container failure handling, driven through a mocked Docker/API layer so
the behavior is verifiable without Unix domain sockets (the full socket chain lives in
tests/collectors/test_docker_collection_verdict.py)."""
import http.client

import pytest

from src.collector import collector

CID_A, CID_B, CID_C = "a" * 64, "b" * 64, "c" * 64


@pytest.fixture(autouse=True)
def _state():
    collector._cpu_previous.clear()
    collector._one_shot_unsupported = False
    yield
    collector._cpu_previous.clear()
    collector._one_shot_unsupported = False


def _configure(monkeypatch, tmp_path, request_impl):
    socket_path = tmp_path / "docker.sock"
    socket_path.touch()  # existence is all collect_docker checks before talking
    monkeypatch.setattr(collector, "_docker_request", request_impl)
    monkeypatch.setenv("INFRADECK_DOCKER_HOST", str(socket_path))
    return str(socket_path)


def _listing():
    return [{"Id": CID_A, "Names": ["/web"], "Image": "nginx", "State": "running"},
            {"Id": CID_B, "Names": ["/db"], "Image": "postgres", "State": "running"}]


def _inspect(cid, name):
    return {"Id": cid, "Name": f"/{name}", "Config": {"Image": "img"}, "State": {"Status": "exited"}}


def test_a_successful_round_carries_the_container_count(monkeypatch, tmp_path):
    def request(path, endpoint):
        if endpoint == "/containers/json?all=1":
            return _listing()
        if endpoint.endswith("/json"):
            return _inspect(endpoint.split("/")[2], "web" if CID_A in endpoint else "db")
        return {}  # /version and /system/df are best-effort side calls

    _configure(monkeypatch, tmp_path, request)

    containers, verdict = collector.collect_docker()

    assert [c["name"] for c in containers] == ["web", "db"]
    assert verdict == {
        "docker_status": "ok", "docker_reason": None, "docker_reason_text": None,
        "docker_latency_ms": verdict["docker_latency_ms"], "docker_container_count": 2, "docker_container_errors": [],
    }
    assert isinstance(verdict["docker_latency_ms"], int)


@pytest.mark.parametrize("error, reason", [
    (collector.DockerProxyError("forbidden"), "forbidden"),
    (collector.DockerProxyError("upstream"), "upstream"),
    (collector.DockerProxyError("closed"), "closed"),
    (TimeoutError(), "timeout"),
    (ConnectionRefusedError(), "refused"),
    (OSError("Docker API returned HTTP 500"), "error"),
])
def test_a_failed_listing_marks_the_round_failed_with_a_fixed_reason(monkeypatch, tmp_path, error, reason):
    def request(path, endpoint):
        raise error

    _configure(monkeypatch, tmp_path, request)

    containers, verdict = collector.collect_docker()

    assert containers == []
    assert verdict["docker_status"] == "unreachable" and verdict["docker_reason"] == reason
    assert verdict["docker_reason_text"] == collector.DOCKER_REASON_TEXT[reason]
    assert verdict["docker_container_count"] == 0 and verdict["docker_container_errors"] == []


def test_proxy_status_codes_map_to_their_reasons(monkeypatch):
    class Response:
        def __init__(self, status):
            self.status = status

        def read(self):
            return b"Forbidden" if self.status == 403 else b"Upstream error"

    class FakeConnection:
        def __init__(self, path, *args, **kwargs):
            self.status = None

        def request(self, method, target, **kwargs):
            self.status = 403 if "forbidden" in target else 502

        def getresponse(self):
            return Response(self.status)

        def close(self):
            pass

    monkeypatch.setattr(collector, "_UnixHTTPConnection", FakeConnection)

    with pytest.raises(collector.DockerProxyError) as forbidden:
        collector._docker_request("sock", "/forbidden")
    assert forbidden.value.code == "forbidden"
    with pytest.raises(collector.DockerProxyError) as upstream:
        collector._docker_request("sock", "/broken")
    assert upstream.value.code == "upstream"


def test_a_closed_connection_is_a_closed_reason_not_a_crash(monkeypatch):
    class Connection:
        def __init__(self, path):
            pass

        def request(self, *args, **kwargs):
            raise http.client.RemoteDisconnected("Connection closed")

        def close(self):
            pass

    monkeypatch.setattr(collector, "_UnixHTTPConnection", Connection)

    with pytest.raises(collector.DockerProxyError) as error:
        collector._docker_request("sock", "/containers/json?all=1")
    assert error.value.code == "closed"
    assert collector._docker_failure_reason(error.value) == "closed"


def test_one_container_detail_failure_only_costs_that_container(monkeypatch, tmp_path):
    def request(path, endpoint):
        if endpoint == "/containers/json?all=1":
            return _listing()
        if endpoint == f"/containers/{CID_A}/json":
            raise collector.DockerProxyError("upstream")
        return _inspect(CID_B, "db")

    _configure(monkeypatch, tmp_path, request)

    containers, verdict = collector.collect_docker()

    assert [c["name"] for c in containers] == ["db"]
    assert verdict["docker_status"] == "ok" and verdict["docker_container_count"] == 1
    assert verdict["docker_container_errors"] == [{"container_id": CID_A, "stage": "inspect", "reason": "upstream"}]


def test_one_container_stats_failure_keeps_its_detail(monkeypatch, tmp_path):
    def request(path, endpoint):
        if endpoint == "/containers/json?all=1":
            return [{"Id": CID_A, "Names": ["/web"], "Image": "img", "State": "running"},
                    {"Id": CID_B, "Names": ["/db"], "Image": "img", "State": "running"}]
        if endpoint.endswith("/json"):
            cid = endpoint.split("/")[2]
            return {"Id": cid, "Name": "/web" if cid == CID_A else "/db", "Config": {"Image": "img"},
                    "State": {"Status": "running", "Health": {"Status": "healthy"}}}
        if CID_B in endpoint:  # both stats attempts for db fail
            raise collector.DockerProxyError("upstream")
        return {"cpu_stats": {}, "precpu_stats": {}, "memory_stats": {"usage": 1, "limit": 2, "stats": {}},
                "networks": {}, "blkio_stats": {}, "pids_stats": {}}

    _configure(monkeypatch, tmp_path, request)

    containers, verdict = collector.collect_docker()
    by_name = {c["name"]: c for c in containers}

    assert set(by_name) == {"web", "db"}
    assert by_name["db"]["status"] == "running" and "memory_used_mb" not in by_name["db"]
    assert "memory_used_mb" in by_name["web"]
    assert verdict["docker_status"] == "ok" and verdict["docker_container_count"] == 2
    assert verdict["docker_container_errors"] == [{"container_id": CID_B, "stage": "stats", "reason": "upstream"}]


def test_when_every_inspect_fails_the_whole_round_is_a_failure(monkeypatch, tmp_path):
    def request(path, endpoint):
        if endpoint == "/containers/json?all=1":
            return [{"Id": CID_A, "Names": ["/web"]}, {"Id": CID_B, "Names": ["/db"]}]
        raise collector.DockerProxyError("upstream")

    socket_path = _configure(monkeypatch, tmp_path, request)
    info = {}

    with pytest.raises(OSError):
        collector.collect_containers(socket_path, info)
    assert [error["stage"] for error in info["container_errors"]] == ["inspect", "inspect"]

    containers, verdict = collector.collect_docker()
    assert containers == [] and verdict["docker_status"] == "unreachable" and verdict["docker_reason"] == "upstream"
    assert [error["stage"] for error in verdict["docker_container_errors"]] == ["inspect", "inspect"]


def test_a_configured_but_missing_socket_is_a_failure_with_the_count_fields(monkeypatch, tmp_path):
    monkeypatch.setenv("INFRADECK_DOCKER_HOST", str(tmp_path / "gone.sock"))

    containers, verdict = collector.collect_docker()

    assert containers == []
    assert verdict["docker_status"] == "unreachable" and verdict["docker_reason"] == "missing"
    assert verdict["docker_reason_text"] == collector.DOCKER_REASON_TEXT["missing"]
    assert verdict["docker_container_count"] == 0 and verdict["docker_container_errors"] == []


def test_a_proxy_refusal_on_stats_is_not_retried_as_an_old_proxy(monkeypatch):
    asked = []

    def request(path, endpoint):
        asked.append(endpoint)
        raise collector.DockerProxyError("forbidden")

    monkeypatch.setattr(collector, "_docker_request", request)

    with pytest.raises(collector.DockerProxyError) as error:
        collector._fetch_stats("sock", CID_A)
    assert error.value.code == "forbidden"
    # Only the one-shot attempt happened: the refusal was propagated, not retried against the classic endpoint.
    assert asked == [f"/containers/{CID_A}/stats?stream=false&one-shot=true"]
    assert not collector._one_shot_unsupported  # a refusal must not flip the one-shot support flag


def test_a_plain_stats_error_still_falls_back_to_the_classic_endpoint(monkeypatch):
    asked = []

    def request(path, endpoint):
        asked.append(endpoint)
        if "one-shot" in endpoint:
            raise OSError("Docker API returned HTTP 404")  # an older proxy/daemon without one-shot
        return {"cpu_stats": {}, "precpu_stats": {}}

    monkeypatch.setattr(collector, "_docker_request", request)

    assert collector._fetch_stats("sock", CID_A) == {"cpu_stats": {}, "precpu_stats": {}}
    assert asked == [f"/containers/{CID_A}/stats?stream=false&one-shot=true",
                     f"/containers/{CID_A}/stats?stream=false"]
    assert collector._one_shot_unsupported
