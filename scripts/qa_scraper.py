#!/usr/bin/env python3
"""IPLoop QA Scraper — test 10 major sites through proxy with real data extraction."""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

PROXY_HOST = "proxy.iploop.io"
PROXY_PORT = 8880
CHROME_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# ── Per-site outcome categories ──────────────────
OUTCOME_SUCCESS = "success"
OUTCOME_EXTRACTION_FAILED = "extraction_failed"
OUTCOME_BLOCKED = "blocked"
OUTCOME_NETWORK_ERROR = "network_error"
OUTCOME_UNKNOWN_SITE = "unknown_site"

BLOCK_STATUSES = {401, 403, 429}
PROXY_ERROR_STATUSES = {407, 502, 504}
BLOCK_KEYWORDS = (
    "captcha",
    "are you a robot",
    "verify you are human",
    "unusual traffic",
    "challenge-platform",
    "cf-browser-verification",
    "access denied",
    "request blocked",
    "you have been blocked",
    "enable javascript and cookies",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _say(message: str, stream=None) -> None:
    """Print without dying on consoles that cannot encode emoji (e.g. GBK)."""
    stream = stream or sys.stdout
    try:
        print(message, file=stream)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"),
              file=stream)


def _detect_block_reason(status: int, body: str) -> Optional[str]:
    """Return a human-readable interception reason, or None if not blocked."""
    lower = (body or "")[:4000].lower()
    keyword = next((word for word in BLOCK_KEYWORDS if word in lower), None)
    if status in BLOCK_STATUSES:
        if keyword:
            return f"HTTP {status} block response (matched '{keyword}')"
        return f"HTTP {status} block response"
    if keyword and status and status < 400:
        return f"HTTP {status} page contains block marker '{keyword}'"
    if keyword and status >= 500:
        return f"HTTP {status} error page contains block marker '{keyword}'"
    return None


# While a batch check is running, fetch()/fetch_scrapling() append low-level
# observations here. This records HTTP status/page size without changing what
# any existing extractor returns.
_FETCH_LOG: Optional[list] = None


def _record_fetch(url: str, status: int, body: str, error: Optional[str], source: str = "http"):
    if _FETCH_LOG is None:
        return
    body = body or ""
    page_size = len(body) if body else (0 if status else None)
    _FETCH_LOG.append({
        "url": url,
        "status": status or 0,
        "page_size": page_size,
        "error": error,
        "blocked_reason": _detect_block_reason(status or 0, body),
        "source": source,
    })

