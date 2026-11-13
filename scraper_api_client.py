"""
wellfound-scraper — 2captcha Scraper API edition (fourth engine)

Fetches one page through the 2captcha Scraper API, which renders it on
2captcha's infrastructure and returns the HTML over plain HTTPS, and feeds it
to this project's product_parser.

When this path is the right one
-------------------------------
Every route this scraper reads is an ordinary HTML page whose payload is
serialised inside it, so there is no endpoint to prefer and no JavaScript to
execute after load — which makes a rendered-HTML service a genuinely good
fit for all three modes.

What decides whether it works is the EXIT, not the rendering. Measured
2026-09-17: from a datacenter address Wellfound answers HTTP 403 with a
Cloudflare challenge on every route, `robots.txt` included; from a
residential US exit it answered 200 on `/`, `/jobs`, every `/role/…` shape
and `/jobs/{id}-{slug}`, three times out of three. The Scraper API's own
exits are datacenter addresses, so pass `--cdp-url` to route the request
through a Scraping Browser session with a residential country segment.

`/company/{slug}` is refused from a residential exit too, and there is no
mode for it here.

    python3 scraper_api_client.py \
        --url "https://wellfound.com/role/r/software-engineer"

    # TWOCAPTCHA_KEY and the CDP endpoint are read from .env as
    # $WELLFOUND_CDP_ENDPOINT, so neither needs to be typed — a secret in
    # argv is readable by anything that can run `ps`.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from typing import Optional

import requests

from product_parser import (BOT_CHALLENGE_MARKERS, MODES, DEFAULT_MODE,
                            category_from_url,
                            detect_bot_challenge, detect_page_state,
                            parse_products, parse_detail)
from output_writer import finish_run, SOURCE_DEFAULT
import env_config
import page_flow

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scraper_api_client")

API_BASE = "https://scraper.2captcha.com"
SYNC_ENDPOINT = f"{API_BASE}/tasks/sync"

# The API caps `timeout` at 120s and rejects bodies over 10,000 bytes.
MAX_API_TIMEOUT = 120

# Exit codes. Kept distinct from 2 (bad usage) on purpose: a remote API
# failing is not the operator passing wrong arguments, and a harness that
# lumps them together sends you looking in the wrong place. An early run
# reported `exit=2` for an HTTP 422 from the API — which reads as "you called
# it wrong".
#
# Imported rather than redefined: the browser engines return the same code for
# a Scraping Browser that will not accept a connection, and two definitions
# of one exit code is how a family's contract drifts.
from output_writer import EXIT_API_ERROR  # noqa: E402

def _mask_credentials(url: str) -> str:
    """Never print a username:password embedded in a ws://... or http://... URL."""
    if "@" not in url:
        return url
    scheme_sep = url.find("://")
    if scheme_sep == -1:
        return url
    scheme, rest = url[:scheme_sep + 3], url[scheme_sep + 3:]
    _, _, host_part = rest.partition("@")
    return f"{scheme}***:***@{host_part}"


# Credentials embedded ANYWHERE in a blob of text, not just in a string that
# is entirely a URL — and every occurrence, not the first. A masker that
# handles one occurrence prints the password the other four times and looks
# like it is working.
_CREDS_IN_TEXT_RE = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s'\"@]+@", re.IGNORECASE)
# Same shape as captcha_solver's and fingerprint_client's. A third copy is
# one too many and they should be unified in a family pass; reaching into
# another module's private name to avoid it would be worse.
_KEY_IN_TEXT_RE = re.compile(
    r"((?:client)?key|token|api[_-]?key)=([^&\s'\"]{6,})", re.IGNORECASE)


def _redact_debug_header(value: str) -> str:
    """The x-debug header, safe to log.

    SECURITY.md names this header as one of three places credentials reach a
    log unmasked, and it was logged verbatim: the API echoes back the task it
    ran, so a run driven through a credentialed CDP endpoint put that
    endpoint's username and password into the log, and a key passed as a
    query parameter would go the same way.

    Redaction rather than an allowlist of fields, deliberately: the header is
    the API's own metadata and its shape is not ours to pin, so an allowlist
    would silently drop the cost and timing figures this is logged FOR the
    first time the API adds a field.
    """
    return _KEY_IN_TEXT_RE.sub(r"\1=***",
                               _CREDS_IN_TEXT_RE.sub(r"\1***:***@", value))


