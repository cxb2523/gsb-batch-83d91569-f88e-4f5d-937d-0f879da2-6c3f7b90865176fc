#!/usr/bin/env python3
"""
Auditable device collection for the GSMArena scraper.

Every device from a brand list ends up in exactly one of two places:

- ``CollectionSummary.devices``: successfully parsed ``DeviceInfo`` entries
- ``CollectionSummary.failures``: ``DeviceFailure`` entries carrying the name
  and URL from the list page plus a machine-readable ``reason``

Failure reasons:
- ``fetch_failed``: the page could not be retrieved (non-200 response other
  than 429, or HTTP 429 after all retries were exhausted, or a transport error)
- ``no_model``: the page was fetched but has no model name
  (``h1[data-spec=modelname]`` missing/empty)
- ``not_android``: the page is not an Android device or its OS version string
  could not be parsed into API levels

The network layer is injectable: ``collect_brand`` accepts any callable
``fetcher(url) -> FetchResponse`` (sync or async), so the whole pipeline can be
exercised offline with local HTML fixtures — no real HTTP required.

This module also hosts the shared parsing primitives (DeviceInfo, the Android
version table, the parse_* helpers) so that both the collection logic and the
aiohttp-based scraper (scrape_gsmarena.py) use one implementation.
"""

import asyncio
import inspect
import re
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

from bs4 import BeautifulSoup

# Android version to API level mapping
ANDROID_VERSION_TO_API = {
    "1.0": 1, "1.1": 2, "1.5": 3, "1.6": 4, "2.0": 5, "2.0.1": 6, "2.1": 7,
    "2.2": 8, "2.3": 9, "2.3.3": 10, "3.0": 11, "3.1": 12, "3.2": 13,
    "4.0": 14, "4.0.3": 15, "4.1": 16, "4.2": 17, "4.3": 18, "4.4": 19,
    "5.0": 21, "5.1": 22, "6.0": 23, "7.0": 24, "7.1": 25, "8.0": 26,
    "8.1": 27, "9": 28, "9.0": 28, "10": 29, "11": 30, "12": 31, "12L": 32,
    "13": 33, "14": 34, "15": 35, "16": 36
}

API_TO_ANDROID_VERSION = {v: k for k, v in ANDROID_VERSION_TO_API.items()}

# Failure reason constants (stable strings, safe to assert on / filter by)
REASON_FETCH_FAILED = "fetch_failed"
REASON_NO_MODEL = "no_model"
REASON_NOT_ANDROID = "not_android"

# Retry policy: HTTP 429 is retried with linear backoff (30s, 60s, 90s, ...),
# matching the backoff strategy the scraper has always used. Any other non-200
# response is recorded as a fetch failure immediately, without retrying.
DEFAULT_RETRIES = 3
DEFAULT_BACKOFF_BASE = 30.0


@dataclass
class DeviceInfo:
    model_code: str
    brand: str
    name: str
    min_android_api: int
    max_android_api: int
    popularity: float
    year: int
    ram_gb: List[int] = field(default_factory=list)
    cpu_cores: int = 0
    chipset: str = ""
    storage_gb: List[int] = field(default_factory=list)


@dataclass
class DeviceFailure:
    """A device from the brand list that could not be collected."""
    brand: str
    name: str          # name as shown on the list page
    url: str           # URL as shown on the list page
    reason: str        # one of the REASON_* constants
    detail: str = ""   # human-readable extra context (status codes, attempts)


@dataclass
class CollectionSummary:
    """Structured outcome of collecting one brand's device list."""
    brand: str
    devices: List[DeviceInfo] = field(default_factory=list)
    failures: List[DeviceFailure] = field(default_factory=list)

    @property
    def succeeded(self) -> int:
        return len(self.devices)

    @property
    def failed(self) -> int:
        return len(self.failures)

    @property
    def total(self) -> int:
        # Invariant: total == succeeded + failed
        return self.succeeded + self.failed

    def stats(self) -> Dict[str, int]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
        }


@dataclass
class FetchResponse:
    """One HTTP attempt's result, as returned by an injected fetcher."""
    status: int                 # HTTP status code; 0 means transport error
    body: str = ""
    error: str = ""             # transport-level error message, if any


