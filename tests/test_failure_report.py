"""The failure report: a checkable list of what the archive does not have.

The summary used to end with a count and up to 50 bare URLs. The report is a
JSON file in the output directory naming every address that could not be
fetched, where it would have been stored, why it failed, and whether other
capture timestamps were tried; one line per address however often it failed.
It is written with the run's result, never mixed in with the downloaded site.

Everything here runs against fake responses: the shared conftest guard fails
any real connection.
"""

import contextlib
import io
import json
import os

import pytest

from wayback_archive.config import Config
from wayback_archive.downloader import WaybackDownloader

WAYBACK_URL = "https://web.archive.org/web/20200101000000/https://example.com/"
SITE = "https://example.com"
REPORT = WaybackDownloader.FAILURE_REPORT_FILE


class _Response:
    """A fake requests response, answered from a handler."""

    def __init__(self, status, body=b"", content_type=None):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": content_type} if content_type else {}
        self.url = ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(response=self)


class _Wayback:
    """web.archive.org stand-in: pages maps an original URL to its answer.

    A value may be bytes, (bytes, content_type), or a callable taking the
    request URL and returning _Response. Anything else is a 404.
    """

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        # Everything is a Wayback capture; match on the original address at
        # the end of the request, which ignores the timestamp and prefix.
        for original, value in self.pages.items():
            if url.endswith("/" + original):
                if callable(value):
                    return value(url)
                body, content_type = value if isinstance(value, tuple) else (value, None)
                return _Response(200, body, content_type)
        return _Response(404)


def _make_downloader(output_dir, max_files=None):
    os.environ["WAYBACK_URL"] = WAYBACK_URL
    config = Config()
    config.output_dir = str(output_dir)
    config.max_files = max_files
    return WaybackDownloader(config)


def _run(tmp_path, pages, max_files=None):
    """Run a crawl; return (downloader, output directory, summary text)."""
    output_dir = tmp_path / "out"
    dl = _make_downloader(output_dir, max_files=max_files)
    dl.session = _Wayback(pages)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        dl.download()
    return dl, output_dir, out.getvalue()


def _report(output_dir):
    path = output_dir / REPORT
    assert path.is_file(), sorted(p.name for p in output_dir.iterdir())
    return json.loads(path.read_text(encoding="utf-8"))


def _site_files(output_dir):
    """The downloaded site: every file except the downloader's own report."""
    return {p.relative_to(output_dir).as_posix() for p in output_dir.rglob("*") if p.is_file()} - {REPORT}


PNG = b"\x89PNG\r\n\x1a\nxx"
HOME = f'<html><body><img src="{SITE}/logo.png"></body></html>'.encode()


class TestSuccess:
    def test_a_run_that_succeeds_writes_an_empty_report(self, tmp_path):
        """The report is always written, so a script may always read it."""
        _, output_dir, out = _run(tmp_path, {SITE + "/": HOME, SITE + "/logo.png": PNG})

        report = _report(output_dir)
        assert report["failed"] == 0
        assert report["failures"] == []
        assert report["wayback_url"] == WAYBACK_URL
        assert "Files failed: 0" in out

    def test_the_report_is_not_mixed_with_the_site(self, tmp_path):
        """The report is bookkeeping: the site files are only the site."""
        _, output_dir, _ = _run(tmp_path, {SITE + "/": HOME, SITE + "/logo.png": PNG})

        assert _site_files(output_dir) == {"index.html", "logo.png"}
        assert (output_dir / REPORT).is_file()
        # The index does not link to it, and nothing downloaded overwrote it.
        assert "wayback-archive-failures.json" not in (output_dir / "index.html").read_text(encoding="utf-8")


