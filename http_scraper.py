#!/usr/bin/env python3
"""potterybarn.com product pages over plain HTTP — the primary PDP transport.

    python3 http_scraper.py \
        --url https://www.potterybarn.com/products/delaney-marble-end-table/ \
        --out delaney

One row per SKU (see output_writer). Several products in one run with
`--url` repeated or `--urls-file`; a listing run's own output can be fed back
in with `--from-listing potterybarn_products.json`.

Three axes, all required, measured 2026-09-24
-------------------------------------------------------------------
1. **The address.** From a non-US address `/robots.txt` 302s to
   potterybarn.co.uk and everything else answers the branded 403. A GB exit
   is refused on every page. It must be a US exit.
2. **The request shape.** From the same US exits, a bare user agent got 403
   on 3 of 3 and the full browser header set got 200 on 3 of 3 (recon,
   2026-09-24). `BROWSER_HEADERS` below is the set every measurement in this
   file used.
3. **The client.** Paired, the SAME six fresh US exits, same headers, same
   minute, one product page:

       system curl, HTTP/2      6 content (733 KB), 0 refused
       python-requests          0 content, 5 refused (403, 1,326 b), 1 timeout

   So `--http-client curl` is the default wherever curl is on PATH. What
   exactly is scored in the handshake was NOT isolated, and this module does
   not claim to know.

And a local browser does worse than either: a Playwright Chromium through the
identical exit, back to back with curl, got 403 on 8 of 9 trials and a
navigation timeout on the ninth, headless and headful alike, while curl got
content on 8 of the same 9 (the ninth was a TLS error at the exit).

Credentials never reach argv, including curl's: the proxy is passed on curl's
stdin via `--config -`, so `ps` sees no password.

Redirects are followed by hand, and only inside www.potterybarn.com. A
non-US exit is redirected to potterybarn.co.uk — a different store in GBP —
and curl's own `--location` would fetch it and hand us a UK page. A hop off
the US host is returned unfetched, marked `offsite_redirect`, and classified
`geo_redirect`: a refusal of THIS exit that rotates to another. The mark is
carried by the response itself rather than inferred from the landing URL, so
a hop to any other host (a sibling brand, say) is refused the same way and
the UK page's body is never parsed, dumped or written into the output.

A redirect chain inside the store is followed up to MAX_REDIRECTS hops; one
more hop raises instead of silently returning the truncated chain. Same-store
is decided on the HOSTNAME only (case-insensitive, query string ignored), so
`https://WWW.POTTERYBARN.COM/products/x/?N=1` is still the same store.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import env_config
import output_writer
import page_flow
import proxy_meter
import product_parser as P
import proxy_pool
from output_writer import SkuRow, finish_run

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None


DEFAULT_OUT = "potterybarn_skus"

# Every measurement on this site used this set; it has NOT been bisected. The
# user agent is a literal because there is no browser in this transport to
# ask (the family rule "the UA comes from the browser" has nothing to apply
# to), and it is kept consistent with `sec-ch-ua` — a Chrome 140 UA beside a
# Chrome 133 client hint is itself a mismatch. Bump both or neither.
CHROME_MAJOR = "140"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/%s.0.0.0 Safari/537.36" % CHROME_MAJOR
)
BROWSER_HEADERS = {
    "accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8,"
               "application/signed-exchange;v=b3;q=0.7"),
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": ('"Chromium";v="%s", "Not=A?Brand";v="24", '
                  '"Google Chrome";v="%s"' % (CHROME_MAJOR, CHROME_MAJOR)),
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": USER_AGENT,
}

MAX_REDIRECTS = 5
CURL_AVAILABLE = shutil.which("curl") is not None


def default_http_client() -> str:
    return "curl" if CURL_AVAILABLE else "requests"


class CurlError(RuntimeError):
    pass


class ProxyAuthError(CurlError):
    """The PROXY refused our credential — the site was never reached.

    Exit 5, never 3, and never retried or rotated: every exit on a dead
    credential fails identically. A 407 has also been measured to be
    TRANSIENT on this vendor (homedepot-scraper, 2026-09-22: an hour of 407s,
    then 200 the next day with nothing changed) — "retry later", not
    "rotate the credential". A 402 (traffic/balance exhausted) is the same
    kind of failure and is raised as this class too, with `.status` 402.
    """

    def __init__(self, message: str = "", status: int = 407):
        self.status = status if status in proxy_pool.PROXY_PRECHECK_STATUSES else 407
        super().__init__(message or "HTTP %d: %s" % (
            self.status, proxy_pool.PROXY_PRECHECK_STATUSES[self.status]))


class _Response:
    __slots__ = ("status_code", "text", "url", "headers", "redirect_to",
                 "offsite_redirect")

    def __init__(self, status_code: int, text: str, url: str,
                 redirect_to: Optional[str] = None,
                 offsite_redirect: bool = False):
        self.status_code = status_code
        self.text = text
        self.url = url
        self.headers: Dict[str, str] = {}
        self.redirect_to = redirect_to
        # True when `url` is a redirect's TARGET on another host and nothing
        # was fetched from it. The body is empty by construction; carrying
        # the fact on the response keeps a hop to any off-store host
        # (potterybarn.co.uk, a sibling brand) classified the same way, and
        # keeps the classifier from having to re-derive it from the URL.
        self.offsite_redirect = offsite_redirect


def _mask_text(text: str) -> str:
    return proxy_pool.mask_text(text)


def _same_store(url: str) -> bool:
    """Is `url` on the US store? Decided on the HOSTNAME alone.

    The hostname is compared case-insensitively (urlparse lowercases it
    already, the `.lower()` keeps this independent of that) and a trailing
    root dot is ignored; the path, the query string and the port have no say.
    A same-store redirect may therefore carry `?N=` facets or land on
    `https://WWW.POTTERYBARN.COM/...` and is still followed.
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host in P.HOSTS


