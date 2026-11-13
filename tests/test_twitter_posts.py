import json
import sys
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from free_scraper import twitter_posts  # noqa: E402


SUCCESS_PAYLOAD = {
    "data": {
        "tweetResult": {
            "result": {
                "core": {
                    "user_results": {
                        "result": {
                            "legacy": {"screen_name": "MongoDB"},
                            "is_blue_verified": True,
                        }
                    }
                },
                "legacy": {
                    "full_text": "We're excited to announce...",
                    "created_at": "Wed Feb 05 12:00:00 +0000 2025",
                    "favorite_count": 29,
                    "retweet_count": 10,
                },
                "views": {"count": "3417"},
            }
        }
    }
}


class FakeResponse:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status_code=200, payload=None, json_error=None):
        self.status_code = status_code
        self._payload = payload
        self._json_error = json_error

    def json(self):
        if self._json_error is not None:
            raise self._json_error
        return self._payload


def make_requester(responses):
    """Build a request_fn returning per-tweet responses or raising per-tweet errors."""

    def request_fn(tweet_id):
        outcome = responses[tweet_id]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return request_fn


def run_collector(tmp_path, responses, tweet_ids=None):
    tweet_ids = tweet_ids or list(responses)
    output_path = tmp_path / "twitter_posts.json"
    sleeps = []
    payload = twitter_posts.collect_tweets(
        tweet_ids,
        request_fn=make_requester(responses),
        sleep_fn=sleeps.append,
        output_path=str(output_path),
    )
    written = json.loads(output_path.read_text(encoding="utf-8"))
    return payload, written, sleeps, output_path


def test_mixed_outcomes_are_reported_per_tweet(tmp_path):
    tweet_ids = ["100", "101", "102", "103", "104"]
    responses = {
        "100": FakeResponse(200, SUCCESS_PAYLOAD),
        "101": requests.exceptions.Timeout("read timed out"),
        "102": FakeResponse(500, {"error": "internal"}),
        "103": FakeResponse(200, {"data": {}}),
        "104": FakeResponse(
            200,
            json_error=requests.exceptions.JSONDecodeError(
                "Expecting value", "<html>oops</html>", 0
            ),
        ),
    }

    payload, written, sleeps, output_path = run_collector(
        tmp_path, responses, tweet_ids
    )

    # The file is the single source of truth for this run.
    assert output_path.exists()
    assert written == payload

    # Successful entries keep the original shape and values.
    assert len(written["results"]) == 1
    success = written["results"][0]
    assert success == {
        "tweet_id": "100",
        "author": "MongoDB",
        "verified": True,
        "content": "We're excited to announce...",
        "posted_at": "Wed Feb 05 12:00:00 +0000 2025",
        "engagement": {"likes": 29, "retweets": 10, "views": "3417"},
    }

    # Every failed tweet has an explicit outcome and short reason.
    failures = {item["tweet_id"]: item for item in written["failures"]}
    assert set(failures) == {"101", "102", "103", "104"}
    assert failures["101"]["outcome"] == twitter_posts.OUTCOME_TIMEOUT
    assert failures["102"]["outcome"] == twitter_posts.OUTCOME_HTTP_ERROR
    assert "500" in failures["102"]["reason"]
    assert failures["103"]["outcome"] == twitter_posts.OUTCOME_MISSING_TWEET_DATA
    assert failures["104"]["outcome"] == twitter_posts.OUTCOME_INVALID_JSON
    for failure in failures.values():
        assert failure["reason"].strip()

    assert written["summary"] == {"success": 1, "failed": 4}

    # Per-item rate-limit sleep is preserved for successes and failures alike.
    assert sleeps == [twitter_posts.REQUEST_INTERVAL] * len(tweet_ids)


def test_network_error_is_a_distinct_outcome(tmp_path):
    responses = {"200": requests.exceptions.ConnectionError("connection reset")}

    _, written, _, _ = run_collector(tmp_path, responses)

    assert written["results"] == []
    assert written["failures"][0]["outcome"] == twitter_posts.OUTCOME_NETWORK_ERROR
    assert "connection reset" in written["failures"][0]["reason"]


def test_all_failed_still_writes_file(tmp_path):
    tweet_ids = ["300", "301", "302"]
    responses = {
        "300": requests.exceptions.Timeout("read timed out"),
        "301": FakeResponse(503),
        "302": FakeResponse(200, {"data": {"tweetResult": {}}}),
    }

    payload, written, _, output_path = run_collector(tmp_path, responses, tweet_ids)

    assert output_path.exists()
    assert written["results"] == []
    assert len(written["failures"]) == 3
    assert written["summary"] == {"success": 0, "failed": 3}
    assert [item["tweet_id"] for item in written["failures"]] == tweet_ids
    assert payload["summary"] == {"success": 0, "failed": 3}


def test_empty_tweet_list_writes_empty_result(tmp_path):
    payload, written, sleeps, output_path = run_collector(
        tmp_path, {}, tweet_ids=[]
    )

    assert output_path.exists()
    assert written == {
        "results": [],
        "failures": [],
        "summary": {"success": 0, "failed": 0},
    }
    assert sleeps == []


def test_main_uses_replaceable_request_dependency(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(twitter_posts, "TWEET_IDS", ["900", "901"])
    monkeypatch.setattr(
        twitter_posts,
        "request_tweet",
        lambda tweet_id: FakeResponse(200, SUCCESS_PAYLOAD),
    )
    monkeypatch.setattr(twitter_posts, "sleep", lambda seconds: None)

    twitter_posts.main()

    written = json.loads((tmp_path / "twitter_posts.json").read_text("utf-8"))
    assert written["summary"] == {"success": 2, "failed": 0}


def test_default_request_uses_unchanged_endpoint_and_credentials(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse(200, SUCCESS_PAYLOAD)

    monkeypatch.setattr(twitter_posts.requests, "get", fake_get)

    twitter_posts.request_tweet("123")

    assert captured["url"] == (
        "https://api.x.com/graphql/_y7SZqeOFfgEivILXIy3tQ/TweetResultByRestId"
    )
    assert captured["cookies"] == twitter_posts.COOKIES
    assert captured["headers"] == twitter_posts.HEADERS
    assert captured["headers"]["authorization"].startswith("Bearer ")
    assert "tweetId" in json.loads(captured["params"]["variables"])


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