SITES = {
    "youtube": {
        "test_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "method": "api",
    },
    "reddit": {
        "test_url": "https://www.reddit.com/r/technology/.json?limit=5",
        "method": "scrapling",
    },
    "stocks": {
        "test_url": "https://query1.finance.yahoo.com/v8/finance/chart/TSLA?interval=1d&range=1d",
        "method": "api",
    },
    "amazon": {
        "test_url": "https://www.amazon.com/dp/B0BSHF7WHW",
        "method": "proxy_http",
    },
    "ebay": {
        "test_url": "https://www.ebay.com/sch/i.html?_nkw=iphone",
        "method": "proxy_http",
        "note": "JS-rendered, limited without browser",
    },
    "twitter": {
        "test_url": "https://x.com/NASA",
        "method": "scrapling",
    },
    "linkedin": {
        "test_url": "https://www.linkedin.com/company/google",
        "method": "scrapling",
    },

    "tiktok": {
        "test_url": "https://www.tiktok.com/@khaby.lame",
        "method": "proxy_http",
    },
    "instagram": {
        "test_url": "https://www.instagram.com/nasa/",
        "method": "scrapling",
        "note": "Login wall, limited without cookies",
    },
    "booking": {
        "test_url": "https://www.booking.com/city/gb/london.html",
        "method": "scrapling",
    },
    "walmart": {
        "test_url": "https://www.walmart.com/browse/electronics",
        "method": "scrapling",
        "note": "Anti-bot, needs Scrapling",
    },
    "target": {
        "test_url": "https://www.target.com/c/electronics/-/N-5xtg6",
        "method": "proxy_http",
    },
    "airbnb": {
        "test_url": "https://www.airbnb.com/s/Paris/homes",
        "method": "proxy_http",
    },
    "bestbuy": {
        "test_url": "https://www.bestbuy.com/site/computers-pcs/laptop-computers/abcat0502000.c",
        "method": "scrapling",
        "note": "Anti-bot, needs Scrapling",
    },
    "cloudflare_test": {
        "test_url": "https://nowsecure.nl",
        "method": "proxy_http",
    },
    "pinterest": {
        "test_url": "https://www.pinterest.com/search/pins/?q=cars",
        "method": "scrapling",
    },
    "zillow": {
        "test_url": "https://www.zillow.com/homes/New-York_rb/",
        "method": "scrapling",
        "note": "Anti-bot, needs Scrapling",
    },
    "shopify_store": {
        "test_url": "https://www.allbirds.com/collections/mens",
        "method": "proxy_http",
    },
    "imdb": {
        "test_url": "https://www.imdb.com/title/tt0111161/",
        "method": "proxy_http",
    },
    "wikipedia": {
        "test_url": "https://en.wikipedia.org/wiki/Proxy_server",
        "method": "proxy_http",
    },
    "hackernews": {
        "test_url": "https://news.ycombinator.com/",
        "method": "proxy_http",
    },
    "github": {
        "test_url": "https://github.com/trending",
        "method": "proxy_http",
    },
    "coingecko": {
        "test_url": "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd",
        "method": "api",
    },
    "spotify": {
        "test_url": "https://open.spotify.com/oembed?url=https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
        "method": "api",
    },
    "stackoverflow": {
        "test_url": "https://stackoverflow.com/questions?tab=votes",
        "method": "proxy_http",
    },
    "npm": {
        "test_url": "https://registry.npmjs.org/express",
        "method": "api",
    },
    "pypi": {
        "test_url": "https://pypi.org/pypi/requests/json",
        "method": "api",
    },
    "xkcd": {
        "test_url": "https://xkcd.com/info.0.json",
        "method": "api",
    },
    "exchangerate": {
        "test_url": "https://open.er-api.com/v6/latest/USD",
        "method": "api",
    },
    "spacex": {
        "test_url": "https://api.spacexdata.com/v4/launches/latest",
        "method": "api",
    },
    "pokemon": {
        "test_url": "https://pokeapi.co/api/v2/pokemon/pikachu",
        "method": "api",
    },
    "steam": {
        "test_url": "https://store.steampowered.com/app/730/CounterStrike_2/",
        "method": "proxy_http",
    },
    "goodreads": {
        "test_url": "https://www.goodreads.com/book/show/11127.The_Hitchhiker_s_Guide_to_the_Galaxy",
        "method": "proxy_http",
    },
    "archive_org": {
        "test_url": "https://archive.org/details/nasa",
        "method": "proxy_http",
    },
    "cnn": {
        "test_url": "https://www.cnn.com/",
        "method": "proxy_http",
    },
    "trustpilot": {
        "test_url": "https://www.trustpilot.com/review/amazon.com",
        "method": "proxy_http",
    },
    "weather": {
        "test_url": "https://api.open-meteo.com/v1/forecast?latitude=40.71&longitude=-74.01&current_weather=true",
        "method": "api",
    },
    "remoteok": {
        "test_url": "https://remoteok.com/api",
        "method": "api",
    },
    "craigslist": {
        "test_url": "https://newyork.craigslist.org/search/sss?query=laptop",
        "method": "proxy_http",
    },
    "nike": {
        "test_url": "https://www.nike.com/w/mens-shoes-nik1zy7ok",
        "method": "scrapling",
        "note": "Heavy anti-bot",
    },
    "wayfair": {
        "test_url": "https://www.wayfair.com/furniture/sb0/sofas-c413892.html",
        "method": "scrapling",
    },
    "homedepot": {
        "test_url": "https://www.homedepot.com/",
        "method": "scrapling",
    },
    "costco": {
        "test_url": "https://www.costco.com/televisions.html",
        "method": "scrapling",
    },
    "nordstrom": {
        "test_url": "https://www.nordstrom.com/browse/men/clothing",
        "method": "scrapling",
    },
    "newegg": {
        "test_url": "https://www.newegg.com/GPUs-Video-Graphics-Cards/SubCategory/ID-48",
        "method": "proxy_http",
    },
    "bbc": {
        "test_url": "https://www.bbc.com/news",
        "method": "proxy_http",
    },
    "nytimes": {
        "test_url": "https://www.nytimes.com/",
        "method": "scrapling",
        "note": "Paywall",
    },
    "quora": {
        "test_url": "https://www.quora.com/What-is-web-scraping",
        "method": "scrapling",
    },
    "medium": {
        "test_url": "https://medium.com/tag/python",
        "method": "proxy_http",
    },
    # ── Added to reach 66 presets ──
    "duckduckgo": {
        "test_url": "https://duckduckgo.com/?q=residential+proxy",
        "method": "proxy_http",
    },
    "bing": {
        "test_url": "https://www.bing.com/search?q=web+scraping",
        "method": "proxy_http",
    },
    "yahoo_news": {
        "test_url": "https://news.yahoo.com/",
        "method": "proxy_http",
    },
    "foxnews": {
        "test_url": "https://www.foxnews.com/",
        "method": "proxy_http",
    },
    "guardian": {
        "test_url": "https://www.theguardian.com/world",
        "method": "proxy_http",
    },
    "twitch": {
        "test_url": "https://www.twitch.tv/directory",
        "method": "scrapling",
    },
    "devto": {
        "test_url": "https://dev.to/",
        "method": "proxy_http",
    },
    "asos": {
        "test_url": "https://www.asos.com/men/",
        "method": "scrapling",
    },
    "ikea": {
        "test_url": "https://www.ikea.com/us/en/cat/sofas-fu003/",
        "method": "scrapling",
    },
    "apple": {
        "test_url": "https://www.apple.com/shop/buy-iphone",
        "method": "proxy_http",
    },
    "samsung": {
        "test_url": "https://www.samsung.com/us/smartphones/",
        "method": "proxy_http",
    },
    "coursera": {
        "test_url": "https://www.coursera.org/courses?query=python",
        "method": "scrapling",
    },
    "zappos": {
        "test_url": "https://www.zappos.com/men-shoes",
        "method": "scrapling",
    },
    "target_tech": {
        "test_url": "https://www.target.com/c/electronics/-/N-5xtg6",
        "method": "proxy_http",
    },
    "hulu": {
        "test_url": "https://www.hulu.com/welcome",
        "method": "scrapling",
    },
    "walmart_grocery": {
        "test_url": "https://www.walmart.com/cp/food/976759",
        "method": "scrapling",
    },
    "microsoft": {
        "test_url": "https://www.microsoft.com/en-us/windows",
        "method": "proxy_http",
    },
}


