"""Automated tests for scripts/request_selfcheck.py.

Runs with the standard library only:

    python -m unittest discover -s tests -v
    python tests/test_request_selfcheck.py

The module under test lives in ../scripts relative to this file; that directory
is inserted on sys.path so the suite works from any checkout location.
"""
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

from request_selfcheck import (  # noqa: E402
    HIGH_ENTROPY_HINTS,
    CheckReport,
    RequestDescription,
    check_request,
    format_report,
)
from sec_ch_ua import sec_ch_ua as compute_sec_ch_ua  # noqa: E402

UA_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
UA_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)


def h2_chrome_headers(**overrides):
    """A known-good Chrome HTTP/2 navigation request; override entries per test."""
    headers = list(overrides.pop("headers", None) or [
        (":method", "GET"),
        (":authority", "example.com"),
        (":scheme", "https"),
        (":path", "/"),
        ("sec-ch-ua", compute_sec_ch_ua("143")),
        ("sec-ch-ua-mobile", "?0"),
        ("sec-ch-ua-platform", '"Windows"'),
        ("upgrade-insecure-requests", "1"),
        ("user-agent", UA_WINDOWS),
        ("accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("sec-fetch-site", "none"),
        ("sec-fetch-mode", "navigate"),
        ("sec-fetch-user", "?1"),
        ("sec-fetch-dest", "document"),
        ("accept-encoding", "gzip, deflate, br, zstd"),
        ("accept-language", "en-US,en;q=0.9"),
        ("cookie", "session=abc"),
        ("priority", "u=0, i"),
    ])
    return RequestDescription(
        http_version=overrides.pop("http_version", "HTTP/2"),
        headers=headers,
        user_agent=overrides.pop("user_agent", UA_WINDOWS),
        accepted_ch=overrides.pop("accepted_ch", None),
    )


def h1_chrome_headers():
    # Realistic Chrome HTTP/1.1 order: Host first, then the same non-alphabetical
    # ordering Chrome uses (hints -> UA -> accept -> sec-fetch -> ... -> cookie).
    return RequestDescription(
        http_version="HTTP/1.1",
        headers=[
            ("Host", "example.com"),
            ("sec-ch-ua", compute_sec_ch_ua("143")),
            ("sec-ch-ua-mobile", "?0"),
            ("sec-ch-ua-platform", '"Windows"'),
            ("User-Agent", UA_WINDOWS),
            ("Accept", "application/json"),
            ("sec-fetch-site", "same-origin"),
            ("sec-fetch-mode", "cors"),
            ("sec-fetch-dest", "empty"),
            ("Accept-Encoding", "gzip, deflate, br, zstd"),
            ("Accept-Language", "en-US,en;q=0.9"),
            ("Cookie", "a=1; b=2"),
        ],
        user_agent=UA_WINDOWS,
    )


class PassingFixturesTests(unittest.TestCase):
    """Normal paths: realistic Chrome requests must pass end to end."""

    def test_h2_navigation_request_passes(self):
        report = check_request(h2_chrome_headers())
        self.assertTrue(
            report.passed,
            msg="\n" + format_report(report),
        )

    def test_h1_request_passes(self):
        report = check_request(h1_chrome_headers())
        self.assertTrue(report.passed, msg="\n" + format_report(report))

    def test_report_structure_and_overall_flag(self):
        report = check_request(h2_chrome_headers())
        self.assertIsInstance(report, CheckReport)
        self.assertTrue(report.results)
        for result in report.results:
            self.assertTrue(hasattr(result, "rule_id"))
            self.assertIsInstance(result.passed, bool)
            self.assertIsInstance(result.message, str)
        self.assertEqual(report.failures, [])
        d = report.as_dict()
        self.assertTrue(d["passed"])
        self.assertEqual(len(d["results"]), len(report.results))
        self.assertIn("rule_id", d["results"][0])

    def test_h2_without_cookies_still_passes_when_cookie_listed_empty(self):
        # Chrome lists an empty cookie header before priority on cookieless requests.
        headers = [
            (":method", "GET"),
            (":authority", "example.com"),
            (":scheme", "https"),
            (":path", "/"),
            ("sec-ch-ua", compute_sec_ch_ua("143")),
            ("sec-ch-ua-mobile", "?0"),
            ("sec-ch-ua-platform", '"Windows"'),
            ("user-agent", UA_WINDOWS),
            ("accept", "*/*"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
            ("accept-language", "en-US,en;q=0.9"),
            ("cookie", ""),
            ("priority", "u=1, i"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertTrue(report.passed, msg="\n" + format_report(report))

    def test_no_priority_header_is_fine(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "priority"]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertTrue(report.passed, msg="\n" + format_report(report))
        self.assertTrue(report.get("PRIORITY_COOKIE_ADJACENCY").passed)


class HttpVersionAndOrderTests(unittest.TestCase):
    """G1/G2/G3: version aliases, pseudo-header order, Host position, case."""

    def test_http_version_aliases(self):
        for alias in ("h2", "2", "HTTP/2", "http2"):
            report = check_request(h2_chrome_headers(http_version=alias))
            self.assertTrue(report.get("HTTP_VERSION").passed, alias)
            self.assertEqual(report.get("HTTP_VERSION").message, "recognized as H2")
        h1_headers = h1_chrome_headers().headers
        for alias in ("h1", "1.1", "HTTP/1.1"):
            report = check_request(RequestDescription(alias, h1_headers, UA_WINDOWS))
            self.assertTrue(report.get("HTTP_VERSION").passed, alias)
            self.assertEqual(report.get("HTTP_VERSION").message, "recognized as H1")

    def test_h2_uppercase_header_name_fails(self):
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":scheme", "https"),
            (":path", "/"), ("User-Agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("H2_HEADER_LOWERCASE").passed)

    def test_h2_wrong_pseudo_order_fails(self):
        headers = [
            (":method", "GET"), (":scheme", "https"), (":authority", "e.com"),
            (":path", "/"), ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("H2_PSEUDO_HEADER_ORDER").passed)

    def test_h2_missing_pseudo_header_fails(self):
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":path", "/"),
            ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("H2_PSEUDO_HEADER_ORDER")
        self.assertFalse(result.passed)
        self.assertIn(":scheme", result.message)

    def test_h2_pseudo_after_regular_header_fails(self):
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":scheme", "https"),
            ("user-agent", UA_WINDOWS), (":path", "/"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("H2_PSEUDO_HEADER_POSITION").passed)

    def test_h2_host_header_rejected(self):
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":scheme", "https"),
            (":path", "/"), ("host", "e.com"), ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("H2_NO_HOST_HEADER").passed)

    def test_h2_missing_authority_fails(self):
        headers = [
            (":method", "GET"), (":scheme", "https"), (":path", "/"),
            ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("H2_NO_HOST_HEADER").passed)

    def test_h1_host_missing_or_not_first_fails(self):
        headers = [
            ("User-Agent", UA_WINDOWS), ("Host", "e.com"),
            ("Accept-Encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h1", headers, UA_WINDOWS))
        self.assertFalse(report.get("H1_HOST_FIRST").passed)

        report_missing = check_request(
            RequestDescription("h1", [("User-Agent", UA_WINDOWS)], UA_WINDOWS)
        )
        self.assertFalse(report_missing.get("H1_HOST_FIRST").passed)

    def test_h1_all_lowercase_alpha_header_flagged(self):
        headers = [
            ("Host", "e.com"), ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h1", headers, UA_WINDOWS))
        self.assertFalse(report.get("H1_HEADER_TITLE_CASE").passed)

    def test_alphabetical_order_detected(self):
        headers = [
            ("Host", "e.com"),
            ("accept", "*/*"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
            ("cookie", "a=1"),
            ("user-agent", UA_WINDOWS),
        ]
        # Regular headers (everything after Host, which Chrome pins first on h1)
        # are strictly sorted: accept < accept-encoding < cookie < user-agent.
        regular = [n.lower() for n, _ in headers[1:]]
        self.assertEqual(regular, sorted(regular))
        report = check_request(RequestDescription("h1", headers, UA_WINDOWS))
        self.assertFalse(report.get("NO_ALPHABETICAL_ORDER").passed)

    def test_alphabetical_check_skipped_for_tiny_requests(self):
        # Boundary: under 3 regular headers a sorted order cannot be distinguished
        # from a real one, so the rule must pass with an explanatory note.
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":scheme", "https"),
            (":path", "/"), ("accept", "*/*"),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("NO_ALPHABETICAL_ORDER")
        self.assertTrue(result.passed)
        self.assertIn("not evaluated", result.message)


class PriorityAndCookieTests(unittest.TestCase):
    """G4/G6 and the cookie-jar / transport rules."""

    def test_priority_without_cookie_fails(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("PRIORITY_COOKIE_ADJACENCY").passed)

    def test_cookie_not_immediately_before_priority_fails(self):
        headers = [
            (":method", "GET"), (":authority", "e.com"), (":scheme", "https"),
            (":path", "/"),
            ("cookie", "a=1"),
            ("accept-language", "en-US,en;q=0.9"),
            ("priority", "u=1, i"),
            ("user-agent", UA_WINDOWS),
            ("accept-encoding", "gzip, deflate, br, zstd"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("PRIORITY_COOKIE_ADJACENCY").passed)

    def test_priority_not_last_on_h2_fails(self):
        headers = [h for h in h2_chrome_headers().headers]
        headers.append(("accept-language", "en-US,en;q=0.9"))  # after priority
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("PRIORITY_LAST").passed)

    def test_priority_last_rule_is_h2_only(self):
        headers = [
            ("Host", "e.com"),
            ("User-Agent", UA_WINDOWS),
            ("Cookie", "a=1"),
            ("Priority", "u=1, i"),
            ("Accept", "*/*"),
            ("Accept-Encoding", "gzip, deflate, br, zstd"),
            ("sec-ch-ua", compute_sec_ch_ua("143")),
            ("sec-ch-ua-platform", '"Windows"'),
        ]
        report = check_request(RequestDescription("h1", headers, UA_WINDOWS))
        self.assertTrue(report.get("PRIORITY_LAST").passed)
        self.assertTrue(report.get("PRIORITY_COOKIE_ADJACENCY").passed)

    def test_duplicate_cookie_name_different_values_fails(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        headers.insert(len(headers) - 1, ("cookie", "sid=abc"))
        headers.insert(len(headers) - 1, ("cookie", "sid=xyz"))
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("COOKIE_NO_DUPLICATE_NAMES")
        self.assertFalse(result.passed)
        self.assertIn("sid", result.message)

    def test_repeated_cookie_same_value_is_allowed(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        headers.insert(len(headers) - 1, ("cookie", "sid=abc"))
        headers.insert(len(headers) - 1, ("cookie", "sid=abc"))
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertTrue(report.get("COOKIE_NO_DUPLICATE_NAMES").passed)

    def test_malformed_cookie_fragment_fails_without_raising(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        headers.insert(len(headers) - 1, ("cookie", "good=1; not-a-cookie; =empty"))
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("COOKIE_WELL_FORMED")
        self.assertFalse(result.passed)
        self.assertIn("2", result.message)

    def test_h2_multiple_cookie_headers_allowed_but_coalesced_rejected(self):
        good = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        good.insert(len(good) - 1, ("cookie", "a=1"))
        good.insert(len(good) - 1, ("cookie", "b=2"))
        report = check_request(RequestDescription("h2", good, UA_WINDOWS))
        self.assertTrue(report.get("COOKIE_TRANSPORT_SHAPE").passed)

        bad = [h for h in h2_chrome_headers().headers if h[0] != "cookie"]
        bad.insert(len(bad) - 1, ("cookie", "a=1; b=2"))
        report = check_request(RequestDescription("h2", bad, UA_WINDOWS))
        self.assertFalse(report.get("COOKIE_TRANSPORT_SHAPE").passed)

    def test_h1_multiple_cookie_headers_rejected(self):
        headers = [
            ("Host", "e.com"),
            ("Cookie", "a=1"),
            ("Cookie", "b=2"),
            ("User-Agent", UA_WINDOWS),
            ("Accept-Encoding", "gzip, deflate, br, zstd"),
            ("sec-ch-ua", compute_sec_ch_ua("143")),
            ("sec-ch-ua-platform", '"Windows"'),
        ]
        report = check_request(RequestDescription("h1", headers, UA_WINDOWS))
        self.assertFalse(report.get("COOKIE_TRANSPORT_SHAPE").passed)


class HeaderValueRulesTests(unittest.TestCase):
    """G5/G8/G9/G10 and the client-hint rules."""

    def test_manual_content_length_fails(self):
        headers = h2_chrome_headers().headers + [("content-length", "128")]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("NO_MANUAL_CONTENT_LENGTH").passed)

    def test_disable_cache_pair_fails_but_single_header_passes(self):
        headers = h2_chrome_headers().headers + [
            ("cache-control", "no-cache"),
            ("pragma", "no-cache"),
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("NO_DISABLE_CACHE_ARTIFACT").passed)

        headers_only_cc = h2_chrome_headers().headers + [("cache-control", "no-cache")]
        report = check_request(RequestDescription("h2", headers_only_cc, UA_WINDOWS))
        self.assertTrue(report.get("NO_DISABLE_CACHE_ARTIFACT").passed)

    def test_accept_encoding_missing_token_fails(self):
        headers = [
            (n, "gzip, deflate, br" if n == "accept-encoding" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("ACCEPT_ENCODING_CHROME")
        self.assertFalse(result.passed)
        self.assertIn("zstd", result.message)

    def test_accept_encoding_extra_tokens_allowed(self):
        headers = [
            (n, "gzip, deflate, br, zstd, identity" if n == "accept-encoding" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertTrue(report.get("ACCEPT_ENCODING_CHROME").passed)

    def test_missing_accept_encoding_fails(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "accept-encoding"]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("ACCEPT_ENCODING_CHROME").passed)

    def test_sec_ch_ua_exact_for_multiple_versions(self):
        for version, ua_fragment in (("108", "108.0.0.0"), ("143", "143.0.0.0")):
            ua = UA_WINDOWS.replace("143.0.0.0", ua_fragment)
            headers = [
                (n, compute_sec_ch_ua(version) if n == "sec-ch-ua" else v)
                for n, v in h2_chrome_headers().headers
            ]
            report = check_request(RequestDescription("h2", headers, ua))
            self.assertTrue(
                report.get("SEC_CH_UA_EXACT").passed,
                msg=f"version {version}\n" + format_report(report),
            )

    def test_stale_grease_value_fails_with_expected_in_message(self):
        # Chrome 108's grease brand carried into a 143 UA with bumped numbers.
        headers = [
            (
                n,
                '"Not?A_Brand";v="8", "Chromium";v="143", "Google Chrome";v="143"',
            )
            if n == "sec-ch-ua"
            else (n, v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("SEC_CH_UA_EXACT")
        self.assertFalse(result.passed)
        self.assertIn(compute_sec_ch_ua("143"), result.message)
        self.assertIn("actual:", result.message)

    def test_missing_sec_ch_ua_fails(self):
        headers = [h for h in h2_chrome_headers().headers if h[0] != "sec-ch-ua"]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("SEC_CH_UA_EXACT").passed)

    def test_platform_quoted_and_matching(self):
        mac_headers = [
            (n, '"macOS"' if n == "sec-ch-ua-platform" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", mac_headers, UA_MAC))
        self.assertTrue(report.get("SEC_CH_UA_PLATFORM").passed)

    def test_platform_unquoted_fails(self):
        headers = [
            (n, "Windows" if n == "sec-ch-ua-platform" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("SEC_CH_UA_PLATFORM").passed)

    def test_platform_os_mismatch_fails(self):
        headers = [
            (n, '"macOS"' if n == "sec-ch-ua-platform" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("SEC_CH_UA_PLATFORM")
        self.assertFalse(result.passed)
        self.assertIn("Windows", result.message)

    def test_high_entropy_hint_without_accept_ch_fails(self):
        headers = h2_chrome_headers().headers + [
            ("sec-ch-ua-full-version-list", compute_sec_ch_ua("143"))
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        result = report.get("ACCEPT_CH_GATING")
        self.assertFalse(result.passed)
        self.assertIn("sec-ch-ua-full-version-list", result.message)

    def test_high_entropy_hint_after_accept_ch_passes(self):
        headers = h2_chrome_headers().headers + [
            ("sec-ch-ua-arch", '"x86"'),
            ("sec-ch-ua-bitness", '"64"'),
        ]
        report = check_request(
            RequestDescription(
                "h2",
                headers,
                UA_WINDOWS,
                accepted_ch={"sec-ch-ua-arch", "sec-ch-ua-bitness"},
            )
        )
        self.assertTrue(report.get("ACCEPT_CH_GATING").passed)

    def test_all_gated_hints_are_documented_high_entropy_names(self):
        self.assertIn("sec-ch-ua-full-version-list", HIGH_ENTROPY_HINTS)
        for low_entropy in ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"):
            self.assertNotIn(low_entropy, HIGH_ENTROPY_HINTS)


class NegativeAndRobustnessTests(unittest.TestCase):
    """Bad input must produce failing CheckResults, never exceptions."""

    def test_unparseable_user_agent_does_not_raise(self):
        report = check_request(
            RequestDescription("h2", h2_chrome_headers().headers, "curl/8.0")
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.get("USER_AGENT_PARSE").passed)
        # Dependent checks degrade with an explanation instead of crashing.
        self.assertFalse(report.get("SEC_CH_UA_EXACT").passed)
        self.assertFalse(report.get("SEC_CH_UA_PLATFORM").passed)

    def test_empty_user_agent_does_not_raise(self):
        report = check_request(
            RequestDescription("h1", [("Host", "e.com")], "")
        )
        self.assertFalse(report.passed)
        self.assertFalse(report.get("USER_AGENT_PARSE").passed)

    def test_unknown_http_version_skips_version_specific_checks(self):
        report = check_request(
            RequestDescription("HTTP/3", [("Host", "e.com")], UA_WINDOWS)
        )
        self.assertFalse(report.get("HTTP_VERSION").passed)
        self.assertIsNone(report.get("H1_HOST_FIRST"))
        self.assertIsNone(report.get("H2_PSEUDO_HEADER_ORDER"))
        # Generic checks still run.
        self.assertIsNotNone(report.get("NO_MANUAL_CONTENT_LENGTH"))
        self.assertFalse(report.passed)

    def test_empty_and_none_headers_do_not_raise(self):
        report = check_request(RequestDescription("h2", [], UA_WINDOWS))
        self.assertFalse(report.passed)
        self.assertTrue(report.failures)

        report_none = check_request(RequestDescription("h2", None, UA_WINDOWS))
        self.assertFalse(report_none.passed)

    def test_missing_required_headers_all_reported(self):
        report = check_request(RequestDescription("h2", [("foo", "bar")], UA_WINDOWS))
        failed_ids = {r.rule_id for r in report.failures}
        for expected in (
            "H2_PSEUDO_HEADER_ORDER",
            "H2_NO_HOST_HEADER",
            "ACCEPT_ENCODING_CHROME",
            "SEC_CH_UA_EXACT",
            "SEC_CH_UA_PLATFORM",
            "USER_AGENT_HEADER_PRESENT",
        ):
            self.assertIn(expected, failed_ids)

    def test_user_agent_header_mismatch_fails(self):
        headers = [
            (n, "Mozilla/5.0 Chrome/120.0.0.0" if n == "user-agent" else v)
            for n, v in h2_chrome_headers().headers
        ]
        report = check_request(RequestDescription("h2", headers, UA_WINDOWS))
        self.assertFalse(report.get("USER_AGENT_HEADER_PRESENT").passed)

    def test_format_report_renders_overall_lines(self):
        good = format_report(check_request(h2_chrome_headers()))
        self.assertIn("OVERALL: PASS", good)
        self.assertIn("PASS", good)

        bad = format_report(
            check_request(RequestDescription("h2", [], UA_WINDOWS))
        )
        self.assertIn("OVERALL: FAIL", bad)
        self.assertIn("FAIL", bad)


if __name__ == "__main__":
    unittest.main(verbosity=2)
