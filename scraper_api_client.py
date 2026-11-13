"""
mercor-scraper — 2captcha Scraper API edition (fourth engine)

Fetches one page through the 2captcha Scraper API, which renders it on
2captcha's infrastructure and returns the HTML over plain HTTPS, and feeds it
to this project's product_parser.

When this path is the right one
-------------------------------
Every route this scraper reads is an ordinary HTML page whose payload is
serialised inside it, so there is no endpoint to prefer and no JavaScript to
execute after load — which makes a rendered-HTML service a genuinely good
fit for all three modes.

It is also, on this site, the path with the least to recommend it, and
saying so is the honest sentence. Measured 2026-09-18: Mercor served every
route to a bare Hetzner datacentre address, to plain `curl` and to an empty
User-Agent, with no challenge on any of seven captures. The Scraper API's
own exits are datacentre addresses too, and nothing here needs an exit that
Mercor does not score — because nothing measured so far suggests Mercor
scores exits at all.

So use this client when you want someone else's infrastructure to run the
browser, not because the site demands it. What it genuinely buys here is
the same thing `--cdp-url` buys: a specific exit country, and no local
Chromium to install.

    python3 scraper_api_client.py \
        --url "https://work.mercor.com/explore"

    # TWOCAPTCHA_KEY and the CDP endpoint are read from .env as
    # $MERCOR_CDP_ENDPOINT, so neither needs to be typed — a secret in
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
                            detect_bot_challenge, detect_page_state,
                            parse_page, parse_detail, is_supported_url,
                            mode_for_url, EXPLORE_URL, CAREERS_URL)
import env_config

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
from output_writer import (EXIT_API_ERROR, SOURCE_DEFAULT,  # noqa: E402
                           finish_run)
from page_flow import (THROTTLED, TARGET_SERVER_ERROR,  # noqa: E402,F401
                       PARSER_FOUND_NOTHING, http_error_stop_reason,
                       target_server_error, throttle_pause)

# `_run_once` asks `main` for another attempt after a target 5xx, a refusal
# (403 or a challenge marker) or a 429. Never returned as an exit code: the
# last attempt reports the failure itself, through `finish_run`.
_RETRY_TARGET_5XX = -5
_RETRY_BLOCKED = -3
_RETRY_THROTTLED = -29
_RETRY = (3, _RETRY_TARGET_5XX, _RETRY_BLOCKED, _RETRY_THROTTLED)

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
    """`waitFor` is sent as an OBJECT. Measured 2026-09-23: the
    JSON-encoded string form is answered with HTTP 422 and still billed
    ($0.0005); the object form gets HTTP 200.

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
        "format": "json",       # so we get {"status", "http_code", "headers", "body"}
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
    # The TARGET's HTTP code is `http_code`. `status` is the API's own
    # verdict string ("success", measured 2026-09-23), and passing it on
    # meant the page classifier never saw a 403. Fall back to `status` only
    # if some response shape carries an int there.
    upstream_status = body.get("http_code")
    if not isinstance(upstream_status, int):
        legacy = body.get("status")
        upstream_status = legacy if isinstance(legacy, int) else None
    if upstream_status is None and body.get("status") == "error":
        # The API's documented verdict for a target network error or 5xx.
        # With no target status to classify, nothing was obtained: exit 5.
        raise RuntimeError("Scraper API task ended with status 'error' and "
                           "no target status: the page was not obtained")
    logger.info("Upstream page HTTP %s (API status %r), %d bytes of HTML.",
                upstream_status, body.get("status"), len(html))
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
        if rc not in _RETRY or attempt == attempts:
            return rc
        # A 429 waits longer each time (the same doubling pause as the
        # browser engines); everything else waits --retry-delay.
        pause = (throttle_pause(args.retry_delay, attempt - 1)
                 if rc == _RETRY_THROTTLED else args.retry_delay)
        logger.info("%s on attempt %d/%d — retrying in %.1fs.",
                    {_RETRY_TARGET_5XX: "Target server error",
                     _RETRY_THROTTLED: "Target HTTP 429 (throttled)"}.get(
                         rc, "Refusal or challenge page"),
                    attempt, attempts, pause)
        time.sleep(pause)
    return rc


