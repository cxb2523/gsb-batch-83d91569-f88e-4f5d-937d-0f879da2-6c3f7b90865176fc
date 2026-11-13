#!/usr/bin/env python3
"""page_flow.py — what one fetched article URL MEANS, decided once for all
three engines (three copies of this triage would drift, and
the drift would be silent — one engine reporting exit 3 where its twin
reports 0 on the same page).

perplexity.ai answers an article request these ways, all seen live on
2026-09-30:

  1. the app page, and `/rest/article/{ref}` returns the article JSON → a
     full row (`source_used="api"`);
  2. the app page, but the API call keeps failing → NO row. The rendered
     HTML is not evidence of WHICH article it is: a dead URL rendered the
     previously viewed article's headings in full, and the HTML carries
     no id to check against. A row with another article's title is worse
     than no row ("fail loudly");
  3. the app page, and the API answers 400 → the article does not exist
     (`not_found`): no row, not a block, never retried harder;
  4. a Cloudflare managed challenge that never cleared (local Chromium,
     headless or headful, from a residential Mac) → `blocked`. Its HTML is
     never parsed: its own heading once came out as an article titled
     "Performing security verification";
  5. HTTP/API 401/403/429 → blocked; other unread responses → failure.

Triage is driver-independent; the shared async flow below consumes engine operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional

import page_parser as pp
from captcha_solver import detect_from_html
from output_writer import Product

BLOCKING_API_STATUSES = (401, 403, 429)
NOT_FOUND_API_STATUSES = (400, 404)
# /rest/ answers 403 in two live situations: a fresh profile before the
# page's own bot check has issued cf_clearance (403 at ~3s, 200 at ~12s),
# and a burst — 13 articles at 0.5s apart, then 403 on every call until
# the profile was left alone for a few minutes. The engines retry the API
# call after each of these pauses; the long last one is for the burst.
API_RETRY_DELAYS_S = (3, 5, 8, 15)


def should_retry_api(status: int, error: Optional[str]) -> bool:
    """Worth another try after a pause: refused or unreadable, not "no such article"."""
    if status in NOT_FOUND_API_STATUSES or (status == 200 and not error):
        return False
    return status in BLOCKING_API_STATUSES or status == 0 or status >= 500 or bool(error)


def is_challenge(html: str) -> bool:
    """A bot-challenge marker on a page that is NOT the app. The app shell
    itself may mention challenge vendors; a page built from the app's own
    assets is never the interstitial."""
    return detect_from_html(html or "", pp.BOT_CHALLENGE_MARKERS) and not pp.is_app_page(html or "")


@dataclass
class Outcome:
    product: Optional[Product]
    blocked: bool
    not_found: bool
    source_used: str
    warnings: List[str] = field(default_factory=list)
    failure: Optional[str] = None
    rate_limited: bool = False


@dataclass
class DiscoveryResult:
    urls: List[str] = field(default_factory=list)
    failure: Optional[str] = None
    blocked: bool = False
    rate_limited: bool = False
    offset: int = 0
    capped: bool = False
    # One record per feed page ATTEMPTED, in order:
    #   {"page", "offset", "items", "new_urls", "has_more", "status", "error"}
    # `items` is None only when the request itself failed; a page the site
    # returned always carries the count it returned, even when it was
    # rejected as unparseable. This is what makes a stopped run auditable
    # page by page instead of just "it stopped somewhere".
    pages: List[dict] = field(default_factory=list)
    # Why pagination stopped when it did not stop for a normal reason
    # (a stuck cursor or empty pages): {"kind", "page", ...}.
    stall: Optional[dict] = None

    @property
    def pages_fetched(self) -> int:
        """Pages the site actually returned (HTTP 200), failed requests
        excluded — the number of pages this run really read."""
        return sum(1 for page in self.pages if page.get("status") == 200)

    @property
    def page_item_counts(self) -> List[int]:
        """How many items each returned page carried, in page order."""
        return [page["items"] for page in self.pages
                if page.get("status") == 200 and page.get("items") is not None]


def decide(
    *, url: str, http_status: Optional[int], html: str, api_status: int,
    article_json: Any, api_error: Optional[str],
) -> Outcome:
    warnings: List[str] = []
    if api_status in NOT_FOUND_API_STATUSES:
        return Outcome(None, False, True, "none",
                       [f"{url}: the article API answered HTTP {api_status} — no such article (page_not_found)."])

    challenged = is_challenge(html)
    if challenged:
        return Outcome(None, True, False, "none",
                       [f"{url}: served a bot challenge that did not clear — blocked."])

    result = pp.safe_parse_page(html, url=url, article_json=None if api_error else article_json)
    product = result.products[0] if result.source_used == "api" else None
    if product is not None and api_status == 200 and not api_error:
        return Outcome(product, False, False, "api", warnings)

    detail = f"article API HTTP {api_status or '-'}" + (f", {api_error}" if api_error else "")
    if http_status in BLOCKING_API_STATUSES or api_status in BLOCKING_API_STATUSES:
        warnings.append(f"{url}: {detail} — blocked, not empty.")
        return Outcome(None, True, False, "none", warnings, rate_limited=api_status == 429 or http_status == 429)

    warnings.append(f"{url}: {detail} — no article read. Re-run with --dump-html to inspect the captured page.")
    return Outcome(None, False, False, "none", warnings,
                   failure="parse_error" if api_status == 200 and not api_error else "fetch_error")


# --------------------------------------------------------------------------- #
# The ONE fetch loop. Until 2026-09-30 each engine carried
# its own copy of everything below. Each engine now passes an `Engine`
# (open a page session, sleep, solve a generic captcha) whose sessions
# provide NAMED operations — goto, content, fetch_json, wait, close — and
# no JavaScript crosses this boundary: each engine spells its own fetch()
# in its own driver's dialect.
# --------------------------------------------------------------------------- #
import logging as _logging
from pathlib import Path as _Path
from typing import Protocol as _Protocol

from output_writer import finish_run as _finish_run
from proxy_pool import is_proxy_dead_error as _is_proxy_dead_error, redact_credentials as _redact

_log = _logging.getLogger("page_flow")

CHALLENGE_WAIT_S = 15  # a Cloudflare managed challenge can clear by itself; give it this long


class PageSession(_Protocol):
    async def goto(self, url: str) -> Optional[int]: ...  # HTTP status or None; raises on failure
    async def content(self) -> str: ...
    async def fetch_json(self, url: str) -> tuple: ...  # (status, decoded JSON or None, error text)
    async def wait(self, seconds: float) -> None: ...
    async def close(self) -> None: ...


class Engine(_Protocol):
    name: str
    readiness_s: float

    async def open(self, proxy) -> PageSession: ...
    async def sleep(self, seconds: float) -> None: ...
    async def solve_captcha(self, session: PageSession, *, html: str, url: str) -> Optional[dict]: ...


class SolveBudget:
    """One cap on PAID captcha solves for the whole run (a
    per-page limit nothing sums is a bill). `limit=0` means never pay."""

    def __init__(self, limit: int):
        self.limit = max(0, int(limit))
        self.spent = 0

    def remaining(self) -> int:
        return max(0, self.limit - self.spent)

    def spend(self) -> None:
        self.spent += 1


def nonnegative_int(value: str) -> int:
    """argparse type for counts where 0 is meaningful (--retries counts EXTRA
    attempts, so 0 still navigates once). A negative value used to be
    accepted by two engines of three and made the loop navigate zero times."""
    import argparse
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value!r})")
    return ivalue


def nonnegative_float(value: str) -> float:
    import argparse
    fvalue = float(value)
    if not fvalue >= 0:  # also rejects nan
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value!r})")
    return fvalue


def resolve_urls(args) -> tuple:
    """(urls, skipped). `--url` wins over `--urls-file`. A robots.txt-
    disallowed path or a non-article URL is logged and skipped, never
    fetched."""
    if args.url:
        candidates = [args.url]
    elif args.urls_file:
        try:
            lines = _Path(args.urls_file).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ValueError(f"could not read --urls-file {args.urls_file!r}: {exc}")
        candidates = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    else:
        return [], 0
    urls, skipped = [], 0
    for url in candidates:
        if pp.is_disallowed_path(url):
            _log.warning("Skipping %s — its path is disallowed by perplexity.ai's robots.txt; this tool never requests a disallowed path.", url)
            skipped += 1
            continue
        if not pp.is_page_url(url):
            _log.warning("Skipping %s — not a perplexity.ai article URL (/page/... or /discover/{topic}/...).", url)
            skipped += 1
            continue
        urls.append(url)
    return urls, skipped


def _dump_path(out_path: str, index: int) -> str:
    return f"{_Path(out_path).with_suffix('')}_debug_{index}.html"


async def _solve_within_budget(engine: Engine, session: PageSession, args, *, html: str, url: str) -> Optional[dict]:
    budget = getattr(args, "_solve_budget", None)
    if budget is not None and budget.remaining() == 0:
        _log.warning("Captcha solving skipped: the run's solve budget is spent (--max-solves %d).", budget.limit)
        return None
    result = await engine.solve_captcha(session, html=html, url=url)
    if budget is not None and result and result.get("action") in ("solved", "warning_solver_error"):
        budget.spend()  # a task was created and billed, whatever came back
    return result


async def fetch_article(engine: Engine, args, url: str, index: int, proxy_pool, client) -> Outcome:
    """One article URL: a typed outcome, including unread and rejected data.
    Open the page (its cookies clear Cloudflare), wait out a challenge
    (bounded), solve one within budget, then read /rest/article/ with the
    page's own fetch(), retrying a refusal (API_RETRY_DELAYS_S)."""
    proxy = proxy_pool.next() if proxy_pool else None
    _log.info("Fetching %s (proxy: %s)", url, proxy.masked() if proxy else "(none — direct, or the --cdp-endpoint session's own exit)")
    try:
        session = await engine.open(proxy)
    except Exception as exc:
        _log.error("Browser connection failed — treating this URL as failed, not a crash: %s", _redact(str(exc)))
        return Outcome(None, False, False, "none", failure="fetch_error")
    try:
        last_error, status = None, None
        for attempt in range(args.retries + 1):
            try:
                status = await session.goto(url)
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 — every remote call must be bounded and reported
                last_error = _redact(str(exc)).splitlines()[0] if str(exc) else type(exc).__name__
                if proxy_pool is not None and proxy is not None and _is_proxy_dead_error(last_error):
                    proxy_pool.report_failure(proxy, dead=True)
                    _log.warning("Proxy reported dead: %s", last_error)
                else:
                    _log.warning("Navigation attempt %d/%d for %s failed: %s", attempt + 1, args.retries + 1, url, last_error)
                if attempt < args.retries:
                    await engine.sleep(args.retry_delay)
        if last_error is not None:
            _log.error("%s permanently failed to load: %s", url, last_error)
            return Outcome(None, False, False, "none", failure="fetch_error")

        html = await session.content()
        waited = 0.0
        while is_challenge(html) and waited < CHALLENGE_WAIT_S:
            await session.wait(1)
            waited += 1
            try:
                html = await session.content()
            except Exception:  # noqa: BLE001 — mid-navigation while the challenge redirects
                continue
        if waited and not is_challenge(html):
            _log.info("%s: Cloudflare challenge cleared by itself after %.0fs.", url, waited)
        if is_challenge(html) and args.solve_captcha != "off":
            result = await _solve_within_budget(engine, session, args, html=html, url=url)
            if result and result.get("action") == "solved":
                await session.wait(engine.readiness_s)
                html = await session.content()

        _topic, ref = pp.article_ref(url)
        api_status, article_json, api_error = (0, None, "skipped: page is a bot challenge")
        if not is_challenge(html):
            api_status, article_json, api_error = await session.fetch_json(pp.article_api_url(ref))
            for delay in API_RETRY_DELAYS_S:
                if not should_retry_api(api_status, api_error) or getattr(engine, "fatal", None):
                    break
                _log.info("%s: article API HTTP %s — retrying in %ss (a fresh profile needs the page's own bot check first).", url, api_status or "-", delay)
                await engine.sleep(delay)
                api_status, article_json, api_error = await session.fetch_json(pp.article_api_url(ref))
        outcome = decide(url=url, http_status=status, html=html, api_status=api_status,
                         article_json=article_json, api_error=api_error)
        for message in outcome.warnings:
            _log.warning("%s", message)
        if proxy_pool is not None and proxy is not None:
            if outcome.blocked and status in (403, 429):
                proxy_pool.report_failure(proxy, dead=True)
            elif not outcome.blocked:
                proxy_pool.report_success(proxy)
        if args.dump_html:
            _Path(_dump_path(args.out, index)).write_text(html, encoding="utf-8")
        if getattr(engine, "last_remote_error", False) and outcome.product is None:
            outcome.failure = "remote_api_error"
        return outcome
    except Exception as exc:
        _log.warning("Article operation failed for %s: %s", url, _redact(str(exc)))
        return Outcome(None, False, False, "none", failure="fetch_error")
    finally:
        await _close_session(session)


