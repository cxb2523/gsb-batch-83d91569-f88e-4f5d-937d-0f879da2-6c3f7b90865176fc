"""Tests for skills/evident-charts/scripts/fetch_data.py and its integration
into check_chart.py.

A local HTTP server (threaded, port 0) serves the fetch scenarios: success,
404, timeout, empty body, corrupt JSON, and a flaky endpoint that recovers
under retries. Request counts per path verify dedupe and cache behavior.
"""
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills" / "evident-charts" / "scripts" / "check_chart.py"
FIX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPT.parent))

import fetch_data  # noqa: E402

CSV_BODY = b"year,value\n2019,10\n2020,12\n2021,15\n2022,19\n2023,24\n"


def make_handler():
    class Handler(BaseHTTPRequestHandler):
        counts = {}

        def do_GET(self):
            type(self).counts[self.path] = type(self).counts.get(self.path, 0) + 1
            if self.path == "/values.csv":
                self._respond(200, CSV_BODY)
            elif self.path == "/empty":
                self._respond(200, b"")
            elif self.path == "/bad.json":
                self._respond(200, b"{not json")
            elif self.path == "/slow":
                time.sleep(2.0)
                self._respond(200, b"ok")
            elif self.path == "/flaky":
                if type(self).counts["/flaky"] <= 2:
                    self._respond(500, b"boom")
                else:
                    self._respond(200, CSV_BODY)
            else:
                self._respond(404, b"nope")

        def _respond(self, code, body):
            try:
                self.send_response(code)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:  # client gave up (timeout test)
                pass

        def log_message(self, *args):
            pass

    return Handler


@pytest.fixture(scope="module")
def server():
    handler = make_handler()
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", handler.counts
    srv.shutdown()


def item(name, url, required=True, fmt=None):
    return {"name": name, "url": url, "required": required, "format": fmt}


