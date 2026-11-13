"""Batch-extract acceptance check against a real FoxProfile API.

Manual script (not part of pytest): needs a running FoxProfile
(`python -m src.server`) with a fetched browser. It builds four local sample
targets — a page with fixed text, a page where the selector never appears, an
unreachable address (standing in for a dead proxy exit) and an invalid URL —
runs them as one batch on a real profile, and verifies:

- each target's status and failure classification,
- the successful target's text is complete and not truncated,
- the profile's browser is still running after the batch,
- a re-run with skip_succeeded marks the earlier success as skipped,
- the batch result is retrievable via GET (latest and by batch id).

Run: python tests/e2e/batch_e2e.py
Env: FOXPROFILE_URL (default http://127.0.0.1:8000), FOXPROFILE_API_TOKEN,
     E2E_ENGINE (profile engine, default camoufox).
"""

import http.server
import json
import os
import pathlib
import sys
import threading
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE = os.getenv("FOXPROFILE_URL", "http://127.0.0.1:8000").rstrip("/") + "/api/v1"
TOKEN = os.getenv("FOXPROFILE_API_TOKEN", "")
ENGINE = os.getenv("E2E_ENGINE", "camoufox")
PROFILE = "e2e-batch"
SELECTOR = "#target"
FIXED_TEXT = "fixed-batch-text-0123456789"

FAILURES = []


def check(label, condition, detail=""):
    print(f"{'PASS' if condition else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))
    if not condition:
        FAILURES.append(label)


def api(method, path, body=None):
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}),
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


class Pages(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ok":
            html = f'<html><body><div id="target">{FIXED_TEXT}</div></body></html>'
        else:
            html = "<html><body><p>nothing to see</p></body></html>"
        payload = html.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass


def main():
    server = http.server.HTTPServer(("127.0.0.1", 0), Pages)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    print(f"local pages on 127.0.0.1:{port}")

    api("DELETE", f"/profiles/{PROFILE}")
    status, _ = api("POST", "/profiles", {"name": PROFILE, "os_type": "windows", "engine": ENGINE})
    check("profile created", status == 201, f"HTTP {status}")
    status, launch = api("POST", f"/browser/{PROFILE}/launch")
    check("browser launched", status == 200 and launch.get("success"), str(launch)[:120])

    targets = [
        {"id": "ok", "url": f"http://127.0.0.1:{port}/ok"},
        {"id": "never-appears", "url": f"http://127.0.0.1:{port}/missing"},
        # Closed local port stands in for an unreachable proxy exit.
        {"id": "unreachable-proxy", "url": "http://127.0.0.1:9/"},
        {"id": "invalid-url", "url": "file:///etc/hostname"},
    ]
    body = {"targets": targets, "selector": SELECTOR, "timeout": 5000}
    status, batch = api("POST", f"/browser/{PROFILE}/page/batch-extract", body)
    check("batch accepted", status == 200, f"HTTP {status}")
    results = {r["id"]: r for r in batch.get("results", [])} if status == 200 else {}

    ok = results.get("ok", {})
    check("ok: success", ok.get("status") == "success", str(ok)[:120])
    check(
        "ok: full text, not truncated",
        ok.get("text") == FIXED_TEXT and ok.get("truncated") is False,
        repr(ok.get("text")),
    )
    check(
        "never-appears: wait_timeout",
        results.get("never-appears", {}).get("status") == "failed"
        and results["never-appears"].get("error_kind") == "wait_timeout",
        str(results.get("never-appears"))[:120],
    )
    check(
        "unreachable-proxy: proxy_or_network_unreachable",
        results.get("unreachable-proxy", {}).get("error_kind") == "proxy_or_network_unreachable",
        str(results.get("unreachable-proxy"))[:160],
    )
    check(
        "invalid-url: invalid_params",
        results.get("invalid-url", {}).get("error_kind") == "invalid_params",
        str(results.get("invalid-url"))[:120],
    )
    check(
        "counts add up",
        status == 200
        and (batch["total"], batch["succeeded"], batch["failed"], batch["skipped"]) == (4, 1, 3, 0),
        str({k: batch.get(k) for k in ("total", "succeeded", "failed", "skipped")}),
    )

    status, running = api("GET", f"/browser/{PROFILE}/status")
    check("profile still running", status == 200 and running.get("is_running") is True)

    status, latest = api("GET", f"/browser/{PROFILE}/page/batch-extract")
    check(
        "latest batch retrievable",
        status == 200 and latest.get("batch_id") == batch.get("batch_id"),
    )
    status, _ = api("GET", f"/browser/{PROFILE}/page/batch-extract/{batch.get('batch_id')}")
    check("batch retrievable by id", status == 200)

    # Re-run the same targets with the skip policy.
    status, rerun = api(
        "POST",
        f"/browser/{PROFILE}/page/batch-extract",
        {**body, "skip_succeeded": True},
    )
    again = {r["id"]: r for r in rerun.get("results", [])} if status == 200 else {}
    skipped = again.get("ok", {})
    check(
        "re-run: previous success skipped with reason",
        skipped.get("status") == "skipped"
        and batch.get("batch_id", " ") in skipped.get("reason", ""),
        str(skipped)[:140],
    )
    check(
        "re-run: failures retried, not skipped",
        again.get("never-appears", {}).get("status") == "failed"
        and again.get("unreachable-proxy", {}).get("status") == "failed"
        and again.get("invalid-url", {}).get("status") == "failed",
    )
    check(
        "re-run: counts",
        status == 200 and (rerun["succeeded"], rerun["failed"], rerun["skipped"]) == (0, 3, 1),
        str({k: rerun.get(k) for k in ("succeeded", "failed", "skipped")}),
    )

    status, running = api("GET", f"/browser/{PROFILE}/status")
    check("profile still running after re-run", running.get("is_running") is True)

    api("POST", f"/browser/{PROFILE}/stop")
    api("DELETE", f"/profiles/{PROFILE}")
    server.shutdown()

    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed: {FAILURES}")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