async def _close_session(session):
    try:
        await session.close()
    except Exception as exc:
        _log.warning("Session cleanup failed: %s", _redact(str(exc)))


# A feed page that answers with nothing but `next_token` set is a stall
# signal only once it repeats: one empty page can be a transient gap, two
# consecutive ones mean the cursor cannot advance (its offset moves by the
# item count, which is 0). Stopping then is the difference between an
# auditable `pagination_stalled` and an endless loop.
MAX_CONSECUTIVE_EMPTY_PAGES = 2

# `pagination_stalled` kinds, reported in the sidecar so a reader can tell
# a stuck cursor from a page that merely offered nothing new:
#   - "duplicate_cursor": this page's items are IDENTICAL to the previous
#     page's (the site ignored the offset and served the same page again);
#   - "empty_pages": N consecutive pages carried 0 items while claiming
#     there was more;
#   - "no_new_items": the page had items, but every one was already seen.
STALL_DUPLICATE_CURSOR = "duplicate_cursor"
STALL_EMPTY_PAGES = "empty_pages"
STALL_NO_NEW_ITEMS = "no_new_items"


async def collect_discover(engine: Engine, args, topic: str, limit: int, proxy_pool) -> DiscoveryResult:
    """Read the Discover feed page by page and stop with a REASON.

    Every attempted page is recorded in `result.pages` — offset, item count
    and outcome — so a stopped run can be audited page by page instead of
    just saying "it stopped". The three ways pagination ends early are kept
    apart on purpose:

      - a repeating page or consecutive empty pages → `pagination_stalled`
        (the cursor is stuck; nothing is blocked, nothing more is coming);
      - a throttle (429) or a refusal after pages were already read →
        `rate_limited` (slow down; a first-page challenge stays `blocked`,
        because that is a bot wall, not a rate limit);
      - a request/parse failure → `fetch_error` / `remote_api_error` /
        `parse_error`.

    In every early-stop case the URLs already collected are returned, so
    `run()` still fetches and writes the articles that DID arrive.
    """
    result = DiscoveryResult()
    session = None
    previous_page_urls: Optional[List[str]] = None
    consecutive_empty = 0
    try:
        session = await engine.open(proxy_pool.next() if proxy_pool else None)
        await session.goto(pp.DISCOVER_URL)
        html = await session.content()
        for _ in range(CHALLENGE_WAIT_S):
            if not is_challenge(html):
                break
            await session.wait(1)
            try:
                html = await session.content()
            except Exception:  # noqa: BLE001 — mid-navigation while the challenge redirects
                continue
        if is_challenge(html):
            result.failure, result.blocked = "blocked", True
            return result
        while len(result.urls) < limit:
            page_number = len(result.pages) + 1
            offset = result.offset
            target = pp.discover_feed_api_url(topic, offset=offset)
            status, data, error = await session.fetch_json(target)
            for delay in API_RETRY_DELAYS_S:
                if not should_retry_api(status, error) or getattr(engine, "fatal", None):
                    break
                await engine.sleep(delay)
                status, data, error = await session.fetch_json(target)

            def record(items=None, new_urls=0, has_more=None, page_status=status, page_error=error):
                result.pages.append({
                    "page": page_number, "offset": offset, "items": items,
                    "new_urls": new_urls, "has_more": has_more,
                    "status": page_status, "error": page_error,
                })

            if error or status != 200:
                record(page_status=status, page_error=error)
                if status in BLOCKING_API_STATUSES and result.pages_fetched:
                    # Refused/throttled AFTER at least one feed page was
                    # read: the feed worked a moment ago, so this is a
                    # rate limit — the caller's answer is "slow down", not
                    # "buy a proxy". Explicitly NOT `blocked`: a stall or
                    # a throttle must never be reported as a bot wall.
                    result.rate_limited = True
                    result.failure = "rate_limited"
                elif status in BLOCKING_API_STATUSES:
                    # Nothing was read yet: a bot challenge walled the feed
                    # before pagination began. That IS a block (exit 3, no
                    # rows), with its own stop_reason kept for a 429.
                    result.blocked = True
                    result.rate_limited = status == 429
                    result.failure = "rate_limited" if result.rate_limited else "blocked"
                else:
                    result.failure = ("remote_api_error" if getattr(engine, "last_remote_error", False)
                                      else "fetch_error")
                break
            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                record()
                result.failure = "parse_error"
                break
            items = data["items"]
            page_urls, has_more = pp.parse_discover_feed(data, topic=topic)
            if len(page_urls) != len(items) or any(not pp.is_page_url(u) for u in page_urls):
                record(items=len(items))
                result.failure = "parse_error"
                break

            new = list(dict.fromkeys(u for u in page_urls if u not in result.urls))
            record(items=len(items), new_urls=len(new), has_more=has_more)

            # The page's URLs are collected whatever happens next: a final
            # page still contributes its items even though it ENDS pagination.
            result.urls.extend(new)
            result.capped = len(result.urls) > limit or (len(result.urls) == limit and has_more)

            # An EXACT repeat of the previous page is checked before
            # `has_more`: "the cursor did not advance" is a stall whether
            # or not the repeat claims more is coming. A page that repeats
            # and says "no more" must not read as a clean end.
            if page_urls and page_urls == previous_page_urls:
                result.stall = {
                    "kind": STALL_DUPLICATE_CURSOR, "page": page_number, "offset": offset,
                    "previous_offset": result.pages[-2]["offset"] if len(result.pages) > 1 else None,
                }
                result.failure = "pagination_stalled"
                break

            if not has_more:
                break  # the feed said this was the last page: a clean end.

            if not page_urls:
                consecutive_empty += 1
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_PAGES:
                    result.stall = {
                        "kind": STALL_EMPTY_PAGES, "page": page_number, "offset": offset,
                        "consecutive_empty": consecutive_empty,
                    }
                    result.failure = "pagination_stalled"
                    break
                # A single empty page may be a gap; ask the same offset
                # again, politely. (`offset` moves by the item count, 0 here.)
                await engine.sleep(args.delay_between_pages)
            else:
                consecutive_empty = 0
                if not new:
                    # Items arrived but every one was already seen: the
                    # cursor is moving over nothing. Also a stall (this is
                    # the case the old `if not new` guard covered).
                    result.stall = {
                        "kind": STALL_NO_NEW_ITEMS, "page": page_number, "offset": offset,
                        "items": len(items),
                    }
                    result.failure = "pagination_stalled"
                    break
                result.offset += len(items)
                if len(result.urls) < limit:
                    await engine.sleep(args.delay_between_pages)
            previous_page_urls = page_urls
        result.urls = result.urls[:limit]
        return result
    except Exception as exc:
        _log.warning("Discover operation failed: %s", _redact(str(exc)))
        result.failure = "fetch_error"
        return result
    finally:
        if session is not None:
            await _close_session(session)