class TestSingleFailure:
    def test_one_missing_asset_is_one_line_with_its_path_and_category(self, tmp_path):
        _, output_dir, out = _run(tmp_path, {SITE + "/": HOME})
        report = _report(output_dir)

        assert len(report["failures"]) == 1
        entry = report["failures"][0]
        assert entry["url"] == SITE + "/logo.png"
        assert entry["local_path"] == "logo.png"
        assert entry["category"] == "missing"
        assert entry["attempts"] == 1
        # A 404 at the original timestamp makes the fallback timestamps run.
        assert entry["tried_other_timestamps"] is True

        # The summary's count is the report's entry count.
        assert "Files failed: 1" in out
        assert report["failed"] == 1

    def test_a_network_failure_is_reported_as_network(self, tmp_path):
        import requests

        def refused(url):
            raise requests.exceptions.ConnectionError("no answer")

        _, output_dir, _ = _run(tmp_path, {SITE + "/": HOME, SITE + "/logo.png": refused})
        entry = _report(output_dir)["failures"][0]
        assert entry["category"] == "network"
        assert entry["local_path"] == "logo.png"

    def test_an_unusable_answer_is_reported_as_unusable(self, tmp_path):
        """Wayback answers an image with an HTML page: a file that cannot be used."""
        wayback_page = b"<!DOCTYPE html><html><head><title>Wayback Machine</title></head><body></body></html>"
        _, output_dir, _ = _run(tmp_path, {SITE + "/": HOME, SITE + "/logo.png": wayback_page})
        entry = _report(output_dir)["failures"][0]
        assert entry["category"] == "unusable"

    def test_a_page_that_cannot_be_processed_is_reported(self, tmp_path):
        """The raw page is saved, but its links are not followed: it failed."""
        dl = _make_downloader(tmp_path / "out")
        home = (f'<html><body><a href="{SITE}/about">about</a><img src="{SITE}/logo.png"></body></html>').encode()
        page = b"<html><body>about</body></html>"
        dl.session = _Wayback({SITE + "/": home, SITE + "/about": page, SITE + "/logo.png": PNG})

        real = dl._process_html

        def broken(html, base_url):
            if base_url.endswith("/about"):
                raise ValueError("broken")
            return real(html, base_url)

        dl._process_html = broken
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            dl.download()
        report = _report(tmp_path / "out")
        assert report["failed"] == 1
        assert report["failures"][0]["url"] == SITE + "/about"
        assert report["failures"][0]["category"] == "unusable"


class TestRepeatedFailure:
    def test_the_same_address_twice_is_one_line_with_two_attempts(self, tmp_path):
        """Two attempts at one address: one report line, two attempts."""
        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True)
        dl = _make_downloader(output_dir)
        dl.session = _Wayback({})  # everything 404s
        # Each call is an attempt; a caller retrying the same address is the
        # case the report dedups.
        assert dl.download_file(SITE + "/logo.png") is None
        assert dl.download_file(SITE + "/logo.png") is None
        dl._write_failure_report()

        report = _report(output_dir)
        assert len(report["failures"]) == 1
        entry = report["failures"][0]
        assert entry["url"] == SITE + "/logo.png"
        assert entry["attempts"] == 2
        assert report["failed"] == 1

    def test_a_later_success_removes_the_address_from_the_report(self, tmp_path):
        """The report lists what is missing now, not what failed once."""
        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True)
        dl = _make_downloader(output_dir)
        dl.session = _Wayback({})
        assert dl.download_file(SITE + "/logo.png") is None
        dl.session = _Wayback({SITE + "/logo.png": PNG})
        assert dl.download_file(SITE + "/logo.png") == PNG
        dl._write_failure_report()
        assert _report(output_dir)["failures"] == []

    def test_attempts_survive_an_interrupted_run_that_resumes(self, tmp_path):
        """The state carries the report, so the resumed run keeps the count."""
        output_dir = tmp_path / "out"
        output_dir.mkdir(parents=True)
        state_path = output_dir / WaybackDownloader.STATE_FILE

        # A report entry that a previous run left in its saved state.
        dl = _make_downloader(output_dir)
        dl.session = _Wayback({})
        assert dl.download_file(SITE + "/logo.png") is None
        dl._save_state(SITE + "/", [], 1, [SITE + "/logo.png"], 0)
        assert _state_attempts(output_dir, SITE + "/logo.png") == 1
        state_path.write_text(
            json.dumps({**json.loads(state_path.read_text(encoding="utf-8")), "complete": False}),
            encoding="utf-8",
        )

        # The resumed run reads it back and adds to the same line.
        dl = _make_downloader(output_dir)
        dl.session = _Wayback({})
        dl._load_state(SITE + "/")
        assert dl.failures[SITE + "/logo.png"]["attempts"] == 1
        assert dl.download_file(SITE + "/logo.png") is None
        dl._write_failure_report()
        entry = _report(output_dir)["failures"][0]
        assert entry["url"] == SITE + "/logo.png"
        assert entry["attempts"] == 2


