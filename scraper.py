"""Google Play discovery pipeline: randomized search plus parallel details fetch.

Two network stages dominate a run:

1. ``collect_candidates`` — issues one search request per (keyword, locale)
   pair. Those requests are independent, so they are fanned out concurrently.
2. ``fetch_details_batch`` — resolves metadata for a sample of candidates. The
   persistent cache is read once for the whole sample, so only genuine misses
   reach the network.

Failures are logged and recorded in the run summary: a single rejected
request must never abort a run that already paid for dozens of others.
"""

import logging
import math
import random
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import streamlit as st
from google_play_scraper import app as get_app_details
from google_play_scraper import search

from config import (
    ALL_KEYWORDS,
    CACHE_TTL_SEARCH,
    COL_ADS,
    COL_GENRE,
    COL_IAP,
    COL_ICON,
    COL_INSTALLS,
    COL_LINK,
    COL_RATING,
    COL_REVIEWS,
    COL_TITLE,
    COL_UPDATED,
    DEFAULT_SEARCH_WORKERS,
    DEFAULT_WORKERS,
    DETAILS_OVERSAMPLE,
    KEY_GENRE,
    KEY_INSTALLS_INT,
    KEY_SCORE,
    MAX_LOCALES_PER_RUN,
    SEARCH_LOCALES,
)
from db import get_cached_details_many, set_cached_details_many

logger = logging.getLogger(__name__)

# Thousands separators, spaces (including non-breaking ones) and the trailing
# "+" Google Play appends. Everything else makes the value unparseable.
_INSTALLS_SEPARATORS = re.compile(r"[\s,._+\u00a0\u202f\u2009]+")

_PLAY_STORE_URL = "https://play.google.com/store/apps/details?id={app_id}"


@dataclass
class RunSummary:
    """Auditable counters and context for a single discovery run.

    The pipeline stages fill this in as they go so a failed search or a
    filtered-out candidate is visible afterwards instead of vanishing. The
    object is stored in the Streamlit session next to the results, so it
    survives the reruns triggered by widgets such as the download button.

    Attributes:
        keywords (list[str]): Keywords actually sampled for the run.
        locales (list[str]): Locales actually sampled, formatted as
            ``"lang/country"``.
        combinations_total (int): Number of keyword × locale combinations
            issued.
        combinations_succeeded (int): Combinations whose search request
            completed without raising.
        failed_combinations (list[dict]): Combinations whose search request
            raised, each as ``{"query", "lang", "country"}``.
        candidates (int): Unique candidate IDs after de-duplication and
            history filtering.
        details_cache_hits (int): Sampled candidates served from the details
            cache.
        details_network (int): Sampled candidates resolved over the network.
        details_missing (int): Sampled candidates skipped because no details
            could be obtained.
        excluded_below_min (int): Candidates dropped for falling under the
            minimum installs bound.
        excluded_above_max (int): Candidates dropped for exceeding the maximum
            installs bound. Stays ``0`` when the bound is disabled (``0``).
        results (int): Rows in the final result set.
        history_saved (bool): ``False`` when the seen-apps history could not
            be persisted after the run.
    """

    keywords: list[str] = field(default_factory=list)
    locales: list[str] = field(default_factory=list)
    combinations_total: int = 0
    combinations_succeeded: int = 0
    failed_combinations: list[dict] = field(default_factory=list)
    candidates: int = 0
    details_cache_hits: int = 0
    details_network: int = 0
    details_missing: int = 0
    excluded_below_min: int = 0
    excluded_above_max: int = 0
    results: int = 0
    history_saved: bool = True


def _thread_pool(max_workers: int) -> ThreadPoolExecutor:
    """Create a pool whose workers inherit the Streamlit script context.

    Threads spawned outside the Streamlit event loop have no
    ``ScriptRunContext``. Attaching the parent context keeps cached calls
    (``st.cache_data``) and other runtime-aware helpers behaving exactly as
    they do on the main thread, and suppresses spurious context warnings.

    Args:
        max_workers (int): Upper bound on concurrent workers. Values below one
            are raised to one because ``ThreadPoolExecutor`` rejects them.

    Returns:
        ThreadPoolExecutor: A ready-to-use executor.

    Examples:
        >>> with _thread_pool(2) as pool:
        ...     sorted(pool.map(abs, (-1, 2)))
        [1, 2]
    """
    return ThreadPoolExecutor(
        max_workers=max(1, max_workers),
        initializer=_make_context_initializer(),
    )