async def run(engine: Engine, args, *, urls: List[str], discover_topic: Optional[str], proxy_pool, client,
              started_at: float) -> int:
    discovery = None
    if discover_topic:
        discovery = await collect_discover(engine, args, discover_topic, args.max_results, proxy_pool)
        urls = discovery.urls
        if discovery.failure:
            if discovery.stall:
                _log.warning("Discover stopped after %d page(s) at offset %s: %s (%s). %d URL(s) already collected.",
                             discovery.pages_fetched, discovery.offset, discovery.failure,
                             discovery.stall.get("kind"), len(discovery.urls))
            else:
                _log.warning("Discover incomplete after %d page(s) at offset %s: %s",
                             discovery.pages_fetched, discovery.offset, discovery.failure)
    products: List[Product] = []
    failed_pages: List[int] = []
    failures = []
    any_blocked = bool(discovery and discovery.blocked)
    rate_limited = bool(discovery and discovery.rate_limited)
    remote_api_error = bool(discovery and discovery.failure == "remote_api_error")
    completed = 0
    batch = urls[:args.max_results]
    for i, url in enumerate(batch, start=1):
        outcome = await fetch_article(engine, args, url, i, proxy_pool, client)
        any_blocked = any_blocked or outcome.blocked
        rate_limited = rate_limited or outcome.rate_limited
        remote_api_error = remote_api_error or outcome.failure == "remote_api_error"
        if outcome.failure or outcome.blocked:
            failed_pages.append(i)
            failures.append({"url": url, "reason": outcome.failure or ("rate_limited" if outcome.rate_limited else "blocked")})
        else:
            completed += 1
        if outcome.product is not None:
            products.append(outcome.product)
        if getattr(engine, "fatal", None):
            for j, pending in enumerate(batch[i:], i + 1):
                failed_pages.append(j)
                failures.append({"url": pending, "reason": "remote_api_error"})
            break
        if i < len(batch):
            await engine.sleep(args.delay_between_pages)
    return finish(args, products=products, blocked=any_blocked, remote_api_error=remote_api_error,
                  engine_name=engine.name, urls=urls, discover_topic=discover_topic, started_at=started_at,
                  pages_completed=completed, failed_pages=failed_pages, failures=failures,
                  discovery=discovery, rate_limited=rate_limited)