def make_proxy_url(api_key: str, country: Optional[str] = None) -> str:
    auth = f"iploop:{api_key}"
    if country:
        auth += f"-country-{country.upper()}"
    return f"http://{auth}@{PROXY_HOST}:{PROXY_PORT}"


def fetch(url: str, proxy_url: Optional[str] = None, timeout: int = 30) -> tuple:
    """Fetch URL, return (status, body, error)."""
    headers = {"User-Agent": CHROME_UA, "Accept": "text/html,application/json,*/*"}
    req = urllib.request.Request(url, headers=headers)

    handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}) if proxy_url else urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(handler)

    try:
        resp = opener.open(req, timeout=timeout)
        body = resp.read().decode("utf-8", errors="replace")
        _record_fetch(url, resp.status, body, None)
        return resp.status, body, None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if e.fp else ""
        _record_fetch(url, e.code, body, str(e))
        return e.code, body, str(e)
    except Exception as e:
        _record_fetch(url, 0, "", str(e))
        return 0, "", str(e)


def fetch_scrapling(url: str, proxy_url: Optional[str] = None, timeout: int = 30) -> tuple:
    """Fetch URL via Scrapling (anti-bot fingerprinting) + proxy, return (status, body, error)."""
    try:
        from scrapling import Fetcher
    except ImportError:
        return 0, "", "scrapling not installed (pip install scrapling curl_cffi browserforge)"

    f = Fetcher()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    try:
        kwargs = {"timeout": timeout}
        if proxies:
            kwargs["proxies"] = proxies
        r = f.get(url, **kwargs)
        body = r.body.decode("utf-8", errors="replace") if r.body else ""
        _record_fetch(url, r.status, body, None, source="scrapling")
        return r.status, body, None
    except Exception as e:
        _record_fetch(url, 0, "", str(e), source="scrapling")
        return 0, "", str(e)


