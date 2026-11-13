#!/usr/bin/env python3
"""Reusable self-check for a captured or hand-written HTTP request.

The anti-bot checks (Akamai, DataDome, ...) most often fail not because of the
generated payload, but because the request itself does not look like real Chrome:
header order, cookie placement, client hints vs. the User-Agent version. This
module turns the manual eyeball comparison behind ``references/request-rules.md``
into a per-rule, machine-readable verdict.

It is an importable library, **not** a command-line sub-command. Pass a
:class:`RequestDescription` to :func:`check_request` and get back a
:class:`CheckReport` containing one :class:`CheckResult` per rule plus an overall
pass/fail flag. A runnable offline demo lives in
``scripts/request_selfcheck_example.py`` and the automated tests in
``tests/test_request_selfcheck.py``.

The exact ``sec-ch-ua`` value is computed by :mod:`sec_ch_ua`; the GREASE tables
live only there and are intentionally not duplicated.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set, Tuple

from sec_ch_ua import sec_ch_ua as compute_sec_ch_ua

__all__ = [
    "RequestDescription",
    "CheckResult",
    "CheckReport",
    "HIGH_ENTROPY_HINTS",
    "LOW_ENTROPY_HINTS",
    "check_request",
    "format_report",
]

# Client hints that the origin must opt into via an Accept-CH response header
# before Chrome will send them (see references/request-rules.md).
HIGH_ENTROPY_HINTS: frozenset = frozenset(
    {
        "sec-ch-ua-arch",
        "sec-ch-ua-full-version-list",
        "sec-ch-ua-model",
        "sec-ch-ua-platform-version",
        "sec-ch-ua-bitness",
        "sec-ch-ua-wow64",
        "sec-ch-ua-form-factors",
        "sec-ch-device-memory",
    }
)

# Sent by default without any Accept-CH declaration.
LOW_ENTROPY_HINTS: frozenset = frozenset(
    {"sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform"}
)

# Chrome's fixed HTTP/2 pseudo-header order (stable per browser).
_H2_PSEUDO_ORDER = (":method", ":authority", ":scheme", ":path")
_REQUIRED_ENCODINGS = ("gzip", "deflate", "br", "zstd")

# Mozilla/5.0 (Windows NT 10.0; Win64; x64) ... Chrome/143.0.0.0 Safari/537.36
_UA_RE = re.compile(
    r"(?P<os>Windows NT|Mac OS X|Linux|Android|iPhone OS|CrOS)[^)]*\)"
    r".*?Chrome/(?P<version>\d+)(?:\.\d+)*",
    re.IGNORECASE,
)


@dataclass
class RequestDescription:
    """Everything the checker needs to reason about one request.

    Attributes:
        http_version: ``"HTTP/2"`` / ``"h2"`` or ``"HTTP/1.1"`` / ``"h1"``
            (case-insensitive; ``2`` / ``"1.1"`` also accepted).
        headers: ``(name, value)`` pairs in the **real on-wire order**,
            including HTTP/2 pseudo-headers (``:method`` ...) first when
            applicable.
        user_agent: the User-Agent string. It is also expected to appear among
            ``headers``; the standalone field is what sec-ch-ua is validated
            against.
        accepted_ch: names of high-entropy hints the site has previously
            advertised via an ``Accept-CH`` response header. Hints outside this
            set are flagged as unsolicited.
    """

    http_version: str
    headers: List[Tuple[str, str]]
    user_agent: str = ""
    accepted_ch: Optional[Set[str]] = None


@dataclass
class CheckResult:
    """One rule verdict."""

    rule_id: str
    passed: bool
    message: str = ""  # populated when ``passed`` is False (may also hold an ok note)

    def as_dict(self) -> dict:
        return {"rule_id": self.rule_id, "passed": self.passed, "message": self.message}


@dataclass
class CheckReport:
    """All rule verdicts plus the overall conclusion."""

    results: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results)

    @property
    def failures(self) -> List[CheckResult]:
        return [r for r in self.results if not r.passed]

    def get(self, rule_id: str) -> Optional[CheckResult]:
        for result in self.results:
            if result.rule_id == rule_id:
                return result
        return None

    def as_dict(self) -> dict:
        return {
            "passed": self.passed,
            "results": [r.as_dict() for r in self.results],
        }


# --------------------------------------------------------------------------- #
# Parsing helpers — every parse failure becomes a CheckResult, never an raise.
# --------------------------------------------------------------------------- #
def _normalize_http_version(raw: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (normalized version, error). normalized is 'h2' or 'h1'."""
    if not raw or not str(raw).strip():
        return None, "HTTP version is missing or empty"
    token = str(raw).strip().lower().replace("_", "/")
    if token in ("2", "h2", "http/2", "http2"):
        return "h2", None
    if token in ("1.1", "h1", "http/1.1", "http1.1"):
        return "h1", None
    return None, f"unrecognized HTTP version {raw!r}; expected HTTP/2 or HTTP/1.1"