def _make_context_initializer():
    """Build a worker initializer that re-attaches the current script context.

    Returns:
        Callable | None: An initializer capturing the parent context, or
        ``None`` when there is no runtime context to propagate (bare mode,
        tests, or an incompatible Streamlit internals layout).

    Notes:
        The initializer body is fully guarded. A raising ``ThreadPoolExecutor``
        initializer poisons every worker in the pool, so context propagation is
        treated as a best-effort optimization rather than a hard requirement.
    """
    try:
        from streamlit.runtime.scriptrunner import (
            add_script_run_ctx,
            get_script_run_ctx,
        )
    except ImportError:  # pragma: no cover - Streamlit internals moved
        logger.debug("ScriptRunContext helpers unavailable; workers run unscoped")
        return None

    parent_ctx = get_script_run_ctx()
    if parent_ctx is None:
        return None

    def _attach_context() -> None:
        try:
            # Streamlit >= 1.49 accepts the context object itself.
            add_script_run_ctx(threading.current_thread(), parent_ctx)
        except Exception as exc:  # pragma: no cover - version drift
            logger.debug("Worker context propagation skipped: %s", exc)

    return _attach_context


@st.cache_data(show_spinner=False, ttl=CACHE_TTL_SEARCH)
def _fetch_search(query: str, lang: str, country: str, limit: int) -> list:
    """Fetch Google Play search results for a localized query.

    Args:
        query (str): The search phrase to submit to Google Play.
        lang (str): The language code used by the scraper request.
        country (str): The country code used to localize search results.
        limit (int): The maximum number of hits to request.

    Returns:
        list: A list of raw search result dictionaries.

    Raises:
        Exception: Scraper errors propagate so the caller can record the
            failed combination in the run summary. Failed calls are not
            cached, so the next run retries them.

    Examples:
        >>> isinstance(_fetch_search("puzzle", "en", "us", 10), list)
        True
    """
    return search(query, lang=lang, country=country, n_hits=limit)


def _fetch_details(app_id: str) -> dict | None:
    """Fetch detailed metadata for a Google Play application.

    Cache reads and writes happen in the caller as batched transactions, so
    this helper only performs the network lookup.

    Args:
        app_id (str): The Google Play application ID to retrieve.

    Returns:
        dict | None: The application details dictionary when retrieval succeeds,
        otherwise ``None`` if the scraper raises an exception.

    Examples:
        >>> result = _fetch_details("com.example.app")
        >>> result is None or isinstance(result, dict)
        True
    """
    try:
        data = get_app_details(app_id)
    except Exception as exc:
        logger.debug("Details lookup failed for %s: %s", app_id, exc)
        return None

    return data if isinstance(data, dict) else None


