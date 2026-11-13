"""Core orchestration pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from tqdm import tqdm

from .config import HarvestConfig
from .extraction import domain_from_url, extract_emails, find_contact_links
from .fetchers import RequestsFetcher, RobotsPolicy, SeleniumFetcher, make_retry_session
from .hunter import HunterClient
from .io_csv import write_fetch_report, write_rows
from .models import (
    EmailObservation,
    Fetcher,
    FetchOutcome,
    FetchStatus,
    HunterClientProtocol,
    SearchBackend,
)
from .scoring import compute_quality
from .search_backends import FallbackSearchBackend, build_queries
from .validation import (
    is_supported_url,
    mx_check,
    normalize_candidate_urls,
    polite_sleep,
)

SleepFn = Callable[[float, float], None]
MxCheckFn = Callable[[str], bool]


def _fetch_detailed(fetcher: Fetcher, url: str) -> FetchOutcome:
    """Return a structured fetch outcome, falling back for plain string fetchers."""
    if not is_supported_url(url):
        return FetchOutcome(
            url=url,
            status=FetchStatus.UNSUPPORTED_URL,
            detail=f"Unsupported URL scheme (only http/https are supported): {url}",
        )
    detailed = getattr(fetcher, "fetch_detailed", None)
    if callable(detailed):
        outcome = detailed(url)
        if isinstance(outcome, FetchOutcome):
            return outcome
    # Compatibility path for fetchers implementing only the string contract.
    content = fetcher.fetch(url)
    if content:
        return FetchOutcome(url=url, status=FetchStatus.SUCCESS, content=content)
    return FetchOutcome(
        url=url,
        status=FetchStatus.FETCH_FAILED,
        detail="Fetch returned no content (reason not reported by this fetcher).",
    )


def collect_candidate_urls(
    config: HarvestConfig,
    *,
    search_backend: SearchBackend,
    sleep_fn: SleepFn,
    logger: logging.Logger,
) -> list[str]:
    """Collect and dedupe candidate URLs from seeds or search."""
    if config.seeds:
        return normalize_candidate_urls(list(config.seeds))

    candidate_urls: list[str] = []
    for query in build_queries(config.categories):
        logger.info("Searching: %s", query)
        urls = search_backend.search(
            query=query,
            num=config.max_results_per_query,
            min_delay=config.min_delay,
            max_delay=config.max_delay,
        )
        logger.info(" --> found %d candidate URLs", len(urls))
        candidate_urls.extend(urls)
        sleep_fn(config.min_delay, config.max_delay)
    return normalize_candidate_urls(candidate_urls)


def process_page(
    url: str,
    *,
    fetcher: Fetcher,
    config: HarvestConfig,
    hunter_client: HunterClientProtocol | None,
    sleep_fn: SleepFn,
) -> tuple[list[EmailObservation], FetchOutcome]:
    """Extract emails from a page, discovered contact pages, and Hunter domain search."""
    observations: list[EmailObservation] = []
    outcome = _fetch_detailed(fetcher, url)
    html = outcome.content
    if not html:
        return observations, outcome

    for email in extract_emails(html):
        observations.append(EmailObservation(email=email, source=url, note="page"))

    for contact_link in find_contact_links(html, url):
        if contact_link.startswith("mailto:"):
            address = contact_link.split(":", maxsplit=1)[1].split("?", maxsplit=1)[0].lower()
            if address:
                observations.append(EmailObservation(email=address, source=url, note="mailto"))
            continue
        sleep_fn(config.min_delay, config.max_delay)
        child_html = fetcher.fetch(contact_link)
        if not child_html:
            continue
        for email in extract_emails(child_html):
            observations.append(
                EmailObservation(email=email, source=contact_link, note="contact_page")
            )

    if config.use_hunter_domain_search and hunter_client:
        domain = domain_from_url(url)
        if domain:
            sleep_fn(config.min_delay, config.max_delay)
            for item in hunter_client.domain_search(domain, limit=10):
                value = item.get("value")
                if not isinstance(value, str) or not value:
                    continue
                confidence = str(item.get("confidence", ""))
                observations.append(
                    EmailObservation(
                        email=value.lower(), source=url, note=f"hunter_domain:{confidence}"
                    )
                )
    return observations, outcome


def _aggregate_observations(observations: list[EmailObservation]) -> dict[str, dict[str, object]]:
    results: dict[str, dict[str, object]] = {}
    for item in observations:
        email = item.email.lower()
        if email not in results:
            results[email] = {
                "first_source": item.source,
                "sources": {item.source},
                "notes": item.note,
            }
            continue
        sources = results[email]["sources"]
        if isinstance(sources, set):
            sources.add(item.source)
    return results


def _verify_hunter_emails(
    *,
    config: HarvestConfig,
    email_map: dict[str, dict[str, object]],
    hunter_client: HunterClientProtocol | None,
    sleep_fn: SleepFn,
    logger: logging.Logger,
) -> dict[str, dict[str, object]]:
    summary: dict[str, dict[str, object]] = {}
    if not (config.use_hunter and config.hunter_key and hunter_client):
        return summary

    candidates = sorted(email_map.keys())
    logger.info("Emails that could be verified by Hunter: %d", len(candidates))

    if config.preview_hunter_costs or not config.yes_run_hunter:
        logger.info("Preview mode enabled: no Hunter verification calls were executed.")
        return summary

    to_verify = candidates[: config.max_hunter_verifications]
    logger.info("Performing up to %d Hunter verifications.", len(to_verify))
    for email in to_verify:
        sleep_fn(config.min_delay, config.max_delay + 0.5)
        summary[email] = hunter_client.verify_email(email, poll=True, timeout=20)
    logger.info("Completed Hunter verification calls: %d", len(summary))
    return summary


def _to_csv_rows(
    email_map: dict[str, dict[str, object]],
    hunter_summary: dict[str, dict[str, object]],
    *,
    sleep_fn: SleepFn,
    min_delay: float,
    max_delay: float,
    mx_checker: MxCheckFn,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for email in sorted(email_map.keys()):
        info = email_map[email]
        sources_obj = info.get("sources", set())
        sources = sorted(sources_obj) if isinstance(sources_obj, set) else []
        first_source = str(info.get("first_source", ""))
        hunter_result = hunter_summary.get(email, {})
        mx_ok = mx_checker(email)
        quality = compute_quality(mx_ok, hunter_result, source_count=len(sources))
        rows.append(
            {
                "email": email,
                "first_seen_source": first_source,
                "all_sources": ";".join(sources),
                "domain": domain_from_url(first_source),
                "mx_ok": "yes" if mx_ok else "no",
                "hunter_result": str(
                    hunter_result.get("result") or hunter_result.get("status") or ""
                ),
                "hunter_confidence": str(
                    hunter_result.get("confidence") or hunter_result.get("score") or ""
                ),
                "quality": quality,
                "date_scraped_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "notes": str(info.get("notes", "")),
            }
        )
        sleep_fn(min_delay * 0.08, max_delay * 0.08)
    return rows


def harvest_records(
    config: HarvestConfig,
    *,
    search_backend: SearchBackend,
    requests_fetcher: Fetcher,
    selenium_fetcher_factory: Callable[[], Fetcher] | None = None,
    hunter_client: HunterClientProtocol | None = None,
    mx_checker: MxCheckFn = mx_check,
    sleep_fn: SleepFn = polite_sleep,
    fetch_outcomes: list[FetchOutcome] | None = None,
    logger: logging.Logger,
) -> list[dict[str, str]]:
    """Run harvesting and return CSV rows.

    When ``fetch_outcomes`` is provided, one :class:`FetchOutcome` per candidate URL is
    appended to it in candidate order. A failure for a single URL never prevents the
    remaining candidate URLs from being processed.
    """
    candidate_urls = collect_candidate_urls(
        config,
        search_backend=search_backend,
        sleep_fn=sleep_fn,
        logger=logger,
    )
    logger.info("Total candidate URLs to scan: %d", len(candidate_urls))

    observations: list[EmailObservation] = []
    # Indexed by candidate URL so the report keeps the deduped candidate order even
    # though worker threads finish in arbitrary order.
    outcomes_by_url: dict[str, FetchOutcome] = {}

    def _record(url: str, page_observations: list[EmailObservation], outcome: FetchOutcome) -> None:
        observations.extend(page_observations)
        outcomes_by_url[url] = outcome

    if config.use_selenium:
        if selenium_fetcher_factory is None:
            raise ValueError("selenium_fetcher_factory is required when use_selenium is enabled.")
        logger.warning("Selenium mode is running in single-thread mode for driver safety.")
        selenium_fetcher = selenium_fetcher_factory()
        try:
            for url in candidate_urls:
                try:
                    page_observations, outcome = process_page(
                        url,
                        fetcher=selenium_fetcher,
                        config=config,
                        hunter_client=hunter_client,
                        sleep_fn=sleep_fn,
                    )
                except Exception as exc:
                    logger.debug("Selenium worker failed for %s: %s", url, exc)
                    page_observations = []
                    outcome = FetchOutcome(
                        url=url,
                        status=FetchStatus.FETCH_FAILED,
                        detail=f"Unexpected worker failure: {exc}",
                    )
                _record(url, page_observations, outcome)
        finally:
            close_fn = getattr(selenium_fetcher, "close", None)
            if callable(close_fn):
                close_fn()
    else:
        with ThreadPoolExecutor(max_workers=config.workers) as executor:
            futures = {
                executor.submit(
                    process_page,
                    url,
                    fetcher=requests_fetcher,
                    config=config,
                    hunter_client=hunter_client,
                    sleep_fn=sleep_fn,
                ): url
                for url in candidate_urls
            }
            iterator = as_completed(futures)
            if config.show_progress:
                iterator = tqdm(iterator, total=len(futures), desc="scanning pages")
            for future in iterator:
                url = futures[future]
                try:
                    page_observations, outcome = future.result()
                except Exception as exc:
                    logger.debug("Worker failed for %s: %s", url, exc)
                    page_observations = []
                    outcome = FetchOutcome(
                        url=url,
                        status=FetchStatus.FETCH_FAILED,
                        detail=f"Unexpected worker failure: {exc}",
                    )
                _record(url, page_observations, outcome)

    ordered_outcomes = [outcomes_by_url[url] for url in candidate_urls]
    if fetch_outcomes is not None:
        fetch_outcomes.extend(ordered_outcomes)

    email_map = _aggregate_observations(observations)
    logger.info("Unique emails found on pages: %d", len(email_map))

    hunter_summary = _verify_hunter_emails(
        config=config,
        email_map=email_map,
        hunter_client=hunter_client,
        sleep_fn=sleep_fn,
        logger=logger,
    )

    return _to_csv_rows(
        email_map,
        hunter_summary,
        sleep_fn=sleep_fn,
        min_delay=config.min_delay,
        max_delay=config.max_delay,
        mx_checker=mx_checker,
    )


def run_pipeline(config: HarvestConfig, *, logger: logging.Logger) -> str:
    """Build concrete dependencies, execute pipeline, and write CSV output."""
    session = make_retry_session(config.user_agent)
    search_backend = FallbackSearchBackend(
        session=session,
        user_agent=config.user_agent,
        timeout=config.request_timeout,
        serpapi_key=config.serpapi_key,
        bing_key=config.bing_key,
        logger=logger,
    )
    requests_fetcher = RequestsFetcher(
        session=session,
        robots_policy=RobotsPolicy(config.user_agent),
        timeout=config.request_timeout,
        logger=logger,
    )
    hunter_client = (
        HunterClient(
            session=session,
            api_key=config.hunter_key,
            timeout=config.request_timeout,
            logger=logger,
        )
        if config.hunter_key
        else None
    )
    selenium_factory = (
        (lambda: SeleniumFetcher(user_agent=config.user_agent, logger=logger))
        if config.use_selenium
        else None
    )
    fetch_outcomes: list[FetchOutcome] = []
    rows = harvest_records(
        config=config,
        search_backend=search_backend,
        requests_fetcher=requests_fetcher,
        selenium_fetcher_factory=selenium_factory,
        hunter_client=hunter_client,
        fetch_outcomes=fetch_outcomes,
        logger=logger,
    )
    write_rows(config.output, rows)
    if config.fetch_report:
        write_fetch_report(config.fetch_report, fetch_outcomes)
        logger.info(
            "Wrote fetch report for %d candidate URLs to %s",
            len(fetch_outcomes),
            config.fetch_report,
        )
    return config.output