def test_all_success(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([item("values", f"{base}/values.csv", fmt="csv")], tmp_path)
    assert rep["ok"] and rep["failures"] == []
    it = rep["items"][0]
    assert it["outcome"] == "ok" and not it["from_cache"] and it["attempts"] == 1
    assert it["elapsed_ms"] >= 0 and Path(it["path"]).read_bytes() == CSV_BODY
    assert rep["paths"] == {"values": it["path"]}


def test_required_404_fails_collection(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([item("missing", f"{base}/nope")], tmp_path)
    assert not rep["ok"] and rep["failures"] == ["missing"]
    it = rep["items"][0]
    assert it["outcome"] == "http_error" and "404" in it["detail"]
    assert it["attempts"] == 1  # 4xx is not retried
    assert rep["paths"] == {}


def test_optional_failure_does_not_block(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([
        item("values", f"{base}/values.csv"),
        item("notes", f"{base}/nope", required=False),
    ], tmp_path)
    assert rep["ok"] and rep["failures"] == []
    assert rep["items"][1]["outcome"] == "http_error"
    assert list(rep["paths"]) == ["values"]


def test_optional_timeout_is_recorded_not_blocking(server, tmp_path):
    base, counts = server
    rep = fetch_data.collect([
        item("values", f"{base}/values.csv"),
        item("slow", f"{base}/slow", required=False),
    ], tmp_path, timeout=0.3, retries=1)
    assert rep["ok"]
    slow = rep["items"][1]
    assert slow["outcome"] == "timeout" and slow["attempts"] == 2
    assert counts["/slow"] == 2


def test_empty_body(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([item("empty", f"{base}/empty")], tmp_path)
    assert rep["items"][0]["outcome"] == "empty"
    assert rep["failures"] == ["empty"]


def test_parse_error(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([item("cfg", f"{base}/bad.json", fmt="json")], tmp_path)
    it = rep["items"][0]
    assert it["outcome"] == "parse_error" and it["path"] is None
    assert rep["failures"] == ["cfg"]


def test_retry_recovers_from_5xx(server, tmp_path):
    base, counts = server
    rep = fetch_data.collect([item("flaky", f"{base}/flaky")], tmp_path, retries=2)
    it = rep["items"][0]
    assert it["outcome"] == "ok" and it["attempts"] == 3
    assert counts["/flaky"] == 3


def test_duplicate_url_fetched_once(server, tmp_path):
    base, counts = server
    before = counts.get("/values.csv", 0)
    rep = fetch_data.collect([
        item("a", f"{base}/values.csv"),
        item("b", f"{base}/values.csv", required=False),
    ], tmp_path)
    assert counts["/values.csv"] == before + 1
    first, second = rep["items"]
    assert second["deduped"] and not first["deduped"]
    assert second["outcome"] == "ok" and second["path"] == first["path"]
    assert rep["paths"]["a"] == rep["paths"]["b"]


def test_cache_hit_skips_request(server, tmp_path):
    base, counts = server
    src = [item("values", f"{base}/values.csv")]
    fetch_data.collect(src, tmp_path)
    before = counts["/values.csv"]
    rep = fetch_data.collect(src, tmp_path)
    it = rep["items"][0]
    assert counts["/values.csv"] == before  # no new request
    assert it["outcome"] == "ok" and it["from_cache"] and "cache" in it["detail"]


def test_local_file_source(tmp_path):
    data = tmp_path / "local.csv"
    data.write_bytes(CSV_BODY)
    rep = fetch_data.collect([item("local", str(data), fmt="csv")], tmp_path / "cache")
    assert rep["ok"] and rep["items"][0]["outcome"] == "ok"


def test_summary_lines_report_outcomes(server, tmp_path):
    base, _ = server
    rep = fetch_data.collect([
        item("values", f"{base}/values.csv"),
        item("missing", f"{base}/nope"),
    ], tmp_path)
    text = "\n".join(fetch_data.summary_lines(rep))
    assert "DATA OK values" in text
    assert "DATA FAILED missing" in text and "http_error" in text and "404" in text
    assert "DATA COLLECTION FAILED: required source(s) failed: missing" in text


# --- CLI integration ---------------------------------------------------------

def write_manifest(tmp_path, sources):
    manifest = tmp_path / "chart.sources.json"
    manifest.write_text(json.dumps({"sources": sources}), encoding="utf-8")
    return manifest


def cli(chart, *args):
    return subprocess.run([sys.executable, str(SCRIPT), str(chart), *map(str, args)],
                          capture_output=True, text=True, timeout=120)


def test_cli_collection_success_and_chart_checked(server, tmp_path):
    base, _ = server
    manifest = write_manifest(tmp_path, [
        {"name": "values", "url": f"{base}/values.csv", "required": True, "format": "csv"}])
    cache = tmp_path / "cache"
    r = cli(FIX / "fetch_chart.py", "--sources", manifest, "--cache-dir", cache)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "DATA OK values" in r.stdout and "DATA COLLECTION OK" in r.stdout
    assert "RESULT" in r.stdout and "figure(s)" in r.stdout  # chart check ran
    # The script really read the cached file (it would KeyError/exit 2 otherwise).
    assert str(cache) in r.stdout


def test_cli_required_failure_skips_chart_check(server, tmp_path):
    base, _ = server
    manifest = write_manifest(tmp_path, [
        {"name": "values", "url": f"{base}/nope", "required": True},
        {"name": "notes", "url": f"{base}/values.csv", "required": False}])
    r = cli(FIX / "fetch_chart.py", "--sources", manifest, "--cache-dir", tmp_path / "cache")
    assert r.returncode == 2
    assert "DATA FAILED values" in r.stdout
    assert "DATA COLLECTION FAILED" in r.stdout
    assert "RESULT DATA-FAILED" in r.stdout and "chart check skipped" in r.stdout
    assert "figure(s)" not in r.stdout  # lint result line never printed


def test_cli_json_reports_collection_and_skip(server, tmp_path):
    base, _ = server
    manifest = write_manifest(tmp_path, [{"name": "values", "url": f"{base}/nope"}])
    r = cli(FIX / "fetch_chart.py", "--sources", manifest, "--cache-dir", tmp_path / "cache", "--json")
    assert r.returncode == 2
    out = json.loads(r.stdout)
    assert out["result"] == "data-failed" and out["chart_check"] == "skipped"
    assert out["failures"] == ["values"]
    it = out["collection"]["items"][0]
    assert it["name"] == "values" and it["url"].endswith("/nope")
    assert it["outcome"] == "http_error" and "404" in it["detail"]
    assert "elapsed_ms" in it and it["path"] is None


def test_cli_json_success_carries_collection(server, tmp_path):
    base, _ = server
    manifest = write_manifest(tmp_path, [{"name": "values", "url": f"{base}/values.csv"}])
    r = cli(FIX / "fetch_chart.py", "--sources", manifest, "--cache-dir", tmp_path / "cache", "--json")
    assert r.returncode == 0, r.stderr + r.stdout
    out = json.loads(r.stdout)
    assert out["collection"]["ok"] and out["collection"]["items"][0]["outcome"] == "ok"


def test_cli_second_run_uses_cache(server, tmp_path):
    base, counts = server
    manifest = write_manifest(tmp_path, [{"name": "values", "url": f"{base}/values.csv"}])
    cache = tmp_path / "cache"
    args = ("--sources", manifest, "--cache-dir", cache)
    assert cli(FIX / "fetch_chart.py", *args).returncode == 0
    before = counts["/values.csv"]
    r = cli(FIX / "fetch_chart.py", *args)
    assert r.returncode == 0
    assert counts["/values.csv"] == before  # second run made no request
    assert "(cache)" in r.stdout


def test_cli_auto_discovers_sources_file(server, tmp_path):
    base, _ = server
    chart = tmp_path / "my_chart.py"
    chart.write_text((FIX / "fetch_chart.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "_clean.py").write_text((FIX / "_clean.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "my_chart.sources.json").write_text(
        json.dumps({"sources": [{"name": "values", "url": f"{base}/values.csv"}]}), encoding="utf-8")
    r = subprocess.run([sys.executable, str(SCRIPT), str(chart)],
                       capture_output=True, text=True, cwd=FIX, timeout=120)
    assert r.returncode == 0, r.stderr + r.stdout
    assert "DATA COLLECTION OK" in r.stdout
