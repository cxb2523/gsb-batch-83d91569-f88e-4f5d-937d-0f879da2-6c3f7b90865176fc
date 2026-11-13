import requests
import json
from time import sleep
from typing import Callable, Dict, List, Optional, Tuple

# Configuration
COOKIES = {
    "d_prefs": "MjoxLGNvbnNlbnRfdmVyc2lvbjoyLHRleHRfdmVyc2lvbjoxMDAw",
    "guest_id": "v1%3A173847241574643869",
    "night_mode": "2",
    "guest_id_marketing": "v1%3A173847241574643869",
    "guest_id_ads": "v1%3A173847241574643869",
    "att": "1-wEVBVhEvbjoeOxO6NcJUbAEuiotm5ZKsu8BeYxWC",
    "gt": "1886026951904682400",
    "personalization_id": '"v1_cJUAgNXUvoHoFMsAKe3A0g=="',
}

HEADERS = {
    "accept": "*/*",
    "accept-language": "en-GB,en;q=0.5",
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",
    "content-type": "application/json",
    "origin": "https://x.com",
    "priority": "u=1, i",
    "referer": "https://x.com/",
    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="132", "Brave";v="132"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "sec-gpc": "1",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "x-client-transaction-id": "iEl80VZz0NJMYOy/rANcZzMNY5jHkotxm/y+lVqI6TcCRgtcDEvSEAzhwUTTzo18wKeA2IvstZMhbaLBQGCh4pMMrHvViw",
    "x-guest-token": "1886026951904682400",
    "x-twitter-active-user": "yes",
    "x-twitter-client-language": "en-GB",
}

