#!/usr/bin/env python3
"""run_policy.py — small pieces of run policy the three engines must agree
on, kept in ONE place so they cannot drift apart:

  - the argparse validators for every numeric flag (a negative --retries
    used to be accepted by two engines of three and silently skip
    navigation; a negative --scroll-delay crashed one of them mid-run);
  - which start URL a run uses when a LIDL_URL from the environment / .env
    meets a --query/--category the caller actually typed;
  - why a run stopped, decided from what the page itself states;
  - which store a run prices against (`--store-id`/`--zip`).

No driver code and no JavaScript lives here.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import lidl_parser as lp
import lidl_stores
from output_writer import (
    EXIT_BLOCKED,
    EXIT_OK,
    EXIT_PARTIAL,
    EXIT_REMOTE_API_ERROR,
    EXIT_ZERO_PRODUCTS,
    Product,
)

log = logging.getLogger("run_policy")


# --------------------------------------------------------------------------- #
# argparse validators — argparse turns ArgumentTypeError into "error:
# argument --flag: ..." and exit 2, which names the flag.
# --------------------------------------------------------------------------- #
def positive_int(value: str) -> int:
    ivalue = int(value)
    if ivalue < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer (got {value!r})")
    return ivalue


def nonnegative_int(value: str) -> int:
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0 (got {value!r})")
    return ivalue


def nonnegative_float(value: str) -> float:
    fvalue = float(value)
    if fvalue != fvalue or fvalue < 0:  # NaN, or negative
        raise argparse.ArgumentTypeError(f"must be a number >= 0 (got {value!r})")
    return fvalue


def unit_float(value: str) -> float:
    fvalue = float(value)
    if not 0.0 <= fvalue <= 1.0:
        raise argparse.ArgumentTypeError(f"must be between 0 and 1 (got {value!r})")
    return fvalue


# --------------------------------------------------------------------------- #
# Start URL
# --------------------------------------------------------------------------- #
class UsageError(Exception):
    """A combination of flags that cannot both be honoured."""


def resolve_start_url(args: argparse.Namespace) -> Optional[str]:
    """Pick the start URL.

    `env_config.apply_env` records `_url_source` when IT filled `--url`
    from LIDL_URL; a `--url` the caller typed carries no such attribute.
    So:

      - a typed --query/--category beats an environment/.env LIDL_URL (the
        variable is a convenience default, not an instruction to ignore
        what was typed) — logged, never silent;
      - a typed --url together with a typed --query/--category is refused:
        one of the two would be ignored, and guessing which is what made a
        run scrape a different search than the one asked for.
    """
    builders = bool(args.query or args.category)
    url_from_env = getattr(args, "_url_source", None)
    if args.url and builders:
        if url_from_env:
            log.info(
                "Ignoring LIDL_URL from %s: --query/--category was given on the command line.",
                url_from_env,
            )
            args.url = None
        else:
            raise UsageError("--url cannot be combined with --query/--category; pass one or the other")
    if args.url:
        return args.url
    if builders:
        return lp.search_url(query=args.query, category=args.category, sort=args.sort)
    return None


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
def resolve_store(args: argparse.Namespace) -> Optional[lidl_stores.Store]:
    """Look up the store `--store-id`/`--zip` name, and from then on record
    the store actually used on every row: `args.store_id` becomes its full
    number and `args.zip_code` its 5-digit zip.

    Raises UsageError for a store that does not exist, and
    lidl_stores.StoreApiError when the site or its store API cannot be read
    — the engines report that as a remote failure (exit 5), never as a run
    priced against no store at all."""
    try:
        store = lidl_stores.resolve_store(store_id=args.store_id, zip_code=args.zip_code)
    except lidl_stores.StoreLookupError as exc:
        raise UsageError(str(exc)) from None
    if store is not None:
        log.info("Pricing against Lidl store %s", store.describe())
        args.store_id = store.object_number
        args.zip_code = store.zip5
    return store


# --------------------------------------------------------------------------- #
# Multi-store runs (--store-ids)
# --------------------------------------------------------------------------- #
# Per-store outcomes in the sidecar's `stores` list and the run conclusion.
STORE_OUTCOME_SUCCESS = "success"   # the store was scraped and returned rows
STORE_OUTCOME_EMPTY = "empty"       # scraped cleanly, but the page yielded no rows
STORE_OUTCOME_FAILED = "failed"     # lookup, navigation/block or crash — no rows kept

# stop_reason values only a multi-store run takes.
STOP_ALL_STORES_EMPTY = "all_stores_empty"
STOP_STORE_FAILURES = "store_failures"
STOP_MIXED = "mixed"


def parse_store_ids(values: Optional[List[str]]) -> List[str]:
    """Flatten the repeatable --store-ids option. Each occurrence may hold
    one store number or a comma-separated list ("US01449,1449"), so both
    `--store-ids US01449 --store-ids 1450` and `--store-ids US01449,1450`
    work. Tokens are trimmed, empties rejected, and repeats of the SAME
    store (any spelling, e.g. "1449" then "US01449") collapse to one
    request — scraping one store twice would only duplicate its rows."""
    if not values:
        return []
    tokens: List[str] = []
    for value in values:
        for token in str(value).split(","):
            token = token.strip()
            if token:
                tokens.append(token)
    if not tokens:
        raise UsageError("--store-ids needs at least one Lidl US store number, e.g. --store-ids US01449,1450")
    # Validate every token's shape up front — a malformed number is a usage
    # error (exit 2) before any network call, matching single --store-id.
    for token in tokens:
        try:
            lidl_stores.normalise_store_id(token)
        except lidl_stores.StoreLookupError as exc:
            raise UsageError(str(exc)) from None
    seen: dict = {}
    unique: List[str] = []
    for token in tokens:
        normalised = lidl_stores.normalise_store_id(token)
        if normalised not in seen:
            seen[normalised] = True
            unique.append(token)
    return unique


def validate_store_flags(args: argparse.Namespace) -> None:
    """--store-ids is mutually exclusive with the single-store selectors:
    honouring both would mean guessing which store set wins, the same
    ambiguity --url vs --query already refuses."""
    if not getattr(args, "store_ids", None):
        return
    if args.store_id:
        raise UsageError("--store-ids cannot be combined with --store-id; pass one or the other")
    if args.zip_code:
        raise UsageError("--store-ids cannot be combined with --zip; --zip names only one store")


@dataclass
class StoreTarget:
    """A store a multi-store run should price against, or the reason it
    could not be resolved. Unresolved targets never reach a browser."""
    requested: str
    object_number: Optional[str] = None
    store: Optional[lidl_stores.Store] = None
    error: Optional[str] = None
    error_kind: Optional[str] = None  # "lookup" | "api"

    @property
    def resolved(self) -> bool:
        return self.store is not None


@dataclass
class StoreScrape:
    """What happened when one resolved target was scraped. The engines
    fill this from scrape_search()'s six-tuple, or mark a store that
    raised out of the engine itself."""
    target: StoreTarget
    products: List[Product] = field(default_factory=list)
    blocked: bool = False
    remote_api_error: bool = False
    scroll_error: bool = False
    stop_reason: Optional[str] = None
    crashed: bool = False
    crash_detail: Optional[str] = None

    @property
    def outcome(self) -> str:
        if self.products:
            return STORE_OUTCOME_SUCCESS
        if self.crashed or self.blocked or self.remote_api_error:
            return STORE_OUTCOME_FAILED
        return STORE_OUTCOME_EMPTY


def resolve_store_targets(args: argparse.Namespace) -> List[StoreTarget]:
    """Resolve every --store-ids token through the existing per-store
    lookup/cookie path (see lidl_stores.resolve_stores). One store that
    does not exist is a failed TARGET, not a fatal run error: the others
    still get scraped and the failure is reported per store in the
    conclusion. Only when EVERY token fails validation/lookup does the
    caller treat the invocation itself as bad usage."""
    validate_store_flags(args)
    tokens = parse_store_ids(args.store_ids)
    resolutions = lidl_stores.resolve_stores(tokens)
    return [
        StoreTarget(
            requested=r.requested, object_number=r.object_number, store=r.store,
            error=r.error, error_kind=r.error_kind,
        )
        for r in resolutions
    ]


def _scrape_entry(scrape: Optional[StoreScrape], target: StoreTarget) -> dict:
    """One sidecar `stores` entry — the per-store success/failure/empty
    conclusion a consumer reads without scraping logs."""
    store = target.store
    if not target.resolved:
        return {
            "requested": target.requested,
            "store_id": target.object_number,
            "zip_code": None,
            "outcome": STORE_OUTCOME_FAILED,
            "error_kind": target.error_kind,
            "detail": target.error,
            "product_count": 0,
        }
    entry = {
        "requested": target.requested,
        "store_id": store.object_number,
        "zip_code": store.zip5,
        "outcome": scrape.outcome if scrape is not None else STORE_OUTCOME_FAILED,
        "product_count": len(scrape.products) if scrape is not None else 0,
        "stop_reason": scrape.stop_reason if scrape is not None else None,
    }
    if scrape is not None and scrape.crashed:
        entry["error_kind"] = "crash"
        entry["detail"] = scrape.crash_detail
    elif scrape is not None and scrape.remote_api_error:
        entry["error_kind"] = "remote_api_error"
    elif scrape is not None and scrape.blocked:
        entry["error_kind"] = "blocked"
    return entry


def plan_multi_store_finish(
    *, targets: List[StoreTarget], scrapes: List[Optional[StoreScrape]],
    pages_requested: int,
) -> dict:
    """Aggregate one multi-store run into the inputs finish_run() needs,
    keeping that function's precedence (and its never-overwrite-a-good-
    output guarantee) as the single decider of status and exit code.

    Returns a dict with products, blocked, remote_api_error,
    failed_pages (1-based positions of stores that did not succeed, so
    finish_run maps rows+failure to EXIT_PARTIAL exactly as a failed
    scroll round already does), stop_reason, extra_meta and a log-ready
    `summary` list. Rows from different stores are simply concatenated:
    the engine-level seen-sku set is per store, so the same SKU at two
    stores survives as two rows distinguished by store_id/zip_code."""
    by_number = {id(s.target): s for s in scrapes if s is not None}
    entries: List[dict] = []
    products: List[Product] = []
    blocked = remote_api_error = False
    failed_positions: List[int] = []
    n_success = n_empty = n_failed = 0

    for position, target in enumerate(targets, start=1):
        scrape = by_number.get(id(target))
        entries.append(_scrape_entry(scrape, target))
        if not target.resolved or scrape is None or not scrape.products:
            failed_positions.append(position)
        if target.resolved and scrape is not None:
            products.extend(scrape.products)
            blocked = blocked or scrape.blocked
            remote_api_error = remote_api_error or scrape.remote_api_error or scrape.crashed
        outcome = entries[-1]["outcome"]
        if outcome == STORE_OUTCOME_SUCCESS:
            n_success += 1
        elif outcome == STORE_OUTCOME_EMPTY:
            n_empty += 1
        else:
            n_failed += 1

    if n_success == 0:
        if n_empty and not n_failed:
            stop_reason = STOP_ALL_STORES_EMPTY
        else:
            stop_reason = STOP_STORE_FAILURES
    elif n_failed or n_empty:
        stop_reason = STOP_MIXED
    else:
        stop_reason = "max_results"

    pages_completed = sum(
        1 for t, s in zip(targets, scrapes)
        if t.resolved and s is not None
    )
    summary = [
        f"store {e['store_id'] or e['requested']}: {e['outcome']}"
        + (f" ({e['product_count']} rows)" if e["outcome"] == STORE_OUTCOME_SUCCESS else "")
        + (f" — {e.get('detail') or e.get('error_kind')}" if e["outcome"] == STORE_OUTCOME_FAILED else "")
        for e in entries
    ]
    extra_meta = {
        "multi_store": True,
        "stores": entries,
        "store_summary": {
            "requested": len(targets), "success": n_success,
            "empty": n_empty, "failed": n_failed,
        },
    }
    return {
        "products": products,
        "blocked": blocked,
        "remote_api_error": remote_api_error,
        "failed_pages": failed_positions,
        "pages_requested": pages_requested,
        "pages_completed": pages_completed,
        "stop_reason": stop_reason,
        "extra_meta": extra_meta,
        "summary": summary,
    }


def all_targets_failed(targets: List[StoreTarget]) -> bool:
    return bool(targets) and all(not t.resolved for t in targets)


def bad_usage_from_targets(targets: List[StoreTarget]) -> str:
    """The exit-2 message when no --store-ids token resolved: name each
    bad store and why, without starting a browser or touching output."""
    details = "; ".join(f"{t.requested}: {t.error}" for t in targets)
    return f"none of the --store-ids stores could be used ({details})"


def expected_exit_from_plan(plan: dict) -> int:
    """The exit code finish_run() will return for a planned multi-store
    run, exposed so engines and tests can state the contract directly."""
    if plan["products"]:
        if plan["blocked"] or plan["remote_api_error"] or plan["failed_pages"]:
            return EXIT_PARTIAL
        return EXIT_OK
    if plan["remote_api_error"]:
        return EXIT_REMOTE_API_ERROR
    if plan["blocked"]:
        return EXIT_BLOCKED
    return EXIT_ZERO_PRODUCTS


def finish_multi_store(*, args, start_url: str, targets, scrapes, started_at: float,
                       engine: str, finish_run, logger) -> int:
    """The shared tail of every engine's multi-store run. Aggregates the
    per-store outcomes once, logs the per-store conclusion, and hands the
    combined rows to ONE finish_run() call, so that function's exit-code
    precedence and atomic-write/never-overwrite guarantees stay the single
    decider — the three engines cannot drift on multi-store status.

    `finish_run`/`engine` are passed in by the caller because output_writer
    is engine-agnostic and run_policy must not import an engine."""
    plan = plan_multi_store_finish(
        targets=targets, scrapes=scrapes, pages_requested=args.max_scrolls)
    for line in plan["summary"]:
        logger.info("Multi-store result — %s", line)
    products = plan["products"]
    price_confirmed_pct = (
        sum(1 for p in products if p.price is not None) / len(products)) if products else None
    parser_failed = any(
        s is not None and s.stop_reason == STOP_PARSER_FOUND_NOTHING for s in scrapes)
    return finish_run(
        products=products,
        out_path=args.out,
        fmt=args.format,
        engine=engine,
        url=start_url,
        pages_requested=plan["pages_requested"],
        pages_completed=plan["pages_completed"],
        failed_pages=plan["failed_pages"],
        blocked=plan["blocked"],
        remote_api_error=plan["remote_api_error"],
        allow_empty=args.allow_empty,
        started_at=started_at,
        price_confirmed_pct=price_confirmed_pct,
        parser_failed=parser_failed,
        stop_reason=plan["stop_reason"],
        extra_meta=plan["extra_meta"],
    )


# --------------------------------------------------------------------------- #
# Scroll budget
# --------------------------------------------------------------------------- #
DEFAULT_MAX_SCROLLS = 20


def default_max_scrolls(max_results: int) -> int:
    """Live, 2026-10-18: 60 products took 11-14 rounds and 200 took 38, so
    a fixed 20 stopped a 200-product aisle at 96. One round per four
    products plus slack, never below the old 20."""
    return max(DEFAULT_MAX_SCROLLS, max_results // 4 + 10)


def apply_scroll_default(args: argparse.Namespace) -> None:
    if args.max_scrolls is None:
        args.max_scrolls = default_max_scrolls(args.max_results)


# --------------------------------------------------------------------------- #
# HTTP status of the first navigation
# --------------------------------------------------------------------------- #
def status_means_blocked(status: Optional[int], html: str) -> bool:
    """A status >= 400 counts as blocked, except Lidl's own no-match page,
    which it serves as a 404 for some stores (see lidl_stores.py)."""
    return status is not None and status >= 400 and not lp.is_no_match_page(html)


# --------------------------------------------------------------------------- #
# End of run
# --------------------------------------------------------------------------- #
# Values `stop_reason` can take in the sidecar.
STOP_MAX_RESULTS = "max_results"
STOP_MAX_SCROLLS = "max_scrolls"
STOP_STALLED = "stalled"
STOP_SCROLL_FAILED = "scroll_failed"
STOP_INCOMPLETE_GRID = "incomplete_grid"
STOP_PARSER_FOUND_NOTHING = "parser_found_nothing"
STOP_NAVIGATION_FAILED = "navigation_failed"
STOP_CDP_CONNECT_FAILED = "cdp_connect_failed"
STOP_BLOCKED = "blocked"
STOP_NO_MATCH = "no_match"


def end_of_run(
    *, final_html: str, collected: int, max_results: int, blocked: bool,
    loop_reason: str, scroll_failed: bool,
) -> Tuple[str, bool, bool]:
    """Decide (stop_reason, shortfall, parser_failed) once the scroll loop
    has ended.

    Lidl prints its own catalogue counter ("142 Products"). When that
    counter states products and the parser collected none, the page was
    SERVED and the rows were lost by our selectors — a parser failure, never
    an empty catalogue. When it states more than were collected (up to
    --max-results) the run is short and must not read as complete.
    """
    total = lp.total_result_count(final_html)
    if blocked:
        # finish_run reports blocked with no rows as 3, with rows as partial.
        return STOP_BLOCKED, False, False
    if lp.is_no_match_page(final_html):
        # The parser drops the unrelated fallback grid this page carries, so
        # its own "N Products" counter must not read as lost rows.
        log.warning("Lidl found no match for this search — the products it shows instead are not results.")
        return STOP_NO_MATCH, False, False
    if total is not None and total > 0 and collected == 0:
        log.error(
            "Lidl's own counter states %d products but the parser recognised none — "
            "treating as a parser failure, not an empty search. Re-run with --dump-html "
            "and compare the markup against lidl_parser.py.", total,
        )
        return STOP_PARSER_FOUND_NOTHING, False, True
    if scroll_failed:
        return STOP_SCROLL_FAILED, True, False
    expected = min(total, max_results) if total is not None else None
    if expected is not None and collected < expected:
        log.warning(
            "Incomplete virtualized grid: Lidl reports %d products, requested %d, collected %d.",
            total, max_results, collected,
        )
        return STOP_INCOMPLETE_GRID, True, False
    return loop_reason, False, False


def warn_if_nothing_found(*, collected: int, blocked: bool, stop_reason: str, logger) -> None:
    """Said once at the end of an empty run, not on a first render that has
    not filled its lazy grid yet (an aisle page always looked empty then)."""
    if collected or blocked or stop_reason in (STOP_NO_MATCH, STOP_PARSER_FOUND_NOTHING):
        return
    logger.warning(
        "No products recognised on this page — either it lists none (a /c/…/s… "
        "landing page often holds no product grid; aisle listings are /h/…/h… "
        "paths), or lidl_parser.py's selectors need updating for the current "
        "lidl.com markup. Re-run with --dump-html to inspect the captured page."
    )


# --------------------------------------------------------------------------- #
# Captcha step — one implementation for all three engines.
# --------------------------------------------------------------------------- #
# None of the local engines injects a solved token into the page, so none of
# them may buy one. The Scraping Browser API (--cdp-endpoint) solves inside
# the remote browser with its own Captcha.setAutoSolve, which is unaffected.
LOCAL_ENGINES_INJECT_TOKEN = False

# Outcomes after which a page with no product cards counts as blocked.
UNSOLVED_ACTIONS = (
    "warning_no_key", "warning_solver_error", "detected_unidentified_widget",
    "detected_not_injectable", "budget_exhausted",
)


def captcha_step(*, html: str, url: str, client, policy: str, min_score: float, budget, logger) -> Optional[dict]:
    """Run the when-blocked solve policy once for one scroll round. `budget`
    is the page's SolveBudget, created once per page by the engine."""
    from captcha_solver import solve_when_blocked  # local: keeps this module light to import

    if policy == "off" or client is None:
        return None
    result = solve_when_blocked(
        client=client, page_url=url, html=html, count_product_links=lp.count_result_cards,
        budget=budget, can_inject=LOCAL_ENGINES_INJECT_TOKEN,
        extra_markers=lp.BOT_CHALLENGE_MARKERS, min_score=min_score,
    )
    action = result.get("action")
    if not budget.first_time(action):
        return result
    if action == "skipped_products_present":
        logger.info("Captcha widget present but results already rendered — not solving.")
    elif action == "warning_no_key":
        logger.warning("Captcha solving skipped: %s", result.get("detail"))
    elif action == "warning_solver_error":
        logger.warning("Captcha solve failed: %s", result.get("detail"))
    elif action == "solved":
        logger.info("Captcha solved via 2Captcha (%s).", result.get("captcha_type"))
    elif action == "detected_unidentified_widget":
        logger.warning("A captcha-like marker was detected but no known widget/sitekey could be extracted.")
    elif action == "detected_not_injectable":
        logger.warning(
            "A %s challenge is gating this page. This engine does not inject a solved token "
            "into a locally launched browser, so no solve was bought (it could not clear the "
            "page). Use --cdp-endpoint (the Scraping Browser API solves inside its own browser) "
            "or a different exit.", result.get("captcha_type"),
        )
    elif action == "budget_exhausted":
        logger.warning("Captcha solve allowance for this page is spent — not buying another.")
    return result
