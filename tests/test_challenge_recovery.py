"""Tests for carrying cookies across bot-check retries.

A retry used to start over with only a freshly harvested WAF token, so every
cookie collected on the way -- most importantly the `session-id` the storefront
issued -- was lost. These tests pin down what a retry now carries, which token
wins when the two disagree, and what the caller is told about the attempts.

Every network call is stubbed: no browser is launched and Amazon is never
contacted.
"""

import pytest
from scrapy import Request
from scrapy.http import HtmlResponse

from main.spiders import base
from main.spiders.base import (
    CHALLENGE_REPORT_KEY,
    CSRF_STEP,
    MAX_CHALLENGE_RETRIES,
    STOREFRONT_STEP,
)
from main.spiders.locations import AmazonLocationSessionSpider

BASE_URL = "https://www.amazon.com"
CSRF_URL = BASE_URL + AmazonLocationSessionSpider.csrf_token_endpoint

STOREFRONT_BODY = b'<html><input id="glowValidationToken" value="token"/></html>'
CSRF_BODY = b'<html><script>var x = { CSRF_TOKEN : "csrf-value" };</script></html>'
AKAMAI_BODY = (
    b'<html><head><meta http-equiv="refresh" '
    b"content=\"5; URL='/?bm-verify=AAQAAAAN'\" /></head></html>"
)
WAF_BODY = b'<html><script>window.gokuProps = {"key":"..."}</script></html>'
CONFIRMATION_BODY = b'<html>"isValidAddress":1</html>'


@pytest.fixture
def spider():
    return AmazonLocationSessionSpider(country="us", zip_code="30322")


@pytest.fixture
def harvests(monkeypatch):
    """Stub the browser harvest and record invalidations and harvest count."""
    state = {"invalidated": [], "harvested": []}

    def fake_get_waf_session(base_url):
        state["harvested"].append(base_url)
        return (
            {"aws-waf-token": f"fresh-{len(state['harvested'])}"},
            f"Mozilla/5.0 (harvested-{len(state['harvested'])})",
        )

    monkeypatch.setattr(
        base,
        "invalidate_waf_session",
        lambda base_url: state["invalidated"].append(base_url),
    )
    monkeypatch.setattr(base, "get_waf_session", fake_get_waf_session)
    return state


def make_request(cookies=None, meta=None):
    return Request(
        url=BASE_URL,
        cookies=cookies or {},
        meta={
            "challenge_retry": 0,
            "carried_cookies": dict(cookies or {}),
            "challenge_attempts": [],
            # Keep the configured storefront URL verbatim, the way the spider's
            # retry does. Without it Scrapy rewrites a bare host to `host/`, and
            # the recorded URL depends on the installed w3lib version.
            "verbatim_url": True,
            **(meta or {}),
        },
    )


def make_response(request, body, status=200, set_cookies=None, headers=None, url=None):
    response_headers = dict(headers or {})
    if set_cookies:
        response_headers["Set-Cookie"] = set_cookies
    return HtmlResponse(
        url=url or request.url,
        status=status,
        body=body,
        headers=response_headers,
        request=request,
    )


def bot_checked_response(
    body, status=200, url=None, cookies=None, meta=None, set_cookies=None
):
    """A response that the flow must retry from the storefront."""
    request = make_request(cookies=cookies, meta=meta)
    return make_response(request, body, status=status, set_cookies=set_cookies, url=url)


