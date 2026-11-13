"""Unit tests for GitHub API queries, parsing, rate limits, and fallback handlers."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from buildsite.github_api import (
    GitHubAPIError,
    PublicCalendarError,
    RateLimitExceededError,
    UserNotFoundError,
    fetch_contributions_graphql,
    fetch_contributions_public_calendar,
    fetch_contributions_rest_fallback,
    get_demo_contributions,
)


def _calendar_html(summary: str, day_rows: str, tooltips: str = "") -> str:
    """Build a local HTML sample shaped like GitHub's public contribution calendar."""
    return f"""<!DOCTYPE html>
<html><body>
  <div class="js-yearly-contributions">
    <h2 class="f4 text-normal mb-2">{summary}</h2>
    <table class="ContributionCalendar-grid">
      <tbody><tr>{day_rows}</tr></tbody>
    </table>
    {tooltips}
  </div>
</body></html>
"""


def _day_cell(date: str, level: int, cell_id: str) -> str:
    return (
        f'<td tabindex="0" data-date="{date}" data-level="{level}" '
        f'id="{cell_id}" class="ContributionCalendar-day"></td>'
    )


def _make_public_session(html: str, user_id: int = 4242) -> MagicMock:
    """Mock requests.Session whose GET serves calendar HTML then the user JSON."""
    session = MagicMock()

    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        if url.rstrip("/").endswith("/contributions"):
            resp.text = html
        else:
            resp.json.return_value = {"id": user_id, "login": "mona"}
        return resp

    session.get.side_effect = side_effect
    return session


VALID_CALENDAR_HTML = _calendar_html(
    summary="13 contributions in the last year",
    day_rows=(
        _day_cell("2026-01-01", 1, "contribution-day-component-0-0")
        + _day_cell("2026-01-02", 0, "contribution-day-component-0-1")
        + _day_cell("2026-01-03", 2, "contribution-day-component-0-2")
    ),
    tooltips=(
        '<tool-tip for="contribution-day-component-0-0">4 contributions on January 1st.</tool-tip>'
        '<tool-tip for="contribution-day-component-0-1">No contributions on January 2nd.</tool-tip>'
        '<tool-tip for="contribution-day-component-0-2">9 contributions on January 3rd.</tool-tip>'
    ),
)


def test_get_demo_contributions():
    """Verify demo mode returns realistic, labeled contribution snapshot."""
    demo = get_demo_contributions(count=450, username="test-user")
    assert demo.login == "test-user"
    assert demo.total_contributions == 450
    assert demo.source == "demo"
    assert demo.user_id > 0
    assert len(demo.years) > 0


@patch("requests.Session.post")
def test_fetch_contributions_graphql_success(mock_post):
    """Verify parsing of valid GraphQL response."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "user": {
                "id": "MDQ6VXNlcjEyMzQ1",
                "databaseId": 12345,
                "login": "mona",
                "contributionsCollection": {
                    "hasAnyContributions": True,
                    "totalCommitContributions": 120,
                    "totalIssueContributions": 10,
                    "totalPullRequestContributions": 15,
                    "totalPullRequestReviewContributions": 5,
                    "contributionCalendar": {
                        "totalContributions": 150,
                        "weeks": [
                            {
                                "contributionDays": [
                                    {"contributionCount": 4, "date": "2026-05-01", "color": "#216e39"},
                                    {"contributionCount": 0, "date": "2026-05-02", "color": "#ebedf0"},
                                    {"contributionCount": 8, "date": "2026-05-03", "color": "#30a14e"}
                                ]
                            }
                        ]
                    },
                    "contributionYears": [2025, 2026]
                }
            }
        }
    }
    mock_post.return_value = mock_resp

    snapshot = fetch_contributions_graphql("mona", token="fake_token")
    assert snapshot.login == "mona"
    assert snapshot.user_id == 12345
    assert snapshot.total_contributions == 150
    assert snapshot.active_days == 2
    assert snapshot.source == "graphql"


@patch("requests.Session.post")
def test_fetch_contributions_graphql_user_not_found(mock_post):
    """Verify UserNotFoundError is raised when user does not exist."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {"user": None},
        "errors": [{"message": "Could not resolve to a User with the login of 'nonexistent'."}]
    }
    mock_post.return_value = mock_resp

    with pytest.raises(UserNotFoundError):
        fetch_contributions_graphql("nonexistent", token="fake_token")


@patch("requests.Session.post")
def test_fetch_contributions_graphql_rate_limit(mock_post):
    """Verify RateLimitExceededError is raised on 403 rate limit response."""
    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 403
    mock_resp.text = "API rate limit exceeded for user ID"
    mock_post.return_value = mock_resp

    with pytest.raises(RateLimitExceededError):
        fetch_contributions_graphql("busyuser", token="fake_token")