def collect_candidates(
    queries_per_run: int,
    search_limit: int,
    seen_apps: set[str],
    custom_queries: list[str] | None = None,
    summary: RunSummary | None = None,
) -> tuple[list[str], list[str]]:
    """Collect unique unseen application IDs from randomized search queries.

    Args:
        queries_per_run (int): The number of keywords to sample for the current
            run.
        search_limit (int): The number of search hits to request per keyword and
            locale combination.
        seen_apps (set[str]): Application IDs that should be excluded from the
            candidate list.
        custom_queries (list[str] | None): Optional user-provided phrases that
            take priority over random keyword sampling.
        summary (RunSummary | None): Optional run summary to fill with the
            sampled keywords and locales, per-combination success/failure
            counts and the de-duplicated candidate count.

    Returns:
        tuple[list[str], list[str]]: A pair of the de-duplicated unseen
        application IDs discovered across the sampled queries and locales, and
        the keywords that were actually sampled for this run.

    Examples:
        >>> candidates, queries = collect_candidates(0, 5, set())
        >>> (candidates, queries) == ([], [])
        True
    """
    query_count = min(max(queries_per_run, 0), len(ALL_KEYWORDS))
    prioritized = list(
        dict.fromkeys(query.strip() for query in (custom_queries or []) if query.strip())
    )
    selected_queries = prioritized[:query_count]
    if len(selected_queries) < query_count:
        used_queries = {query.casefold() for query in selected_queries}
        remaining = [query for query in ALL_KEYWORDS if query.casefold() not in used_queries]
        selected_queries.extend(
            random.sample(
                remaining,
                k=min(query_count - len(selected_queries), len(remaining)),
            )
        )

    selected_locales = random.sample(
        SEARCH_LOCALES, k=min(MAX_LOCALES_PER_RUN, len(SEARCH_LOCALES))
    )

    if summary is not None:
        summary.keywords = list(selected_queries)
        summary.locales = [f"{lang}/{country}" for lang, country in selected_locales]

    if not selected_queries or not selected_locales:
        return [], selected_queries

    combinations = [
        (query, lang, country) for query in selected_queries for lang, country in selected_locales
    ]
    if summary is not None:
        summary.combinations_total = len(combinations)

    candidate_ids: list[str] = []
    workers = min(len(combinations), DEFAULT_SEARCH_WORKERS)

    with _thread_pool(workers) as executor:
        futures = {
            executor.submit(_fetch_search, query, lang, country, search_limit): (
                query,
                lang,
                country,
            )
            for query, lang, country in combinations
        }
        for future in as_completed(futures):
            query, lang, country = futures[future]
            try:
                results = future.result()
            except Exception as exc:
                # Rate limiting and transient network errors are expected here;
                # the run continues with the remaining combinations and the
                # failure is only recorded in the summary.
                logger.warning("Search failed for %r [%s/%s]: %s", query, lang, country, exc)
                if summary is not None:
                    summary.failed_combinations.append(
                        {"query": query, "lang": lang, "country": country}
                    )
                continue

            if summary is not None:
                summary.combinations_succeeded += 1

            # sample() returns a new list, so shuffling never touches the
            # object handed back by the Streamlit cache.
            for item in random.sample(results, k=len(results)):
                app_id = item.get("appId") if isinstance(item, dict) else None
                if app_id and app_id not in seen_apps:
                    candidate_ids.append(app_id)

    candidates = list(dict.fromkeys(candidate_ids))
    if summary is not None:
        summary.candidates = len(candidates)
    return candidates, selected_queries