class TestCarryingCookiesAcrossRetries:
    def test_waf_rejection_keeps_response_cookies_with_the_new_token(
        self, spider, harvests
    ):
        response = bot_checked_response(
            WAF_BODY,
            status=202,
            cookies={"aws-waf-token": "stale"},
            set_cookies=[b"session-id=session-1; Path=/", b"ak_bmsc=edge-1; Path=/"],
        )

        retry = spider.parse_ajax_token(response=response)

        assert retry.cookies["session-id"] == "session-1"
        assert retry.cookies["ak_bmsc"] == "edge-1"
        # The stale token must not survive the merge: the retry carries the
        # token harvested for it, not the one that was just rejected.
        assert retry.cookies["aws-waf-token"] == "fresh-1"
        assert spider.waf_user_agent == "Mozilla/5.0 (harvested-1)"
        assert retry.headers[b"User-Agent"] == b"Mozilla/5.0 (harvested-1)"
        assert harvests["invalidated"] == [BASE_URL]

    def test_a_response_setting_an_old_token_cannot_override_the_harvest(
        self, spider, harvests
    ):
        """A late `Set-Cookie` for the rejected token is still an old token."""
        response = bot_checked_response(
            WAF_BODY,
            status=202,
            cookies={"aws-waf-token": "stale"},
            set_cookies=[
                b"session-id=session-1; Path=/",
                b"aws-waf-token=stale; Path=/",
            ],
        )

        retry = spider.parse_ajax_token(response=response)

        assert retry.cookies["aws-waf-token"] == "fresh-1"
        assert retry.cookies["session-id"] == "session-1"

    def test_akamai_interstitial_retry_keeps_the_cached_token(self, spider, harvests):
        response = bot_checked_response(
            AKAMAI_BODY,
            cookies={"aws-waf-token": "cached"},
            set_cookies=[b"ak_bmsc=edge-1; Path=/"],
        )

        retry = spider.parse_ajax_token(response=response)

        assert harvests["invalidated"] == []
        assert retry.cookies["aws-waf-token"] == "fresh-1"
        assert retry.cookies["ak_bmsc"] == "edge-1"

    def test_csrf_block_keeps_the_first_storefront_cookies(self, spider, harvests):
        storefront = bot_checked_response(
            STOREFRONT_BODY, set_cookies=[b"session-id=session-1; Path=/"]
        )
        csrf_request = spider.parse_ajax_token(response=storefront)
        csrf_blocked = make_response(csrf_request, AKAMAI_BODY)

        retry = spider.parse_cookies(
            response=csrf_blocked, cookies=csrf_request.cookies
        )

        assert retry.url == BASE_URL
        assert retry.cookies["session-id"] == "session-1"
        assert retry.cookies["aws-waf-token"] == "fresh-1"
        # An Akamai page says nothing about the token, so no harvest is forced.
        assert harvests["invalidated"] == []

    def test_csrf_waf_rejection_keeps_cookies_and_reharvests(self, spider, harvests):
        storefront = bot_checked_response(
            STOREFRONT_BODY, set_cookies=[b"session-id=session-1; Path=/"]
        )
        csrf_request = spider.parse_ajax_token(response=storefront)
        csrf_blocked = make_response(
            csrf_request,
            WAF_BODY,
            status=202,
            headers={"x-amzn-waf-action": "challenge"},
        )

        retry = spider.parse_cookies(
            response=csrf_blocked, cookies=csrf_request.cookies
        )

        assert retry.cookies["session-id"] == "session-1"
        assert harvests["invalidated"] == [BASE_URL]
        assert harvests["harvested"] == [BASE_URL]

    def test_a_tokenless_harvest_does_not_bring_the_old_token_back(
        self, spider, harvests, monkeypatch
    ):
        """A harvest that only saw the Akamai branch has no token to offer."""
        monkeypatch.setattr(
            base, "get_waf_session", lambda base_url: ({}, "Mozilla/5.0 (harvested)")
        )
        response = bot_checked_response(
            WAF_BODY,
            status=202,
            cookies={"aws-waf-token": "stale"},
            set_cookies=[b"session-id=session-1; Path=/"],
        )

        retry = spider.parse_ajax_token(response=response)

        assert "aws-waf-token" not in retry.cookies
        assert retry.cookies["session-id"] == "session-1"
        assert retry.headers[b"User-Agent"] == b"Mozilla/5.0 (harvested)"

    def test_the_retry_is_a_fresh_start_with_the_same_cookies(self, spider, harvests):
        response = bot_checked_response(
            WAF_BODY, status=202, set_cookies=[b"session-id=session-1; Path=/"]
        )

        retry = spider.parse_ajax_token(response=response)

        assert retry.url == BASE_URL
        assert retry.callback == spider.parse_ajax_token
        assert retry.dont_filter is True
        assert retry.meta["challenge_retry"] == 1