def _parse_user_agent(ua: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (chrome_major, platform, error) without raising on bad input."""
    if not ua or not ua.strip():
        return None, None, "User-Agent string is missing or empty"
    match = _UA_RE.search(ua)
    if not match:
        return None, None, (
            f"could not parse Chrome version and OS from User-Agent: {ua!r}"
        )
    os_token = match.group("os").lower()
    platform = {
        "windows nt": "Windows",
        "mac os x": "macOS",
        "linux": "Linux",
        "cros": "Chrome OS",
        "android": "Android",
        "iphone os": "iOS",
    }.get(os_token)
    if platform is None:  # pragma: no cover - regex already restricts the tokens
        return None, None, f"could not map User-Agent OS token {os_token!r} to a platform"
    return match.group("version"), platform, None


def _header_index(names: Sequence[str], name: str) -> Optional[int]:
    """Case-insensitive positional lookup of a header name."""
    wanted = name.lower()
    for i, current in enumerate(names):
        if current.lower() == wanted:
            return i
    return None


def _has_header(names: Sequence[str], name: str) -> bool:
    return _header_index(names, name) is not None


def _values_for(headers: Sequence[Tuple[str, str]], name: str) -> List[str]:
    wanted = name.lower()
    return [value for header_name, value in headers if header_name.lower() == wanted]


def _is_pseudo(name: str) -> bool:
    return name.startswith(":")


def _parse_cookies(headers: Sequence[Tuple[str, str]]) -> Tuple[dict, int]:
    """Return ({name: [values...]}, number of unparseable cookie fragments)."""
    jar: dict = {}
    malformed = 0
    for name, value in headers:
        if name.lower() != "cookie":
            continue
        for fragment in value.split(";"):
            fragment = fragment.strip()
            if not fragment:
                continue
            if "=" not in fragment:
                malformed += 1
                continue
            cookie_name, cookie_value = fragment.split("=", 1)
            cookie_name = cookie_name.strip()
            if not cookie_name:
                malformed += 1
                continue
            jar.setdefault(cookie_name, []).append(cookie_value.strip())
    return jar, malformed


# --------------------------------------------------------------------------- #
# Individual checks. Each returns one or more CheckResult and never raises.
# --------------------------------------------------------------------------- #
def _check_http_version(description: RequestDescription) -> Tuple[List[CheckResult], Optional[str]]:
    version, error = _normalize_http_version(description.http_version)
    if error:
        return [CheckResult("HTTP_VERSION", False, error)], None
    return [CheckResult("HTTP_VERSION", True, f"recognized as {version.upper()}")], version


def _check_h2_lowercase(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    bad = [n for n, _ in headers if not n.islower()]
    if bad:
        return CheckResult(
            "H2_HEADER_LOWERCASE",
            False,
            "HTTP/2 requires lowercase header names; found non-lowercase: "
            + ", ".join(repr(n) for n in bad),
        )
    return CheckResult("H2_HEADER_LOWERCASE", True)


def _check_h2_pseudo_order(headers: Sequence[Tuple[str, str]]) -> List[CheckResult]:
    names = [n for n, _ in headers]
    pseudo = [n for n in names if _is_pseudo(n)]
    results: List[CheckResult] = []

    missing = [p for p in _H2_PSEUDO_ORDER if p not in pseudo]
    if missing:
        results.append(
            CheckResult(
                "H2_PSEUDO_HEADER_ORDER",
                False,
                "missing required HTTP/2 pseudo-header(s): " + ", ".join(missing),
            )
        )
    else:
        observed = [p for p in pseudo if p in _H2_PSEUDO_ORDER]
        if observed != list(_H2_PSEUDO_ORDER):
            results.append(
                CheckResult(
                    "H2_PSEUDO_HEADER_ORDER",
                    False,
                    "pseudo-headers are not in Chrome order :method, :authority, "
                    f":scheme, :path; observed: {', '.join(observed)}",
                )
            )
        else:
            results.append(CheckResult("H2_PSEUDO_HEADER_ORDER", True))

    # All pseudo-headers must precede regular headers.
    first_regular = next((i for i, n in enumerate(names) if not _is_pseudo(n)), len(names))
    late_pseudo = [n for i, n in enumerate(names) if _is_pseudo(n) and i > first_regular]
    if late_pseudo:
        results.append(
            CheckResult(
                "H2_PSEUDO_HEADER_POSITION",
                False,
                "pseudo-header(s) appear after regular headers: " + ", ".join(late_pseudo),
            )
        )
    else:
        results.append(CheckResult("H2_PSEUDO_HEADER_POSITION", True))
    return results


def _check_h2_no_host(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    names = [n for n, _ in headers]
    if _has_header(names, "host"):
        return CheckResult(
            "H2_NO_HOST_HEADER",
            False,
            "HTTP/2 uses the :authority pseudo-header; a Host header must not be sent",
        )
    if not _has_header(names, ":authority"):
        return CheckResult(
            "H2_NO_HOST_HEADER",
            False,
            "neither Host header nor :authority pseudo-header present; :authority is "
            "the HTTP/2 replacement for Host",
        )
    return CheckResult("H2_NO_HOST_HEADER", True)


def _check_h1_host_first(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    names = [n for n, _ in headers]
    position = _header_index(names, "host")
    if position is None:
        return CheckResult(
            "H1_HOST_FIRST", False, "required Host header is missing on HTTP/1.1"
        )
    if position != 0:
        return CheckResult(
            "H1_HOST_FIRST",
            False,
            f"Host must be the first HTTP/1.1 header; found at position {position} "
            f"(after {names[position - 1]!r})",
        )
    return CheckResult("H1_HOST_FIRST", True)


def _check_h1_title_case(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    # Chrome Title-Cases conventional headers on HTTP/1.1, but headers whose
    # registered name is lowercase (the sec-ch-ua*/sec-fetch-* families) are
    # sent lowercase on every protocol version — only flag the former.
    bad = [
        n
        for n, _ in headers
        if not _is_pseudo(n)
        and not n.lower().startswith("sec-")
        and any(ch.isalpha() for ch in n)
        and n == n.lower()
    ]
    if bad:
        return CheckResult(
            "H1_HEADER_TITLE_CASE",
            False,
            "HTTP/1.1 headers are Title-Case in real Chrome; all-lowercase name(s): "
            + ", ".join(repr(n) for n in bad),
        )
    return CheckResult("H1_HEADER_TITLE_CASE", True)


def _check_not_alphabetical(headers: Sequence[Tuple[str, str]], version: str) -> CheckResult:
    # Pseudo-headers and single/dual-header requests cannot meaningfully be
    # "sorted", so only evaluate three or more regular headers. On HTTP/1.1
    # Chrome pins Host first regardless of order — exclude that pinned slot.
    regular = [
        (i, n)
        for i, (n, _) in enumerate(headers)
        if not _is_pseudo(n) and not (version == "h1" and i == 0 and n.lower() == "host")
    ]
    names = [n for _, n in regular]
    comparable = [n.lower() for n in names]
    if len(comparable) < 3:
        return CheckResult(
            "NO_ALPHABETICAL_ORDER",
            True,
            "not evaluated: fewer than 3 orderable headers, alphabetical sorting "
            "cannot be distinguished from a real order",
        )
    if comparable == sorted(comparable):
        return CheckResult(
            "NO_ALPHABETICAL_ORDER",
            False,
            "headers are in alphabetical order — the classic requests/axios tell: "
            + ", ".join(names),
        )
    return CheckResult("NO_ALPHABETICAL_ORDER", True)


def _check_priority_cookie(headers: Sequence[Tuple[str, str]], version: str) -> List[CheckResult]:
    names = [n for n, _ in headers]
    results: List[CheckResult] = []
    priority_pos = _header_index(names, "priority")
    cookie_pos = _header_index(names, "cookie")

    if priority_pos is None:
        results.append(
            CheckResult(
                "PRIORITY_COOKIE_ADJACENCY",
                True,
                "no priority header present; cookie-adjacency rule not applicable",
            )
        )
        return results

    if cookie_pos is None:
        results.append(
            CheckResult(
                "PRIORITY_COOKIE_ADJACENCY",
                False,
                "priority is present but there is no cookie header immediately before "
                "it; list cookie explicitly before priority even when the jar is empty "
                "(most clients auto-append cookie after priority)",
            )
        )
    elif cookie_pos != priority_pos - 1:
        results.append(
            CheckResult(
                "PRIORITY_COOKIE_ADJACENCY",
                False,
                f"cookie (position {cookie_pos}) must be immediately before priority "
                f"(position {priority_pos}); header in between is "
                f"{names[priority_pos - 1]!r}",
            )
        )
    else:
        results.append(CheckResult("PRIORITY_COOKIE_ADJACENCY", True))

    if version == "h2" and priority_pos != len(names) - 1:
        results.append(
            CheckResult(
                "PRIORITY_LAST",
                False,
                "on HTTP/2 Chrome sends priority last; header(s) follow it: "
                + ", ".join(names[priority_pos + 1 :]),
            )
        )
    else:
        results.append(
            CheckResult(
                "PRIORITY_LAST",
                True,
                "priority is last" if version == "h2" else "priority-last rule is HTTP/2-only",
            )
        )
    return results


def _check_content_length(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    if _has_header([n for n, _ in headers], "content-length"):
        return CheckResult(
            "NO_MANUAL_CONTENT_LENGTH",
            False,
            "content-length must not be set manually; let the HTTP client compute it "
            "(setting it risks a duplicate/conflicting value)",
        )
    return CheckResult("NO_MANUAL_CONTENT_LENGTH", True)


def _check_no_cache_artifacts(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    def _no_cache(name: str) -> bool:
        return any("no-cache" in value.lower() for value in _values_for(headers, name))

    if _no_cache("cache-control") and _no_cache("pragma"):
        return CheckResult(
            "NO_DISABLE_CACHE_ARTIFACT",
            False,
            "cache-control: no-cache and pragma: no-cache appear together — a DevTools "
            '"Disable cache" artifact that real Chrome traffic does not carry',
        )
    return CheckResult("NO_DISABLE_CACHE_ARTIFACT", True)


def _check_accept_encoding(headers: Sequence[Tuple[str, str]]) -> CheckResult:
    position = _header_index([n for n, _ in headers], "accept-encoding")
    if position is None:
        return CheckResult(
            "ACCEPT_ENCODING_CHROME",
            False,
            "required accept-encoding header is missing; Chrome sends "
            + ", ".join(_REQUIRED_ENCODINGS),
        )
    value = headers[position][1].lower()
    tokens = {t.strip().split(";", 1)[0] for t in value.split(",") if t.strip()}
    missing = [enc for enc in _REQUIRED_ENCODINGS if enc not in tokens]
    if missing:
        return CheckResult(
            "ACCEPT_ENCODING_CHROME",
            False,
            f"accept-encoding {headers[position][1]!r} is missing Chrome token(s): "
            + ", ".join(missing)
            + f"; expected all of {', '.join(_REQUIRED_ENCODINGS)}",
        )
    return CheckResult("ACCEPT_ENCODING_CHROME", True)


def _check_ua_header_present(
    headers: Sequence[Tuple[str, str]], user_agent: str
) -> CheckResult:
    if not _has_header([n for n, _ in headers], "user-agent"):
        return CheckResult(
            "USER_AGENT_HEADER_PRESENT",
            False,
            "required user-agent header is missing from the header list",
        )
    if user_agent:
        sent = _values_for(headers, "user-agent")
        if sent and sent[0] != user_agent:
            return CheckResult(
                "USER_AGENT_HEADER_PRESENT",
                False,
                f"user-agent header value {sent[0]!r} does not match the declared "
                f"User-Agent {user_agent!r}",
            )
    return CheckResult("USER_AGENT_HEADER_PRESENT", True)


def _check_sec_ch_ua(
    headers: Sequence[Tuple[str, str]], chrome_major: Optional[str]
) -> CheckResult:
    actual_values = _values_for(headers, "sec-ch-ua")
    if not actual_values:
        return CheckResult(
            "SEC_CH_UA_EXACT",
            False,
            "required sec-ch-ua header is missing",
        )
    actual = actual_values[0].strip()
    if chrome_major is None:
        return CheckResult(
            "SEC_CH_UA_EXACT",
            False,
            "cannot validate sec-ch-ua because the User-Agent Chrome version could "
            "not be parsed",
        )
    expected = compute_sec_ch_ua(chrome_major)
    if actual != expected:
        return CheckResult(
            "SEC_CH_UA_EXACT",
            False,
            "sec-ch-ua does not match the exact GREASE value for Chrome "
            f"{chrome_major}.\n"
            f"  expected: {expected}\n"
            f"  actual:   {actual}",
        )
    return CheckResult("SEC_CH_UA_EXACT", True)


def _check_sec_ch_ua_platform(
    headers: Sequence[Tuple[str, str]], platform: Optional[str]
) -> CheckResult:
    actual_values = _values_for(headers, "sec-ch-ua-platform")
    if not actual_values:
        return CheckResult(
            "SEC_CH_UA_PLATFORM", False, "required sec-ch-ua-platform header is missing"
        )
    actual = actual_values[0].strip()
    quoted = re.fullmatch(r'"[^"]+"', actual)
    if not quoted:
        return CheckResult(
            "SEC_CH_UA_PLATFORM",
            False,
            f"sec-ch-ua-platform value {actual!r} must be a quoted string "
            '(e.g. "Windows")',
        )
    if platform is None:
        return CheckResult(
            "SEC_CH_UA_PLATFORM",
            False,
            "cannot compare sec-ch-ua-platform because the User-Agent OS could not "
            "be parsed",
        )
    inner = actual[1:-1]
    if inner != platform:
        return CheckResult(
            "SEC_CH_UA_PLATFORM",
            False,
            f"sec-ch-ua-platform {actual!r} does not match the User-Agent OS "
            f"{platform!r}",
        )
    return CheckResult("SEC_CH_UA_PLATFORM", True)


def _check_accept_ch_gating(
    headers: Sequence[Tuple[str, str]], accepted_ch: Optional[Set[str]]
) -> CheckResult:
    declared = {h.lower() for h in (accepted_ch or set())}
    seen: List[str] = []
    for name, _ in headers:
        lowered = name.lower()
        if lowered in HIGH_ENTROPY_HINTS and lowered not in declared:
            seen.append(lowered)
    if seen:
        return CheckResult(
            "ACCEPT_CH_GATING",
            False,
            "high-entropy client hint(s) sent without an Accept-CH declaration: "
            + ", ".join(seen)
            + " — unsolicited high-entropy hints contradict the sensor payload "
            "(a common DataDome block cause)",
        )
    return CheckResult(
        "ACCEPT_CH_GATING",
        True,
        "no unsolicited high-entropy hints"
        if not declared
        else "all high-entropy hints are covered by Accept-CH",
    )


def _check_cookie_consistency(
    headers: Sequence[Tuple[str, str]], version: str
) -> List[CheckResult]:
    jar, malformed = _parse_cookies(headers)
    results: List[CheckResult] = []

    conflicts = {name: values for name, values in jar.items() if len(set(values)) > 1}
    if conflicts:
        detail = "; ".join(
            f"{name} -> {values}" for name, values in sorted(conflicts.items())
        )
        results.append(
            CheckResult(
                "COOKIE_NO_DUPLICATE_NAMES",
                False,
                "the same cookie name appears with different values (broken cookie "
                f"jar): {detail}",
            )
        )
    else:
        results.append(CheckResult("COOKIE_NO_DUPLICATE_NAMES", True))

    if malformed:
        results.append(
            CheckResult(
                "COOKIE_WELL_FORMED",
                False,
                f"{malformed} cookie fragment(s) lack a name=value pair",
            )
        )
    else:
        results.append(CheckResult("COOKIE_WELL_FORMED", True))

    # Chrome transport shape per HTTP version (references/request-rules.md).
    cookie_lines = sum(1 for name, _ in headers if name.lower() == "cookie")
    if cookie_lines:
        if version == "h2":
            # On h2 each cookie gets its own header; a coalesced line is the anomaly.
            coalesced = [
                value
                for name, value in headers
                if name.lower() == "cookie" and value.count("=") > 1
            ]
            if coalesced:
                results.append(
                    CheckResult(
                        "COOKIE_TRANSPORT_SHAPE",
                        False,
                        "HTTP/2 Chrome sends each cookie as its own cookie header "
                        "(RFC 9113); found coalesced cookie line(s): "
                        + " | ".join(coalesced),
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "COOKIE_TRANSPORT_SHAPE",
                        True,
                        "one cookie header per cookie, as Chrome does on HTTP/2",
                    )
                )
        elif version == "h1":
            if cookie_lines > 1:
                results.append(
                    CheckResult(
                        "COOKIE_TRANSPORT_SHAPE",
                        False,
                        f"HTTP/1.1 coalesces cookies into one Cookie header; found "
                        f"{cookie_lines} separate cookie headers",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "COOKIE_TRANSPORT_SHAPE", True, "single coalesced Cookie header"
                    )
                )
    else:
        results.append(
            CheckResult(
                "COOKIE_TRANSPORT_SHAPE", True, "no cookies; transport shape not applicable"
            )
        )
    return results


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def check_request(description: RequestDescription) -> CheckReport:
    """Run every applicable rule against one request description.

    Never raises for bad input: missing required headers, an unparseable
    User-Agent, conflicting cookies and similar problems are returned as failing
    :class:`CheckResult` entries instead.
    """
    report = CheckReport()
    headers = list(description.headers or [])

    version_results, version = _check_http_version(description)
    report.results.extend(version_results)

    # UA parsing feeds several later checks; a parse failure becomes its own
    # verdict and downgrades the dependent checks rather than aborting the run.
    chrome_major, platform, ua_error = _parse_user_agent(description.user_agent)
    if ua_error:
        report.results.append(CheckResult("USER_AGENT_PARSE", False, ua_error))
    else:
        report.results.append(
            CheckResult(
                "USER_AGENT_PARSE",
                True,
                f"Chrome {chrome_major} on {platform}",
            )
        )

    if version == "h2":
        report.results.append(_check_h2_lowercase(headers))
        report.results.extend(_check_h2_pseudo_order(headers))
        report.results.append(_check_h2_no_host(headers))
    elif version == "h1":
        report.results.append(_check_h1_host_first(headers))
        report.results.append(_check_h1_title_case(headers))

    if version is not None:
        report.results.append(_check_not_alphabetical(headers, version))
        report.results.extend(_check_priority_cookie(headers, version))
        report.results.extend(_check_cookie_consistency(headers, version))

    report.results.append(_check_content_length(headers))
    report.results.append(_check_no_cache_artifacts(headers))
    report.results.append(_check_accept_encoding(headers))
    report.results.append(_check_ua_header_present(headers, description.user_agent))
    report.results.append(_check_sec_ch_ua(headers, chrome_major))
    report.results.append(_check_sec_ch_ua_platform(headers, platform))
    report.results.append(_check_accept_ch_gating(headers, description.accepted_ch))
    return report


def format_report(report: CheckReport) -> str:
    """Human-readable rendering of a report (the library itself stays structured)."""
    lines = []
    for result in report.results:
        marker = "PASS" if result.passed else "FAIL"
        lines.append(f"[{marker}] {result.rule_id}")
        if not result.passed and result.message:
            for part in result.message.splitlines():
                lines.append(f"       {part}")
    lines.append("")
    lines.append(
        f"OVERALL: {'PASS' if report.passed else 'FAIL'} "
        f"({len(report.failures)} failing rule(s) of {len(report.results)})"
    )
    return "\n".join(lines)
