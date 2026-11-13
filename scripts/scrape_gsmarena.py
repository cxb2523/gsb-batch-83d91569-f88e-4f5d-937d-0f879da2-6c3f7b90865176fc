#!/usr/bin/env python3
"""
GSMArena Async Scraper - Fast concurrent scraping of device specifications.

Features:
- Async/concurrent scraping with aiohttp
- Realistic Windows Chrome headers
- Extracts: model codes, Android versions, RAM, CPU, chipset
- Rate limiting with semaphore
- Progress tracking
- Auditable collection: every device from the brand lists ends up either in
  "devices" (full specs) or in "collection.failures" (name, URL, reason),
  with totals reported under "collection".

The collection/parsing/retry logic lives in collect_devices.py; this module
provides the aiohttp-based transport and the main() entry point.
"""

import asyncio
import aiohttp
import json
import random
import ssl
import time
from pathlib import Path
from typing import List, Optional, Tuple

# Shared parsing + collection primitives (re-exported for backwards
# compatibility with any code importing them from scrape_gsmarena).
from collect_devices import (
    ANDROID_VERSION_TO_API,
    API_TO_ANDROID_VERSION,
    DEFAULT_BACKOFF_BASE,
    DEFAULT_RETRIES,
    CollectionSummary,
    DeviceFailure,
    DeviceInfo,
    FetchResponse,
    collect_brand,
    fetch_with_retries,
    merge_summaries,
    parse_android_version,
    parse_cpu_cores,
    parse_device_list,
    parse_device_page,
    parse_device_page_detailed,
    parse_hits,
    parse_ram,
    parse_storage,
    parse_year,
)

# Realistic Windows Chrome headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Connection": "keep-alive",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

# Concurrency settings - be gentle to avoid rate limiting
MAX_CONCURRENT_REQUESTS = 3
REQUEST_DELAY = 2.0  # seconds between requests