def discovery_meta(discovery: DiscoveryResult) -> dict:
    """The sidecar's `discovery` block — everything needed to audit HOW the
    feed read ended without re-running it:

      - `complete` / `stop_reason`: whether it ended cleanly, and the
        machine-readable reason it did not (`pagination_stalled`,
        `rate_limited`, ...);
      - `pages_fetched`: pages the site actually returned;
      - `page_items`: how many items EACH returned page carried, in order —
        a page's count that contradicts its offset is how a stuck cursor
        shows up on inspection;
      - `pages`: the per-page log (offset, items, new URLs, outcome), which
        also records the request that failed, so "why did it stop" is not
        just the last page's word;
      - `stall`: the stall kind and the page/offset where the cursor got
        stuck (None unless `stop_reason == "pagination_stalled"`).

    `urls_collected` counts URLs the feed offered; `written_rows` /
    `unfetched_urls` (what became of each of them) are added by `finish()`,
    which is where those facts exist.
    """
    return {
        "complete": discovery.failure is None,
        "stop_reason": discovery.failure,
        "offset": discovery.offset,
        "urls_collected": len(discovery.urls),
        "pages_fetched": discovery.pages_fetched,
        "page_items": discovery.page_item_counts,
        "pages": list(discovery.pages),
        "stall": discovery.stall,
        "blocked": discovery.blocked,
        "rate_limited": discovery.rate_limited,
        "capped": discovery.capped,
    }


