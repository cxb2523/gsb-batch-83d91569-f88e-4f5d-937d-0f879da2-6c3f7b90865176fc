import json
from collections.abc import AsyncIterator

from scrapy import Request, Spider
from scrapy.http import HtmlResponse

from main.settings import COUNTRY_BASE_URLS, HEADERS
from main.utils import extract_response_cookies
from main.waf import get_waf_session, invalidate_waf_session

# A cached WAF token can stop being accepted at any time, and Amazon also swaps
# in an Akamai Bot Manager interstitial for some sessions. Both are recoverable:
# drop the token, harvest a new one, ask again. Each retry runs a browser, so the
# budget is kept small enough that a crawl stays inside the API's timeout.
MAX_CHALLENGE_RETRIES = 2

# Key under which a successful result reports how the flow went. It is returned
# beside the cookies, but it is metadata rather than a cookie: it must never end
# up in a request's cookie jar, where it would be sent to Amazon as a cookie no
# browser ever set.
CHALLENGE_REPORT_KEY = "_challenge_report"

# The two points in the flow that can answer with a bot check instead of a page.
STOREFRONT_STEP = "storefront"
CSRF_STEP = "csrf"

# The cookie that ties a request to the browser that solved the WAF challenge.
# It is always owned by the most recent harvest, never carried over from an
# earlier attempt: an old token paired with a new user agent is challenged again.
WAF_TOKEN_COOKIE = "aws-waf-token"