def _finish_refused(args, stop_reason: str) -> int:
    """A refused page (403, a challenge, a persistent 429) through the same
    `finish_run` as the browser engines: exit 3, earlier output kept, and
    with --allow-empty and nothing earlier, a `blocked` sidecar."""
    return finish_run([], args.out, args.format, args.allow_empty,
                      blocked=True, stop_reason=stop_reason,
                      pages_requested=1, pages_completed=0,
                      pages_failed=[1], mode=args.mode,
                      source=SOURCE_DEFAULT, start_url=args.url,
                      final_url=args.url,
                      extra={"route_is_paginated": args.mode == "job",
                             "mode": args.mode})


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
    # `mode=` matters: without it the page is judged as a LISTING whatever
    # was asked for, so a perfectly good detail page — which holds no
    # `listings` — reads as a page whose records went missing. The browser
    # engines pass it; this client did not, the same omission the mirror
    # engines had.
    state = detect_page_state(html, status=upstream_status, url=args.url,
                              mode=args.mode)
    if state == THROTTLED:
        # Mercor's own 429 in `http_code`. Retried within --retries with a
        # growing pause, then a refusal: exit 3 through finish_run, earlier
        # output kept. Not an answer about the page.
        if attempt < attempts:
            return _RETRY_THROTTLED
        logger.error("Mercor answered HTTP 429 (too many requests) for %s on "
                     "every attempt — exit 3, NOT an empty result (exit 4). "
                     "Wait, or raise --retries/--retry-delay.", args.url)
        return _finish_refused(args, THROTTLED)

    if state == "blocked":
        if attempt < attempts:
            return _RETRY_BLOCKED
        dump = f"{args.out}_scraperapi_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html)
        logger.error(
            "Mercor did not serve the Scraper API's request (upstream HTTP "
            "%s, %d bytes) — saved to %s. This is NEW: on 2026-09-18 this "
            "site served every route to a bare datacentre address with no "
            "challenge of any kind, so there is no measured remedy to "
            "recommend and the saved HTML is the evidence for what changed. "
            "--cdp-url routes the request through a Scraping Browser session "
            "with a country segment, which is the usual next move. This is "
            "exit 3, distinct from an empty result (exit 4).",
            upstream_status, len(html), dump)
        return _finish_refused(args, "blocked_refused")

    stop_reason = ("single_page_route" if args.mode in ("listings", "careers")
                   else "completed")
    server_error = target_server_error(state, upstream_status)
    if server_error is not None:
        # Mercor's own 5xx, carried in `http_code` of an HTTP 200 API answer.
        # It says nothing about what the page holds: retried within
        # --retries, then the content was not obtained (exit 5), never the
        # empty result of exit 4. No rows, so earlier output is kept.
        # Only a 5xx is retried; any other unexplained non-2xx is final, as
        # in the browser engines.
        if server_error >= 500 and attempt < attempts:
            return _RETRY_TARGET_5XX
        logger.error("Mercor answered HTTP %d for %s — "
                     "exit %d: the page was not obtained, NOT an empty "
                     "result (exit 4).", server_error, args.url, EXIT_API_ERROR)
        return finish_run([], args.out, args.format, args.allow_empty,
                          blocked=False,
                          stop_reason=http_error_stop_reason(server_error),
                          pages_requested=1, pages_completed=0,
                          pages_failed=[1], mode=args.mode,
                          source=SOURCE_DEFAULT, start_url=args.url,
                          final_url=args.url,
                          extra={"route_is_paginated": args.mode == "job",
                                 "mode": args.mode,
                                 "pages_target_http_error": {"1": server_error}})
    if state == "not_found":
        # `upstream_status` is the TARGET's status: the Scraper API answers
        # HTTP 200 and carries a site 404 in `http_code` (its documentation
        # says a site 404 "is returned with HTTP 200 from the API"). The API's
        # own 404 means an unknown task id on the async result endpoint, which
        # this client does not call, and any non-200 from the API is exit 5
        # above. So this is Mercor saying the address does not exist: the
        # same `not_found` the browser engines reach from goto()'s status,
        # and the same exit 4 and sidecar they produce for it.
        logger.warning("Mercor answered HTTP %s for %s: no such %s. Exit 4, "
                       "a real answer from the site, not a failed fetch.",
                       upstream_status, args.url,
                       "job" if args.mode == "job" else "page")
        extra = {"route_is_paginated": args.mode == "job", "mode": args.mode}
        if args.mode == "job":
            extra["jobs_not_found"] = 1
            extra["urls_not_found"] = [args.url]
        return finish_run([], args.out, args.format, args.allow_empty,
                          blocked=False, stop_reason=stop_reason,
                          pages_requested=1, pages_completed=1,
                          mode=args.mode, source=SOURCE_DEFAULT,
                          start_url=args.url, final_url=args.url, extra=extra)

    vendor = detect_bot_challenge(html)
    if vendor:
        logger.error(
            "The Scraper API returned a %s bot-challenge page (%d bytes), not real content.",
            vendor, len(html),
        )
        logger.error("A challenge page is not a final answer — retry before "
                     "concluding anything (--retries). Mercor rendered no "
                     "challenge to any request measured on 2026-09-18, so "
                     "there is no measured remedy here — --cdp-url routes "
                     "through a Scraping Browser session with a country "
                     "segment, and playwright_scraper.py with a residential "
                     "--proxy is the other move.")
        return 3

    # One dispatch, shared with the browser engines, so this client cannot
    # quietly disagree with them about which reader a mode uses.
    products = parse_page(html, mode=args.mode, url=args.url, page=1)
    # NO per-row category assignment here, and its removal is a fix rather
    # than an omission. This client inherited `row.category = args.category`
    # from the repo it was copied from, where the row class has no
    # `category` field either — so it set an attribute that `asdict()` never
    # reads and that reached neither the JSON nor the CSV. It looked like it
    # was labelling rows and was doing nothing at all (a
    # copied file is the one with no evidence behind it).
    #
    # `--category` labels the RUN, and the sidecar is where a run-level fact
    # belongs; `finish_run` already records it. Checked before removing: two
    # siblings (bbb, montblanc) do carry a real `category` column and their
    # identical line is correct there, so this is not a family-wide fix.
    logger.info("Parsed %d job(s).", len(products))

    if not products:
        dump = f"{args.out}_scraperapi_debug.html"
        with open(dump, "w", encoding="utf-8") as f:
            f.write(html)
        logger.warning("0 jobs parsed — saved the raw response to %s so "
                       "you can see what actually came back.", dump)
        if state != "empty":
            # Served, and either this parser could not find where the records
            # would be (`parse_error`) or the response never was the payload
            # (`unknown`). Only `empty` — the site's own container, present
            # and holding nothing — is the site saying there are no jobs.
            # Anything else is exit 5 through finish_run, the same number
            # and sidecar the browser engines give it.
            logger.error("The page was served (state %r) but holds neither "
                         "records nor the site's own empty answer — exit %d, "
                         "NOT an empty result (exit 4). The saved response "
                         "shows what came back.", state, EXIT_API_ERROR)
            return finish_run([], args.out, args.format, args.allow_empty,
                              blocked=False, stop_reason=PARSER_FOUND_NOTHING,
                              pages_requested=1, pages_completed=0,
                              pages_failed=[1], mode=args.mode,
                              source=SOURCE_DEFAULT, start_url=args.url,
                              final_url=args.url,
                              extra={"route_is_paginated": args.mode == "job",
                                     "mode": args.mode, "pages_unreadable": [1]})
        # Served, and the site's own payload holds nothing: exit 4 through
        # the same `finish_run` as the browser engines, so `--allow-empty`
        # writes the same empty output and sidecar here as there.
        return finish_run([], args.out, args.format, args.allow_empty,
                          blocked=False, stop_reason=stop_reason,
                          pages_requested=1, pages_completed=1,
                          mode=args.mode, source=SOURCE_DEFAULT,
                          start_url=args.url, final_url=args.url)

    # Through `finish_run`, not a bare `save`. This client used to write rows
    # and NO sidecar, which was true and defensible while nothing depended on
    # one — and then `diff_runs.py` needed to REQUIRE one, because a run whose
    # completeness cannot be verified cannot be told from a partial one, and
    # the family refuses to diff those. The requirement could not be made
    # until this client wrote what it requires, or every diff of its output
    # would have been refused for a reason that is the client's, not the
    # user's.
    return finish_run(products, args.out, args.format, args.allow_empty,
                      blocked=False, stop_reason=stop_reason,
                      pages_requested=1, pages_completed=1,
                      mode=args.mode, source=SOURCE_DEFAULT,
                      start_url=args.url, final_url=args.url)


