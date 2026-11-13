#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Local end-to-end test for scripts/scraper.py and scripts/parser.py.

Everything is served by a mock HTTP server on localhost; no network access is
required. The scenario deliberately includes:

* normal search pages with match links;
* a match link repeated across pages and a fragment-only variant of the same
  link (URL de-duplication);
* a search page that fails twice before succeeding (retry);
* a search page that always fails (the run must continue with later pages);
* a match URL that always fails to download;
* an empty HTML file in the output directory (parser must tolerate it);
* a missing input folder (parser must skip it with a notice).
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import scraper  # noqa: E402
import parser as cricket_parser  # noqa: E402

MATCH_PAGES = {
    "100": ("Team Alpha", "Team Beta", "100"),
    "101": ("Team Gamma", "Team Delta", "101"),
    "102": ("Team Epsilon", "Team Zeta", "102"),
    "103": ("Team Eta", "Team Theta", "103"),
    "104": ("Team Iota", "Team Kappa", "104"),
}


def match_html(match_id):
    team1, team2, real_id = MATCH_PAGES[match_id]
    return (
        '<html><head><title>{t1} v {t2} Test Report | ESPN | Cricket'
        "</title></head><body>"
        '<a class="teamLink">{t1}</a><a class="teamLink">{t2}</a>'
        "<span>Toss  - <span class='normal'>{t1}, who chose to bat"
        "</span></span>"
        '<div class="innings-requirement">{t1} won by 7 wickets</div>'
        'title="view the ground profile for Lord\'s, London"'
        ">Match Notes<div></div>"
        '<div data-matchId="{mid}"></div>'
        "</body></html>"
    ).format(t1=team1, t2=team2, mid=real_id).encode("utf-8")


def search_html(page):
    links_by_page = {
        0: ["/match/100.html", "/match/101.html"],
        # 101 repeats page 0; the #scorecard variant normalizes to the same
        # URL; 200 always fails to download.
        1: [
            "/match/101.html",
            "/match/101.html#scorecard",
            "/match/102.html",
            "/match/200.html",
        ],
        2: ["/match/103.html"],
        3: [],
        4: ["/match/104.html"],
    }
    anchors = "".join(
        '<a class="srchPlyrNmTxt" href="{0}">match</a>'.format(href)
        for href in links_by_page[page]
    )
    return ("<html><body>{0}</body></html>".format(anchors)).encode("utf-8")