class CurlSession:
    """A `requests.Session`-shaped wrapper around system curl. `.get()` only.

    The proxy line is written to curl's own config format on stdin
    (`--config -`), never as `--proxy`, which `ps` would show.
    """

    def __init__(self, proxy: Optional[str] = None):
        self.proxy = proxy
        self.headers = dict(BROWSER_HEADERS)

    def _once(self, url: str, timeout: int) -> _Response:
        header_args: List[str] = []
        for name, value in self.headers.items():
            header_args += ["-H", "%s: %s" % (name, value)]
        command = [
            "curl", "--silent", "--show-error",
            # HTTP/2 explicitly: on homedepot.com forcing 1.1 changed the
            # answer, and every measurement here was HTTP/2.
            "--http2", "--compressed",
            "--max-time", str(timeout),
            # The four sizes feed --proxy-budget-mb: request headers, request
            # body, every response header block (CONNECT too), and the body as
            # downloaded (compressed).
            "--write-out", "\n%{http_code} %{size_request} %{size_upload} %{size_header} "
                           "%{size_download} %{url_effective} %{redirect_url}",
            "--config", "-",
        ] + header_args + [url]
        config = "proxy = \"%s\"\n" % self.proxy if self.proxy else ""
        try:
            completed = subprocess.run(command, input=config, capture_output=True,
                                       text=True, timeout=timeout + 15)
        except subprocess.TimeoutExpired:
            raise CurlError("curl timed out after %ds" % (timeout + 15)) from None
        if completed.returncode != 0:
            # curl still prints --write-out on a failure (a refused CONNECT,
            # a timeout): what it did exchange counts too.
            failed_sizes = completed.stdout.rpartition("\n")[2].split(" ")[1:5]
            if self.proxy and len(failed_sizes) == 4 and all(n.isdigit() for n in failed_sizes):
                proxy_meter.current().add(sum(int(n) for n in failed_sizes))
            message = _mask_text(completed.stderr.strip()[:300])
            if completed.returncode in (56, 7):
                for code in proxy_pool.PROXY_PRECHECK_STATUSES:
                    if re.search(r"\b%d\b" % code, message):
                        raise ProxyAuthError(status=code)
            raise CurlError("curl exited %d: %s" % (completed.returncode, message))
        body, _, trailer = completed.stdout.rpartition("\n")
        parts = trailer.split(" ")
        try:
            status = int(parts[0])
            sizes = [int(n) for n in parts[1:5]]
            if len(sizes) != 4:
                raise ValueError(trailer)
        except (ValueError, IndexError):
            raise CurlError("could not read curl's status line: %r"
                            % trailer[:120]) from None
        if self.proxy:
            proxy_meter.current().add(sum(sizes))
        if status in proxy_pool.PROXY_PRECHECK_STATUSES:
            raise ProxyAuthError(status=status)
        final = parts[5] if len(parts) > 5 else url
        redirect = parts[6] if len(parts) > 6 and parts[6] else None
        return _Response(status, body, final, redirect)

    def get(self, url: str, timeout: int = 60, allow_redirects: bool = True):
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            response = self._once(current, timeout)
            if not (allow_redirects and 300 <= response.status_code < 400
                    and response.redirect_to):
                return response
            target = urljoin(current, response.redirect_to)
            if not _same_store(target):
                # Returned UNFETCHED: see the module docstring. The mark is
                # on the response, so the state is `geo_redirect` whatever
                # host the hop named, and its body is never read.
                return _Response(response.status_code, "", target,
                                 redirect_to=target, offsite_redirect=True)
            current = target
        raise CurlError("more than %d redirects from %s" % (MAX_REDIRECTS, url))


