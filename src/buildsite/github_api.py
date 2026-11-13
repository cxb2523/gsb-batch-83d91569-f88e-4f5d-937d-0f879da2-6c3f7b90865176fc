"""GitHub API collector for BuildSite.

Collects verified contribution history and calendar data using GitHub's
official GraphQL and REST APIs, respecting rate limits, UTC dates, and
privacy policies.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from buildsite.models import ContributionDay, ContributionSnapshot

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
GITHUB_REST_ENDPOINT = "https://api.github.com"


class GitHubAPIError(Exception):
    """Raised when GitHub API requests fail."""


class RateLimitExceededError(GitHubAPIError):
    """Raised when GitHub API rate limit is exceeded."""


class UserNotFoundError(GitHubAPIError):
    """Raised when the specified GitHub user does not exist."""


class PublicCalendarError(GitHubAPIError):
    """Raised when the public contribution calendar cannot be parsed reliably.

    This signals that the public-calendar channel is unusable and callers
    should fall through to the next contribution source instead of treating
    the page as an empty (zero-contribution) calendar.
    """


GRAPHQL_CONTRIBUTIONS_QUERY = """
query ($login: String!, $from: DateTime, $to: DateTime) {
  user(login: $login) {
    id
    databaseId
    login
    contributionsCollection(from: $from, to: $to) {
      hasAnyContributions
      totalCommitContributions
      totalIssueContributions
      totalPullRequestContributions
      totalPullRequestReviewContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
            color
          }
        }
      }
      contributionYears
    }
  }
}
"""


def get_default_headers(token: Optional[str] = None) -> Dict[str, str]:
    """Prepare standard request headers.

    ``token=None`` falls back to ``GITHUB_TOKEN``/``GH_TOKEN`` from the
    environment. Pass an empty string to explicitly issue an unauthenticated
    request (used by the tokenless GraphQL retry in the CLI fallback chain).
    """
    headers = {
        "User-Agent": "BuildSite-Engine/1.0 (+https://github.com/buildsite/buildsite)",
        "Accept": "application/vnd.github.v3+json",
    }
    actual_token = token
    if actual_token is None:
        actual_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if actual_token:
        headers["Authorization"] = f"bearer {actual_token}"
    return headers


def fetch_contributions_graphql(
    username: str,
    token: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> ContributionSnapshot:
    """Fetch verified contribution history via GitHub GraphQL API.

    Args:
        username: GitHub login handle.
        token: Optional GitHub Personal Access Token or GITHUB_TOKEN.
        from_date: Optional ISO 8601 UTC start datetime string.
        to_date: Optional ISO 8601 UTC end datetime string.
        session: Optional requests.Session instance for connection reuse.

    Returns:
        ContributionSnapshot with normalized metrics.
    """
    headers = get_default_headers(token)
    req_session = session or requests.Session()

    variables: Dict[str, Any] = {"login": username}
    if from_date:
        variables["from"] = from_date
    if to_date:
        variables["to"] = to_date

    payload = {"query": GRAPHQL_CONTRIBUTIONS_QUERY, "variables": variables}

    try:
        response = req_session.post(
            GITHUB_GRAPHQL_ENDPOINT,
            json=payload,
            headers=headers,
            timeout=15.0
        )
    except requests.RequestException as exc:
        raise GitHubAPIError(f"Network error querying GitHub GraphQL: {exc}") from exc

    if response.status_code == 401:
        raise GitHubAPIError("GitHub API authorization failed. Check your GITHUB_TOKEN permissions.")
    if response.status_code == 403:
        if "rate limit" in response.text.lower():
            raise RateLimitExceededError("GitHub API rate limit exceeded.")
        raise GitHubAPIError(f"GitHub API access forbidden (HTTP 403): {response.text}")

    if not response.ok:
        raise GitHubAPIError(f"GitHub API responded with HTTP {response.status_code}: {response.text}")

    data = response.json()
    if "errors" in data:
        error_msgs = [e.get("message", "Unknown error") for e in data["errors"]]
        if any("Could not resolve to a User" in m for m in error_msgs):
            raise UserNotFoundError(f"GitHub user '{username}' was not found.")
        raise GitHubAPIError(f"GraphQL returned errors: {'; '.join(error_msgs)}")

    user_data = data.get("data", {}).get("user")
    if not user_data:
        raise UserNotFoundError(f"GitHub user '{username}' was not found.")

    database_id = user_data.get("databaseId") or 0
    resolved_login = user_data.get("login", username)
    collection = user_data.get("contributionsCollection", {})
    calendar = collection.get("contributionCalendar", {})
    total_contributions = calendar.get("totalContributions", 0)
    years = collection.get("contributionYears", [])

    contribution_days: List[ContributionDay] = []
    active_days_count = 0

    for week in calendar.get("weeks", []):
        for day in week.get("contributionDays", []):
            cnt = day.get("contributionCount", 0)
            date_str = day.get("date", "")
            contribution_days.append(ContributionDay(date=date_str, count=cnt))
            if cnt > 0:
                active_days_count += 1

    return ContributionSnapshot(
        user_id=int(database_id),
        login=resolved_login,
        total_contributions=total_contributions,
        active_days=active_days_count,
        calendar_days=contribution_days,
        years=years,
        collected_at=datetime.now(timezone.utc).isoformat(),
        source="graphql"
    )


PUBLIC_CALENDAR_URL = "https://github.com/users/{username}/contributions"

# Matches the summary line rendered above the public contribution graph, e.g.
# "1,234 contributions in the last year".
_PUBLIC_TOTAL_RE = re.compile(
    r'([0-9][0-9,]*)\s+contributions?\s+in\s+the\s+last\s+year',
    re.IGNORECASE,
)
# Looser fallback for localized/minimal variants of the summary line.
_PUBLIC_TOTAL_ANY_RE = re.compile(r'([0-9][0-9,]*)\s+contributions?', re.IGNORECASE)
# Any element carrying a data-date attribute (GitHub renders these as <td>s).
_CALENDAR_DAY_ELEMENT_RE = re.compile(
    r'<[a-zA-Z][a-zA-Z0-9:-]*\b(?P<attrs>[^>]*\bdata-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*)>',
    re.IGNORECASE,
)
_DATA_COUNT_RE = re.compile(r'\bdata-count="([0-9]+)"', re.IGNORECASE)
_DATA_LEVEL_RE = re.compile(r'\bdata-level="([0-9]+)"', re.IGNORECASE)
_LABELLEDBY_RE = re.compile(r'\baria-labelledby="([^"]+)"', re.IGNORECASE)
_ID_ATTR_RE = re.compile(r'\bid="([^"]+)"', re.IGNORECASE)
_TOOLTIP_RE = re.compile(
    r'<tool-tip\b(?P<attrs>[^>]*)>(?P<text>.*?)</tool-tip>',
    re.IGNORECASE | re.DOTALL,
)
_TOOLTIP_FOR_RE = re.compile(r'\bfor="([^"]+)"', re.IGNORECASE)
_TOOLTIP_COUNT_RE = re.compile(r'([0-9][0-9,]*)\s+contributions?', re.IGNORECASE)
_NO_CONTRIBUTIONS_RE = re.compile(r'\bno\s+contributions?\b', re.IGNORECASE)
_TOOLTIP_ELEMENT_RE = re.compile(r'<tool-tip\b.*?</tool-tip>', re.IGNORECASE | re.DOTALL)
_SCRIPT_STYLE_RE = re.compile(r'<(?:script|style)\b.*?</(?:script|style)>', re.IGNORECASE | re.DOTALL)


def _strip_calendar_noise(html_content: str) -> str:
    """Remove tooltips and script/style blocks before matching the yearly total.

    Per-day tool-tips also contain the word "contributions" (e.g.
    "3 contributions on Sunday, ..."), so they must not be mistaken for the
    annual summary line.
    """
    cleaned = _TOOLTIP_ELEMENT_RE.sub(" ", html_content)
    return _SCRIPT_STYLE_RE.sub(" ", cleaned)


def _parse_public_total(html_content: str) -> int:
    """Extract the yearly contribution total, raising when it is not present.

    A missing total means the page is not a usable contribution calendar (for
    example an interstitial or a changed markup). Returning 0 in that case
    would silently tell generate that the user has no contributions.

    The loose "N contributions" form is only accepted when every occurrence
    agrees; otherwise (e.g. a page where only per-month summaries remain) the
    intended yearly total is ambiguous and the channel fails.
    """
    cleaned = _strip_calendar_noise(html_content)
    match = _PUBLIC_TOTAL_RE.search(cleaned)
    if match is not None:
        return int(match.group(1).replace(",", ""))

    candidates = {
        int(m.group(1).replace(",", ""))
        for m in _PUBLIC_TOTAL_ANY_RE.finditer(cleaned)
    }
    if len(candidates) == 1:
        return candidates.pop()
    if not candidates:
        raise PublicCalendarError(
            "Public contribution calendar does not contain a 'X contributions' total; "
            "refusing to treat it as an empty calendar."
        )
    raise PublicCalendarError(
        "Public contribution calendar contains conflicting 'X contributions' totals "
        f"({', '.join(str(c) for c in sorted(candidates))}); cannot determine the yearly total."
    )


def _parse_public_calendar_days(
    html_content: str,
) -> tuple[List[ContributionDay], bool]:
    """Parse per-day records from the public calendar markup.

    Preferred sources of a daily value, in order:

    1. ``data-count="N"`` — exact, when GitHub emits it.
    2. The ``<tool-tip>`` associated with the cell (matched through the cell's
       ``id``/``aria-labelledby``) — exact ("4 contributions on ...",
       "No contributions on ...").
    3. ``data-level="L"`` — GitHub's activity bucket. Level 0 reliably means no
       contributions; level > 0 marks the day active. Bucket values are kept
       as the day count, but the second return value reports that some counts
       are bucket-based so callers skip exact-sum consistency checks.

    A cell with only ``data-date`` and no activity signal is *not* guessed as
    ``count=1``; the markup is considered unparseable and
    :class:`PublicCalendarError` is raised.

    Returns:
        (days, all_counts_exact)
    """
    tooltip_counts: Dict[str, int] = {}
    for match in _TOOLTIP_RE.finditer(html_content):
        for_attr = _TOOLTIP_FOR_RE.search(match.group("attrs"))
        if not for_attr:
            continue
        text = match.group("text")
        if _NO_CONTRIBUTIONS_RE.search(text):
            tooltip_counts[for_attr.group(1)] = 0
            continue
        count_match = _TOOLTIP_COUNT_RE.search(text)
        if count_match:
            tooltip_counts[for_attr.group(1)] = int(count_match.group(1).replace(",", ""))

    days_by_date: Dict[str, ContributionDay] = {}
    all_counts_exact = True

    for match in _CALENDAR_DAY_ELEMENT_RE.finditer(html_content):
        date_str = match.group("date")
        attrs = match.group("attrs")

        count: Optional[int] = None
        exact = True

        data_count = _DATA_COUNT_RE.search(attrs)
        if data_count:
            count = int(data_count.group(1))
        else:
            for ref in (_LABELLEDBY_RE.search(attrs), _ID_ATTR_RE.search(attrs)):
                if not ref:
                    continue
                for candidate in ref.group(1).split():
                    if candidate in tooltip_counts:
                        count = tooltip_counts[candidate]
                        break
                if count is not None:
                    break

        if count is None:
            level = _DATA_LEVEL_RE.search(attrs)
            if level:
                # Activity bucket, not an exact per-day contribution count.
                count = int(level.group(1))
                exact = False

        if count is None:
            raise PublicCalendarError(
                f"Public contribution calendar exposes no activity data for {date_str}; "
                "refusing to infer daily contributions from data-date alone."
            )

        existing = days_by_date.get(date_str)
        if existing is not None:
            if existing.count != count:
                raise PublicCalendarError(
                    f"Public contribution calendar contains conflicting records for {date_str}."
                )
            continue

        days_by_date[date_str] = ContributionDay(date=date_str, count=count)
        all_counts_exact = all_counts_exact and exact

    return list(days_by_date.values()), all_counts_exact


def fetch_contributions_public_calendar(
    username: str,
    session: Optional[requests.Session] = None
) -> ContributionSnapshot:
    """Fetch the verified contribution count from GitHub's public calendar page.

    Works without authentication tokens. Raises :class:`PublicCalendarError`
    when the page cannot be parsed reliably (no yearly total, no daily records,
    or daily records that contradict the total) rather than fabricating zeros
    or per-day counts. ``UserNotFoundError`` is raised for unknown users.

    Args:
        username: GitHub login handle.
        session: Optional requests.Session instance for connection reuse.
    """
    req_session = session or requests.Session()
    calendar_url = PUBLIC_CALENDAR_URL.format(username=username)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        resp = req_session.get(calendar_url, headers=headers, timeout=12.0)
    except Exception as exc:
        raise GitHubAPIError(f"Network error querying public contribution calendar: {exc}") from exc

    if resp.status_code == 404:
        raise UserNotFoundError(f"GitHub user '{username}' was not found.")
    if not resp.ok:
        raise GitHubAPIError(f"GitHub contributions page returned HTTP {resp.status_code}")

    html_content = resp.text
    total_count = _parse_public_total(html_content)
    contribution_days, exact_daily_counts = _parse_public_calendar_days(html_content)

    if not contribution_days:
        raise PublicCalendarError(
            "Public contribution calendar does not contain any parsable daily records."
        )

    active_days = sum(1 for day in contribution_days if day.count > 0)
    parsed_total = sum(day.count for day in contribution_days)

    if total_count > 0 and active_days == 0:
        raise PublicCalendarError(
            f"Public contribution calendar reports {total_count} contributions, "
            "but none of the parsed days are active."
        )
    if active_days > total_count:
        raise PublicCalendarError(
            f"Public contribution calendar reports {total_count} contributions, "
            f"but {active_days} parsed days are active."
        )
    if total_count == 0 and active_days > 0:
        raise PublicCalendarError(
            f"Public contribution calendar reports 0 contributions, "
            f"but {active_days} parsed days are active."
        )
    if exact_daily_counts and parsed_total > total_count:
        raise PublicCalendarError(
            f"Public contribution calendar reports {total_count} contributions, "
            f"but the parsed daily records sum to {parsed_total}."
        )

    years_seen = {int(day.date.split("-")[0]) for day in contribution_days}

    user_id = 0
    try:
        u_resp = req_session.get(f"{GITHUB_REST_ENDPOINT}/users/{username}", headers=get_default_headers(), timeout=5.0)
        if u_resp.ok:
            user_id = u_resp.json().get("id", 0)
    except Exception:
        pass

    if user_id == 0:
        import hashlib
        user_id = int(hashlib.md5(username.encode()).hexdigest()[:8], 16)

    return ContributionSnapshot(
        user_id=user_id,
        login=username,
        total_contributions=total_count,
        active_days=active_days,
        calendar_days=contribution_days,
        years=sorted(years_seen) if years_seen else [datetime.now(timezone.utc).year],
        collected_at=datetime.now(timezone.utc).isoformat(),
        source="public_calendar"
    )


def fetch_contributions_rest_fallback(
    username: str,
    token: Optional[str] = None,
    session: Optional[requests.Session] = None,
) -> ContributionSnapshot:
    """Fallback contribution retrieval using REST API public profile & public events.

    Used when GraphQL access is restricted (e.g. unauthenticated public access).
    The resulting totals are heuristic estimates derived from public repository
    and event counts, not verified contribution counts; the snapshot is marked
    ``is_estimate=True`` and ``source="rest"`` accordingly.
    """
    headers = get_default_headers(token)
    req_session = session or requests.Session()

    user_url = f"{GITHUB_REST_ENDPOINT}/users/{username}"
    try:
        user_resp = req_session.get(user_url, headers=headers, timeout=10.0)
    except requests.RequestException as exc:
        raise GitHubAPIError(f"Network error querying GitHub REST API: {exc}") from exc

    if user_resp.status_code == 404:
        raise UserNotFoundError(f"GitHub user '{username}' was not found.")
    if user_resp.status_code == 403 and "rate limit" in user_resp.text.lower():
        raise RateLimitExceededError("GitHub REST API rate limit exceeded.")
    if not user_resp.ok:
        raise GitHubAPIError(f"REST API error HTTP {user_resp.status_code}: {user_resp.text}")

    user_info = user_resp.json()
    user_id = user_info.get("id", 0)
    login = user_info.get("login", username)
    public_repos = user_info.get("public_repos", 0)

    # Estimate base contributions from public metrics or public events
    events_url = f"{GITHUB_REST_ENDPOINT}/users/{username}/events/public?per_page=100"
    event_count = 0
    try:
        events_resp = req_session.get(events_url, headers=headers, timeout=10.0)
        if events_resp.ok:
            events_data = events_resp.json()
            event_count = len(events_data)
    except Exception:
        event_count = 0

    estimated_total = max(public_repos * 5 + event_count, 1)

    return ContributionSnapshot(
        user_id=user_id,
        login=login,
        total_contributions=estimated_total,
        active_days=min(event_count, 30),
        calendar_days=[],
        years=[datetime.now(timezone.utc).year],
        collected_at=datetime.now(timezone.utc).isoformat(),
        source="rest",
        is_estimate=True
    )


def get_demo_contributions(count: int = 327, username: str = "demo-developer") -> ContributionSnapshot:
    """Generate deterministic, clearly labeled demo contributions snapshot for testing."""
    return ContributionSnapshot(
        user_id=12345678,
        login=username,
        total_contributions=max(0, count),
        active_days=min(count, 185),
        calendar_days=[
            ContributionDay(date="2026-01-01", count=4),
            ContributionDay(date="2026-01-02", count=7),
            ContributionDay(date="2026-01-03", count=12),
        ],
        years=[2024, 2025, 2026],
        collected_at=datetime.now(timezone.utc).isoformat(),
        source="demo"
    )
