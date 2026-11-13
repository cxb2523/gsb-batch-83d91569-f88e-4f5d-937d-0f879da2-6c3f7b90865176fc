#!/usr/bin/env python3

import argparse
import csv
import sys
import time

from .sitemap_harvester import (
    SITEMAP_STATUS_PARSE_FAILED,
    SITEMAP_STATUS_REQUEST_FAILED,
    SITEMAP_STATUS_SKIPPED,
    SITEMAP_STATUS_SUCCESS,
    SitemapCrawler,
)


def format_summary(crawler: SitemapCrawler) -> str:
    """Build the short stderr summary that matches the crawler's summary."""
    summary = crawler.get_summary()
    lines = ["Crawl summary:"]

    if summary.no_sitemaps_found:
        lines.append("  Sitemaps: none found (no sitemap.xml or robots.txt Sitemap entries)")
        lines.append("  Pages fetched: 0 (succeeded: 0, failed: 0)")
        return "\n".join(lines)

    lines.append(
        "  Sitemaps: {attempted} attempted ({success} succeeded, "
        "{parse_failed} parse failed, {request_failed} request failed, "
        "{skipped} duplicate skipped); {found} discovered".format(
            attempted=summary.sitemaps_attempted,
            success=summary.sitemaps_succeeded,
            parse_failed=summary.sitemaps_parse_failed,
            request_failed=summary.sitemaps_request_failed,
            skipped=summary.sitemaps_skipped,
            found=summary.sitemaps_found,
        )
    )
    for attempt in summary.sitemap_attempts:
        detail = attempt.url
        if attempt.status == SITEMAP_STATUS_SUCCESS:
            label = "success"
            detail = f"{attempt.url} ({attempt.url_count} URLs)"
        elif attempt.status == SITEMAP_STATUS_PARSE_FAILED:
            label = "parse failed"
            detail = f"{attempt.url} ({attempt.error})"
        elif attempt.status == SITEMAP_STATUS_REQUEST_FAILED:
            label = "request failed"
            detail = f"{attempt.url} ({attempt.error})"
        elif attempt.status == SITEMAP_STATUS_SKIPPED:
            label = "skipped (already visited)"
        else:
            label = attempt.status
        lines.append(f"    - {label}: {detail}")

    lines.append(
        "  URLs: {after} unique ({before} before dedup, {duplicates} duplicate removed)".format(
            before=summary.total_urls_before_dedup,
            after=summary.total_urls_after_dedup,
            duplicates=summary.duplicates_removed,
        )
    )
    lines.append(
        "  Pages fetched: {total} (succeeded: {ok}, failed: {failed})".format(
            total=summary.pages_fetched,
            ok=summary.pages_succeeded,
            failed=summary.pages_failed,
        )
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Crawl website sitemaps and extract metadata"
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Base URL of the website (e.g., https://example.com)",
    )
    parser.add_argument(
        "--output",
        default=f"sitemap_links-{int(time.time())}.csv",
        help="Output CSV file (default: sitemap_links-{timestamp}.csv)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=10,
        help="Request timeout in seconds (default: 10)",
    )

    args = parser.parse_args()

    crawler = SitemapCrawler(args.url, timeout=args.timeout)
    results = crawler.crawl()
    summary = crawler.get_summary()

    if not results:
        if summary.no_sitemaps_found:
            print("No results to write: no sitemaps found", file=sys.stderr)
        elif summary.all_sitemaps_failed:
            print(
                "No results to write: all {failed} sitemap(s) failed "
                "(parse or request errors)".format(failed=summary.sitemaps_failed),
                file=sys.stderr,
            )
        else:
            print("No results to write", file=sys.stderr)
        print(format_summary(crawler), file=sys.stderr)
        sys.exit(1)

    all_keys = set()
    for result in results:
        all_keys.update(result.keys())

    priority_fields = [
        "url",
        "title",
        "description",
        "keywords",
        "author",
        "canonical",
        "og_title",
        "image",
    ]
    fieldnames = [f for f in priority_fields if f in all_keys]
    fieldnames.extend(sorted(all_keys - set(fieldnames)))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"\nResults written to {args.output}", file=sys.stderr)
    print(format_summary(crawler), file=sys.stderr)


if __name__ == "__main__":
    main()