class _RequestsSession:
    """`requests`, with the same hand-rolled, same-store redirect rule."""

    def __init__(self, proxy: Optional[str]):
        self._session = requests.Session()
        self._session.headers.update(BROWSER_HEADERS)
        if proxy:
            self._session.proxies.update({"http": proxy, "https": proxy})
            # Every response through the proxy counts toward --proxy-budget-mb.
            self._session.hooks["response"].append(
                lambda response, *a, **k: proxy_meter.current().requests_hook(response))

    def get(self, url: str, timeout: int = 60, allow_redirects: bool = True):
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            r = self._session.get(current, timeout=timeout, allow_redirects=False)
            if r.status_code in proxy_pool.PROXY_PRECHECK_STATUSES:
                raise ProxyAuthError(status=r.status_code)
            location = r.headers.get("location")
            if allow_redirects and 300 <= r.status_code < 400 and location:
                target = urljoin(current, location)
                if not _same_store(target):
                    return _Response(r.status_code, "", target,
                                     redirect_to=target, offsite_redirect=True)
                current = target
                continue
            out = _Response(r.status_code, r.text, r.url)
            out.headers = {k.lower(): v for k, v in r.headers.items()}
            return out
        raise CurlError("more than %d redirects from %s" % (MAX_REDIRECTS, url))


def proxy_message(exc: "ProxyAuthError") -> str:
    """The one wording for a gateway 407/402, shared with the browser engines."""
    text = proxy_pool.precheck_message(
        proxy_pool.ProxyPrecheckError(exc.status), "POTTERYBARN_PROXY", "potterybarn.com",
        browser=False)
    if exc.status == 407:
        text += ("\n    A 407 has been measured to be transient on this vendor: "
                 "retry later before replacing anything.")
    return text


def build_session(proxy: Optional[str], client: Optional[str] = None):
    client = client or default_http_client()
    if client == "curl":
        if not CURL_AVAILABLE:
            raise RuntimeError("--http-client curl was asked for but curl is "
                               "not on PATH")
        return CurlSession(proxy)
    if requests is None:
        raise RuntimeError("the requests client needs `requests`: "
                           "pip install -r requirements.txt")
    return _RequestsSession(proxy)