class MockHandler(BaseHTTPRequestHandler):
    # page number -> number of failures before a successful response
    flaky_failures = {2: 2}
    always_failing_pages = {3}
    attempts = {}

    def log_message(self, format, *args):  # silence test server logging
        pass

    def _send(self, status, body, content_type="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/search":
            page = int(parse_qs(parsed.query)["page"][0])
            seen = self.attempts.get(("search", page), 0) + 1
            self.attempts[("search", page)] = seen
            if page in self.always_failing_pages:
                self._send(500, b"always failing")
                return
            required_failures = self.flaky_failures.get(page, 0)
            if seen <= required_failures:
                self._send(500, b"transient failure")
                return
            self._send(200, search_html(page))
            return
        if parsed.path.startswith("/match/"):
            match_id = parsed.path[len("/match/"):].replace(".html", "")
            if match_id == "200":
                self._send(404, b"not found")
                return
            if match_id in MATCH_PAGES:
                self._send(200, match_html(match_id))
                return
        self._send(404, b"unknown route")


class TestHarness:
    def __init__(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.output_dir = os.path.join(self.tempdir.name, "espncricinfo-fc")
        self.manifest_path = os.path.join(
            self.tempdir.name, "manifest.json"
        )
        self.csv_path = os.path.join(self.tempdir.name, "final_output.csv")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base_url = "http://127.0.0.1:{0}".format(
            self.server.server_address[1]
        )

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.tempdir.cleanup()

    def run_scraper(self):
        return subprocess.run(
            [
                sys.executable,
                "-I",
                os.path.join(SCRIPTS_DIR, "scraper.py"),
                "--start-page",
                "0",
                "--end-page",
                "4",
                "--sleep",
                "0",
                "--output-dir",
                self.output_dir,
                "--manifest",
                self.manifest_path,
                "--search-url",
                self.base_url + "/search",
                "--base-url",
                self.base_url,
                "--timeout",
                "5",
                "--max-attempts",
                "3",
                "--retry-backoff",
                "0",
            ],
            capture_output=True,
            text=True,
        )

    def load_manifest(self):
        with open(self.manifest_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def run_parser(self, input_folders):
        return subprocess.run(
            [
                sys.executable,
                "-I",
                os.path.join(SCRIPTS_DIR, "parser.py"),
                "--input-folders",
                *input_folders,
                "--output",
                self.csv_path,
            ],
            capture_output=True,
            text=True,
        )


def check(condition, message):
    if not condition:
        raise AssertionError(message)
    print("ok - {0}".format(message))


def main():
    harness = TestHarness()
    failures = 0
    try:
        # ---- first scrape ------------------------------------------------
        result = harness.run_scraper()
        check(
            result.returncode == 0,
            "scraper exits 0 even though a page and a match download fail "
            "(exit={0})".format(result.returncode),
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)

        manifest = harness.load_manifest()
        check(isinstance(manifest, dict), "manifest is machine-readable JSON")
        check("summary" in manifest, "manifest contains summary counts")

        pages = {entry["page"]: entry for entry in manifest["pages"]}
        check(len(pages) == 5, "all five pages appear in the manifest")
        check(
            pages[3]["status"] == scraper.PAGE_STATUS_FAILED,
            "page 3 recorded as failed with reason: {0}".format(
                pages[3].get("error")
            ),
        )
        check(
            pages[2]["status"]
            == scraper.PAGE_STATUS_SUCCESS_AFTER_RETRY
            and pages[2]["attempts"] == 3,
            "page 2 recorded as success after retries (3 attempts)",
        )
        check(
            pages[0]["status"] == scraper.PAGE_STATUS_SUCCESS
            and pages[4]["status"] == scraper.PAGE_STATUS_SUCCESS,
            "pages after the failed page still processed",
        )
        check(
            manifest["summary"]["pages_failed"] == 1,
            "summary counts one failed page",
        )

        downloaded = sorted(os.listdir(harness.output_dir))
        check(
            downloaded == ["100.html", "101.html", "102.html", "103.html",
                           "104.html"],
            "exactly the five unique match pages were downloaded once "
            "(got {0})".format(downloaded),
        )
        check(
            not os.path.exists(
                os.path.join(harness.output_dir, "200.html")
            ),
            "the match whose download always failed has no file",
        )

        duplicate_urls = {item["url"] for item in manifest["duplicates"]}
        check(
            len(manifest["duplicates"]) == 2
            and all(url.endswith("/match/101.html") for url in
                    duplicate_urls),
            "repeated and fragment-only links recorded as duplicates of "
            "101",
        )
        failed_urls = {
            item["url"] for item in manifest["download_failures"]
        }
        check(
            any(url.endswith("/match/200.html") for url in failed_urls),
            "failed match download recorded with its URL",
        )
        check(
            manifest["summary"]["match_files_downloaded"] == 5
            and manifest["summary"]["match_download_failures"] == 1
            and manifest["summary"]["duplicates_skipped"] == 2,
            "summary counts match downloads, failures and duplicates",
        )

        # ---- second scrape: resume --------------------------------------
        result2 = harness.run_scraper()
        check(
            result2.returncode == 0,
            "resume run exits 0",
        )
        manifest2 = harness.load_manifest()
        check(
            manifest2["summary"]["pages_resumed"] == 3,
            "fully completed pages (0, 2, 4) are skipped on rerun",
        )
        check(
            manifest2["summary"]["match_files_downloaded"] == 0,
            "no match file is downloaded again on rerun",
        )
        check(
            manifest2["summary"]["match_files_skipped_existing"] == 2
            and manifest2["summary"]["duplicates_skipped"] == 1,
            "rerun marks on-disk matches as skipped-existing and still "
            "deduplicates links",
        )
        check(
            manifest2["summary"]["pages_failed"] == 1
            and manifest2["summary"]["match_download_failures"] == 1,
            "the always-failing search page and match download are "
            "retried and recorded again",
        )
        check(
            sorted(os.listdir(harness.output_dir))
            == ["100.html", "101.html", "102.html", "103.html",
                "104.html"],
            "no partial or extra files appear after the resume run",
        )

        # ---- parser with an empty file and a missing folder --------------
        empty_path = os.path.join(harness.output_dir, "empty.html")
        with open(empty_path, "wb"):
            pass
        check(os.path.getsize(empty_path) == 0, "empty test file created")

        missing_folder = os.path.join(
            harness.tempdir.name, "does-not-exist"
        )
        parse_result = harness.run_parser(
            [missing_folder, harness.output_dir]
        )
        check(
            parse_result.returncode == 0,
            "parser exits 0 with missing folder and empty file",
        )
        check(
            "does not exist, skipping" in parse_result.stdout,
            "parser announces the missing folder and skips it",
        )

        with open(harness.csv_path, "r", encoding="utf-8", newline="") \
                as handle:
            lines = handle.readlines()
            reader = csv.reader(lines)
            rows = list(reader)
        check(
            lines[0].rstrip("\n") == cricket_parser.HEADER,
            "CSV keeps the original header and field order",
        )
        data_rows = rows[1:]
        check(
            len(data_rows) == 6,
            "parser row count equals number of files in the successful "
            "download directory (5 matches + 1 empty file)",
        )
        ids = {row[12] for row in data_rows}
        check(
            ids == {"100", "101", "102", "103", "104", ""},
            "match_id parsed for every real match, empty for the empty "
            "file (got {0})".format(ids),
        )
        empty_row = next(
            row for row in data_rows if row[0].endswith("empty.html")
        )
        check(
            empty_row[1] == "" and empty_row[12] == ""
            and empty_row[8] == "0",
            "empty file yields empty values instead of an error",
        )
        match_row = next(
            row for row in data_rows if row[0].endswith("100.html")
        )
        check(
            match_row[1] == "Team Alpha"
            and match_row[2] == "Team Beta"
            and match_row[5] == "Team Alpha won by 7 wickets",
            "normal match rows still extract all fields",
        )
    except AssertionError as exc:
        failures += 1
        print("FAIL - {0}".format(exc))
    finally:
        harness.close()

    if failures:
        print("{0} test(s) failed".format(failures))
        return 1
    print("all tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