@patch("requests.Session.get")
def test_fetch_contributions_rest_fallback(mock_get):
    """Verify REST API fallback when GraphQL is unavailable."""
    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        if "/users/backup_user/events" in url:
            resp.json.return_value = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        else:
            resp.json.return_value = {"id": 9876, "login": "backup_user", "public_repos": 10}
        return resp

    mock_get.side_effect = side_effect

    snapshot = fetch_contributions_rest_fallback("backup_user")
    assert snapshot.login == "backup_user"
    assert snapshot.user_id == 9876
    assert snapshot.total_contributions >= 50
    assert snapshot.source == "rest"


def test_fetch_contributions_public_calendar_parses_exact_totals():
    """Verify a well-formed public calendar yields exact totals and daily counts."""
    session = _make_public_session(VALID_CALENDAR_HTML, user_id=4242)

    snapshot = fetch_contributions_public_calendar("mona", session=session)

    assert snapshot.source == "public_calendar"
    assert snapshot.is_estimate is False
    assert snapshot.total_contributions == 13
    assert snapshot.active_days == 2
    assert snapshot.user_id == 4242
    assert snapshot.years == [2026]
    # Exact daily counts come from the per-day tool-tips, not data-level buckets.
    assert [(d.date, d.count) for d in snapshot.calendar_days] == [
        ("2026-01-01", 4),
        ("2026-01-02", 0),
        ("2026-01-03", 9),
    ]


def test_fetch_contributions_public_calendar_uses_data_count_attribute():
    """Verify exact data-count attributes are preferred over data-level buckets."""
    html = _calendar_html(
        summary="11 contributions in the last year",
        day_rows=(
            '<td data-date="2026-02-01" data-level="2" data-count="5"></td>'
            '<td data-date="2026-02-02" data-level="4" data-count="6"></td>'
        ),
    )
    snapshot = fetch_contributions_public_calendar("mona", session=_make_public_session(html))

    assert snapshot.total_contributions == 11
    assert snapshot.active_days == 2
    assert [d.count for d in snapshot.calendar_days] == [5, 6]