class FetchResult:
    __slots__ = ("requested_url", "final_url", "status", "html", "attempts",
                 "elapsed_ms", "error", "exit_used", "offsite_redirect",
                 "attempt_states", "attempt_exits", "offsite_hops")

    def __init__(self, requested_url: str, final_url: str = "",
                 status: Optional[int] = None, html: str = "", attempts: int = 0,
                 elapsed_ms: int = 0, error: Optional[str] = None,
                 exit_used: Optional[str] = None,
                 offsite_redirect: bool = False):
        self.requested_url = requested_url
        self.final_url = final_url or requested_url
        self.status = status
        self.html = html
        self.attempts = attempts
        self.elapsed_ms = elapsed_ms
        self.error = error
        self.exit_used = exit_used
        # Set when the last hop went to another host and was NOT fetched:
        # the body is empty and the status is the redirect's own.
        self.offsite_redirect = offsite_redirect
        # The state and the masked exit of EVERY attempt, oldest first. A
        # geo-redirect that was retried away is not the page's final state,
        # so the final `state` alone would lose the evidence that the exit
        # was refused at all — and the exit list must name only exits that
        # actually issued a request.
        self.attempt_states: List[str] = []
        self.attempt_exits: List[Optional[str]] = []
        # Every off-site hop made while fetching this page, with the exit
        # that made it: `{"status", "target", "exit"}`. A retried page can
        # hop off more than once, and all of those exits refused the page.
        self.offsite_hops: List[Dict[str, Any]] = []

    @property
    def state(self) -> str:
        if self.error and self.status is None:
            return "transport_error"
        return P.detect_page_state(self.html, status=self.status,
                                   url=self.final_url,
                                   offsite_redirect=self.offsite_redirect)


