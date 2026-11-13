"""One adapter per upstream. Each knows its keys, how to price a call before making it, and how to call.

estimate(endpoint, body, fresh) -> USD upper bound for one call (fresh=False may read the price cache)
prepare(endpoint, body)        -> body to send (AnyAPI pins sources, Yir adds max_cost); may raise Stop
call(endpoint, body)           -> (raw result, charged USD, rows returned, ok)
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from getcheapapi import lanes as L
from getcheapapi.core import EXIT_NO_BALANCE, EXIT_UNAVAILABLE, NotServed, Refused, Stop, Unavailable, env, has_env, home, http, key_source, list_len, now, read_json, write_json

DAY = 86400
DATA_DIR = Path(__file__).resolve().parent / "data"


def snapshot(provider: str) -> dict:
    """Bundled cheapest-price snapshot {endpoint: usd}, used to compare providers the user has no key for."""
    return read_json(DATA_DIR / "prices.json", {}).get(provider, {})


class Provider:
    name = ""
    keys: tuple[str, ...] = ()
    site = ""

    @classmethod
    def configured(cls) -> bool:
        return has_env(*cls.keys)

    def credential_source(self) -> str:
        return key_source(*self.keys)

    def prepare(self, endpoint: str, body: dict) -> dict:
        return body

    def estimate(self, endpoint: str, body: dict, fresh: bool = True) -> float:
        raise NotImplementedError

    def call(self, endpoint: str, body: dict):
        raise NotImplementedError


class AnyAPI(Provider):
    name, keys, site = "anyapi", ("ANYAPI_API_KEY",), "https://getanyapi.com/?via=q89thkytbw"
    base = L.BASE

    def __init__(self, max_ratio: float = L.DEFAULT_MAX_RATIO):
        self.max_ratio = max_ratio
        self._pinned: dict[int, tuple[set, float]] = {}  # id(pinned body) -> (allowed sources, max price)

    def prepare(self, endpoint, body):
        """Pin to the cheap sources on fresh prices; refuse before any spend when only dearer ones fit."""
        try:
            pinned, allowed, price = L.pin(endpoint, body, L.fetch_lanes(endpoint, self.key), self.max_ratio)
        except L.PricierOnly as exc:
            hint = "" if isinstance(exc, L.PriceRose) else "(--max-ratio N raises the ratio.) "
            raise Refused(f"{exc}\n{hint}Show the user this table and wait for their decision.") from None
        self._pinned[id(pinned)] = (allowed, price)
        return pinned

    @property
    def key(self) -> str:
        return env("ANYAPI_API_KEY")

    def estimate(self, endpoint, body, fresh=True):
        if id(body) in self._pinned:
            return self._pinned[id(body)][1]
        if not self.configured():  # compare without a key: the bundled snapshot of cheapest prices
            price = snapshot("anyapi").get(endpoint)
            if price is None:
                raise Stop(f"anyapi {endpoint}: no key and no snapshot price")
            return float(price)
        return L.cheapest(L.fetch_lanes(endpoint, self.key, 0 if fresh else DAY), body)

    def call(self, endpoint, body):
        allowed, price = self._pinned[id(body)]
        try:
            result = http("POST", f"{self.base}/run/{endpoint}", {"X-API-Key": self.key}, body)
        except Stop as exc:
            if exc.code == EXIT_NO_BALANCE:
                raise
            if "invalid_input" in str(exc):  # bad fields: see `describe anyapi`
                raise NotServed(str(exc)) from None
            raise Unavailable(f"{exc}\nThe pinned source {sorted(allowed)} cannot serve it now (no charge). Wait and run "
                              f"the same command again; others cost more:\n{L.price_table(endpoint, body, L.fetch_lanes(endpoint, self.key))}\n"
                              "Ask the user before rerunning with --max-ratio N.", EXIT_UNAVAILABLE) from None
        cost = float(result.get("costUsd") or 0)
        if result.get("requestId") and result.get("nextAction") and not result.get("output"):
            return result, cost, 0, True  # async SKU accepted; the source is known only when polled
        problem = L.served_ok(result, allowed, price)
        if problem:
            raise Stop(f"AnyAPI {endpoint} {problem}; stopping.", cost=cost)
        output = result.get("output") or {}
        return result, cost, list_len(output.get("data")), True

    def balance(self):
        return http("GET", f"{self.base}/balance", {"X-API-Key": self.key})


# GoAnyAPI credits per successful call, used when its catalog gives no price (2026-11). $10 = 10,000 credits.
GOANY_CREDITS = {"backlink": 4, "dr": 2, "traffic": 6, "keyword-difficulty": 3, "keyword-generator": 3,
                 "keyword-suggestions": 1, "keyword-search-volume": 3, "serp": 3, "serp-standard": 2,
                 "serp-stable": 1, "bing-serp": 2, "google-intitle": 4, "google-site-search": 4,
                 "google-trends": 6, "transparency": 4, "adsense": 3, "ads-statistics": 5,
                 "html-to-markdown-api": 1}
GOANY_USD_PER_CREDIT = 0.001


class GoAnyAPI(Provider):
    name, keys, site = "goanyapi", ("GOANYAPI_API_KEY",), "https://goanyapi.com/r/ga-ccef6a6e4f"
    base = "https://api.goanyapi.com/api/v1"

    @property
    def key(self) -> str:
        return env("GOANYAPI_API_KEY")

    @staticmethod
    def credits(endpoint: str) -> int:
        cached = read_json(home() / "prices" / "goanyapi.json", {}).get("credits", {})
        return int(cached.get(endpoint) or GOANY_CREDITS.get(endpoint, 6))

    @classmethod
    def refresh_prices(cls) -> dict:
        """Fixed-credit prices from the public catalog (no key needed), merged over the built-in table."""
        apis = http("GET", f"{cls.base}/mcp/catalog", {}, timeout=60)["data"]["apis"]
        credits = dict(GOANY_CREDITS)
        for a in apis:
            p = a.get("pricing") or {}
            if p.get("kind") == "fixed" and p.get("credits") is not None:
                credits[a["id"]] = int(p["credits"])
            elif p.get("kind") == "free":
                credits[a["id"]] = 0
        write_json(home() / "prices" / "goanyapi.json", {"at": now(), "credits": credits})
        return credits

    def estimate(self, endpoint, body, fresh=True):
        return self.credits(endpoint) * GOANY_USD_PER_CREDIT

    def call(self, endpoint, body):
        query = urllib.parse.urlencode(body)
        result = http("GET", f"{self.base}/{endpoint}?{query}", {"Authorization": f"Bearer {self.key}"})
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        return result, float(data.get("costCredits") or 0) * GOANY_USD_PER_CREDIT, list_len(data), True

    def balance(self):
        return http("GET", f"{self.base}/credits/balance", {"Authorization": f"Bearer {self.key}"})


class DataForSEO(Provider):
    name, keys, site = "dataforseo", ("DATAFORSEO_LOGIN", "DATAFORSEO_PASSWORD"), "https://try.dataforseo.com/lhyz26vduxeo"
    base = "https://api.dataforseo.com/v3"

    @property
    def auth(self) -> dict:
        token = base64.b64encode(f"{env('DATAFORSEO_LOGIN')}:{env('DATAFORSEO_PASSWORD')}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def estimate(self, endpoint, body, fresh=True):
        """Published prices (2026-11); DataForSEO has no quote API."""
        limit = int(body.get("limit") or 100)
        if "task_get" in endpoint or "tasks_ready" in endpoint:
            return 0.0  # collecting a queued task is free; the charge was taken at task_post
        if endpoint.startswith("keywords_data/google_ads/"):
            return 0.09 if endpoint.endswith("/live") else 0.06
        if endpoint.startswith("backlinks/"):
            rows = len(body.get("targets") or []) or limit
            return 0.024 + 0.000036 * rows
        if endpoint.startswith("dataforseo_labs/"):
            return 0.012 + 0.00012 * limit
        if endpoint.startswith("serp/"):
            pages = max(1, int(body.get("depth") or 10) // 10)
            live = "/live/" in endpoint
            per_page = 0.002 if live else 0.0006
            ops = any(op in str(body.get("keyword", "")) for op in ("site:", "intitle:", "inurl:", "allinurl:"))
            return per_page * pages * (5 if ops else 1)
        return 0.05

    def call(self, endpoint, body):
        collect = "task_get" in endpoint or "tasks_ready" in endpoint
        result = http("GET" if collect else "POST", f"{self.base}/{endpoint}", self.auth, None if collect else [body])
        if result.get("status_code") in (40200, 40210):
            raise Stop(f"DataForSEO {result.get('status_code')}: {result.get('status_message')}", EXIT_NO_BALANCE)
        task = (result.get("tasks") or [{}])[0]
        ok = task.get("status_code", 0) < 40000
        if not ok and task.get("status_code") in (40200, 40210):
            raise Stop(f"DataForSEO {task['status_code']}: {task.get('status_message')}", EXIT_NO_BALANCE)
        items = sum(len(r.get("items") or []) for r in task.get("result") or [] if isinstance(r, dict))
        return result, float(result.get("cost") or 0), items, ok

    def balance(self):
        info = http("GET", f"{self.base}/appendix/user_data", self.auth)
        money = ((info.get("tasks") or [{}])[0].get("result") or [{}])[0].get("money") or {}
        return {"balanceUsd": money.get("balance"), "totalUsd": money.get("total")}


TWITTERAPI_USD_PER_ITEM = 0.00015  # per post; also the per-call minimum, charged on empty results
TWITTERAPI_USD_PER_USER = 0.00003  # followers/followings: 1-3 credits each, priced at the top
# Writes and logins name a verb in the last segment (create_tweet_v2, follow_user_v2, user_login_v2);
# monitoring lives under oapi/. Reads such as user/followers or tweet/retweeters stay allowed.
TWITTERAPI_WRITE = re.compile(r"(^|/)(create|delete|send|like|unlike|retweet|unretweet|follow|unfollow|"
                              r"user_login|login|upload|update|add|remove)_[^/]*$|^oapi/")


def twitterapi_unit(endpoint: str) -> float:
    return TWITTERAPI_USD_PER_USER if re.search(r"follow(er|ing)", endpoint, re.I) else TWITTERAPI_USD_PER_ITEM


class TwitterAPI(Provider):
    """Read-only. Writes, logins and monitoring are out of scope for a price router."""
    name, keys, site = "twitterapi", ("TWITTERAPI_IO_KEY",), "https://twitterapi.io/?ref=wn7a9fzv"
    base = "https://api.twitterapi.io"

    @property
    def key(self) -> str:
        return env("TWITTERAPI_IO_KEY")

    def estimate(self, endpoint, body, fresh=True):
        if TWITTERAPI_WRITE.search(endpoint.lstrip("/")):
            raise Stop("twitterapi.io writes, logins and monitoring are not routed by getcheapapi.")
        unit = twitterapi_unit(endpoint)
        if unit == TWITTERAPI_USD_PER_USER:
            return max(TWITTERAPI_USD_PER_ITEM, 200 * unit)  # pages of up to 200 users
        ids = body.get("tweet_ids") or body.get("userIds")
        return (len(str(ids).split(",")) if ids else 20) * unit  # list endpoints return pages of about 20 posts

    def call(self, endpoint, body):
        if TWITTERAPI_WRITE.search(endpoint.lstrip("/")):
            raise Stop("twitterapi.io writes, logins and monitoring are not routed by getcheapapi.")
        result = http("GET", f"{self.base}/{endpoint.lstrip('/')}?{urllib.parse.urlencode(body)}", {"X-API-Key": self.key})
        rows = list_len(result) or list_len(result.get("data"))
        # twitterapi.io returns no cost: credits per returned item, 15 minimum even when empty.
        cost = max(TWITTERAPI_USD_PER_ITEM, rows * twitterapi_unit(endpoint))
        return result, cost, rows, result.get("status", "success") != "error"

    def balance(self):
        return http("GET", f"{self.base}/oapi/my/info", {"X-API-Key": self.key})


YIR_TERMINAL = {"succeeded", "failed", "cancelled"}
YIR_PATHS = {"image": "/v1/images", "video": "/v1/videos", "audio": "/v1/audio", "3d": "/v1/3d"}


class Yir(Provider):
    """Image, video, audio and 3D generation. Yir starts on the model's cheapest channel; getcheapapi turns its
    failover off, since a failed attempt a channel billed is charged too, unless the input sets routing.fallback.
    It quotes before every job, caps it server-side with max_cost, and waits for the result.
    Text prompts only; reference uploads, batches and resumable jobs live in the yir skill/CLI."""
    name, keys, site = "yir", ("YIR_API_KEY",), "https://yir.ai/?utm_source=getcheapapi&utm_medium=cli"

    def __init__(self, timeout: int = 1800):
        self.base = (os.environ.get("YIR_BASE_URL") or "https://gateway.yir.ai").rstrip("/")
        self.timeout = timeout
        self._quotes: dict[str, dict] = {}

    @property
    def auth(self) -> dict:
        return {"Authorization": f"Bearer {env('YIR_API_KEY')}"}

    @staticmethod
    def request(body: dict) -> dict:
        """Capability body {model, prompt, parameters, input_type} -> Yir request body."""
        req = {"model": body["model"], "input": {"type": body.get("input_type", "text"), "prompt": body.get("prompt")},
               "parameters": body.get("parameters") or {}, "routing": {"fallback": False, **(body.get("routing") or {})}}
        return req

    def quote(self, kind: str, body: dict) -> dict:
        key = repr((kind, sorted(self.request(body).items(), key=str)))
        for attempt in range(3):  # quotes are free and idempotent: retry the gateway's transient 5xx
            if key in self._quotes:
                break
            try:
                self._quotes[key] = http("POST", f"{self.base}{YIR_PATHS[kind]}/quotes", self.auth, self.request(body), timeout=90)
            except Stop as exc:
                if not str(exc).startswith("HTTP 5") or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
        return self._quotes[key]

    @staticmethod
    def amount(q: dict) -> float | None:
        value = q.get("expected_amount")
        if value is None:
            value = (q.get("primary") or {}).get("amount")
        return None if value is None else float(value)

    def estimate(self, endpoint, body, fresh=True):
        q = self.quote(endpoint, body)
        if not (q.get("supply") or {}).get("available", True):
            raise Stop(f"Yir {body['model']}: no channel can take this spec now ({q.get('supply')}).")
        amount = self.amount(q)
        if amount is None:
            raise Stop(f"Yir {body['model']}: quote has no price for this spec; not running without one.")
        return amount

    def official(self, endpoint, body) -> float | None:
        o = (self.quote(endpoint, body).get("official") or {}).get("amount")
        return None if o is None else float(o)

    def prepare(self, endpoint, body):
        # Cap the job at the quote plus 10% headroom; Yir refuses with YIR_BUDGET_EXCEEDED past it.
        return {**body, "max_cost": f"{self.estimate(endpoint, body) * 1.1:.4f}"}

    def call(self, endpoint, body):
        req = {**self.request(body), "max_cost": body["max_cost"]}
        job = http("POST", f"{self.base}{YIR_PATHS[endpoint]}/generations",
                   {**self.auth, "Idempotency-Key": str(uuid.uuid4())}, req)
        start = time.time()
        while job.get("status") not in YIR_TERMINAL:
            if time.time() - start > self.timeout:
                raise Stop(f"Yir job {job.get('id')} still {job.get('status')} after {self.timeout}s; "
                           "it may still be charged. Check it later with the yir CLI: job <id>.")
            status = http("GET", f"{self.base}/v1/jobs/{job['id']}/status?wait=20", self.auth, timeout=60)
            if status.get("status") in YIR_TERMINAL:
                job = http("GET", f"{self.base}/v1/jobs/{job['id']}", self.auth)
            else:
                job = {**job, **status}
        charged = float((job.get("billing") or {}).get("total_charged_by_yir") or 0)
        files = (job.get("result") or {}).get("files") or []
        return job, charged, len(files), job.get("status") == "succeeded"

    def download(self, job: dict, out_dir: Path, stem: str) -> list[str]:
        import urllib.request
        paths = []
        files = (job.get("result") or {}).get("files") or []
        for i, f in enumerate(files):
            ext = Path(urllib.parse.urlparse(f["url"]).path).suffix or ".bin"
            path = out_dir / f"{stem}{f'-{i + 1}' if len(files) > 1 else ''}{ext}"
            out_dir.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(f["url"], timeout=300) as resp:  # signed URL, no key sent
                path.write_bytes(resp.read())
            paths.append(str(path))
        return paths

    def balance(self):
        return http("GET", f"{self.base}/v1/balance", self.auth)


class GoogleAds(Provider):
    name, site = "googleads", "https://developers.google.com/google-ads/api/docs/oauth/single-user-authentication"
    base = "https://googleads.googleapis.com/v26"
    endpoints = ("generateKeywordHistoricalMetrics", "generateKeywordIdeas")
    month_names = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
                   "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")
    # https://developers.google.com/google-ads/api/data/codes-formats#languages
    languages = {
        "ar": 1019, "bg": 1020, "bn": 1056, "ca": 1038, "cs": 1021, "da": 1009,
        "de": 1001, "el": 1022, "en": 1000, "es": 1003, "et": 1043, "fa": 1064,
        "fi": 1011, "fr": 1002, "gu": 1072, "he": 1027, "hi": 1023, "hr": 1039,
        "hu": 1024, "id": 1025, "is": 1026, "it": 1004, "iw": 1027, "ja": 1005,
        "kn": 1086, "ko": 1012, "lt": 1029, "lv": 1028, "ml": 1098, "mr": 1101,
        "ms": 1102, "nl": 1010, "no": 1013, "pa": 1110, "pl": 1030, "pt": 1014,
        "ro": 1032, "ru": 1031, "sk": 1033, "sl": 1034, "sr": 1035, "sv": 1015,
        "ta": 1130, "te": 1131, "th": 1044, "tl": 1042, "tr": 1037, "uk": 1036,
        "ur": 1041, "vi": 1040, "zh_cn": 1017, "zh_tw": 1018,
    }

    def __init__(self):
        self._token = ""
        self._token_expires = 0.0
        self._next_request = 0.0
        self._discovered_customer = ""

    @staticmethod
    def oauth_file() -> Path:
        configured = os.environ.get("GOOGLE_ADS_OAUTH_FILE", "").strip()
        return Path(configured).expanduser() if configured else home() / "google-ads-oauth.json"

    @classmethod
    def configured(cls) -> bool:
        return cls.oauth_file().is_file()

    def credential_source(self) -> str:
        return str(self.oauth_file()) if self.configured() else "not configured"

    def balance(self) -> dict:
        return {"provider": self.name, "costPerCallUsd": 0, "quota": "Google Cloud Console"}

    def request_body(self, endpoint: str, body: dict) -> dict:
        if endpoint not in self.endpoints:
            raise Refused(f"googleads: supported endpoints are {', '.join(self.endpoints)}")
        location = str(body.get("location_code", 2840))
        if not re.fullmatch(r"[1-9][0-9]*", location):
            raise Refused("googleads: location_code must be a Google Ads geographic criterion ID")
        language = self.languages.get(str(body.get("language_code", "en")).lower().replace("-", "_"))
        if language is None:
            raise Refused("googleads: language_code must be a supported Google Ads language code")
        request = {"geoTargetConstants": [f"geoTargetConstants/{location}"],
                   "language": f"languageConstants/{language}", "keywordPlanNetwork": "GOOGLE_SEARCH"}
        request |= self.month_range(body)
        if endpoint == "generateKeywordIdeas":
            if body.get("device") is True:  # Google totals all returned ideas per device; no per-keyword split
                request["aggregateMetrics"] = {"aggregateMetricTypes": ["DEVICE"]}
            return request | self.idea_seed(body)
        return request | {"keywords": self.terms(body.get("keywords"), 10000)}

    @staticmethod
    def terms(keywords, most: int) -> list[str]:
        if (not isinstance(keywords, list) or not 1 <= len(keywords) <= most
                or any(not isinstance(term, str) or not term.strip() for term in keywords)):
            raise Refused(f"googleads: keywords must contain 1 to {most} non-empty strings")
        return keywords

    def idea_seed(self, body: dict) -> dict:
        keywords = body.get("keywords") or ([body["keyword"]] if body.get("keyword") else None)
        url, site = body.get("url"), body.get("site")
        if site and (keywords or url):
            raise Refused("googleads: site cannot be combined with keywords or url")
        if url is not None and not (isinstance(url, str) and re.fullmatch(r"https?://\S+", url)):
            raise Refused("googleads: url must start with http:// or https://")
        if site is not None and not (isinstance(site, str) and re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}", site)):
            raise Refused("googleads: site must be a bare domain such as example.com")
        limit = body.get("limit", 100)
        if not isinstance(limit, int) or not 1 <= limit <= 10000:
            raise Refused("googleads: limit must be an integer from 1 to 10000")
        page = {"pageSize": limit}
        if site:
            return page | {"siteSeed": {"site": site}}
        if keywords and url:
            return page | {"keywordAndUrlSeed": {"url": url, "keywords": self.terms(keywords, 20)}}
        if keywords:
            return page | {"keywordSeed": {"keywords": self.terms(keywords, 20)}}
        if url:
            return page | {"urlSeed": {"url": url}}
        raise Refused("googleads: keyword ideas need keyword, keywords, url or site")

    @staticmethod
    def month_range(body: dict) -> dict:
        """Optional month range, YYYY-MM, start and end together; Google's default is the last 12 months."""
        options = {}
        start, end = body.get("start_month"), body.get("end_month")
        if start or end:
            months = []
            for value in (start, end):
                match = re.fullmatch(r"(20[0-9]{2})-(0[1-9]|1[0-2])", str(value or ""))
                if not match:
                    raise Refused("googleads: start_month and end_month must both be YYYY-MM")
                months.append({"year": int(match[1]), "month": GoogleAds.month_names[int(match[2]) - 1]})
            if (start, end) != tuple(sorted((start, end))):
                raise Refused("googleads: start_month must not be after end_month")
            options["historicalMetricsOptions"] = {"yearMonthRange": {"start": months[0], "end": months[1]}}
        return options

    def estimate(self, endpoint, body, fresh=True):
        self.request_body(endpoint, body)
        return 0.0

    def access_token(self) -> str:
        if time.monotonic() < self._token_expires:
            return self._token
        fields = ("client_id", "client_secret", "refresh_token")
        try:
            credentials = read_json(self.oauth_file(), {})
        except OSError:
            raise Refused("googleads: could not read the local OAuth JSON file") from None
        if not isinstance(credentials, dict) or not all(
            isinstance(credentials.get(field), str) and credentials[field].strip() for field in fields
        ):
            raise Refused("googleads: configure an authorized-user OAuth JSON with a refresh token")
        form = {field: credentials[field] for field in fields}
        form["grant_type"] = "refresh_token"
        req = urllib.request.Request("https://oauth2.googleapis.com/token", urllib.parse.urlencode(form).encode())
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.load(response)
            token, expires_in = data["access_token"], int(data["expires_in"])
        except urllib.error.HTTPError as exc:
            raise NotServed(f"googleads: OAuth token refresh failed (HTTP {exc.code})") from None
        except (KeyError, TypeError, ValueError):
            raise NotServed("googleads: invalid OAuth token response") from None
        if not isinstance(token, str) or not token or expires_in <= 0:
            raise NotServed("googleads: invalid OAuth token response")
        self._token = token
        self._token_expires = time.monotonic() + max(0, expires_in - 60)
        return token

    @staticmethod
    def customer_id(variable: str) -> str:
        value = os.environ.get(variable, "").strip().replace("-", "")
        if value and not re.fullmatch(r"[0-9]{10}", value):
            raise Refused(f"googleads: {variable} must be a 10-digit Google Ads customer ID")
        return value

    def call(self, endpoint, body):
        request = self.request_body(endpoint, body)
        customer = self.customer_id("GOOGLE_ADS_CUSTOMER_ID") or self._discovered_customer
        manager = self.customer_id("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
        if manager and not customer:
            raise Refused("googleads: set GOOGLE_ADS_CUSTOMER_ID when using a manager account")
        headers = {"Authorization": f"Bearer {self.access_token()}"}
        if not customer:
            names = http("GET", f"{self.base}/customers:listAccessibleCustomers", headers, timeout=40).get("resourceNames", [])
            if len(names) != 1 or not re.fullmatch(r"customers/[0-9]{10}", names[0]):
                raise Refused("googleads: set GOOGLE_ADS_CUSTOMER_ID to select an accessible Ads account")
            customer = self._discovered_customer = names[0].split("/")[1]
        if manager:
            headers["login-customer-id"] = manager
        delay = self._next_request - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self._next_request = time.monotonic() + 1
        result = http("POST", f"{self.base}/customers/{customer}:{endpoint}", headers, request, timeout=60)
        return result, 0.0, len(result.get("results", [])), True


PROVIDERS: dict[str, type[Provider]] = {p.name: p for p in (AnyAPI, GoAnyAPI, DataForSEO, TwitterAPI, Yir, GoogleAds)}