def test_fetch_contributions_public_calendar_missing_total_raises():
    """A page without an 'X contributions' total must fail, not return zero."""
    html = _calendar_html(
        summary="Something unexpected happened",
        day_rows=_day_cell("2026-01-01", 1, "contribution-day-component-0-0"),
    )

    with pytest.raises(PublicCalendarError, match="does not contain"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_ambiguous_total_raises():
    """Ambiguous monthly-only totals must not be mistaken for the yearly total."""
    html = _calendar_html(
        summary="February: 7 contributions, March: 9 contributions",
        day_rows=_day_cell("2026-02-01", 1, "contribution-day-component-0-0"),
    )

    with pytest.raises(PublicCalendarError, match="conflicting"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_rejects_total_active_day_contradiction():
    """A positive total with no active days is contradictory and must fail."""
    html = _calendar_html(
        summary="42 contributions in the last year",
        day_rows=(
            _day_cell("2026-01-01", 0, "contribution-day-component-0-0")
            + _day_cell("2026-01-02", 0, "contribution-day-component-0-1")
        ),
    )

    with pytest.raises(PublicCalendarError, match="none of the parsed days are active"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_rejects_zero_total_with_active_days():
    """Zero total with active days is equally contradictory."""
    html = _calendar_html(
        summary="0 contributions in the last year",
        day_rows=_day_cell("2026-01-01", 3, "contribution-day-component-0-0"),
        tooltips=(
            '<tool-tip for="contribution-day-component-0-0">'
            "3 contributions on January 1st.</tool-tip>"
        ),
    )

    with pytest.raises(PublicCalendarError, match="0 contributions"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_rejects_daily_sum_exceeding_total():
    """Exact per-day counts that exceed the reported total are contradictory."""
    html = _calendar_html(
        summary="3 contributions in the last year",
        day_rows=(
            '<td data-date="2026-01-01" data-level="2" data-count="8"></td>'
            '<td data-date="2026-01-02" data-level="1" data-count="2"></td>'
        ),
    )

    with pytest.raises(PublicCalendarError, match="parsed daily records sum to 10"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_does_not_invent_days_from_data_date():
    """Cells carrying only data-date (no activity signal) must not become count=1."""
    html = _calendar_html(
        summary="2 contributions in the last year",
        day_rows=(
            '<td data-date="2026-01-01"></td>'
            '<td data-date="2026-01-02"></td>'
        ),
    )

    with pytest.raises(PublicCalendarError, match="no activity data"):
        fetch_contributions_public_calendar("mona", session=_make_public_session(html))


def test_fetch_contributions_public_calendar_accepts_level_zero_as_inactive():
    """data-level=0 reliably means an inactive day (no contributions)."""
    html = _calendar_html(
        summary="1 contribution in the last year",
        day_rows=(
            '<td data-date="2026-01-01" data-level="0"></td>'
            '<td data-date="2026-01-02" data-level="1"></td>'
        ),
    )
    snapshot = fetch_contributions_public_calendar("mona", session=_make_public_session(html))

    assert snapshot.total_contributions == 1
    assert snapshot.active_days == 1
    assert [(d.date, d.count) for d in snapshot.calendar_days] == [
        ("2026-01-01", 0),
        ("2026-01-02", 1),
    ]


def test_fetch_contributions_public_calendar_user_not_found():
    """404 on the calendar page raises UserNotFoundError."""
    session = MagicMock()
    resp = MagicMock()
    resp.ok = False
    resp.status_code = 404
    session.get.return_value = resp

    with pytest.raises(UserNotFoundError):
        fetch_contributions_public_calendar("ghost", session=session)


def test_fetch_contributions_rest_fallback_is_marked_estimate():
    """REST fallback values must be flagged as estimates, not verified counts."""
    def side_effect(url, **kwargs):
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        if "/users/backup_user/events" in url:
            resp.json.return_value = [{"id": "1"}, {"id": "2"}]
        else:
            resp.json.return_value = {"id": 9876, "login": "backup_user", "public_repos": 3}
        return resp

    session = MagicMock()
    session.get.side_effect = side_effect

    snapshot = fetch_contributions_rest_fallback("backup_user", session=session)
    assert snapshot.source == "rest"
    assert snapshot.is_estimate is True


@patch("requests.Session.post")
def test_public_calendar_contradiction_falls_back_to_graphql(mock_post):
    """A contradictory public calendar makes the CLI chain degrade to GraphQL."""
    from buildsite.cli import fetch_snapshot_with_fallbacks

    contradicting_html = _calendar_html(
        summary="42 contributions in the last year",
        day_rows=(
            _day_cell("2026-01-01", 0, "contribution-day-component-0-0")
            + _day_cell("2026-01-02", 0, "contribution-day-component-0-1")
        ),
    )
    calendar_session = _make_public_session(contradicting_html)

    graphql_resp = MagicMock()
    graphql_resp.ok = True
    graphql_resp.status_code = 200
    graphql_resp.json.return_value = {
        "data": {
            "user": {
                "databaseId": 12345,
                "login": "mona",
                "contributionsCollection": {
                    "contributionCalendar": {
                        "totalContributions": 150,
                        "weeks": [
                            {
                                "contributionDays": [
                                    {"contributionCount": 4, "date": "2026-05-01"},
                                    {"contributionCount": 0, "date": "2026-05-02"},
                                    {"contributionCount": 8, "date": "2026-05-03"},
                                ]
                            }
                        ],
                    },
                    "contributionYears": [2025, 2026],
                },
            }
        }
    }
    mock_post.return_value = graphql_resp

    # Exercise the real parser and the real contradiction check against local
    # HTML; only the transport is mocked. No token -> step 1 is skipped, so the
    # chain goes public calendar -> unauthenticated GraphQL.
    def real_public_calendar(username):
        return fetch_contributions_public_calendar(username, session=calendar_session)

    with patch("buildsite.cli.fetch_contributions_public_calendar", side_effect=real_public_calendar):
        snapshot = fetch_snapshot_with_fallbacks("mona", token="")

    assert snapshot.source == "graphql"
    assert snapshot.total_contributions == 150
    assert snapshot.active_days == 2


def test_fetch_snapshot_raises_when_all_channels_fail():
    """All channels failing raises GitHubAPIError instead of returning zeros."""
    from buildsite.cli import fetch_snapshot_with_fallbacks

    with patch(
        "buildsite.cli.fetch_contributions_public_calendar",
        side_effect=PublicCalendarError("no total"),
    ), patch(
        "buildsite.cli.fetch_contributions_graphql",
        side_effect=GitHubAPIError("graphql down"),
    ), patch(
        "buildsite.cli.fetch_contributions_rest_fallback",
        side_effect=GitHubAPIError("rest down"),
    ):
        with pytest.raises(GitHubAPIError, match="All contribution retrieval methods failed"):
            fetch_snapshot_with_fallbacks("mona", token="fake_token")


def test_fetch_snapshot_user_not_found_does_not_degrade():
    """UserNotFoundError from any channel aborts the fallback chain."""
    from buildsite.cli import fetch_snapshot_with_fallbacks

    with patch(
        "buildsite.cli.fetch_contributions_public_calendar",
        side_effect=UserNotFoundError("missing"),
    ) as mock_calendar, patch(
        "buildsite.cli.fetch_contributions_graphql",
        side_effect=UserNotFoundError("missing"),
    ):
        with pytest.raises(UserNotFoundError):
            fetch_snapshot_with_fallbacks("ghost", token="fake_token")

    # The authenticated GraphQL channel reports the missing user; nothing else
    # is attempted afterwards.
    assert mock_calendar.call_count == 0

