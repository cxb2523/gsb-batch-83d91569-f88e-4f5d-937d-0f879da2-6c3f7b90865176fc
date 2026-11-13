"""Local-only verification for the qa_scraper batch outcome/resume feature.

Everything here runs against a throwaway local HTTP server. No real external
sites and no real proxy credentials are used.
"""

import json
import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import qa_scraper  # noqa: E402


GOOD_HTML = """<!doctype html><html><head><title>Local Good Page</title></head>
<body><h1>hello</h1><p>plenty of real content here for extraction</p>
<!-- padding -->
""" + ("<p>filler paragraph with ordinary page content</p>\n" * 30) + "</body></html>"

CAPTCHA_HTML = """<!doctype html><html><head><title>Access Denied</title></head>
<body><h1>Are you a robot?</h1><p>Please solve this captcha to continue.</p></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/ok"):
            self._send(200, GOOD_HTML)
        elif self.path.startswith("/blocked"):
            self._send(403, CAPTCHA_HTML)
        elif self.path.startswith("/empty"):
            # Page loads fine but has nothing an extractor can pull out.
            self._send(200, "<html><body></body></html>")
        else:
            self._send(404, "<html><body>not found</body></html>")

    def _send(self, status, body):
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # silence test server logs
        pass


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def local_server():
    port = _free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    try:
        yield {"base": base, "port": port}
    finally:
        httpd.shutdown()
        httpd.server_close()


def _manifest(base, **paths):
    """Build a site manifest pointing at the local server."""
    mapping = {
        "good": {"test_url": f"{base}/ok", "method": "proxy_http"},
        "blocked": {"test_url": f"{base}/blocked", "method": "proxy_http"},
        "refused": {"test_url": f"{base}/ok", "method": "proxy_http"},
        "extract_fail": {"test_url": f"{base}/empty", "method": "proxy_http"},
    }
    mapping.update(paths)
    return mapping


def test_classify_three_main_outcomes(local_server):
    base = local_server["base"]
    sites = _manifest(base)
    # "refused" points at a port nothing listens on.
    dead_port = _free_port()
    sites["refused"]["test_url"] = f"http://127.0.0.1:{dead_port}/"

    good = _run_one("good", sites, None)
    blocked = _run_one("blocked", sites, None)
    refused = _run_one("refused", sites, None)

    assert good["outcome"] == qa_scraper.OUTCOME_SUCCESS
    assert good["success"] is True
    assert good["http_status"] == 200
    assert good["page_size"] and good["page_size"] > 0

    assert blocked["outcome"] == qa_scraper.OUTCOME_BLOCKED
    assert blocked["success"] is False
    assert blocked["http_status"] == 403
    assert "captcha" in (blocked["blocked_reason"] or "").lower()

    assert refused["outcome"] == qa_scraper.OUTCOME_NETWORK_ERROR
    assert refused["success"] is False
    assert refused["http_status"] is None or refused["http_status"] == 0


def _run_one(site_name, sites_config, report_path):
    original = qa_scraper._FETCH_LOG
    qa_scraper._FETCH_LOG = []
    try:
        result = qa_scraper.run_site(site_name, None, None, sites_config=sites_config)
        events = qa_scraper._FETCH_LOG
    finally:
        qa_scraper._FETCH_LOG = original
    return qa_scraper.build_outcome_entry(site_name, result, events, sites_config)


def test_extraction_failed_is_distinct(local_server):
    sites = _manifest(local_server["base"])
    entry = _run_one("extract_fail", sites, None)
    assert entry["outcome"] == qa_scraper.OUTCOME_EXTRACTION_FAILED
    assert entry["http_status"] == 200
    assert entry["success"] is False


def test_unknown_site_outcome(local_server):
    sites = _manifest(local_server["base"])
    entry = _run_one("does_not_exist", sites, None)
    assert entry["outcome"] == qa_scraper.OUTCOME_UNKNOWN_SITE
    assert entry["success"] is False


@pytest.fixture()
def report_path(tmp_path):
    return str(tmp_path / "qa_report.json")


def test_batch_writes_one_record_per_site_and_counts(local_server, report_path):
    sites = _manifest(local_server["base"])
    dead_port = _free_port()
    sites["refused"]["test_url"] = f"http://127.0.0.1:{dead_port}/"

    out = qa_scraper.run_batch(
        ["good", "blocked", "refused", "extract_fail"],
        None, sites_config=sites, report_path=report_path, verbose=False,
    )
    counts = out["counts"]
    assert counts["executed"] == 4
    assert counts["skipped"] == 0
    assert counts["succeeded"] == 1
    assert counts["failed"] == 3
    assert counts["outcomes"] == {
        "blocked": 1, "extraction_failed": 1, "network_error": 1, "success": 1,
    }

    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert set(saved["sites"]) == {"good", "blocked", "refused", "extract_fail"}
    assert len(saved["sites"]) == 4  # exactly one record per site
    assert saved["sites"]["good"]["outcome"] == "success"
    assert saved["sites"]["blocked"]["outcome"] == "blocked"


def test_resume_skips_successful_sites_and_retries_failures(local_server, report_path):
    base = local_server["base"]
    sites = _manifest(base)
    dead_port = _free_port()
    sites["refused"]["test_url"] = f"http://127.0.0.1:{dead_port}/"

    first = qa_scraper.run_batch(
        ["good", "blocked", "refused"], None,
        sites_config=sites, report_path=report_path, verbose=False,
    )
    assert first["counts"]["executed"] == 3
    first_good = first["entries"]["good"]

    # Second run: the failed site is fixed; the good site must be skipped.
    sites["blocked"]["test_url"] = f"{base}/ok"
    second = qa_scraper.run_batch(
        ["good", "blocked", "refused"], None,
        sites_config=sites, report_path=report_path, verbose=False,
    )
    counts = second["counts"]
    assert counts["executed"] == 2
    assert counts["skipped"] == 1
    # "succeeded" counts this round's executions only; the skipped success is
    # reported separately under "skipped".
    assert counts["succeeded"] == 1
    assert counts["successful_in_file"] == 2
    # The skipped success kept its original record (not re-run/re-stamped).
    assert second["entries"]["good"]["checked_at"] == first_good["checked_at"]

    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert len(saved["sites"]) == 3
    assert saved["sites"]["good"]["outcome"] == "success"
    assert saved["sites"]["blocked"]["outcome"] == "success"
    # "refused" is still a failure and must have been retried.
    assert saved["sites"]["refused"]["outcome"] == "network_error"


def test_partial_run_keeps_previously_written_success(local_server, report_path):
    base = local_server["base"]
    sites = _manifest(base)

    qa_scraper.run_batch(["good"], None, sites_config=sites, report_path=report_path, verbose=False)
    with open(report_path, encoding="utf-8") as fh:
        assert json.load(fh)["sites"]["good"]["outcome"] == "success"

    # Now run only a different subset, as if resuming after an interruption.
    qa_scraper.run_batch(["blocked"], None, sites_config=sites, report_path=report_path, verbose=False)
    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert set(saved["sites"]) == {"good", "blocked"}
    assert saved["sites"]["good"]["outcome"] == "success"  # not lost
    assert saved["sites"]["blocked"]["outcome"] == "blocked"


def test_no_resume_flag_reruns_successful(local_server, report_path):
    sites = _manifest(local_server["base"])
    first = qa_scraper.run_batch(
        ["good"], None, sites_config=sites, report_path=report_path, verbose=False,
    )
    second = qa_scraper.run_batch(
        ["good"], None, sites_config=sites, report_path=report_path,
        skip_successful=False, verbose=False,
    )
    assert first["counts"]["executed"] == 1
    assert second["counts"]["executed"] == 1
    assert second["counts"]["skipped"] == 0


def test_interruption_keeps_prior_successes_and_resumes(local_server, report_path, monkeypatch):
    """A KeyboardInterrupt mid-batch must not lose records already written."""
    base = local_server["base"]
    sites = _manifest(base)
    dead_port = _free_port()
    sites["refused"]["test_url"] = f"http://127.0.0.1:{dead_port}/"

    real_run_site = qa_scraper.run_site
    state = {"calls": 0}

    def flaky_run_site(*args, **kwargs):
        state["calls"] += 1
        if state["calls"] == 3:  # interrupt while the 3rd site is in flight
            raise KeyboardInterrupt()
        return real_run_site(*args, **kwargs)

    monkeypatch.setattr(qa_scraper, "run_site", flaky_run_site)
    with pytest.raises(KeyboardInterrupt):
        qa_scraper.run_batch(
            ["good", "blocked", "refused"], None,
            sites_config=sites, report_path=report_path, verbose=False,
        )

    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    # The two completed sites were flushed before the interrupt.
    assert saved["sites"]["good"]["outcome"] == "success"
    assert saved["sites"]["blocked"]["outcome"] == "blocked"
    assert "refused" not in saved["sites"]
    assert saved["counts"]["interrupted_at"] == "refused"

    # Resume: success skipped, blocked retried, refused now attempted.
    monkeypatch.setattr(qa_scraper, "run_site", real_run_site)
    resumed = qa_scraper.run_batch(
        ["good", "blocked", "refused"], None,
        sites_config=sites, report_path=report_path, verbose=False,
    )
    assert resumed["counts"]["skipped"] == 1
    assert resumed["counts"]["executed"] == 2
    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert set(saved["sites"]) == {"good", "blocked", "refused"}
    assert saved["sites"]["good"]["outcome"] == "success"


def test_batch_unknown_site_is_explicit_outcome(local_server, report_path):
    sites = _manifest(local_server["base"])
    out = qa_scraper.run_batch(
        ["good", "not_in_manifest"], None,
        sites_config=sites, report_path=report_path, verbose=False,
    )
    assert out["counts"]["outcomes"]["unknown_site"] == 1
    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved["sites"]["not_in_manifest"]["outcome"] == "unknown_site"
    assert len(saved["sites"]) == 2


def test_extractor_crash_is_extraction_failed_not_network(local_server, report_path, monkeypatch):
    sites = _manifest(local_server["base"])
    # "api" method routes through extract_generic, so the crash happens inside
    # the extraction stage rather than in a transport fallback.
    sites["extract_fail"]["method"] = "api"

    def boom(*args, **kwargs):
        raise RuntimeError("extractor blew up")

    monkeypatch.setattr(qa_scraper, "extract_generic", boom)
    out = qa_scraper.run_batch(
        ["extract_fail"], None, sites_config=sites, report_path=report_path, verbose=False,
    )
    entry = out["entries"]["extract_fail"]
    assert entry["outcome"] == qa_scraper.OUTCOME_EXTRACTION_FAILED
    assert "extractor blew up" in entry["error"]
    # The rest of the batch must still have completed.
    assert out["counts"]["executed"] == 1


def test_fetch_log_hook_does_not_change_extractor_output(local_server):
    """The instrumentation must be inert outside a batch run."""
    sites = _manifest(local_server["base"])
    original = qa_scraper._FETCH_LOG
    qa_scraper._FETCH_LOG = None
    try:
        result = qa_scraper.run_site("good", None, None, sites_config=sites)
    finally:
        qa_scraper._FETCH_LOG = original
    assert result["success"] is True
    assert result["status"] == 200


def test_corrupt_report_is_not_silently_overwritten(local_server, report_path):
    """A truncated/corrupt report must abort rather than drop earlier records."""
    sites = _manifest(local_server["base"])
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write('{"version": 1, "sites": {"good": {"outco')  # truncated write

    with pytest.raises(qa_scraper.ReportError):
        qa_scraper.run_batch(
            ["good"], None, sites_config=sites, report_path=report_path, verbose=False,
        )
    # The damaged file is left untouched for inspection.
    with open(report_path, encoding="utf-8") as fh:
        assert "outco" in fh.read()


def test_subset_run_only_touches_requested_sites(local_server, report_path):
    base = local_server["base"]
    sites = _manifest(base)
    qa_scraper.run_batch(["good"], None, sites_config=sites, report_path=report_path, verbose=False)

    sub = qa_scraper.run_batch(
        ["blocked"], None, sites_config=sites, report_path=report_path, verbose=False,
    )
    assert sub["counts"]["total"] == 1
    assert sub["counts"]["executed"] == 1
    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert set(saved["sites"]) == {"good", "blocked"}
    assert saved["last_run"]["sites_requested"] == ["blocked"]


def test_manifest_loading_rejects_bad_entries(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"sites": {"x": {"method": "api"}}}), encoding="utf-8")
    with pytest.raises(ValueError):
        qa_scraper.load_sites_manifest(str(bad))


def test_manifest_loading(tmp_path):
    manifest = {
        "sites": {
            "local_ok": {"test_url": "http://127.0.0.1:1/ok", "method": "api"},
        }
    }
    path = tmp_path / "sites.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    loaded = qa_scraper.load_sites_manifest(str(path))
    assert loaded["local_ok"]["test_url"] == "http://127.0.0.1:1/ok"
    assert loaded["local_ok"]["method"] == "api"


def test_cli_batch_json_end_to_end(local_server, report_path, monkeypatch):
    """Drive the real CLI path (--all --sites-file --report) with local sites."""
    sites = _manifest(local_server["base"])
    dead_port = _free_port()
    sites["refused"]["test_url"] = f"http://127.0.0.1:{dead_port}/"

    manifest_path = os.path.join(os.path.dirname(report_path), "sites.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(sites, fh)

    monkeypatch.setattr(sys, "argv", [
        "qa_scraper.py", "--all",
        "--sites-file", manifest_path,
        "--report", report_path,
        "--no-proxy",
        "--sites", "good", "blocked", "refused",
        "--json",
    ])
    qa_scraper.main()  # no --fail-on-error: failures are recorded, not raised

    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert set(saved["sites"]) == {"good", "blocked", "refused"}
    assert saved["sites"]["good"]["outcome"] == "success"
    assert saved["sites"]["blocked"]["outcome"] == "blocked"
    assert saved["sites"]["refused"]["outcome"] == "network_error"


def test_cli_resume_skips_success(local_server, report_path, monkeypatch, capsys):
    sites = _manifest(local_server["base"])
    manifest_path = os.path.join(os.path.dirname(report_path), "sites.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(sites, fh)

    def _invoke():
        monkeypatch.setattr(sys, "argv", [
            "qa_scraper.py", "--all",
            "--sites-file", manifest_path,
            "--report", report_path,
            "--no-proxy",
            "--sites", "good", "blocked",
            "--json",
        ])
        qa_scraper.main()
        return json.loads(capsys.readouterr().out)

    first = _invoke()
    assert first["counts"]["executed"] == 2
    second = _invoke()
    assert second["counts"]["skipped"] == 1
    assert second["counts"]["executed"] == 1

    with open(report_path, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert len(saved["sites"]) == 2  # one record each, no duplicates