def _state_attempts(output_dir, url):
    state = json.loads((output_dir / WaybackDownloader.STATE_FILE).read_text(encoding="utf-8"))
    return next(e["attempts"] for e in state["failures"] if e["url"] == url)


class TestMaxFiles:
    def test_the_report_lists_only_what_was_attempted(self, tmp_path, monkeypatch):
        """MAX_FILES stops the crawl: failures nobody tried are not reported."""
        monkeypatch.setenv("MAX_FILES", "2")
        (*_,) = ()
        images = "".join(f'<img src="{SITE}/i{n}.png">' for n in range(6))
        page = f"<html><body>{images}</body></html>".encode()
        dl, output_dir, out = _run(tmp_path, {SITE + "/": page}, max_files=2)

        report = _report(output_dir)
        # The home page, then one image within the limit.
        assert report["failed"] == 1
        assert report["failures"][0]["url"] == SITE + "/i0.png"
        assert "Stopped at MAX_FILES" in out
        for n in range(1, 6):
            assert all(e["url"] != f"{SITE}/i{n}.png" for e in report["failures"])

    def test_a_failed_attempt_counts_toward_the_limit_and_is_reported(self, tmp_path):
        """The failed file is one of the N tried, and it is on the report."""
        page = f'<html><body><img src="{SITE}/gone.png"><img src="{SITE}/ok.png"></body></html>'.encode()
        dl, output_dir, out = _run(tmp_path, {SITE + "/": page, SITE + "/ok.png": PNG}, max_files=2)
        report = _report(output_dir)
        assert [e["url"] for e in report["failures"]] == [SITE + "/gone.png"]
        assert "Files failed: 1" in out