# ── Extractors ──────────────────────────────────

def extract_youtube(url: str, proxy_url: Optional[str]) -> dict:
    oembed = f"https://noembed.com/embed?url={urllib.parse.quote(url, safe='')}"
    status, body, err = fetch(oembed)
    if err:
        return {"success": False, "error": err}
    try:
        data = json.loads(body)
        title = data.get("title", "")
        author = data.get("author_name", "")
        if title:
            return {"success": True, "title": title, "author": author, "source": "oEmbed"}
    except json.JSONDecodeError:
        pass
    return {"success": False, "error": "No title in oEmbed response"}


def extract_reddit(url: str, proxy_url: Optional[str]) -> dict:
    if not url.endswith(".json"):
        url = url.rstrip("/") + ".json"
    status, body, err = fetch(url, proxy_url)
    if err:
        return {"success": False, "error": err}
    try:
        data = json.loads(body)
        posts = []
        children = data.get("data", {}).get("children", []) if isinstance(data, dict) else (data[0]["data"]["children"] if isinstance(data, list) and data else [])
        for child in children[:10]:
            d = child.get("data", {})
            posts.append({"title": d.get("title", ""), "score": d.get("score", 0)})
        if posts:
            return {"success": True, "posts": len(posts), "sample": posts[0]["title"], "source": "JSON API"}
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return {"success": False, "error": "Could not parse Reddit JSON"}


def extract_stocks(url: str, proxy_url: Optional[str]) -> dict:
    status, body, err = fetch(url)
    if err:
        return {"success": False, "error": err}
    try:
        data = json.loads(body)
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice", 0)
        symbol = meta.get("symbol", "")
        prev = meta.get("previousClose", 0)
        change = round(price - prev, 2) if price and prev else None
        if price:
            return {"success": True, "symbol": symbol, "price": price, "change": change, "source": "Yahoo Finance API"}
    except (json.JSONDecodeError, KeyError, IndexError):
        pass
    return {"success": False, "error": "Could not parse Yahoo Finance"}


def extract_google(url: str, proxy_url: Optional[str]) -> dict:
    status, body, err = fetch(url, proxy_url)
    if err:
        return {"success": False, "error": err}
    results = re.findall(r'<a[^>]*href="(https?://[^"]+)"[^>]*><h3[^>]*>([^<]+)</h3>', body, re.I)
    if not results:
        results = re.findall(r'class="result[^"]*"[^>]*>.*?<a[^>]*href="(https?://[^"]+)"[^>]*>([^<]+)', body, re.I | re.S)
    if len(results) >= 3:
        return {"success": True, "results": len(results), "top": results[0][1], "source": "Startpage"}
    # Try alternate parsing
    h3s = re.findall(r'<h3[^>]*>([^<]+)</h3>', body)
    if len(h3s) >= 3:
        return {"success": True, "results": len(h3s), "top": h3s[0], "source": "Startpage (h3)"}
    return {"success": False, "error": f"Only {len(results)} results found", "page_size": len(body)}


def extract_amazon(url: str, proxy_url: Optional[str]) -> dict:
    status, body, err = fetch(url, proxy_url)
    if err:
        return {"success": False, "error": err}
    title_m = re.search(r'id="productTitle"[^>]*>([^<]+)', body)
    price_m = re.search(r'class="a-price-whole">([^<]+)', body)
    title = title_m.group(1).strip() if title_m else ""
    price = price_m.group(1).strip() if price_m else ""
    if title or price:
        return {"success": True, "title": title[:100], "price": price, "page_size": len(body), "source": "HTTP"}
    if len(body) > 50000:
        return {"success": True, "title": "(page loaded, extraction partial)", "page_size": len(body), "source": "HTTP"}
    return {"success": False, "error": "No product data", "page_size": len(body)}