def fetch(session, url: str, timeout: int, *, retries: int = 2,
          retry_delay: float = 2.0, log=None, rotate=None,
          exit_label: Optional[str] = None) -> Tuple[FetchResult, Any]:
    """One page with bounded retries. Returns `(result, session_now_in_use)`.

    A refusal (`blocked`, `geo_redirect`) asks `rotate()` for a DIFFERENT
    exit; a transport fault (timeout, reset, TLS error at the exit) tries the
    same exit again. Those want opposite responses.

    `exit_label` is the masked exit `session` is currently using (the caller
    holds it, because a rotation hands out a new one); it is stamped onto
    every attempt so the sidecar can name WHICH exit refused a page.
    """
    started = time.time()
    last: Optional[FetchResult] = None
    attempts = max(1, retries + 1)
    attempt_states: List[str] = []
    attempt_exits: List[Optional[str]] = []
    hops: List[Dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        # The exit this attempt's request goes through. Read BEFORE any
        # rotation below, so the attempt is stamped with the exit that
        # actually issued it, never the one a later rotation handed out.
        used_exit = exit_label
        if proxy_meter.exceeded():
            # --proxy-budget-mb: no further request through the proxy.
            if last is not None:
                last.attempt_states = attempt_states
                last.attempt_exits = attempt_exits
                last.offsite_hops = hops
            return (last or FetchResult(url, error=proxy_meter.STOP_REASON, attempts=attempt - 1,
                                        exit_used=used_exit)), session
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
        except ProxyAuthError:
            raise
        except Exception as exc:  # noqa: BLE001 - curl and requests raise widely
            last = FetchResult(url, error="%s: %s" % (type(exc).__name__,
                                                      _mask_text(str(exc))),
                               attempts=attempt, exit_used=used_exit,
                               elapsed_ms=int((time.time() - started) * 1000))
            if log:
                log("  attempt %d/%d failed: %s" % (attempt, attempts, last.error))
        else:
            last = FetchResult(url, final_url=str(response.url),
                               status=response.status_code, html=response.text,
                               attempts=attempt, exit_used=used_exit,
                               offsite_redirect=bool(getattr(
                                   response, "offsite_redirect", False)),
                               elapsed_ms=int((time.time() - started) * 1000))
            state = last.state
            if last.offsite_redirect:
                # Nothing was fetched from the target: say which exit sent
                # this page where, so the run records what it burned.
                hops.append({"page_url": url, "status": last.status,
                             "target": last.final_url, "exit": used_exit})
            if not page_flow.should_retry(state):
                attempt_states.append(state)
                attempt_exits.append(used_exit)
                last.attempt_states = attempt_states
                last.attempt_exits = attempt_exits
                last.offsite_hops = hops
                return last, session
            if log:
                log("  attempt %d/%d: %s (HTTP %s, %d bytes)"
                    % (attempt, attempts, state, last.status, len(last.html)))
            if page_flow.should_rotate_exit(state) and rotate is not None \
                    and attempt < attempts:
                # Not on the LAST attempt: there is no retry left to use the
                # new exit, and minting one would (a) count an exit nothing
                # was sent through and (b) leave `session` on an exit whose
                # label the caller does not hold, so the next page would be
                # logged against the wrong one.
                rotated = rotate()
                if rotated is not None:
                    session, exit_label = rotated
                    if log:
                        log("  rotating exit -> %s" % exit_label)
        # Every attempt's state and exit is kept, not only the last one's: a
        # refusal that a rotation then answered is still evidence about the
        # exit that refused, and the run's sidecar has to be able to say it.
        attempt_states.append(last.state)
        attempt_exits.append(used_exit)
        if attempt < attempts:
            time.sleep(retry_delay)
    if last is not None:
        last.attempt_states = attempt_states
        last.attempt_exits = attempt_exits
        last.offsite_hops = hops
    return last, session  # type: ignore[return-value]


def make_rotator(args, pool, facts: Dict[str, Any]):
    """A callable returning `(fresh session, masked exit)` or None.

    On a 2Captcha gateway a rotation MINTS a fresh session-pinned exit rather
    than cycling a fixed list: a pinned session was measured drifting from El
    Paso to Frankfurt (an AWS address) minutes into its life, and "a fresh
    session fixed it every time" (recon, 2026-09-23). A fresh SESSION object
    too, so no cookie issued to exit A is replayed from exit B.
    """
    state = {"rotations": 0}

    def rotate():
        if pool is None or state["rotations"] >= args.proxy_block_retries:
            return None
        if proxy_pool.is_2captcha_gateway(pool.current) and len(pool) == 1:
            nxt = proxy_pool.mint_sessions(pool.current, 1)[0]
        elif len(pool) > 1:
            nxt = pool.advance("blocked")
        else:
            return None
        state["rotations"] += 1
        # `exits_used` is appended when the new exit ISSUES a request (see
        # `scrape`), not here: the last rotation of a page that never retried
        # again would otherwise name an exit nothing was ever sent through.
        return build_session(nxt, args.http_client), proxy_pool.mask(nxt)
    return rotate


def _note_exit(facts: Dict[str, Any], label: Optional[str]) -> None:
    """Record one attempt's exit: the sequence, the distinct set, and the
    number of CHANGES between consecutive attempts.

    Counted as changes rather than as `len(distinct) - 1`, because a pool of
    two exits rotated three times goes back through the first one: the
    distinct set is still two, but three rotations really happened, and a run
    that burned exits must not under-report it.
    """
    if not label:
        return
    sequence = facts["exit_sequence"]
    if sequence and sequence[-1] != label:
        facts["rotations"] += 1
    sequence.append(label)
    facts["exit"] = label
    if label not in facts["exits_used"]:
        facts["exits_used"].append(label)


def targets_from_args(args) -> List[str]:
    urls: List[str] = list(args.url or [])
    if args.urls_file:
        with open(args.urls_file, encoding="utf-8") as handle:
            urls += [line.strip() for line in handle
                     if line.strip() and not line.startswith("#")]
    if args.from_listing:
        # One fetch per PRODUCT: several listing rows can be sub-groups of
        # one product (`?subGroupId=`), and its page lists every SKU anyway.
        with open(args.from_listing, encoding="utf-8") as handle:
            urls += [P.product_url(row["product_id"]) for row in json.load(handle)
                     if row.get("product_id")]
    seen, out = set(), []
    for url in urls:
        if url not in seen:
            seen.add(url)
            out.append(url)
    if args.max_products:
        out = out[:args.max_products]
    return out


def validate_target(url: str) -> Optional[str]:
    """None if `url` is a product page this repo may fetch, else the reason."""
    ok, reason = P.supported_host(url)
    if not ok:
        return reason
    if not P.slug_from_url(url):
        return ("not a product page (/products/<slug>/). For a category, use "
                "api_scraper.py, which reads the listing from its API.")
    if not P.robots_allows(url):
        return "disallowed by potterybarn.com's robots.txt"
    return None


def scrape(args) -> Tuple[List[SkuRow], Dict[str, Any]]:
    targets = targets_from_args(args)
    if not targets:
        raise output_writer.UsageError("nothing to fetch: pass --url, --urls-file or "
                         "--from-listing with product-page URLs")
    for url in targets:
        problem = validate_target(url)
        if problem:
            raise output_writer.UsageError("refusing %s: %s" % (url, problem))

    pool = proxy_pool.from_args(args)
    proxy = pool.current if pool else None
    proxy_meter.start(getattr(args, "proxy_budget_mb", proxy_meter.DEFAULT_BUDGET_MB), active=bool(proxy))
    if not proxy:
        print("WARNING: no proxy configured. Measured 2026-09-23, a non-US "
              "address gets the branded 403 on every product page. Set "
              "POTTERYBARN_PROXY in .env to a US exit.", file=sys.stderr)
    session = build_session(proxy, args.http_client)
    log = (lambda m: print(m, file=sys.stderr)) if args.verbose else (lambda m: None)

    facts: Dict[str, Any] = {
        "transport": "http-%s" % args.http_client,
        "exit": proxy_pool.mask(proxy) if proxy else None,
        # Every exit this run actually used, masked, in order: the first one
        # plus each distinct rotation. `exit` above stays the LAST one, so a
        # reader can see both how many exits were burned and which they were.
        "exits_used": [proxy_pool.mask(proxy)] if proxy else [],
        # One entry per ATTEMPT: which exit issued it, in order. `rotations`
        # is how many CONSECUTIVE entries differ, so a two-exit pool rotated
        # three times reports three, not one.
        "exit_sequence": [],
        "pages_requested": len(targets),
        "pages_completed": 0,
        "failed_pages": [],
        # Pages the site refused at least ONCE: the final state was a
        # refusal (403 or a hop off the store), or an attempt was a
        # geo-redirect even though a rotation later answered the page. A
        # page that recovered is here but NOT in `failed_pages` — nothing
        # was lost, yet the refusal still cost an exit and must be visible.
        "refused_pages": [],
        # Pages that hopped off the US store at ANY attempt.
        "geo_redirect_pages": [],
        # Pages whose FINAL state was `geo_redirect`. The stop reason keys
        # on these, so a run that also met a plain 403 elsewhere is not
        # reported as a geo-redirect run.
        "geo_redirect_failures": [],
        # Where an off-store hop was sent and which exit sent it there. The
        # target is recorded, never fetched, so this is the only trace of
        # the UK (or sibling-brand) page in the run.
        "offsite_targets": [],
        "states": [],
        # One entry per ATTEMPT, so a geo-redirect answered by the next exit
        # is still visible; `attempt_counts` is the same list collapsed.
        "attempt_states": [],
        "attempt_counts": {},
        "products": [],
        "blocked": False,
        "transport_error": False,
        "rotations": 0,
        "sku_count_mismatches": [],
        "start_url": targets[0],
        "final_url": targets[0],
    }
    rotate = make_rotator(args, pool, facts)
    current_exit = proxy_pool.mask(proxy) if proxy else None
    rows: List[SkuRow] = []
    seen: set = set()
    for index, url in enumerate(targets, 1):
        if proxy_meter.exceeded():
            # --proxy-budget-mb: no further product page through the proxy.
            facts["unattempted_pages"] = list(range(index, len(targets) + 1))
            break
        log("product %d/%d: %s" % (index, len(targets), url))
        result, session = fetch(session, url, args.timeout, retries=args.retries,
                                retry_delay=args.retry_delay, log=log,
                                rotate=rotate, exit_label=current_exit)
        # A rotation that happened inside `fetch` hands back a session on a
        # NEW exit; that one carries over to the next page, so remember it.
        # `attempt_exits[-1]` is the exit the LAST attempt actually used —
        # never the one a final, unused rotation would have handed out.
        if result.attempt_exits:
            current_exit = result.attempt_exits[-1]
        state = result.state
        facts["states"].append(state)
        for attempt_state, attempt_exit in zip(result.attempt_states,
                                               result.attempt_exits):
            facts["attempt_states"].append(attempt_state)
            facts["attempt_counts"][attempt_state] = \
                facts["attempt_counts"].get(attempt_state, 0) + 1
            # An exit is recorded only when it issued a request: the last
            # rotation of a page that never retried again names an exit
            # nothing was sent through, and that would inflate the count.
            _note_exit(facts, attempt_exit)
        if state == "geo_redirect" or "geo_redirect" in result.attempt_states:
            # Counted whether the page was finally read or not: a redirect
            # the next exit answered is still evidence that the first exit
            # was refused, and the run has to report what it burned.
            if index not in facts["geo_redirect_pages"]:
                facts["geo_redirect_pages"].append(index)
            if index not in facts["refused_pages"]:
                facts["refused_pages"].append(index)
        if not result.offsite_redirect:
            # An off-store hop was NOT fetched: nothing from the other store
            # reaches `--dump-html` (nor a stray empty file, which a reader
            # could mistake for a served page).
            _dump(args, result.html, index)
        for hop in getattr(result, "offsite_hops", []):
            # Every off-site hop, with the exit that made it: nothing was
            # fetched from the target, so this is the only trace of the
            # other store's page in the run, and after a retry it also
            # names each exit that did not work for this page.
            facts["offsite_targets"].append(dict(hop, page=index))
        if state != "product":
            facts["failed_pages"].append(index)
            if result.html:
                facts.setdefault("unparsed_pages", []).append(
                    dict(P.page_shape(result.html), page=index, state=state,
                         status=result.status))
            if state == "transport_error":
                facts["transport_error"] = True
            elif page_flow.counts_as_blocked(state):
                facts["blocked"] = True
                if index not in facts["refused_pages"]:
                    facts["refused_pages"].append(index)
                if state == "geo_redirect":
                    # Only a page that was STILL refused when the exits ran
                    # out counts toward the stop reason; see `_stop_reason`.
                    facts["geo_redirect_failures"].append(index)
            print("product %d: %s (HTTP %s, %d bytes)%s"
                  % (index, state, result.status, len(result.html),
                     " — " + result.error if result.error else ""),
                  file=sys.stderr)
            continue
        try:
            page_rows, page_facts = P.parse_product(result.html, url=url,
                                                    category=args.category)
        except P.DecodeError as exc:
            print("product %d: %s" % (index, exc), file=sys.stderr)
            facts["failed_pages"].append(index)
            facts["products"].append({"url": url, "error": str(exc)})
            continue
        for row in page_rows:
            row.page = index
        fresh = output_writer.dedupe_by_sku(page_rows, seen)
        rows.extend(fresh)
        facts["pages_completed"] += 1
        facts["final_url"] = result.final_url
        facts["products"].append(page_facts)
        if not page_facts["sku_check"]["closes"]:
            # The rows are kept, and the run is NOT called complete: the page
            # says it holds a different number of SKUs than were read. The
            # rule matched skuCount on 40 of 40 product pages (2026-10-01), so
            # a mismatch is evidence, not noise.
            check = page_facts["sku_check"]
            print("[!] %s: %d SKUs read, %d of them counted, but the page states "
                  "skuCount=%s — the SKU list may be incomplete%s"
                  % (page_facts["product_id"], check["rows"], check["counted"],
                     check["sku_count_stated"],
                     "" if args.accept_count_mismatch else
                     " (run marked partial; --accept-count-mismatch to override)"),
                  file=sys.stderr)
            facts["sku_count_mismatches"].append(page_facts["product_id"])
            if not args.accept_count_mismatch:
                facts["failed_pages"].append(index)
        log("  %d SKUs (%s), %d total" % (len(page_rows),
                                         page_facts["subsets_source"], len(rows)))
        if index < len(targets):
            time.sleep(args.delay)
    return rows, facts


def _dump(args, html: str, index: int) -> None:
    """`--dump-html` writes on SUCCESS too."""
    if not getattr(args, "dump_html", None):
        return
    import os
    root, ext = os.path.splitext(args.dump_html)
    path = "%s_p%d%s" % (root, index, ext or ".html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html or "")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1, got %s" % value)
    return number


def _non_negative_int(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0, got %s" % value)
    return number


def _non_negative_float(value):
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0, got %s" % value)
    return number


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Scrape potterybarn.com product pages over plain HTTP — "
                    "one row per SKU.",
        epilog="Credentials belong in .env, never on a command line — `ps` "
               "reads argv.")
    p.add_argument("--url", action="append", default=None,
                   help="A product page, /products/<slug>/. Repeatable.")
    p.add_argument("--urls-file", default=None,
                   help="One product URL per line.")
    p.add_argument("--from-listing", default=None,
                   help="A JSON output of api_scraper.py; fetches every "
                        "product it lists.")
    p.add_argument("--max-products", type=_positive_int, default=None)
    p.add_argument("--accept-count-mismatch", action="store_true",
                   help="Do not mark the run partial when a product's SKU "
                        "count disagrees with the page's own skuCount.")
    p.add_argument("--category", default=None,
                   help="Label written into the rows' `category` column.")
    p.add_argument("--retries", type=_non_negative_int, default=2,
                   help="Extra attempts after the first. 0 means one attempt.")
    p.add_argument("--retry-delay", type=_non_negative_float, default=2.0)
    p.add_argument("--delay", type=_non_negative_float, default=1.0)
    p.add_argument("--timeout", type=_positive_int, default=60)
    p.add_argument("--format", choices=["json", "csv", "both"], default="both")
    p.add_argument("--out", default=DEFAULT_OUT)
    p.add_argument("--allow-empty", action="store_true")
    p.add_argument("--dump-html", default=None)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--http-client", choices=["curl", "requests"],
                   default=default_http_client(),
                   help="Default %s. Measured 2026-09-24 on six identical US "
                        "exits: curl got the product page on 6, requests was "
                        "refused on 5 and timed out on 1."
                        % default_http_client())
    p.add_argument("--proxy", default=None,
                   help="Prefer POTTERYBARN_PROXY in .env — a proxy URL on the "
                        "command line is visible to `ps`.")
    p.add_argument("--proxy-file", default=None)
    p.add_argument("--proxy-rotate", choices=proxy_pool.ROTATE_MODES,
                   default="per-run")
    p.add_argument("--proxy-shuffle", action="store_true")
    p.add_argument("--proxy-sessions", type=_positive_int, default=None,
                   help="Turn one 2Captcha proxy credential into N "
                        "session-pinned exits.")
    p.add_argument("--proxy-block-retries", type=_non_negative_int, default=3,
                   help="How many times a refused page may move to a "
                        "different exit before it is reported.")
    proxy_meter.add_budget_argument(p)
    args = p.parse_args(argv)
    env_config.apply(args, keys={k: v for k, v in env_config.ENV_KEYS.items()
                                 if v != "url"})
    return args