FEATURES = {
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": False,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

TWEET_IDS = [
    "1882412972414214544",
    "1879604491764297992",
    "1869427646368792599",
    "1867608933176946806",
    "1885406586136383634",
]

TWEET_URL = "https://api.x.com/graphql/_y7SZqeOFfgEivILXIy3tQ/TweetResultByRestId"
REQUEST_TIMEOUT = 10
REQUEST_INTERVAL = 1
OUTPUT_PATH = "twitter_posts.json"

# Outcome categories recorded for tweets that could not be collected.
OUTCOME_TIMEOUT = "timeout"
OUTCOME_HTTP_ERROR = "http_error"
OUTCOME_MISSING_TWEET_DATA = "missing_tweet_data"
OUTCOME_NETWORK_ERROR = "network_error"
OUTCOME_INVALID_JSON = "invalid_json"
OUTCOME_UNEXPECTED_ERROR = "unexpected_error"


def _short_reason(message: str, limit: int = 200) -> str:
    """Collapse whitespace and cap length so failure reasons stay readable."""
    reason = " ".join(str(message).split())
    if not reason:
        reason = "unknown error"
    if len(reason) > limit:
        reason = reason[: limit - 3] + "..."
    return reason


def request_tweet(tweet_id: str):
    """Perform the HTTP request for a single tweet.

    Kept as a separate, replaceable function so tests can supply fake
    responses without touching the real endpoint configuration below.
    """
    params = {
        "variables": json.dumps(
            {
                "tweetId": tweet_id,
                "withCommunity": False,
                "includePromotedContent": False,
                "withVoice": False,
            }
        ),
        "features": json.dumps(FEATURES),
        "fieldToggles": json.dumps(
            {
                "withArticleRichContentState": True,
                "withArticlePlainText": False,
                "withGrokAnalyze": False,
                "withDisallowedReplyControls": False,
            }
        ),
    }

    return requests.get(
        TWEET_URL,
        params=params,
        cookies=COOKIES,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )


def _failure(tweet_id: str, outcome: str, reason: str) -> Dict:
    return {"tweet_id": tweet_id, "outcome": outcome, "reason": _short_reason(reason)}


def _get(node, *keys, default=None):
    """Walk nested dict keys, tolerating missing or non-dict nodes."""
    for key in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(key)
    return node if node is not None else default


def fetch_tweet_data(
    tweet_id: str,
    request_fn: Optional[Callable[[str], object]] = None,
) -> Tuple[Optional[Dict], Optional[Dict]]:
    """
    Fetch and extract essential data for a single tweet

    Args:
        tweet_id: The ID of the tweet to fetch
        request_fn: Callable performing the HTTP request. Defaults to
            ``request_tweet`` resolved at call time, so it can be replaced
            by tests or callers.

    Returns:
        A ``(tweet_data, failure)`` tuple. On success ``tweet_data`` holds the
        tweet record and ``failure`` is ``None``; on failure ``tweet_data`` is
        ``None`` and ``failure`` describes the outcome.
    """
    if request_fn is None:
        request_fn = request_tweet

    try:
        response = request_fn(tweet_id)

        if response.status_code != 200:
            return None, _failure(
                tweet_id,
                OUTCOME_HTTP_ERROR,
                f"HTTP status {response.status_code}",
            )

        data = response.json()

        result = _get(data, "data", "tweetResult", "result", default={})

        if not isinstance(result, dict) or not result:
            return None, _failure(
                tweet_id,
                OUTCOME_MISSING_TWEET_DATA,
                "response contained no tweet data",
            )

        user = _get(result, "core", "user_results", "result", default={})
        legacy = _get(result, "legacy", default={})

        return (
            {
                "tweet_id": tweet_id,
                "author": _get(user, "legacy", "screen_name"),
                "verified": user.get("is_blue_verified")
                if isinstance(user, dict)
                else None,
                "content": _get(legacy, "full_text"),
                "posted_at": _get(legacy, "created_at"),
                "engagement": {
                    "likes": _get(legacy, "favorite_count"),
                    "retweets": _get(legacy, "retweet_count"),
                    "views": _get(result, "views", "count"),
                },
            },
            None,
        )

    except requests.exceptions.Timeout as e:
        return None, _failure(
            tweet_id,
            OUTCOME_TIMEOUT,
            f"request timed out after {REQUEST_TIMEOUT}s: {e}",
        )
    except requests.exceptions.JSONDecodeError as e:
        # requests' JSONDecodeError also subclasses RequestException, so it
        # must be handled before the generic network-error branch.
        return None, _failure(tweet_id, OUTCOME_INVALID_JSON, f"invalid JSON: {e}")
    except requests.exceptions.RequestException as e:
        return None, _failure(tweet_id, OUTCOME_NETWORK_ERROR, e)
    except json.JSONDecodeError as e:
        return None, _failure(tweet_id, OUTCOME_INVALID_JSON, f"invalid JSON: {e}")
    except Exception as e:
        return None, _failure(tweet_id, OUTCOME_UNEXPECTED_ERROR, e)


def collect_tweets(
    tweet_ids: List[str],
    request_fn: Optional[Callable[[str], object]] = None,
    sleep_fn: Callable[[float], None] = sleep,
    interval: float = REQUEST_INTERVAL,
    output_path: str = OUTPUT_PATH,
) -> Dict:
    """Fetch every tweet ID and always write a result file.

    The output file is a single object containing successful ``results``,
    per-tweet ``failures`` and a ``summary`` with the success/failure counts.
    It is written even when every request failed, so downstream consumers can
    tell "nothing collected" apart from "the script never ran".
    """
    results: List[Dict] = []
    failures: List[Dict] = []

    if request_fn is None:
        request_fn = request_tweet

    for tweet_id in tweet_ids:
        print(f"Processing tweet {tweet_id}...")
        tweet_data, failure = fetch_tweet_data(tweet_id, request_fn=request_fn)

        if tweet_data is not None:
            results.append(tweet_data)
        else:
            failures.append(failure)
            print(
                f"Failed tweet {tweet_id}: {failure['outcome']} "
                f"({failure['reason']})"
            )

        # Rate limiting protection (kept for every item, as before)
        sleep_fn(interval)

    payload = {
        "results": results,
        "failures": failures,
        "summary": {"success": len(results), "failed": len(failures)},
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print(
        f"Summary: {len(results)} succeeded, {len(failures)} failed "
        f"- saved to {output_path}"
    )
    return payload


def main():
    """Main function to fetch and save tweet data"""
    collect_tweets(TWEET_IDS, request_fn=request_tweet)


if __name__ == "__main__":
    main()