def finish(args, *, products: List[Product], blocked: bool, remote_api_error: bool, engine_name: str,
           urls: List[str], discover_topic: Optional[str], started_at: float, pages_completed: int,
           failed_pages: List[int], failures=None, discovery=None, rate_limited=False) -> int:
    budget = getattr(args, "_solve_budget", None)
    label = f"{pp.DISCOVER_URL} (topic={discover_topic})" if discover_topic else (urls[0] if urls else "")
    selection = ({"mode": "discover", "topic": discover_topic, "max_results": args.max_results}
                 if discover_topic else {"mode": "urls", "urls": urls, "max_results": args.max_results})
    extra = {"solves_spent": budget.spent if budget is not None else 0, "discover_topic": discover_topic,
             "selection": selection, "failed_urls": failures or []}
    if discovery is not None:
        block = discovery_meta(discovery)
        # The two facts that only exist here, after the articles were tried:
        # what actually made it into the file, and which feed URLs did not,
        # each with its own reason. A stalled or throttled feed is auditable
        # without cross-referencing `failed_urls` by hand.
        block["written_rows"] = len(products)
        block["unfetched_urls"] = [dict(item) for item in (failures or [])]
        extra["discovery"] = block
    return _finish_run(
        products=products, out_path=args.out, fmt=args.format, engine=engine_name, url=label,
        pages_requested=len(urls[: args.max_results]), pages_completed=pages_completed,
        failed_pages=failed_pages or None, blocked=blocked, remote_api_error=remote_api_error,
        allow_empty=args.allow_empty, started_at=started_at, price_confirmed_pct=None,
        max_results=args.max_results, rate_limited=rate_limited,
        incomplete_reason=(discovery.failure if discovery and discovery.failure else
                           next((f["reason"] for f in (failures or []) if f["reason"] == "parse_error"), None)),
        capped=discovery.capped if discovery else len(urls) > args.max_results,
        extra_meta=extra,
    )


def validate_common(args, *, urls, skipped, print_err) -> Optional[int]:
    """The usage checks every engine makes before launching anything;
    returns an exit code to stop with, or None to go on."""
    from output_writer import EXIT_BAD_USAGE
    discover_topic = None if urls or args.url or args.urls_file else args.discover
    if not urls and not discover_topic:
        if skipped:
            print_err(f"Error: none of the URLs given is a fetchable article ({skipped} skipped) — nothing left to fetch")
        else:
            print_err("Error: provide --url, --urls-file or --discover")
        return EXIT_BAD_USAGE
    if args.format not in ("json", "csv"):
        print_err(f"Error: unsupported --format {args.format!r}")
        return EXIT_BAD_USAGE
    return None