def _build_wait_for(args) -> Optional[dict]:
    """`waitFor` is sent as a JSON OBJECT.

    Measured 2026-09-23 against /tasks/sync: the JSON-encoded STRING form
    this client used to send (on the strength of the API docs of the time)
    is now answered HTTP 422, "params.waitFor must be an object" -- and the
    task is still billed ($0.0005). The same request with an object is
    answered HTTP 200.

    Default (no flag): wait for the DOM. On a challenge-protected page
    that resolves instantly against the challenge page itself — which is
    exactly the trap documented in this module's docstring, so
    --wait-text/--wait-element exist to wait on something only the real
    page can contain."""
    if args.wait_text:
        return {"text": args.wait_text}
    if args.wait_element:
        return {"element": args.wait_element, "checkVisible": True}
    if args.wait_state:
        return {"state": args.wait_state}
    return None


def fetch_html(args) -> str:
    payload = {
        "task_type": "scrape",
        "url": args.url,
        "data_format": "raw",   # we want HTML; product_parser does the rest
        "format": "json",       # so we get {"status", "headers", "body"}
        "timeout": min(args.timeout, MAX_API_TIMEOUT),
    }

    wait_for = _build_wait_for(args)
    if wait_for:
        payload["waitFor"] = wait_for
        logger.info("waitFor: %s", json.dumps(wait_for))

    if args.cdp_url:
        payload["cdpurl"] = args.cdp_url
        logger.info("Routing through an existing browser session: %s",
                    _mask_credentials(args.cdp_url))

    logger.info("POST %s (url=%s)", SYNC_ENDPOINT, args.url)
    resp = requests.post(
        SYNC_ENDPOINT,
        headers={"Authorization": f"Bearer {args.key}", "Content-Type": "application/json"},
        json=payload,
        # Give the HTTP call more headroom than the API-side task timeout,
        # otherwise a task that legitimately runs the full 120s looks like
        # a client-side network failure.
        timeout=min(args.timeout, MAX_API_TIMEOUT) + 30,
    )

    # The API returns its own per-task metadata (price, timings, status)
    # in an x-debug header — worth logging, it's the only place the real
    # cost of the call shows up.
    debug = resp.headers.get("x-debug")
    if debug:
        logger.info("x-debug: %s", _redact_debug_header(debug))

    if resp.status_code != 200:
        # 422 = task ran but errored (this is what a bad/unreachable
        # cdpurl produces: "CDP connect failed (user cdpurl) after N
        # attempts"); 402 = out of balance; 408 = sync wait exceeded.
        raise RuntimeError(
            f"Scraper API returned HTTP {resp.status_code}: {resp.text[:500]}"
        )

    body = resp.json()
    html = body.get("body") or ""
    # The TARGET's HTTP status is `http_code` (an int). `status` is the
    # API's own verdict STRING ("success"), which this line used to read --
    # so a target 403 or 503 reached the classifier as "success" and was
    # never seen (measured 2026-09-23). `status` is kept as a fallback only
    # when it really is an int.
    upstream_status = body.get("http_code")
    if not isinstance(upstream_status, int):
        raw = body.get("status")
        upstream_status = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
    logger.info("Upstream page status (http_code) %s, %d bytes of HTML.", upstream_status, len(html))
    # The STATUS is returned alongside the HTML, not thrown away. It used to
    # be, and that cost this engine the family's central distinction. On this
    # site a refusal carries no markup at all — nothing a challenge check
    # on it, so the challenge check below finds nothing and the run fell
    # through to "0 products" and exit 4. A pipeline branching on the exit
    # code then reads a block as an empty category. See detect_page_state,
    # which the three browser engines already reach through page_flow.
    return html, upstream_status


def main() -> int:
    args = parse_args()

    if not args.key:
        logger.error("No 2captcha API key. Pass --key, or better, export TWOCAPTCHA_KEY.")
        return 2

    # A challenge page is not necessarily final (see _run_once), so a
    # single attempt is not evidence. Each retry is a fresh billable task —
    # $0.0005 at the observed rate — so the default is deliberately low.
    attempts = max(1, args.retries + 1)
    for attempt in range(1, attempts + 1):
        rc = _run_once(args, attempt, attempts)
        if rc != 3 or attempt == attempts:
            return rc
        logger.info("Challenge page on attempt %d/%d — retrying in %ds.",
                    attempt, attempts, args.retry_delay)
        time.sleep(args.retry_delay)
    return rc