@dataclass
class FetchOutcome:
    """Result of fetch_with_retries: either a body or an explained failure."""
    body: Optional[str]
    status: int                 # last status seen (0 for transport errors)
    attempts: int               # how many times the fetcher was called
    retries_429: int = 0        # how many 429 backoff waits happened
    error: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_android_version(os_string: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Parse Android version string to extract min and max API levels.

    Examples:
        "Android 9.0 (Pie), upgradable to Android 11" -> (28, 30)
        "Android 9.0, up to Android 10, MIUI 12" -> (28, 29)
        "Android 14, One UI 6" -> (34, 34)
    """
    if not os_string or "Android" not in os_string:
        return None, None

    os_string = os_string.replace('\n', ' ').replace('\r', ' ')

    # Find all Android version patterns
    versions = re.findall(r'Android (\d+(?:\.\d+)?)', os_string)

    if not versions:
        return None, None

    api_levels = []
    for v in versions:
        parts = v.split('.')
        # For old versions like 4.4, 5.1
        if len(parts) >= 2 and int(parts[0]) < 10:
            normalized = f"{parts[0]}.{parts[1]}"
        else:
            normalized = parts[0]

        api = ANDROID_VERSION_TO_API.get(normalized)
        if not api:
            api = ANDROID_VERSION_TO_API.get(parts[0])
        if api:
            api_levels.append(api)

    if not api_levels:
        return None, None

    return min(api_levels), max(api_levels)


def parse_ram(ram_string: str) -> List[int]:
    """Extract RAM sizes in GB from string like '6/8' or '6GB RAM'."""
    if not ram_string:
        return []

    # Match patterns like "6/8", "6GB", "6 GB"
    matches = re.findall(r'(\d+)\s*(?:GB)?', ram_string)
    return [int(m) for m in matches if 1 <= int(m) <= 24]


def parse_storage(storage_string: str) -> List[int]:
    """Extract storage sizes in GB from string."""
    if not storage_string:
        return []

    # Match patterns like "64GB", "128GB", "256GB"
    matches = re.findall(r'(\d+)\s*GB', storage_string, re.IGNORECASE)
    return [int(m) for m in matches if 16 <= int(m) <= 2048]


def parse_cpu_cores(cpu_string: str) -> int:
    """Extract CPU core count from string like 'Octa-core' or 'Quad-core'."""
    if not cpu_string:
        return 0

    cpu_lower = cpu_string.lower()
    if 'octa' in cpu_lower:
        return 8
    elif 'hexa' in cpu_lower:
        return 6
    elif 'quad' in cpu_lower:
        return 4
    elif 'dual' in cpu_lower:
        return 2
    elif 'single' in cpu_lower:
        return 1

    # Try to find pattern like "8x" or "4x"
    match = re.search(r'(\d+)x', cpu_string, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return 0


def parse_year(date_string: str) -> Optional[int]:
    """Extract year from date string."""
    if not date_string:
        return None

    match = re.search(r'20\d{2}', date_string)
    return int(match.group()) if match else None


def parse_hits(hits_string: str) -> int:
    """Parse hits count from string like '2,960,930 hits'."""
    if not hits_string:
        return 0

    match = re.search(r'([\d,]+)\s*hits', hits_string, re.IGNORECASE)
    if match:
        return int(match.group(1).replace(',', ''))
    return 0


def parse_device_page_detailed(html: str, brand: str) -> Tuple[Optional[DeviceInfo], Optional[str]]:
    """
    Parse a device page, distinguishing *why* parsing failed.

    Returns (DeviceInfo, None) on success, or (None, reason) where reason is
    REASON_NO_MODEL or REASON_NOT_ANDROID.
    """
    soup = BeautifulSoup(html, 'html.parser')

    # Get device name
    name_elem = soup.find('h1', {'data-spec': 'modelname'})
    name = name_elem.get_text(strip=True) if name_elem else ""
    if not name:
        return None, REASON_NO_MODEL

    # Get OS info
    os_elem = soup.find('td', {'data-spec': 'os'})
    os_string = os_elem.get_text(strip=True) if os_elem else ""

    min_api, max_api = parse_android_version(os_string)
    if min_api is None:
        return None, REASON_NOT_ANDROID  # Not an Android device / unparseable OS

    # Get model codes
    models_elem = soup.find('td', {'data-spec': 'models'})
    models_string = models_elem.get_text(strip=True) if models_elem else ""

    # Extract model codes based on brand patterns
    model_codes = []
    if brand == "samsung":
        model_codes = re.findall(r'SM-[A-Z]\d{3,4}[A-Z0-9]*', models_string)
    elif brand == "xiaomi_ecosystem":
        # Xiaomi uses various patterns
        model_codes = re.findall(r'[A-Z0-9]{6,12}(?:[A-Z]{2})?', models_string)
        if not model_codes:
            model_codes = re.findall(r'M\d{4}[A-Z0-9]+', models_string)
    elif brand == "google_pixel":
        model_codes = re.findall(r'G[A-Z0-9]{3,6}', models_string)
    elif brand == "oppo_realme_generic":
        model_codes = re.findall(r'CPH\d{4}|RMX\d{4}|PEEM\d{2}|PEGM\d{2}', models_string)

    # Use device name as fallback model code
    model_code = model_codes[0] if model_codes else name

    # Get release year
    year_elem = soup.find('td', {'data-spec': 'year'})
    year_string = year_elem.get_text(strip=True) if year_elem else ""
    year = parse_year(year_string) or 2020

    # Get RAM
    ram_elem = soup.find('span', {'data-spec': 'ramsize-hl'})
    ram_string = ram_elem.get_text(strip=True) if ram_elem else ""
    ram_sizes = parse_ram(ram_string)

    # Also check internal memory for RAM info
    internal_elem = soup.find('td', {'data-spec': 'internalmemory'})
    internal_string = internal_elem.get_text(strip=True) if internal_elem else ""
    if not ram_sizes:
        # Parse from internal memory like "64GB 6GB RAM"
        ram_matches = re.findall(r'(\d+)\s*GB\s*RAM', internal_string, re.IGNORECASE)
        ram_sizes = list(set([int(m) for m in ram_matches]))

    # Get storage
    storage_sizes = parse_storage(internal_string)

    # Get CPU
    cpu_elem = soup.find('td', {'data-spec': 'cpu'})
    cpu_string = cpu_elem.get_text(strip=True) if cpu_elem else ""
    cpu_cores = parse_cpu_cores(cpu_string)

    # Get chipset
    chipset_elem = soup.find('td', {'data-spec': 'chipset'})
    chipset = chipset_elem.get_text(strip=True) if chipset_elem else ""

    # Get popularity (hits)
    hits_elem = soup.find('li', class_='help-popularity')
    hits_string = hits_elem.get_text(strip=True) if hits_elem else ""
    hits = parse_hits(hits_string)

    popularity = hits / 10_000_000 if hits else 0.01

    return DeviceInfo(
        model_code=model_code,
        brand=brand,
        name=name,
        min_android_api=min_api,
        max_android_api=max_api,
        popularity=popularity,
        year=year,
        ram_gb=ram_sizes,
        cpu_cores=cpu_cores,
        chipset=chipset,
        storage_gb=storage_sizes
    ), None


def parse_device_page(html: str, brand: str) -> Optional[DeviceInfo]:
    """Backwards-compatible wrapper: DeviceInfo or None, without the reason."""
    device, _reason = parse_device_page_detailed(html, brand)
    return device


def parse_device_list(html: str) -> List[Tuple[str, str]]:
    """Parse brand device list page to get device URLs and names."""
    soup = BeautifulSoup(html, 'html.parser')
    devices = []

    # Find all device links in the makers container
    makers_div = soup.find('div', class_='makers')
    if not makers_div:
        return devices

    for link in makers_div.find_all('a'):
        href = link.get('href', '')
        if href and href.endswith('.php') and 'compare' not in href:
            name_span = link.find('span')
            name = name_span.get_text(strip=True) if name_span else ""
            if name:
                devices.append((href, name))

    return devices


# ---------------------------------------------------------------------------
# Fetch with observable 429 retry
# ---------------------------------------------------------------------------

Fetcher = Callable[[str], Union[FetchResponse, "asyncio.Future[Any]"]]


async def fetch_with_retries(
    fetcher: Fetcher,
    url: str,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    sleep: Optional[Callable[[float], Any]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> FetchOutcome:
    """
    Fetch ``url`` through ``fetcher`` with the standard retry policy:

    - 200            -> return the body
    - 429            -> wait backoff_base * (attempt + 1) seconds and retry;
                        only exhausting all retries counts as failure
    - any other != 200 (including transport errors) -> fail immediately, no retry

    ``fetcher`` may be a plain or async callable returning FetchResponse.
    ``sleep`` defaults to asyncio.sleep; tests can pass a no-op.
    ``log`` receives one human-readable line per retry/give-up event.
    """
    if sleep is None:
        sleep = asyncio.sleep

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    retries_429 = 0
    last_status = 0
    last_error = ""

    for attempt in range(retries):
        resp = fetcher(url)
        if inspect.isawaitable(resp):
            resp = await resp

        last_status = resp.status
        last_error = resp.error

        if resp.status == 200:
            return FetchOutcome(body=resp.body, status=200, attempts=attempt + 1,
                                retries_429=retries_429)

        if resp.status == 429:
            retries_429 += 1
            wait_time = backoff_base * (attempt + 1)
            _log(f"  Rate limited (429) on {url} "
                 f"(attempt {attempt + 1}/{retries}), waiting {wait_time:.0f}s...")
            maybe_sleep = sleep(wait_time)
            if inspect.isawaitable(maybe_sleep):
                await maybe_sleep
            continue

        # Any other non-200: no retry, immediate fetch failure.
        _log(f"  HTTP {resp.status} for {url} - not retrying")
        return FetchOutcome(body=None, status=resp.status, attempts=attempt + 1,
                            retries_429=retries_429, error=resp.error)

    _log(f"  Retries exhausted for {url} (last status {last_status})")
    return FetchOutcome(body=None, status=last_status, attempts=retries,
                        retries_429=retries_429, error=last_error)


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------

async def collect_brand(
    brand: str,
    device_entries: Sequence[Tuple[str, str]],
    fetcher: Fetcher,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff_base: float = DEFAULT_BACKOFF_BASE,
    sleep: Optional[Callable[[float], Any]] = None,
    log: Optional[Callable[[str], None]] = None,
) -> CollectionSummary:
    """
    Collect every (url, name) entry of one brand into a CollectionSummary.

    A failure or exception on one device never aborts the batch: it is recorded
    as a DeviceFailure and the remaining devices continue. Results preserve the
    input list order regardless of completion order.
    """
    async def _one(entry: Tuple[str, str]) -> Tuple[Optional[DeviceInfo], Optional[DeviceFailure]]:
        url, name = entry[0], entry[1]
        try:
            outcome = await fetch_with_retries(
                fetcher, url, retries=retries, backoff_base=backoff_base,
                sleep=sleep, log=log,
            )

            if outcome.body is None:
                if outcome.status == 429:
                    detail = f"HTTP 429 after {outcome.attempts} attempts (retries exhausted)"
                elif outcome.status:
                    detail = f"HTTP {outcome.status}"
                else:
                    detail = outcome.error or "transport error"
                return None, DeviceFailure(brand=brand, name=name, url=url,
                                           reason=REASON_FETCH_FAILED, detail=detail)

            device, reason = parse_device_page_detailed(outcome.body, brand)
            if device is None:
                return None, DeviceFailure(brand=brand, name=name, url=url, reason=reason)
            return device, None

        except Exception as exc:  # one bad device must not kill the batch
            return None, DeviceFailure(brand=brand, name=name, url=url,
                                       reason=REASON_FETCH_FAILED,
                                       detail=f"unexpected error: {exc}")

    results = await asyncio.gather(*[_one(entry) for entry in device_entries])

    summary = CollectionSummary(brand=brand)
    for device, failure in results:
        if device is not None:
            summary.devices.append(device)
        if failure is not None:
            summary.failures.append(failure)
    return summary


def collect_brand_sync(
    brand: str,
    device_entries: Sequence[Tuple[str, str]],
    fetcher: Fetcher,
    **kwargs: Any,
) -> CollectionSummary:
    """Synchronous wrapper around collect_brand (for tests and offline use)."""
    return asyncio.run(collect_brand(brand, device_entries, fetcher, **kwargs))


def merge_summaries(
    summaries: Sequence[CollectionSummary],
) -> Tuple[Dict[str, List[Dict[str, Any]]], List[Dict[str, Any]], Dict[str, int]]:
    """
    Merge per-brand summaries into the JSON-ready pieces:

    - devices_by_brand: brand -> [device dicts]; brands with zero successes
      are omitted entirely (no empty "devices" groups)
    - failures: flat list of failure dicts, kept even for fully-failed brands
    - stats: {"total", "succeeded", "failed"} with total == succeeded + failed
    """
    devices_by_brand: Dict[str, List[Dict[str, Any]]] = {}
    failures: List[Dict[str, Any]] = []

    for summary in summaries:
        if summary.devices:
            devices_by_brand.setdefault(summary.brand, []).extend(
                asdict(d) for d in summary.devices
            )
        failures.extend(asdict(f) for f in summary.failures)

    stats = {
        "total": sum(s.total for s in summaries),
        "succeeded": sum(s.succeeded for s in summaries),
        "failed": sum(s.failed for s in summaries),
    }
    return devices_by_brand, failures, stats