async def fetch_once(session: aiohttp.ClientSession, url: str,
                     semaphore: asyncio.Semaphore) -> FetchResponse:
    """
    Single HTTP attempt through aiohttp, adapted to the FetchResponse
    interface so collect_devices.fetch_with_retries can drive retries.
    """
    async with semaphore:
        await asyncio.sleep(REQUEST_DELAY + random.uniform(0.5, 1.5))
        try:
            async with session.get(url, headers=HEADERS,
                                   timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status == 200:
                    return FetchResponse(status=200, body=await response.text())
                return FetchResponse(status=response.status)
        except asyncio.TimeoutError:
            return FetchResponse(status=0, error="timeout")
        except Exception as e:
            return FetchResponse(status=0, error=str(e))


async def fetch_page(session: aiohttp.ClientSession, url: str,
                     semaphore: asyncio.Semaphore,
                     retries: int = DEFAULT_RETRIES) -> Optional[str]:
    """Fetch a page with rate limiting and retries (used for list pages)."""
    async def _fetcher(u: str) -> FetchResponse:
        return await fetch_once(session, u, semaphore)

    outcome = await fetch_with_retries(_fetcher, url, retries=retries, log=print)
    return outcome.body


async def get_all_device_urls(session: aiohttp.ClientSession, semaphore: asyncio.Semaphore,
                               brand: str, base_url: str, max_pages: int = 10) -> List[Tuple[str, str]]:
    """Get all device URLs from paginated brand listings."""
    import re

    all_devices = []

    # Parse brand ID from URL (e.g., "samsung-phones-9.php" -> "9")
    brand_match = re.search(r'-(\d+)\.php', base_url)
    brand_id = brand_match.group(1) if brand_match else ""

    for page in range(1, max_pages + 1):
        if page == 1:
            url = f"https://www.gsmarena.com/{base_url}"
        else:
            # Pattern: samsung-phones-f-9-0-p2.php
            base_name = base_url.replace('.php', '').replace(f'-{brand_id}', '')
            url = f"https://www.gsmarena.com/{base_name}-f-{brand_id}-0-p{page}.php"

        print(f"  Fetching page {page}...", end=" ", flush=True)
        html = await fetch_page(session, url, semaphore)

        if not html:
            print("failed")
            break

        devices = parse_device_list(html)
        print(f"found {len(devices)} devices")

        if not devices:
            break

        all_devices.extend(devices)

        # Check if there's a next page
        if 'class="pages-next"' not in html and f'p{page + 1}' not in html:
            break

    return all_devices


async def scrape_brand(brand: str, base_url: str, max_devices: int = 200,
                       max_pages: int = 15) -> CollectionSummary:
    """
    Scrape all devices for a brand.

    Returns a CollectionSummary: every device from the list pages is either a
    parsed DeviceInfo or a DeviceFailure with a reason.
    """
    print(f"\n{'='*60}")
    print(f"Scraping {brand}")
    print(f"{'='*60}")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    # Create SSL context that doesn't verify certificates
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    connector = aiohttp.TCPConnector(ssl=ssl_context, limit=MAX_CONCURRENT_REQUESTS)

    async with aiohttp.ClientSession(connector=connector) as session:
        # Get all device URLs
        device_urls = await get_all_device_urls(session, semaphore, brand, base_url, max_pages)
        print(f"Total devices found: {len(device_urls)}")

        if not device_urls:
            return CollectionSummary(brand=brand)

        # Limit devices
        device_urls = device_urls[:max_devices]

        # Collect devices concurrently; one failure never aborts the batch
        print(f"Scraping {len(device_urls)} devices concurrently...")

        async def fetcher(url: str) -> FetchResponse:
            full_url = url if url.startswith("http") else f"https://www.gsmarena.com/{url}"
            return await fetch_once(session, full_url, semaphore)

        summary = await collect_brand(
            brand, device_urls, fetcher,
            retries=DEFAULT_RETRIES, backoff_base=DEFAULT_BACKOFF_BASE,
            log=print,
        )

        print(f"Successfully scraped: {summary.succeeded} devices, "
              f"failed: {summary.failed}")
        return summary


async def main():
    print("=" * 70)
    print("GSMArena Async Device Scraper")
    print("=" * 70)

    start_time = time.time()
    summaries: List[CollectionSummary] = []

    # Brand configurations (reduced for faster scraping)
    brands = [
        ("samsung", "samsung-phones-9.php", 100, 8),
        ("google_pixel", "google-phones-107.php", 30, 3),
        ("xiaomi_ecosystem", "xiaomi-phones-80.php", 100, 8),
        ("oppo_realme_generic", "oppo-phones-82.php", 50, 5),
    ]

    for brand_key, base_url, max_devices, max_pages in brands:
        try:
            summaries.append(await scrape_brand(brand_key, base_url, max_devices, max_pages))
        except Exception as e:
            print(f"Error scraping {brand_key}: {e}")

    # Also scrape Realme (merged into the oppo_realme_generic group)
    try:
        realme_summary = await scrape_brand("realme", "realme-phones-118.php", 50, 5)
        # Change brand to oppo for consistency
        for d in realme_summary.devices:
            d.brand = "oppo"
        realme_summary.brand = "oppo_realme_generic"
        for f in realme_summary.failures:
            f.brand = "oppo_realme_generic"
        summaries.append(realme_summary)
    except Exception as e:
        print(f"Error scraping Realme: {e}")

    # Merge: brands with zero successes get no (empty) devices group, but
    # their failures are always kept in the failure list.
    all_devices, failures, stats = merge_summaries(summaries)

    # Normalize popularity within each brand
    for brand, device_list in all_devices.items():
        total = sum(d['popularity'] for d in device_list)
        if total > 0:
            for d in device_list:
                d['popularity'] = d['popularity'] / total

    # Build output
    output = {
        "meta": {
            "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "source": "GSMArena async scrape",
            "total_devices": stats["succeeded"],
            "scrape_time_seconds": round(time.time() - start_time, 1)
        },
        "api_to_version": API_TO_ANDROID_VERSION,
        "devices": all_devices,
        "collection": {
            "total": stats["total"],
            "succeeded": stats["succeeded"],
            "failed": stats["failed"],
            "failures": failures,
        },
    }

    # Save
    output_path = Path(__file__).parent.parent / "uaforge" / "data" / "android_device_specs.json"
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - start_time
    print(f"\n{'='*70}")
    print(f"Completed in {elapsed:.1f} seconds")
    print(f"Saved {stats['succeeded']} devices to {output_path}")
    print(f"Collection: {stats['total']} listed, {stats['succeeded']} ok, "
          f"{stats['failed']} failed")
    print(f"{'='*70}")

    # Print summary
    for brand, devices in all_devices.items():
        if devices:
            min_api = min(d['min_android_api'] for d in devices)
            max_api = max(d['max_android_api'] for d in devices)
            print(f"  {brand}: {len(devices)} devices, API {min_api}-{max_api}")

    # Print failures so a skipped device is never invisible
    if failures:
        print(f"\nFailed devices ({len(failures)}):")
        for f in failures:
            print(f"  [{f['reason']}] {f['brand']}: {f['name']} ({f['url']})"
                  + (f" - {f['detail']}" if f.get('detail') else ""))

    # Show some sample devices
    print(f"\nSample devices:")
    for brand in ["xiaomi_ecosystem", "samsung"]:
        devices = all_devices.get(brand, [])
        for d in devices[:2]:
            print(f"  {d['name']}: API {d['min_android_api']}-{d['max_android_api']}, "
                  f"RAM: {d.get('ram_gb', [])}, CPU: {d.get('cpu_cores', 0)} cores")


if __name__ == "__main__":
    asyncio.run(main())