def _stop_reason(facts: Dict[str, Any], accept_mismatch: bool = False) -> str:
    if facts["sku_count_mismatches"] and not accept_mismatch:
        return "sku_count_mismatch"
    if facts["pages_completed"] == facts["pages_requested"]:
        return "completed"
    if facts["transport_error"] and not facts["blocked"]:
        return "transport_error"
    if facts["blocked"]:
        if facts.get("geo_redirect_failures"):
            # The pages that defeated the run were geo-redirected. Named
            # separately from `blocked` so the sidecar says WHICH refusal it
            # was: exhausted exits on the UK redirect is a proxy-region
            # problem (`-region-us`), not the branded 403's problem. A run
            # whose final failure was any OTHER refusal reports `blocked`;
            # see `geo_redirect_failures`.
            return "geo_redirect"
        return "blocked"
    return "incomplete"


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        rows, facts = scrape(args)
    except ProxyAuthError as exc:
        print(proxy_message(exc), file=sys.stderr)
        try:
            targets = targets_from_args(args)
        except (OSError, ValueError, KeyError):
            targets = []
        output_writer.write_failed_attempt(
            args.out, stop_reason="proxy_auth_failed", mode="product",
            start_url=targets[0] if targets else None,
            pages_requested=len(targets),
            transport_error="proxy: %s" % exc)
        return output_writer.EXIT_REMOTE_API_ERROR
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print("run failed: %s: %s" % (type(exc).__name__, _mask_text(str(exc))),
              file=sys.stderr)
        return output_writer.EXIT_CRASH
    return finish_run(
        rows, args.out, args.format, args.allow_empty,
        blocked=facts["blocked"],
        transport_error=facts["transport_error"],
        stop_reason=_stop_reason(facts, args.accept_count_mismatch),
        pages_requested=facts["pages_requested"],
        pages_completed=facts["pages_completed"],
        pages_failed=facts["failed_pages"],
        mode="product",
        scope={"max_products": args.max_products,
               "targets": len(facts["products"]) + len(facts["failed_pages"])},
        start_url=facts["start_url"], final_url=facts["final_url"],
        extra=facts,
    )


if __name__ == "__main__":
    sys.exit(main())