def extract_linkedin(url: str, proxy_url: Optional[str]) -> dict:
    status, body, err = fetch(url, proxy_url)
    if err:
        return {"success": False, "error": err}
    name_m = re.search(r'<title>([^<]+)', body)
    emp_m = re.search(r'([\d,]+)\s*employees', body, re.I)
    name = name_m.group(1).strip() if name_m else ""
    employees = emp_m.group(1) if emp_m else ""
    if name and "LinkedIn" in name:
        return {"success": True, "name": name.split("|")[0].strip(), "employees": employees, "source": "HTTP"}
    return {"success": False, "error": "No company data", "page_size": len(body)}


def extract_generic(url: str, proxy_url: Optional[str], site_name: str) -> dict:
    status, body, err = fetch(url, proxy_url)
    if err:
        return {"success": False, "error": err}
    title_m = re.search(r'<title>([^<]+)', body)
    title = title_m.group(1).strip() if title_m else ""
    return {
        "success": len(body) > 10 and status >= 200 and status < 400,
        "title": title[:100],
        "page_size": len(body),
        "status": status,
        "source": "HTTP",
    }


EXTRACTORS = {
    "youtube": extract_youtube,
    "reddit": extract_reddit,
    "stocks": extract_stocks,
    "google": extract_google,
    "amazon": extract_amazon,
    "linkedin": extract_linkedin,
}


def extract_scrapling_generic(url: str, proxy_url: Optional[str], site_name: str) -> dict:
    """Fetch via Scrapling for anti-bot sites, extract title + page size."""
    status, body, err = fetch_scrapling(url, proxy_url)
    if err:
        # Fallback to regular proxy
        status, body, err = fetch(url, proxy_url)
        if err:
            return {"success": False, "error": err}
    title_m = re.search(r'<title>([^<]+)', body)
    title = title_m.group(1).strip() if title_m else ""
    blocked_words = ["captcha", "are you a robot", "blocked", "access denied", "verify you are human",
                      "unusual traffic", "challenge-platform", "cf-browser-verification"]
    lower_body = body.lower()[:3000]
    is_blocked = any(w in lower_body for w in blocked_words)
    # Don't count meta robots tag as blocked
    if is_blocked and 'name="robots"' in body[:3000]:
        is_blocked = any(w in lower_body for w in blocked_words if w != "robot")
    # Large pages with sign-in links aren't blocked (LinkedIn, etc)
    if is_blocked and len(body) > 100000:
        is_blocked = False
    return {
        "success": len(body) > 500 and status >= 200 and status < 400 and not is_blocked,
        "title": title[:100],
        "page_size": len(body),
        "status": status,
        "blocked": is_blocked,
        "source": "Scrapling" if not err else "HTTP fallback",
    }


def run_site(site_name: str, url: Optional[str], proxy_url: Optional[str],
             sites_config: Optional[dict] = None) -> dict:
    config = (sites_config or SITES).get(site_name)
    if not config:
        return {"success": False, "error": f"Unknown site: {site_name}",
                "site": site_name, "url": url, "method": None}
    test_url = url or config["test_url"]
    method = config["method"]

    # Default: always try Scrapling+proxy first, fallback to plain HTTP proxy
    if method == "api":
        extractor = EXTRACTORS.get(site_name, lambda u, p: extract_generic(u, p, site_name))
    elif site_name in EXTRACTORS:
        # Sites with custom extractors: try extractor first, scrapling fallback
        def combo_extractor(u, p, sn=site_name):
            result = EXTRACTORS[sn](u, p)
            if not result.get("success"):
                result = extract_scrapling_generic(u, p, sn)
            return result
        extractor = combo_extractor
    else:
        # Everything else: Scrapling+proxy by default
        extractor = lambda u, p: extract_scrapling_generic(u, p, site_name)

    needs_proxy = method != "api"
    result = extractor(test_url, proxy_url if needs_proxy else None)
    result["site"] = site_name
    result["url"] = test_url
    result["method"] = method
    if "note" in config:
        result["note"] = config["note"]
    return result


# ── Outcome classification ──────────────────────

def _resolve_blocked_reason(result: dict, fetch_events: list) -> Optional[str]:
    """Prefer the block evidence from the final fetch, then the extractor's own."""
    if fetch_events:
        reason = fetch_events[-1].get("blocked_reason")
        if reason:
            return reason
    reason = result.get("blocked_reason")
    if reason:
        return reason
    if result.get("blocked"):
        return "blocked page markers detected"
    return None


