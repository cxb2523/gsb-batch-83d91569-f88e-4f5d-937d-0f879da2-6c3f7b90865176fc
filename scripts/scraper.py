#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Download Cricket Data.

Scrapes the espncricinfo match search pages, follows the match links found on
each page and stores every match page as a single HTML file in an output
directory.

The scrape is resumable and auditable:

* pagination range, per-page delay and output directory are configurable;
* every request has a timeout and a finite number of retries, and a page that
  keeps failing is recorded (page number + reason) without aborting the run;
* match URLs are de-duplicated, non-empty files already on disk are skipped,
  and failed match downloads are recorded;
* a machine-readable JSON manifest is written at the end of the run (and on
  Ctrl+C) describing every page, every duplicate and every failure together
  with summary counts.
"""

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urldefrag, urlsplit
from urllib.request import Request, urlopen

DEFAULT_SEARCH_URL = (
    "http://search.espncricinfo.com/ci/content/match/search.html"
)
DEFAULT_BASE_URL = "http://www.espncricinfo.com"
DEFAULT_OUTPUT_DIR = "espncricinfo-fc"
DEFAULT_SEARCH_TERM = "first class"
DEFAULT_START_PAGE = 0
DEFAULT_END_PAGE = 6018
DEFAULT_SLEEP_SECONDS = 1.0
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF = 2.0
MANIFEST_FILENAME = "manifest.json"
USER_AGENT = "Mozilla/5.0 (compatible; cricket-scraper/2.0)"

PAGE_STATUS_SUCCESS = "success"
PAGE_STATUS_SUCCESS_AFTER_RETRY = "success_after_retry"
PAGE_STATUS_FAILED = "failed"


class MatchLinkExtractor(HTMLParser):
    """Collect hrefs of <a class="srchPlyrNmTxt"> match links."""

    def __init__(self):
        HTMLParser.__init__(self)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        href = attributes.get("href")
        if "srchPlyrNmTxt" in classes and href:
            self.links.append(href)


def build_search_url(search_url, search_term, page):
    query = urlencode({"search": search_term, "all": 1, "page": page})
    return "{0}?{1}".format(search_url, query)


def fetch(url, timeout, max_attempts, retry_backoff):
    """Fetch a URL with timeout and finite retries.

    Returns a tuple ``(content, attempts, error)``: on success ``content`` is
    the response body (non-empty bytes), ``attempts`` the number of attempts
    used and ``error`` is ``None``; on final failure ``content`` is ``None``
    and ``error`` describes the last failure reason.
    """
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                content = response.read()
            if content:
                return content, attempt, None
            last_error = "empty response body"
        except HTTPError as exc:
            last_error = "HTTP {0}: {1}".format(exc.code, exc.reason)
        except (URLError, socket.timeout, TimeoutError, OSError) as exc:
            last_error = "{0}: {1}".format(type(exc).__name__, exc)
        if attempt < max_attempts:
            time.sleep(retry_backoff * attempt)
    return None, max_attempts, last_error


def normalize_url(url):
    """Drop fragments so the same page is never counted twice."""
    return urldefrag(url)[0]


def filename_for_url(url):
    """Return the basename of the URL path, or ``None`` if there is none."""
    path = urlsplit(url).path
    name = os.path.basename(path)
    return name or None


def atomic_write(path, content):
    """Write via a temp file so a partial download is never seen as complete."""
    temporary_path = path + ".part"
    with open(temporary_path, "wb") as handle:
        handle.write(content)
    os.replace(temporary_path, path)


def extract_match_links(content):
    parser = MatchLinkExtractor()
    parser.feed(content.decode("utf-8", errors="replace"))
    parser.close()
    return parser.links


def load_previous_manifest(manifest_path):
    try:
        with open(manifest_path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def previously_completed_pages(manifest):
    """Pages that fully succeeded in a previous run and can be skipped.

    A page is only fully complete when its search page was fetched and none of
    its match downloads failed.
    """
    if not manifest:
        return {}
    completed = {}
    pages_with_failures = {
        item.get("page") for item in manifest.get("download_failures", [])
    }
    for entry in manifest.get("pages", []):
        page = entry.get("page")
        if (
            page is not None
            and entry.get("status")
            in (PAGE_STATUS_SUCCESS, PAGE_STATUS_SUCCESS_AFTER_RETRY)
            and page not in pages_with_failures
        ):
            completed[page] = entry
    return completed


def write_manifest(manifest_path, manifest):
    directory = os.path.dirname(os.path.abspath(manifest_path))
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    temporary_path = manifest_path + ".part"
    with open(temporary_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary_path, manifest_path)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Download first class cricket match pages from "
        "espncricinfo."
    )
    parser.add_argument(
        "--start-page",
        type=int,
        default=DEFAULT_START_PAGE,
        help="first search page to fetch (default: %(default)s)",
    )
    parser.add_argument(
        "--end-page",
        type=int,
        default=DEFAULT_END_PAGE,
        help="last search page to fetch, inclusive (default: %(default)s)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="seconds to wait between search pages (default: %(default)s)",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help="directory for downloaded match HTML files "
        "(default: %(default)s)",
    )
    parser.add_argument(
        "--search",
        default=DEFAULT_SEARCH_TERM,
        help="match search term (default: %(default)s)",
    )
    parser.add_argument(
        "--search-url",
        default=DEFAULT_SEARCH_URL,
        help="search endpoint (default: %(default)s)",
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="base URL prefixed to relative match links (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=DEFAULT_MAX_ATTEMPTS,
        help="maximum attempts per request (default: %(default)s)",
    )
    parser.add_argument(
        "--retry-backoff",
        type=float,
        default=DEFAULT_RETRY_BACKOFF,
        help="base seconds to wait before retrying; the wait grows linearly "
        "with the attempt number (default: %(default)s)",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help="path of the JSON run manifest "
        "(default: <output-dir>/{0})".format(MANIFEST_FILENAME),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="do not skip pages that fully succeeded in a previous run",
    )
    return parser.parse_args(argv)


def run(args):
    if args.start_page > args.end_page:
        raise ValueError(
            "start-page ({0}) must not be greater than end-page ({1})".format(
                args.start_page, args.end_page
            )
        )
    if args.max_attempts < 1:
        raise ValueError("max-attempts must be at least 1")

    output_dir = args.output_dir
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    manifest_path = args.manifest or os.path.join(
        output_dir, MANIFEST_FILENAME
    )

    previous_manifest = (
        None if args.no_resume else load_previous_manifest(manifest_path)
    )
    completed_pages = previously_completed_pages(previous_manifest)

    manifest = {
        "run": {
            "started_at": datetime.now().isoformat(),
            "finished_at": None,
            "interrupted": False,
            "search_url": args.search_url,
            "base_url": args.base_url,
            "search_term": args.search,
            "start_page": args.start_page,
            "end_page": args.end_page,
            "sleep_seconds": args.sleep,
            "timeout_seconds": args.timeout,
            "max_attempts": args.max_attempts,
            "retry_backoff": args.retry_backoff,
            "output_dir": output_dir,
            "resumed_from": os.path.abspath(manifest_path)
            if previous_manifest
            else None,
        },
        "pages": [],
        "duplicates": [],
        "skipped_existing": [],
        "download_failures": [],
        "summary": {},
    }

    seen_urls = set()
    downloaded = 0
    interrupted = False

    try:
        for page in range(args.start_page, args.end_page + 1):
            if page in completed_pages:
                resumed_entry = dict(completed_pages[page])
                resumed_entry["resumed"] = True
                manifest["pages"].append(resumed_entry)
                print(
                    "page {0}: resumed, skipped (complete in previous run)".format(
                        page
                    )
                )
                continue

            search_url = build_search_url(
                args.search_url, args.search, page
            )
            print("page {0}: fetching {1}".format(page, search_url))
            content, attempts, error = fetch(
                search_url,
                args.timeout,
                args.max_attempts,
                args.retry_backoff,
            )
            if error is not None:
                manifest["pages"].append(
                    {
                        "page": page,
                        "url": search_url,
                        "status": PAGE_STATUS_FAILED,
                        "attempts": attempts,
                        "error": error,
                        "match_links_found": 0,
                    }
                )
                print(
                    "page {0}: FAILED after {1} attempt(s): {2}".format(
                        page, attempts, error
                    )
                )
                continue

            try:
                links = extract_match_links(content)
            except Exception as exc:  # parser must never abort the run
                manifest["pages"].append(
                    {
                        "page": page,
                        "url": search_url,
                        "status": PAGE_STATUS_FAILED,
                        "attempts": attempts,
                        "error": "parse error: {0}: {1}".format(
                            type(exc).__name__, exc
                        ),
                        "match_links_found": 0,
                    }
                )
                print(
                    "page {0}: FAILED while parsing: {1}".format(page, exc)
                )
                continue

            page_entry = {
                "page": page,
                "url": search_url,
                "status": PAGE_STATUS_SUCCESS
                if attempts == 1
                else PAGE_STATUS_SUCCESS_AFTER_RETRY,
                "attempts": attempts,
                "error": None,
                "match_links_found": len(links),
            }
            print(
                "page {0}: {1} ({2} match link(s))".format(
                    page, page_entry["status"], len(links)
                )
            )

            for href in links:
                match_url = normalize_url(urljoin(args.base_url, href))
                if match_url in seen_urls:
                    manifest["duplicates"].append(
                        {"page": page, "url": match_url}
                    )
                    print(
                        "  duplicate skipped: {0} (page {1})".format(
                            match_url, page
                        )
                    )
                    continue

                filename = filename_for_url(match_url)
                if filename is None:
                    manifest["download_failures"].append(
                        {
                            "page": page,
                            "url": match_url,
                            "filename": None,
                            "error": "could not derive a filename from URL",
                        }
                    )
                    print(
                        "  download failed: {0}: no filename".format(
                            match_url
                        )
                    )
                    continue

                destination = os.path.join(output_dir, filename)
                if (
                    os.path.isfile(destination)
                    and os.path.getsize(destination) > 0
                ):
                    seen_urls.add(match_url)
                    manifest["skipped_existing"].append(
                        {
                            "page": page,
                            "url": match_url,
                            "filename": filename,
                        }
                    )
                    print(
                        "  already downloaded, skipped: {0}".format(filename)
                    )
                    continue

                match_content, match_attempts, match_error = fetch(
                    match_url,
                    args.timeout,
                    args.max_attempts,
                    args.retry_backoff,
                )
                if match_error is not None:
                    manifest["download_failures"].append(
                        {
                            "page": page,
                            "url": match_url,
                            "filename": filename,
                            "attempts": match_attempts,
                            "error": match_error,
                        }
                    )
                    print(
                        "  download failed: {0}: {1}".format(
                            filename, match_error
                        )
                    )
                    continue

                atomic_write(destination, match_content)
                seen_urls.add(match_url)
                downloaded += 1
                print("  downloaded: {0}".format(filename))

            manifest["pages"].append(page_entry)
            if args.sleep > 0:
                time.sleep(args.sleep)
    except KeyboardInterrupt:
        interrupted = True
        manifest["run"]["interrupted"] = True
        print("\ninterrupted; writing manifest with partial results ...")
    finally:
        pages = manifest["pages"]
        manifest["summary"] = {
            "pages_total": len(pages),
            "pages_requested": args.end_page - args.start_page + 1,
            "pages_success": sum(
                1 for entry in pages if entry.get("status") ==
                PAGE_STATUS_SUCCESS and not entry.get("resumed")
            ),
            "pages_success_after_retry": sum(
                1
                for entry in pages
                if entry.get("status") == PAGE_STATUS_SUCCESS_AFTER_RETRY
                and not entry.get("resumed")
            ),
            "pages_resumed": sum(
                1 for entry in pages if entry.get("resumed")
            ),
            "pages_failed": sum(
                1
                for entry in pages
                if entry.get("status") == PAGE_STATUS_FAILED
            ),
            "match_links_found": sum(
                entry.get("match_links_found", 0) for entry in pages
            ),
            "unique_match_links": len(seen_urls),
            "duplicates_skipped": len(manifest["duplicates"]),
            "match_files_downloaded": downloaded,
            "match_files_skipped_existing": len(
                manifest["skipped_existing"]
            ),
            "match_download_failures": len(manifest["download_failures"]),
        }
        manifest["run"]["finished_at"] = datetime.now().isoformat()
        write_manifest(manifest_path, manifest)
        print("manifest written to {0}".format(manifest_path))
        print("summary: {0}".format(json.dumps(manifest["summary"])))

    return 130 if interrupted else 0


def main(argv=None):
    args = parse_args(argv)
    try:
        return run(args)
    except ValueError as exc:
        print("error: {0}".format(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