class TestInterrupt:
    def test_an_interrupted_run_writes_only_a_whole_report(self, tmp_path):
        """An interrupt after a failure writes the report once, complete."""
        dl = _make_downloader(tmp_path / "out")
        dl.session = _Wayback({SITE + "/": HOME, SITE + "/logo.png": PNG})

        real = dl.download_file

        def interrupt(url):
            if url == SITE + "/logo.png":
                raise KeyboardInterrupt
            return real(url)

        dl.download_file = interrupt
        with pytest.raises(KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            dl.download()

        # The first page was saved; the interrupted file is not a failure.
        assert (tmp_path / "out" / "index.html").is_file()
        report = _report(tmp_path / "out")
        assert report["failed"] == 0
        assert not list((tmp_path / "out").rglob("*.part"))

    def test_an_interrupt_after_a_failure_keeps_it_in_the_report(self, tmp_path):
        """The report is written for an interrupted run: it holds what failed."""
        dl = _make_downloader(tmp_path / "out")
        real = dl.download_file
        seen = {"failed": False}

        # The first image fails; the second one is interrupted, so the
        # interrupt lands after the failure rather than on it.
        page = (f'<html><body><img src="{SITE}/gone.png"><img src="{SITE}/slow.png"></body></html>').encode()
        dl.session = _Wayback({SITE + "/": page, SITE + "/slow.png": PNG})

        def interrupt_later(url):
            if url == SITE + "/slow.png":
                raise KeyboardInterrupt
            if url == SITE + "/gone.png":
                seen["failed"] = True
            return real(url)

        dl.download_file = interrupt_later
        with pytest.raises(KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            dl.download()

        assert seen["failed"]
        report = _report(tmp_path / "out")
        assert report["failed"] == 1
        assert report["failures"][0]["url"] == SITE + "/gone.png"
        assert not list((tmp_path / "out").rglob("*.part"))

    def test_a_resumed_interrupted_run_writes_the_report(self, tmp_path):
        dl = _make_downloader(tmp_path / "out")
        dl.session = _Wayback({SITE + "/": HOME, SITE + "/logo.png": PNG})

        real = dl.download_file

        def interrupt(url):
            if url == SITE + "/logo.png":
                raise KeyboardInterrupt
            return real(url)

        dl.download_file = interrupt
        with pytest.raises(KeyboardInterrupt), contextlib.redirect_stdout(io.StringIO()):
            dl.download()

        dl = _make_downloader(tmp_path / "out")
        dl.session = _Wayback({SITE + "/": HOME, SITE + "/logo.png": PNG})
        with contextlib.redirect_stdout(io.StringIO()):
            dl.download()
        assert _report(tmp_path / "out")["failed"] == 0


class TestRefusals:
    def test_urls_the_next_run_retries_are_not_left_in_the_report(self, tmp_path):
        """Refused URLs go back to the queue, so the report drops them too."""
        import requests

        links = "".join(f'<a href="/p{n}.html">p{n}</a>' for n in range(10))
        start = f"<!DOCTYPE html><html><body>{links}</body></html>".encode()
        output_dir = tmp_path / "out"
        dl = _make_downloader(output_dir)

        def handler(url, kwargs):
            if url.endswith("/" + SITE + "/"):
                return _Response(200, start)
            raise requests.exceptions.ConnectionError("reset")

        dl.session = _Wayback({})
        dl.session.get = lambda url, **kwargs: handler(url, kwargs)
        with pytest.raises(RuntimeError, match="refused 5 requests in a row"):
            with contextlib.redirect_stdout(io.StringIO()):
                dl.download()

        # The refused files are queued for the next run: not in the summary,
        # not in the report.
        report = _report(output_dir)
        assert report["failed"] == 0
        state = json.loads((output_dir / WaybackDownloader.STATE_FILE).read_text(encoding="utf-8"))
        refused = state["queue"][:5]
        assert all(u.startswith(SITE + "/p") for u in refused)
        assert state["failed_urls"] == []


class TestReportShape:
    def test_the_report_is_json_with_the_contracted_fields(self, tmp_path):
        _, output_dir, _ = _run(tmp_path, {SITE + "/": HOME})
        report = _report(output_dir)
        assert set(report) == {"generated_by", "wayback_url", "start_url", "failed", "failures"}
        fields = {"url", "local_path", "category", "attempts", "tried_other_timestamps"}
        assert all(set(entry) == fields for entry in report["failures"])
        assert all(entry["category"] in WaybackDownloader.FAILURE_CATEGORIES for entry in report["failures"])

    def test_a_file_that_is_saved_from_the_cdn_is_not_reported(self, tmp_path):
        """A fallback that saves the file means it is not missing."""
        css = '<html><head><link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto"></head></html>'

        def refused(url):
            raise ConnectionError("Wayback is down")

        _, output_dir, out = _run(
            tmp_path,
            {
                SITE + "/": css.encode(),
                "https://fonts.googleapis.com/css?family=Roboto": b"body{color:red}",
            },
        )
        report = _report(output_dir)
        # The stylesheet came from the CDN, so nothing is reported for it.
        assert all("fonts.googleapis.com" not in e["url"] for e in report["failures"])
        assert "Files failed: 0" in out

    def test_an_archived_file_cannot_overwrite_the_report(self, tmp_path):
        """A URL that maps to the report's name is refused, like the state file."""
        output_dir = tmp_path / "out"
        dl = _make_downloader(output_dir)
        page = f'<html><body><a href="{SITE}/{REPORT}">r</a></body></html>'.encode()
        dl.session = _Wayback({SITE + "/": page, SITE + "/" + REPORT: b"{}"})
        with contextlib.redirect_stdout(io.StringIO()):
            dl.download()

        report = _report(output_dir)
        entry = next(e for e in report["failures"] if e["url"].endswith("/" + REPORT))
        assert entry["category"] == "unsafe_path"
        assert entry["local_path"] == REPORT
        # The report itself is the downloader's, not the archived b"{}".
        assert report["generated_by"] == "wayback-archive"