def classify_outcome(site_name: str, result: dict, fetch_events: list,
                     sites_config: Optional[dict] = None) -> str:
    """Map one site's raw result to a single explicit outcome category.

    Signals come from the final fetch the extractor performed (HTTP status and
    any interception markers in the body) plus whatever the extractor itself
    reported. A block or connection failure is never collapsed into a generic
    "failure".
    """
    if site_name not in (sites_config or SITES):
        return OUTCOME_UNKNOWN_SITE

    if result.get("success"):
        return OUTCOME_SUCCESS

    # An extractor that raised is a processing failure, not a connectivity one.
    if result.get("internal_error"):
        return OUTCOME_EXTRACTION_FAILED

    last = fetch_events[-1] if fetch_events else None
    status = result.get("status")
    if not status and last:
        status = last.get("status")
    status = status if isinstance(status, int) else 0

    blocked_reason = _resolve_blocked_reason(result, fetch_events)

    # No HTTP response at all, or a proxy/upstream status → connectivity problem.
    if status == 0 or status in PROXY_ERROR_STATUSES:
        return OUTCOME_NETWORK_ERROR
    # A definitive interception signal wins over a plain extraction failure.
    if blocked_reason or status in BLOCK_STATUSES:
        return OUTCOME_BLOCKED
    # 5xx without any block marker: the origin could not serve a usable page.
    if status >= 500:
        return OUTCOME_NETWORK_ERROR
    # The page answered, but the extractor could not produce data.
    return OUTCOME_EXTRACTION_FAILED


def build_outcome_entry(site_name: str, result: dict, fetch_events: list,
                        sites_config: Optional[dict] = None) -> dict:
    outcome = classify_outcome(site_name, result, fetch_events, sites_config)
    last = fetch_events[-1] if fetch_events else None

    status = result.get("status")
    if not status and last:
        status = last.get("status")
    http_status = status if isinstance(status, int) and status > 0 else None

    page_size = result.get("page_size")
    if page_size is None and last:
        page_size = last.get("page_size")
    if page_size is None:
        page_size = len(result["body"]) if isinstance(result.get("body"), str) else None

    blocked_reason = _resolve_blocked_reason(result, fetch_events) \
        if outcome == OUTCOME_BLOCKED else None
    if outcome == OUTCOME_BLOCKED and not blocked_reason:
        blocked_reason = "interception detected (blocked HTTP status)"

    error = result.get("error")
    if outcome == OUTCOME_UNKNOWN_SITE:
        error = error or f"Unknown site: {site_name}"
    elif outcome == OUTCOME_NETWORK_ERROR:
        if not error and last:
            error = last.get("error")
        error = error or "no HTTP response (connection or proxy failure)"
    elif outcome == OUTCOME_EXTRACTION_FAILED:
        error = error or "page fetched but extractor produced no data"

    entry = {
        "site": site_name,
        "outcome": outcome,
        "success": outcome == OUTCOME_SUCCESS,
        "http_status": http_status,
        "page_size": page_size,
        "error": error or None,
        "blocked_reason": blocked_reason,
        "url": result.get("url"),
        "method": result.get("method"),
        "checked_at": _now_iso(),
    }
    if "note" in result:
        entry["note"] = result["note"]
    return entry


# ── Persistent per-site outcome file ─────────────

REPORT_VERSION = 1


class ReportError(RuntimeError):
    """An existing report exists but cannot be trusted; refuse to overwrite it."""