def _run_once(args, attempt: int = 1, attempts: int = 1) -> int:
    if attempts > 1:
        logger.info("Attempt %d/%d", attempt, attempts)

    try:
        html, upstream_status = fetch_html(args)
    except requests.RequestException as e:
        logger.error("Network error talking to the Scraper API: %s", e)
        return EXIT_API_ERROR
    except RuntimeError as e:
        # HTTP 4xx/5xx from the API, including the 422 that a busy or
        # unreachable cdpurl produces.
        logger.error("%s", e)
        return EXIT_API_ERROR

    if args.dump_html:
        with open(args.dump_html, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info("Raw HTML written to %s", args.dump_html)

    # Same policy as the browser engines: the status decides the blocked
    # case, because this site's refusal has no marker to detect.
    state = detect_page_state(html, status=upstream_status, url=args.url,
                              mode=args.mode)
    if state == "not_found":
        # A 404 is the site's own definitive answer — the job is gone — so it
        # is a genuine empty result (exit 4), not a parse failure, exactly as
        # in the browser engines.
        logger.warning("Wellfound answered HTTP 404 for %s: nothing there.",
                       args.url)
        return finish_run([], args.out, args.format, args.allow_empty,
                          blocked=False, stop_reason="completed",
                          pages_requested=1, pages_completed=1,
                          pages_failed=[], mode=args.mode,
                          source=SOURCE_DEFAULT, start_url=args.url,
                          final_url=args.url,
                          extra={"category": args.category
                                 or category_from_url(args.url),
                                 "via": "scraper_api"})
    if state == "blocked":
        dump = f"{args.out}_scraperapi_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html)
        logger.error(
            "Wellfound did not serve the Scraper API's request (upstream HTTP %s, "
            "%d bytes) — saved to %s. Measured 2026-09-17 on "
            "/role/r/software-engineer, two attempts: the Scraper API's own "
            "exits are datacenter addresses and Wellfound refuses them "
            "(upstream 403, 11,825 bytes, both times), while the SAME task "
            "routed through a Scraping Browser session returned upstream 200 "
            "with 610,897 bytes and parsed 37 job rows. Pass --cdp-url. This "
            "is exit 3, distinct from an empty result (exit 4).",
            upstream_status, len(html), dump)
        return 3

    vendor = detect_bot_challenge(html)
    if vendor:
        logger.error(
            "The Scraper API returned a %s bot-challenge page (%d bytes), not real content.",
            vendor, len(html),
        )
        logger.error("A challenge page is not a final answer — retry before "
                     "concluding anything (--retries). On Wellfound what "
                     "clears it is the EXIT: measured 2026-09-17, a "
                     "residential US exit was served 200 on every route this "
                     "client reads, three times out of three, while a "
                     "datacenter address was refused on all of them. Pass "
                     "--cdp-url to route through a Scraping Browser session, "
                     "or use playwright_scraper.py directly with a "
                     "residential --proxy.")
        return 3

    if args.mode == "job":
        row = parse_detail(html, args.url)
        products = [row] if row is not None else []
    else:
        products = parse_products(html, args.url, mode=args.mode)
    logger.info("Parsed %d job(s).", len(products))

    # `--category` is a RUN LABEL, not a column. It used to be assigned to
    # each row as `row.category`, and `JobPosting` has no such field — so
    # Python attached a dynamic attribute that `asdict()` never sees, and
    # the flag silently did nothing. It goes in the sidecar, which is where
    # the browser engines put it too.
    label = args.category or category_from_url(args.url)

    # A page the API SERVED that parses to nothing is this repo's bug, not
    # an empty catalogue. It used to return 4 — the same
    # conflation the engines carried until this audit — so it now reports a
    # non-complete stop reason, which `finish_run` maps to exit 5 and never
    # to "no jobs".
    if not products:
        dump = f"{args.out}_scraperapi_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html)
        logger.warning("0 jobs parsed from a page the API served (%d bytes) "
                       "— saved to %s. That is a parser failure, not an "
                       "empty listing.", len(html), dump)
        stop = "content_not_obtained_parse_error"
    else:
        stop = "completed"

    return finish_run(products, args.out, args.format, args.allow_empty,
                      blocked=False, stop_reason=stop,
                      pages_requested=1, pages_completed=1 if products else 0,
                      pages_failed=[] if products else [1],
                      mode=args.mode, source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=args.url,
                      extra={"category": label, "via": "scraper_api"})


def parse_args():
    p = argparse.ArgumentParser(
        description="Wellfound scraper — 2captcha Scraper API edition (no local "
                    "browser). What decides success is the EXIT: its own "
                    "server-rendered page and a good fit. NOT the way to "
                    "browser needed). What decides success is the EXIT: "
                    "ordinary HTTPS request with no key and no proxy, so "
                    "paying for a rendered page there buys nothing. "
                    "--cdp-url is REQUIRED — the Scraper API's own exits are "
                    "datacenter addresses and Wellfound refuses them.")
    # NOT required: prefer the TWOCAPTCHA_KEY env var. A key passed on the
    # command line is visible to anyone who can run `ps`, and it lands in
    # shell history and in any log that echoes the command line.
    p.add_argument("--key", default=os.environ.get("TWOCAPTCHA_KEY"),
                   help="2captcha.com API key (sent as a Bearer token). "
                        "Defaults to $TWOCAPTCHA_KEY, which is the safer way to pass it.")
    p.add_argument("--url", default=None,
                   help="A wellfound.com URL: a /role/… landing page, "
                        "/jobs, or /jobs/{id}-{slug} with --mode job. Used if "
                        "endpoint answers that for free. Required, unless "
                        "WELLFOUND_URL is set in the environment or .env.")
    p.add_argument("--mode", choices=list(MODES),
                   default=DEFAULT_MODE,
                   help="Which page kind to read (default %(default)s). "
                        "The same three the browser engines take; this path "
                        "renders the page remotely instead of locally.")
    p.add_argument("--category", default=None,
                   help="Label for the RUN, recorded in the sidecar — not a "
                        "column on the rows. Defaults to what the URL "
                        "selects.")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="wellfound_jobs_scraperapi", help="Output file prefix")
    p.add_argument("--timeout", type=page_flow.at_least_one, default=60,
                   help=f"API-side task timeout in seconds (1-{MAX_API_TIMEOUT}, default 60)")
    p.add_argument("--cdp-url", default=None,
                   help="Route the fetch through an existing browser session over CDP "
                        "(sent as the API's `cdpurl` param), e.g. ws://user:pass@host:port")
    wait = p.add_mutually_exclusive_group()
    wait.add_argument("--wait-text", default=None,
                      help="Wait until this string appears on the page, e.g. '$'. Use this "
                           "on protected sites — a DOM/load wait is satisfied instantly by "
                           "the challenge page itself.")
    wait.add_argument("--wait-element", default=None,
                      help="Wait until this CSS selector is visible, e.g. 'a[href*=\"-item-\"]'")
    wait.add_argument("--wait-state", choices=["load", "domcontentloaded"], default=None,
                      help="Wait for a page load state instead of specific content")
    p.add_argument("--allow-empty", action="store_true",
                   help="Write output files even when 0 products were parsed. Off by "
                        "default so a failed fetch can't overwrite a good result.")
    p.add_argument("--retries", type=page_flow.non_negative, default=1,
                   help="Extra attempts if a bot-challenge page comes back. One retry is "
                        "usually worth it. Each attempt is a separate billable task, so "
                        "this defaults to 1.")
    p.add_argument("--retry-delay", type=page_flow.seconds, default=10,
                   help="Seconds between retries (default 10)")
    p.add_argument("--dump-html", default=None,
                   help="Also write the raw returned HTML to this path (always, even on success)")
    args = p.parse_args()
    # This client uses --key and --cdp-url rather than --twocaptcha-key and
    # --cdp-endpoint, so the env mapping is spelled out instead of defaulted.
    env_config.apply(args, keys={
        "TWOCAPTCHA_KEY": "key",
        "WELLFOUND_CDP_ENDPOINT": "cdp_url",
        "WELLFOUND_URL": "url",
    })
    if not args.url:
        p.error("no --url given, and WELLFOUND_URL is not set in the environment "
                "or in .env.")
    return args


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