def fetch_details_batch(
    app_ids: list[str],
    min_installs: int,
    max_installs: int,
    results_limit: int,
    summary: RunSummary | None = None,
) -> list[dict]:
    """Fetch, filter, and normalize metadata for a sampled batch of apps.

    Args:
        app_ids (list[str]): Candidate application IDs to inspect. Duplicates
            are collapsed so a repeated ID is only counted and fetched once.
        min_installs (int): The minimum install count allowed in the output.
        max_installs (int): The maximum install count allowed in the output. A
            value of ``0`` disables the upper bound.
        results_limit (int): The target number of results shown to the user and
            the basis for the sampling size.
        summary (RunSummary | None): Optional run summary to fill with cache
            hit/network counts, the number of candidates skipped for missing
            details and the per-bound exclusion counts.

    Returns:
        list[dict]: A list of normalized application rows ready for display in
        the UI.

    Examples:
        >>> isinstance(fetch_details_batch([], 0, 0, 10), list)
        True
    """
    unique_ids = list(dict.fromkeys(app_ids))
    if not unique_ids or results_limit <= 0:
        return []

    sample_size = min(len(unique_ids), max(results_limit, results_limit * DETAILS_OVERSAMPLE))
    sampled = random.sample(unique_ids, sample_size)

    # One batched query for the whole sample; only the misses hit the network.
    details_by_id = get_cached_details_many(sampled)
    if summary is not None:
        summary.details_cache_hits = len(details_by_id)
    missing = [app_id for app_id in sampled if app_id not in details_by_id]

    if missing:
        fetched_details: dict[str, dict] = {}
        workers = min(DEFAULT_WORKERS, max(4, results_limit // 2 + 2), len(missing))
        with _thread_pool(workers) as executor:
            futures = {executor.submit(_fetch_details, app_id): app_id for app_id in missing}
            for future in as_completed(futures):
                app_id = futures[future]
                try:
                    details = future.result()
                except Exception as exc:
                    logger.warning("Details task for %s failed: %s", app_id, exc)
                    continue
                if details:
                    details_by_id[app_id] = details
                    fetched_details[app_id] = details

        if summary is not None:
            summary.details_network = len(fetched_details)

        # A single transaction is substantially cheaper than one connection per
        # network response and still cannot invalidate an otherwise valid run.
        set_cached_details_many(fetched_details)

    found: list[dict] = []
    # Iterate the sample rather than completion order so identical inputs give
    # identical output ordering regardless of network timing.
    for app_id in sampled:
        details = details_by_id.get(app_id)
        if not details:
            if summary is not None:
                summary.details_missing += 1
            continue

        installs_count = _resolve_installs(details)
        if installs_count < min_installs:
            if summary is not None:
                summary.excluded_below_min += 1
            continue
        if max_installs and installs_count > max_installs:
            if summary is not None:
                summary.excluded_above_max += 1
            continue

        found.append(_normalize_row(app_id, details, installs_count))

    return found


def _normalize_row(app_id: str, details: dict, installs_count: int) -> dict:
    """Build a display row from raw Google Play metadata.

    Args:
        app_id (str): The Google Play application ID.
        details (dict): Raw metadata returned by the scraper.
        installs_count (int): The already parsed install count.

    Returns:
        dict: A row containing display columns plus the private fields used for
        filtering and novelty scoring. Missing metadata falls back to safe
        placeholders instead of ``None``.

    Examples:
        >>> row = _normalize_row("com.example.app", {"title": "Example"}, 1000)
        >>> row[COL_LINK].endswith("id=com.example.app")
        True
    """
    score = _finite_float(details.get("score"))
    genre = _display_text(details.get("genre"), "Unknown")
    ratings_count = _non_negative_int(details.get("ratings"))

    return {
        "appId": app_id,
        COL_TITLE: _display_text(details.get("title"), app_id),
        COL_INSTALLS: f"{installs_count:,}".replace(",", " "),
        COL_RATING: f"{score:.1f}",
        COL_GENRE: genre,
        COL_REVIEWS: ratings_count,
        COL_UPDATED: _display_text(details.get("lastUpdatedOn"), "—"),
        COL_ADS: "Да" if details.get("containsAds") is True else "Нет",
        COL_IAP: "Да" if details.get("offersIAP") is True else "Нет",
        COL_ICON: _safe_image_url(details.get("icon")),
        # The package id is untrusted input: quote it so it cannot smuggle
        # extra query parameters into the generated link.
        COL_LINK: _PLAY_STORE_URL.format(app_id=quote(app_id, safe="")),
        KEY_INSTALLS_INT: installs_count,
        KEY_SCORE: score,
        KEY_GENRE: genre,
    }


def _finite_float(value) -> float:
    """Return a finite, non-negative float for untrusted store metadata."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return number if math.isfinite(number) and number >= 0 else 0.0


def _non_negative_int(value) -> int:
    """Return a bounded integer representation of an optional numeric field."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _display_text(value, fallback: str) -> str:
    """Convert optional text to a trimmed value with a predictable fallback."""
    if not isinstance(value, str):
        return fallback
    return value.strip() or fallback


def _safe_image_url(value) -> str:
    """Allow only absolute HTTP(S) image URLs in the result grid."""
    if not isinstance(value, str):
        return ""
    url = value.strip()
    parsed = urlsplit(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _resolve_installs(details: dict) -> int:
    """Return the install count for an app, preferring the numeric field.

    Args:
        details (dict): Raw metadata returned by the scraper.

    Returns:
        int: The install count, or ``0`` when no usable value is present.

    Examples:
        >>> _resolve_installs({"minInstalls": 5000})
        5000
        >>> _resolve_installs({"installs": "10,000+"})
        10000
    """
    for key in ("minInstalls", "installs"):
        parsed = _parse_installs(details.get(key))
        if parsed:
            return parsed
    return 0


def _parse_installs(val) -> int:
    """Convert a Google Play installs value into an integer count.

    Args:
        val (Any): A raw installs value such as ``"100,000+"``, ``"10 000+"``
        or an integer field, possibly ``None``.

    Returns:
        int: The parsed install count, or ``0`` when the value is missing or
        cannot be interpreted as an integer.

    Examples:
        >>> _parse_installs("100,000+")
        100000
        >>> _parse_installs("1.5M")
        0
    """
    if val is None:
        return 0
    if isinstance(val, bool):
        return 0
    if isinstance(val, int):
        return max(0, val)

    cleaned = _INSTALLS_SEPARATORS.sub("", str(val))
    # Reject anything that is not plain digits rather than guessing: a wrong
    # number silently corrupts the install-range filter.
    return int(cleaned) if cleaned.isdigit() else 0