def parse_args():
    p = argparse.ArgumentParser(
        description="Mercor scraper — 2captcha Scraper API edition (no local "
                    "browser). Fetches one page and parses it with the same "
                    "reader the browser engines use. Mercor served every "
                    "route to a bare datacentre address when measured, so "
                    "this path is for when you want someone else's "
                    "infrastructure to run the browser, not because the "
                    "site demands it. --cdp-url is optional.")
    # NOT required: prefer the TWOCAPTCHA_KEY env var. A key passed on the
    # command line is visible to anyone who can run `ps`, and it lands in
    # shell history and in any log that echoes the command line.
    p.add_argument("--key", default=os.environ.get("TWOCAPTCHA_KEY"),
                   help="2captcha.com API key (sent as a Bearer token). "
                        "Defaults to $TWOCAPTCHA_KEY, which is the safer way to pass it.")
    p.add_argument("--url", default=None,
                   help="A mercor.com URL: work.mercor.com/explore with "
                        "--mode listings, www.mercor.com/careers with --mode "
                        "careers, or work.mercor.com/jobs/{id}/{slug} with "
                        "--mode job. Needed only for --mode job: the index and "
                        "the careers page each have one address. Defaults to "
                        "MERCOR_URL from the environment or .env when that "
                        "names the same route as --mode.")
    p.add_argument("--mode", choices=list(MODES),
                   default=DEFAULT_MODE,
                   help="Which reader to parse the page with. Same "
                        "default as the browser engines (%s)." % DEFAULT_MODE)
    p.add_argument("--category", default=None, help="Accepted for flag parity with the browser engines. The row has no category column (the site's own category for a listing is `domain`), so this client does not use it.")
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default="mercor_jobs_scraperapi", help="Output file prefix")
    p.add_argument("--timeout", type=int, default=60,
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
    p.add_argument("--retries", type=int, default=1,
                   help="Extra attempts if a bot-challenge page comes back. One retry is "
                        "usually worth it. Each attempt is a separate billable task, so "
                        "this defaults to 1.")
    p.add_argument("--retry-delay", type=int, default=10,
                   help="Seconds between retries (default 10)")
    p.add_argument("--dump-html", default=None,
                   help="Also write the raw returned HTML to this path (always, even on success)")
    args = p.parse_args()
    # Whether --url was TYPED, captured before the environment fills it: a
    # MERCOR_URL from .env is a default, not a request.
    typed_url = args.url
    # This client uses --key and --cdp-url rather than --twocaptcha-key and
    # --cdp-endpoint, so the env mapping is spelled out instead of defaulted.
    env_config.apply(args, keys={
        "TWOCAPTCHA_KEY": "key",
        "MERCOR_CDP_ENDPOINT": "cdp_url",
        "MERCOR_URL": "url",
    })
    if args.url:
        ok, why = is_supported_url(args.url)
        if not ok:
            p.error(why)
        implied = mode_for_url(args.url)
        if implied and implied != args.mode:
            if typed_url:
                # Refused rather than parsed with the wrong reader, which
                # would report a served page as zero rows.
                p.error("--url is a %s URL but --mode is %s; pass --mode %s, "
                        "or drop --url." % (implied, args.mode, implied))
            print("[i] MERCOR_URL (%s) is read by --mode %s; ignoring it for "
                  "--mode %s." % (args.url, implied, args.mode),
                  file=sys.stderr)
            args.url = None
    if not args.url:
        # The index and the careers page each have one address, so those two
        # modes need no URL. A job page does.
        if args.mode == "careers":
            args.url = CAREERS_URL
        elif args.mode == "listings":
            args.url = EXPLORE_URL
        else:
            p.error("--mode job needs --url (a work.mercor.com/jobs/... "
                    "address); MERCOR_URL is not set to one.")
    return args


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