class AmazonBaseSessionSpider(Spider):
    """Base Amazon spider for extracting delivery cookies."""

    name = ""

    address_change_endpoint = (
        "/portal-migration/hz/glow/address-change?actionSource=glow"
    )
    csrf_token_endpoint = (
        "/portal-migration/hz/glow/get-rendered-address-selections?deviceType=desktop"
        "&pageType=Search&storeContext=NoStoreName&actionSource=desktop-modal"
    )
    countries_base_urls = COUNTRY_BASE_URLS

    def __init__(self, country: str, *args: tuple, **kwargs: str) -> None:
        super().__init__(*args, **kwargs)
        self.country = country.upper()
        self.args = args
        self.kwargs = kwargs
        # Replaced in `start` by the user agent the WAF token belongs to.
        self.waf_user_agent = HEADERS["user-agent"]

    def build_headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """
        Build request headers pinned to the user agent the WAF token was issued to.

        Every request in the flow must reuse it: replaying `aws-waf-token` under a
        different user agent gets challenged again.
        """
        return {**HEADERS, "user-agent": self.waf_user_agent, **(extra or {})}

    async def start(self) -> AsyncIterator[Request]:
        """
        Make start request to main Amazon country page.

        The storefront sits behind an AWS WAF challenge, so the request carries a
        browser-issued `aws-waf-token` and the user agent it was issued to.

        Scrapy 2.13 replaced `start_requests` with this method and 2.17 dropped
        the old name entirely -- a spider still defining it is simply never asked
        for any requests, and the crawl finishes with no items and no error.
        """
        base_url = self.countries_base_urls.get(self.country)
        if not base_url:
            raise ValueError(f"Invalid country code: {self.country}")

        waf_cookies, self.waf_user_agent = get_waf_session(base_url=base_url)
        yield Request(
            url=base_url,
            headers=self.build_headers(),
            cookies=waf_cookies,
            callback=self.parse_ajax_token,
            meta={
                "challenge_retry": 0,
                "carried_cookies": dict(waf_cookies),
                "challenge_attempts": [],
                # Ask for the configured URL exactly as written. Newer w3lib
                # versions rewrite a bare host to `host/`, which would make the
                # URL the flow uses depend on the installed dependency version.
                "verbatim_url": True,
            },
        )

    def parse_ajax_token(self, response: HtmlResponse) -> Request:
        """
        Parse ajax token from response, retrying if the storefront never arrived.
        """
        ajax_token = self._get_ajax_token(response=response)
        if ajax_token is None:
            return self._retry_start(response=response, step=STOREFRONT_STEP)

        headers = self.build_headers({"anti-csrftoken-a2z": ajax_token})
        cookies = self._collect_cookies(
            response=response, base=self._carried_cookies(response=response)
        )
        return response.request.replace(
            url=self.countries_base_urls[self.country] + self.csrf_token_endpoint,
            headers=headers,
            cookies=cookies,
            callback=self.parse_cookies,
            cb_kwargs={"cookies": cookies},
            meta={**response.meta, "carried_cookies": cookies},
        )

    def build_payload(self) -> dict:
        """
        Build the address-change payload (implemented by child classes).
        """
        raise NotImplementedError

    def parse_cookies(self, response: HtmlResponse, cookies: dict[str, str]) -> Request:
        """
        Read the CSRF token and post the location change.

        This step gets bot-checked just like the first one, so a response without
        a CSRF token restarts the flow instead of failing the crawl.
        """
        csrf_token = self._get_csrf_token(response=response)
        if csrf_token is None:
            return self._retry_start(response=response, step=CSRF_STEP, cookies=cookies)

        headers = self.build_headers(
            {"content-type": "application/json", "anti-csrftoken-a2z": csrf_token}
        )
        cookies = self._collect_cookies(response=response, base=cookies)
        return Request(
            url=self.countries_base_urls[self.country] + self.address_change_endpoint,
            method="POST",
            body=json.dumps(self.build_payload()),
            headers=headers,
            cookies=cookies,
            callback=self.parse_result,
            cb_kwargs={"cookies": cookies},
            meta={
                "challenge_retry": response.meta.get("challenge_retry", 0),
                "carried_cookies": cookies,
                "challenge_attempts": list(
                    response.meta.get("challenge_attempts") or []
                ),
            },
        )

    @staticmethod
    def _token_was_rejected(response: HtmlResponse) -> bool:
        """
        Say whether the WAF turned the request away, as opposed to some other
        bot check. AWS WAF answers `202` and sets `x-amzn-waf-action`; only that
        means the cached token itself is worthless and has to be replaced.
        """
        return bool(response.status == 202 or response.headers.get("x-amzn-waf-action"))

    def _retry_start(
        self, response: HtmlResponse, step: str, cookies: dict[str, str] | None = None
    ) -> Request:
        """
        Start the whole flow over after a bot check answered in place of a page.

        Amazon serves those in several shapes -- a WAF challenge, an Akamai
        interstitial, occasionally a plain page missing the token being read --
        and they come and go, so any unusable response is retried rather than
        picked apart. Both steps of the flow can be hit, and either way the
        session is suspect, so the retry restarts from the storefront. Only a WAF
        rejection costs a new token; the rest reuse the cached one.

        Everything collected from the responses so far is carried into the
        retry: the storefront hands out a `session-id` on the first hit, and
        abandoning it meant every retry started a new Amazon session and threw
        away the progress already made. The newly harvested token still wins
        over any carried copy -- see `_collect_cookies`.
        """
        attempt = response.meta.get("challenge_retry", 0) + 1
        base_url = self.countries_base_urls[self.country]
        rejected = self._token_was_rejected(response=response)
        attempts = [*response.meta.get("challenge_attempts", [])]

        # Recorded before the cap is checked: an over-budget crawl still has to
        # say where the last block happened. `reharvested` stays false there,
        # because no harvest happened.
        blocked = {
            "step": step,
            "url": response.url,
            "status": response.status,
            "bytes": len(response.body),
            "waf_rejected": rejected,
            "reharvested": False,
        }
        attempts.append(blocked)

        if attempt > MAX_CHALLENGE_RETRIES:
            raise ValueError(
                f"No usable page from {base_url} after {MAX_CHALLENGE_RETRIES} "
                f"retries (last: {response.url}, HTTP {response.status}, "
                f"{len(response.body)} bytes); {self._format_attempts(attempts)}"
            )

        if rejected:
            self.logger.info(f"WAF rejected the token for {base_url}, harvesting anew")
            invalidate_waf_session(base_url=base_url)
            blocked["reharvested"] = True

        self.logger.info(
            f"Bot check instead of {response.url} (HTTP {response.status}, "
            f"{len(response.body)} bytes) at step {step}, "
            f"retry {attempt}/{MAX_CHALLENGE_RETRIES}"
        )
        waf_cookies, self.waf_user_agent = get_waf_session(base_url=base_url)
        # The CSRF step passes its cookies explicitly: they are the jar the
        # address-change POST was about to use, and the response's own `meta`
        # does not carry them. The storefront step relies on `meta` instead.
        carried = (
            cookies if cookies is not None else self._carried_cookies(response=response)
        )
        cookies = self._collect_cookies(
            response=response, base=carried, harvested=waf_cookies
        )
        return Request(
            url=base_url,
            headers=self.build_headers(),
            cookies=cookies,
            callback=self.parse_ajax_token,
            dont_filter=True,
            meta={
                "challenge_retry": attempt,
                "carried_cookies": cookies,
                "challenge_attempts": attempts,
                # Restart at the storefront exactly as the crawl began, rather
                # than at whatever form the URL normaliser would make of it. The
                # rest of the crawl depends on the configured URL, and a rewrite
                # here would also change the URL the tests and logs compare.
                "verbatim_url": True,
            },
        )

    def _carried_cookies(self, response: HtmlResponse) -> dict[str, str]:
        """
        Return the cookies collected up to this point in the flow.

        Taken from `meta` when the previous step recorded them, otherwise from
        the request that produced this response -- that jar is what was actually
        sent, and it is the best record of what the session has so far.
        """
        if carried := response.meta.get("carried_cookies"):
            return dict(carried)
        return dict(response.request.cookies) if response.request else {}

    def _collect_cookies(
        self,
        response: HtmlResponse,
        base: dict[str, str],
        harvested: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """
        Merge this response's `Set-Cookie` values into the cookies carried so far.

        `harvested` is the WAF session returned by `get_waf_session`; passing it
        -- even when it holds no token -- marks that a harvest just ran and that
        its token is the only one valid under the user agent now in use. An old
        token carried over from an earlier attempt was issued to a different
        browser and would be challenged on sight, so it is never brought back:
        once a harvest has run, a token-less harvest means the retry goes out
        without a token at all rather than with the stale one.

        Without a harvest (the steps that build the next request from a normal
        page) the response's own token is newest, and the token this request was
        sent with is the fallback.
        """
        response_cookies = extract_response_cookies(response=response)
        cookies = {**base, **response_cookies}

        if harvested is not None:
            token = harvested.get(WAF_TOKEN_COOKIE)
        else:
            token = response_cookies.get(WAF_TOKEN_COOKIE) or self._waf_token(
                response=response
            )

        if token:
            cookies[WAF_TOKEN_COOKIE] = token
        else:
            cookies.pop(WAF_TOKEN_COOKIE, None)
        return cookies

    @staticmethod
    def _waf_token(response: HtmlResponse) -> str | None:
        """
        Return the WAF token the request behind `response` carried, if any.
        """
        request = response.request
        return request.cookies.get(WAF_TOKEN_COOKIE) if request else None

    @staticmethod
    def _format_attempts(attempts: list[dict]) -> str:
        """
        Render the per-attempt record into one line for an exception message.
        """
        if not attempts:
            return "no bot checks recorded"
        parts = [
            f"attempt {number}: {item['step']} (HTTP {item['status']}, "
            f"{item['bytes']} bytes, "
            f"{'WAF-rejected' if item['waf_rejected'] else 'other bot check'}, "
            f"{'re-harvested' if item['reharvested'] else 'kept token'})"
            for number, item in enumerate(attempts, start=1)
        ]
        return f"{len(attempts)} bot checks: " + "; ".join(parts)

    @staticmethod
    def _challenge_report(attempts: list[dict], base_url: str) -> dict:
        """
        Describe how the crawl went in a form the caller can read.

        `total_attempts` counts passes over the storefront step, the blocked
        ones included, so a run that was never challenged reports one attempt
        and an empty `attempts` list. The report is returned beside the cookies,
        never merged into the jar that goes on the wire.
        """
        return {
            "total_attempts": len(attempts) + 1,
            "blocked_attempts": len(attempts),
            "attempts": [
                {
                    "step": item["step"],
                    "url": item["url"],
                    "status": item["status"],
                    "bytes": item["bytes"],
                    "waf_rejected": item["waf_rejected"],
                    "reharvested": item["reharvested"],
                }
                for item in attempts
            ],
            "store_url": base_url,
        }

    def parse_result(self, response: HtmlResponse, cookies: dict[str, str]) -> dict:
        """
        Check if confirmation string exists in Amazon response.
        If `isValidAddress` equal to 1 it means that location changed successfully.

        The returned dict holds the cookies plus a record of the bot checks the
        crawl went through. The record sits under `CHALLENGE_REPORT_KEY`, which
        is never a request cookie: the cookies in `cookies` were already sent as
        headers, so adding a field to that jar would put a value Amazon never
        set on the wire.
        """
        if '"isValidAddress":1' not in response.text:
            return {}

        report = self._challenge_report(
            attempts=response.meta.get("challenge_attempts") or [],
            base_url=self.countries_base_urls[self.country],
        )
        return {**cookies, CHALLENGE_REPORT_KEY: report}

    @staticmethod
    def _get_ajax_token(response: HtmlResponse) -> str | None:
        """
        Extract ajax token from response, or `None` if this is not a storefront.
        """
        selector = "//input[@id='glowValidationToken']/@value"
        return response.xpath(selector).get()

    @staticmethod
    def _get_csrf_token(response: HtmlResponse) -> str | None:
        """
        Extract CSRF token from response, or `None` if the page does not carry one.
        """
        selector, regex = "script", r'CSRF_TOKEN : "(.+?)"'
        return response.css(selector).re_first(regex)