class TestAttemptReport:
    def test_retries_are_still_capped_and_the_error_says_why(self, spider, harvests):
        prior = [
            {
                "step": STOREFRONT_STEP,
                "url": BASE_URL,
                "status": 202,
                "bytes": 10,
                "waf_rejected": True,
                "reharvested": True,
            },
            {
                "step": CSRF_STEP,
                "url": CSRF_URL,
                "status": 200,
                "bytes": 20,
                "waf_rejected": False,
                "reharvested": False,
            },
        ]
        response = bot_checked_response(
            WAF_BODY,
            status=202,
            meta={
                "challenge_retry": MAX_CHALLENGE_RETRIES,
                "challenge_attempts": prior,
            },
        )

        with pytest.raises(ValueError) as error:
            spider.parse_ajax_token(response=response)

        message = str(error.value)
        # The bits the original error already carried stay in it.
        assert "No usable page from" in message
        assert BASE_URL in message
        assert "HTTP 202" in message
        assert f"{len(WAF_BODY)} bytes" in message
        # ... and the summary names each block, its step, and what it cost.
        assert "3 bot checks" in message
        assert "attempt 1: storefront" in message
        assert "attempt 2: csrf" in message
        assert "attempt 3: storefront" in message
        assert "WAF-rejected" in message
        assert "other bot check" in message
        assert "re-harvested" in message
        assert "kept token" in message

    def test_success_reports_every_blocked_attempt(self, spider, harvests):
        first = bot_checked_response(
            WAF_BODY,
            status=202,
            meta={"challenge_retry": 0},
            set_cookies=[b"session-id=session-1; Path=/"],
        )
        retry = spider.parse_ajax_token(response=first)

        second = make_response(retry, AKAMAI_BODY, status=200)
        second_retry = spider.parse_ajax_token(response=second)

        storefront = make_response(second_retry, STOREFRONT_BODY)
        csrf = spider.parse_ajax_token(response=storefront)
        change = spider.parse_cookies(
            response=make_response(csrf, CSRF_BODY), cookies=csrf.cookies
        )
        result = spider.parse_result(
            response=make_response(change, CONFIRMATION_BODY), cookies=change.cookies
        )

        report = result[CHALLENGE_REPORT_KEY]
        assert report["store_url"] == BASE_URL
        assert report["total_attempts"] == 3
        assert report["blocked_attempts"] == 2
        assert report["attempts"] == [
            {
                "step": STOREFRONT_STEP,
                "url": BASE_URL,
                "status": 202,
                "bytes": len(WAF_BODY),
                "waf_rejected": True,
                "reharvested": True,
            },
            {
                "step": STOREFRONT_STEP,
                "url": BASE_URL,
                "status": 200,
                "bytes": len(AKAMAI_BODY),
                "waf_rejected": False,
                "reharvested": False,
            },
        ]

    def test_a_clean_run_reports_one_attempt(self, spider, harvests):
        storefront = make_response(make_request(), STOREFRONT_BODY)
        csrf = spider.parse_ajax_token(response=storefront)
        change = spider.parse_cookies(
            response=make_response(csrf, CSRF_BODY), cookies=csrf.cookies
        )

        result = spider.parse_result(
            response=make_response(change, CONFIRMATION_BODY), cookies=change.cookies
        )

        report = result[CHALLENGE_REPORT_KEY]
        assert report["total_attempts"] == 1
        assert report["blocked_attempts"] == 0
        assert report["attempts"] == []

    def test_the_report_is_not_a_cookie(self, spider, harvests):
        storefront = make_response(make_request(), STOREFRONT_BODY)
        csrf = spider.parse_ajax_token(response=storefront)
        change = spider.parse_cookies(
            response=make_response(csrf, CSRF_BODY), cookies=csrf.cookies
        )

        assert CHALLENGE_REPORT_KEY not in change.cookies
        result = spider.parse_result(
            response=make_response(change, CONFIRMATION_BODY), cookies=change.cookies
        )

        assert CHALLENGE_REPORT_KEY in result
        assert set(result) == {*change.cookies, CHALLENGE_REPORT_KEY}
        # Whatever the run reported, the cookies handed back are all plain
        # strings: the report is metadata and never travels in the jar.
        assert all(
            isinstance(value, str)
            for key, value in result.items()
            if key != CHALLENGE_REPORT_KEY
        )

    def test_failure_without_success_still_returns_no_cookies(self, spider, harvests):
        request = make_request()
        response = make_response(request, b'<html>"isValidAddress":0</html>')

        assert spider.parse_result(response=response, cookies={"session-id": "1"}) == {}

    def test_a_csrf_block_is_labelled_as_such(self, spider, harvests):
        csrf_request = make_request(
            cookies={"aws-waf-token": "cached"},
            meta={
                "challenge_retry": 0,
                "carried_cookies": {"aws-waf-token": "cached"},
                "challenge_attempts": [],
            },
        )
        retry = spider.parse_cookies(
            response=make_response(csrf_request, WAF_BODY, status=202, url=CSRF_URL),
            cookies=csrf_request.cookies,
        )

        assert retry.meta["challenge_attempts"] == [
            {
                "step": CSRF_STEP,
                "url": CSRF_URL,
                "status": 202,
                "bytes": len(WAF_BODY),
                "waf_rejected": True,
                "reharvested": True,
            }
        ]
