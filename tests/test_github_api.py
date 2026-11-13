"""Unit tests for GitHub API queries, parsing, rate limits, and fallback handlers."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from buildsite.github_api import (
    GitHubAPIError,
    RateLimitExceededError,
    UserNotFoundError,
    fetch_contributions_graphql,
    fetch_contributions_rest_fallback,
    get_demo_contributions,
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
