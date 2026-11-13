#!/usr/bin/env python3

import argparse
import csv
import sys
import time

from .sitemap_harvester import SitemapCrawler


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

    if not results:
        print("No results to write", file=sys.stderr)
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


if __name__ == "__main__":
    main()
