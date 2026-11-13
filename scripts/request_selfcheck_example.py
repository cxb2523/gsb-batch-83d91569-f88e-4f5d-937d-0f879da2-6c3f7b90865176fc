#!/usr/bin/env python3
"""Offline demo for :mod:`request_selfcheck` — no network access anywhere.

Run it directly:

    python scripts/request_selfcheck_example.py
    python -I scripts/request_selfcheck_example.py

It builds two synthetic request descriptions by hand:

1. a Chrome-style HTTP/2 navigation request that passes every rule;
2. a stock-HTTP-library-style HTTP/1.1 request that fails several rules at once.

Both the expected ``sec-ch-ua`` and the request data are generated locally; the
script never opens a socket.
"""
import sys
from pathlib import Path

# Allow running both as ``python scripts/request_selfcheck_example.py`` and via
# ``python -m`` style invocation from a checkout where scripts/ is on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_selfcheck import (  # noqa: E402
    RequestDescription,
    check_request,
    format_report,
)
from sec_ch_ua import sec_ch_ua as compute_sec_ch_ua  # noqa: E402

CHROME_VERSION = "143"
WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)


def build_passing_request() -> RequestDescription:
    """A Chrome-on-HTTP/2 navigation request in real on-wire order."""
    return RequestDescription(
        http_version="HTTP/2",
        headers=[
            (":method", "GET"),
            (":authority", "example.com"),
            (":scheme", "https"),
            (":path", "/products"),
            ("sec-ch-ua", compute_sec_ch_ua(CHROME_VERSION)),
            ("sec-ch-ua-mobile", "?0"),
            ("sec-ch-ua-platform", '"Windows"'),
            ("upgrade-insecure-requests", "1"),
            ("user-agent", WINDOWS_UA),
            (
                "accept",
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8",
            ),
            ("sec-fetch-site", "none"),
            ("sec-fetch-mode", "navigate"),
            ("sec-fetch-user", "?1"),
            ("sec-fetch-dest", "document"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
            ("accept-language", "en-US,en;q=0.9"),
            ("cookie", "session=abc123"),
            ("priority", "u=0, i"),
        ],
        user_agent=WINDOWS_UA,
        accepted_ch=None,  # only the three low-entropy hints are sent
    )


def build_failing_request() -> RequestDescription:
    """A hand-written HTTP/1.1 request carrying the classic library tells.

    Deliberate mistakes: Host not first, alphabetical header order, manual
    content-length, DevTools no-cache pair, incomplete accept-encoding, a stale
    sec-ch-ua from another Chrome version, an unquoted platform hint, the same
    cookie name with two values, and an unsolicited high-entropy hint.
    """
    return RequestDescription(
        http_version="HTTP/1.1",
        headers=[
            ("Accept", "application/json"),
            ("Accept-Encoding", "gzip, deflate"),
            ("Cache-Control", "no-cache"),
            ("Content-Length", "42"),
            ("Cookie", "sid=abc; sid=xyz"),
            ("Host", "api.example.com"),
            ("Pragma", "no-cache"),
            # GREASE value of Chrome 108 with the numbers bumped — impossible combo
            ("sec-ch-ua", '"Not?A_Brand";v="8", "Chromium";v="143", "Google Chrome";v="143"'),
            ("sec-ch-ua-arch", '"x86"'),
            ("sec-ch-ua-platform", "Windows"),
            ("User-Agent", WINDOWS_UA),
        ],
        user_agent=WINDOWS_UA,
        accepted_ch=None,  # nothing was ever advertised via Accept-CH
    )


def main() -> int:
    failures = 0

    print("=" * 78)
    print("CASE 1 — Chrome-style HTTP/2 navigation request (expected: PASS)")
    print("=" * 78)
    good_report = check_request(build_passing_request())
    print(format_report(good_report))
    if not good_report.passed:
        failures += 1
        print("\nUNEXPECTED: the passing fixture reported failures.")

    print("\n" + "=" * 78)
    print("CASE 2 — hand-written HTTP/1.1 library request (expected: FAIL)")
    print("=" * 78)
    bad_report = check_request(build_failing_request())
    print(format_report(bad_report))
    if bad_report.passed:
        failures += 1
        print("\nUNEXPECTED: the failing fixture passed.")

    print("\n" + "-" * 78)
    if failures:
        print(f"DEMO FAILED — {failures} expectation(s) not met")
        return 1
    print("DEMO OK — one request passed, the other exposed the planted defects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