def load_report(path: str) -> dict:
    """Load a prior outcome file. Returns {site_name: entry}.

    A missing file is normal (first run). An *unreadable* file is not: silently
    treating it as empty would overwrite previously written successes, so we
    refuse instead and let the operator inspect or move the file.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        raise ReportError(
            f"Cannot read existing report {path}: {exc}. "
            "Refusing to overwrite it (this would lose recorded outcomes). "
            "Move or delete the file to start a fresh run."
        ) from exc
    if isinstance(data, dict) and isinstance(data.get("sites"), dict):
        return {k: v for k, v in data["sites"].items() if isinstance(v, dict)}
    if isinstance(data, dict):
        return {k: v for k, v in data.items() if isinstance(v, dict) and "outcome" in v}
    raise ReportError(
        f"Report {path} does not look like a QA outcome file; refusing to overwrite it."
    )


def save_report(path: str, sites: dict, counts: dict, run_meta: Optional[dict] = None) -> None:
    """Atomically persist all per-site outcomes (one latest record per site)."""
    payload = {
        "version": REPORT_VERSION,
        "updated_at": _now_iso(),
        "counts": counts,
        "sites": {name: sites[name] for name in sorted(sites)},
    }
    if run_meta:
        payload["last_run"] = run_meta
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


# ── Batch runner ─────────────────────────────────

def run_batch(site_names: list, proxy_url: Optional[str],
              sites_config: Optional[dict] = None,
              report_path: Optional[str] = None,
              skip_successful: bool = True,
              verbose: bool = True) -> dict:
    """Run the batch check one site at a time, persisting each outcome immediately.

    A site whose latest recorded outcome is success is skipped by default; failed,
    blocked, extraction-failed or unknown sites are retried. Every site keeps
    exactly one latest record in the report, so writes survive an interruption.
    """
    global _FETCH_LOG
    config = sites_config or SITES
    ordered, seen = [], set()
    for name in site_names:
        if name not in seen:
            seen.add(name)
            ordered.append(name)

    prior = load_report(report_path) if report_path else {}
    counts = {
        "total": len(ordered),
        "executed": 0,
        "skipped": 0,
        "succeeded": 0,
        "failed": 0,
        "outcomes": {},
    }
    entries = dict(prior)

    for site_name in ordered:
        previous = prior.get(site_name)
        if skip_successful and previous and previous.get("outcome") == OUTCOME_SUCCESS:
            counts["skipped"] += 1
            if verbose:
                _say(f"⏭️  {site_name}: already {OUTCOME_SUCCESS} — skipped (resume)")
            continue

        _FETCH_LOG = []
        try:
            result = run_site(site_name, None, proxy_url, sites_config=config)
        except KeyboardInterrupt:
            # Persist everything completed so far, then let the caller stop.
            _FETCH_LOG = None
            counts["interrupted_at"] = site_name
            counts["outcomes"] = dict(sorted(counts["outcomes"].items()))
            counts["records_in_file"] = len(entries)
            counts["successful_in_file"] = sum(
                1 for entry in entries.values() if entry.get("outcome") == OUTCOME_SUCCESS
            )
            if report_path:
                save_report(report_path, entries, counts,
                            run_meta={"sites_requested": ordered, "resume": bool(skip_successful)})
            raise
        except Exception as exc:  # never let one site abort the batch
            result = {"success": False, "internal_error": True,
                      "error": f"{type(exc).__name__}: {exc}",
                      "site": site_name, "url": None, "method": None}
        events, _FETCH_LOG = _FETCH_LOG, None

        entry = build_outcome_entry(site_name, result, events, config)
        entries[site_name] = entry
        counts["executed"] += 1
        counts["outcomes"][entry["outcome"]] = counts["outcomes"].get(entry["outcome"], 0) + 1
        if entry["success"]:
            counts["succeeded"] += 1
        else:
            counts["failed"] += 1

        if report_path:
            save_report(report_path, entries, counts)

        if verbose:
            icon = "✅" if entry["success"] else "❌"
            detail = {k: v for k, v in entry.items() if k not in ("site", "url", "checked_at")}
            _say(f"{icon} {site_name} [{entry['outcome']}]: "
                 f"{json.dumps(detail, ensure_ascii=False)}")

    counts["outcomes"] = dict(sorted(counts["outcomes"].items()))
    counts["records_in_file"] = len(entries)
    counts["successful_in_file"] = sum(
        1 for entry in entries.values() if entry.get("outcome") == OUTCOME_SUCCESS
    )
    if report_path:
        save_report(report_path, entries, counts, run_meta={
            "sites_requested": ordered,
            "resume": bool(skip_successful),
        })
    return {"counts": counts, "entries": entries}


def load_sites_manifest(path: str) -> dict:
    """Load a custom site manifest: {name: {test_url, method}} or {"sites": {...}}."""
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict) and isinstance(data.get("sites"), dict):
        data = data["sites"]
    if not isinstance(data, dict) or not data:
        raise ValueError(f"Site manifest {path} must be a non-empty object of site configs")
    cleaned = {}
    for name, cfg in data.items():
        if not isinstance(cfg, dict) or "test_url" not in cfg:
            raise ValueError(f"Site manifest entry '{name}' needs at least 'test_url'")
        cleaned[name] = {
            "test_url": cfg["test_url"],
            "method": cfg.get("method", "proxy_http"),
        }
        if "note" in cfg:
            cleaned[name]["note"] = cfg["note"]
    return cleaned


def main():
    parser = argparse.ArgumentParser(description="IPLoop QA Scraper")
    parser.add_argument("--all", action="store_true", help="Test all sites")
    parser.add_argument("--site", type=str, help="Test single site")
    parser.add_argument("--url", type=str, help="Custom URL for --site")
    parser.add_argument("--api-key", type=str, default="testkey123", help="IPLoop API key")
    parser.add_argument("--country", type=str, help="Country code (US, DE, GB...)")
    parser.add_argument("--proxy-host", type=str, default=PROXY_HOST)
    parser.add_argument("--proxy-port", type=int, default=PROXY_PORT)
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--sites", type=str, nargs="+",
                        help="--all: only run these sites from the manifest/presets")
    parser.add_argument("--sites-file", type=str,
                        help="--all: JSON site manifest {name: {test_url, method}}")
    parser.add_argument("--report", "--results-file", dest="report", type=str,
                        help="--all: persist per-site outcomes to this JSON file")
    parser.add_argument("--no-resume", action="store_true",
                        help="--all: re-run sites already recorded as successful")
    parser.add_argument("--no-proxy", action="store_true",
                        help="--all: skip proxy routing entirely (local/test use)")
    parser.add_argument("--fail-on-error", action="store_true",
                        help="--all: exit nonzero if any site did not succeed")
    args = parser.parse_args()

    proxy_host = args.proxy_host
    proxy_port = args.proxy_port

    def _make_proxy(api_key, country=None):
        auth = f"iploop:{api_key}"
        if country:
            auth += f"-country-{country.upper()}"
        return f"http://{auth}@{proxy_host}:{proxy_port}"

    sites_config = SITES
    if args.sites_file:
        try:
            sites_config = load_sites_manifest(args.sites_file)
        except (OSError, ValueError) as exc:
            print(f"Error loading site manifest: {exc}", file=sys.stderr)
            sys.exit(2)

    proxy_url = None if args.no_proxy else _make_proxy(args.api_key, args.country)

    if args.site:
        result = run_site(args.site, args.url, proxy_url, sites_config=sites_config)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            status = "✅" if result.get("success") else "❌"
            _say(f"{status} {result['site']}: {json.dumps({k: v for k, v in result.items() if k not in ('site', 'url')}, ensure_ascii=False)}")
    elif args.all:
        if args.sites:
            missing = [name for name in args.sites if name not in sites_config]
            if missing:
                # Keep unknown sites visible as an explicit outcome instead of
                # silently dropping them from the run.
                for name in missing:
                    _say(f"⚠️  Unknown site (not in manifest): {name}", stream=sys.stderr)
            requested = list(args.sites)
        else:
            requested = list(sites_config)

        try:
            report = run_batch(
                requested, proxy_url,
                sites_config=sites_config,
                report_path=args.report,
                skip_successful=not args.no_resume,
                verbose=not args.json,
            )
        except ReportError as exc:
            _say(f"Error: {exc}", stream=sys.stderr)
            sys.exit(2)
        counts = report["counts"]
        if args.json:
            print(json.dumps({
                "passed": counts["succeeded"],
                "total": counts["total"],
                "counts": counts,
                "results": list(report["entries"].values()),
            }, indent=2, ensure_ascii=False))
        else:
            print(f"\n{'='*40}")
            print(f"Executed {counts['executed']}/{counts['total']} | "
                  f"Skipped {counts['skipped']} | Succeeded {counts['succeeded']}")
            print(f"Outcomes: {json.dumps(counts['outcomes'], ensure_ascii=False)}")
            if args.report:
                print(f"Report: {os.path.abspath(args.report)}")
        if args.fail_on_error and counts["failed"]:
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
