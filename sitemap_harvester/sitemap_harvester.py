#!/usr/bin/env python3

import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# Sitemap attempt statuses used in :class:`CrawlSummary`.
SITEMAP_STATUS_SUCCESS = "success"
SITEMAP_STATUS_PARSE_FAILED = "parse_failed"
SITEMAP_STATUS_REQUEST_FAILED = "request_failed"
SITEMAP_STATUS_SKIPPED = "skipped"

_FAILURE_STATUSES = (
    SITEMAP_STATUS_PARSE_FAILED,
    SITEMAP_STATUS_REQUEST_FAILED,
)


@dataclass
class SitemapAttempt:
    """Record describing what happened to a single sitemap URL."""

    url: str
    status: str
    #: Number of page URLs extracted directly from this sitemap document.
    url_count: int = 0
    #: Error message when ``status`` is a failure, otherwise ``None``.
    error: Optional[str] = None


@dataclass
class CrawlSummary:
    """Auditable summary of a :meth:`SitemapCrawler.crawl` run.

    The three ambiguous outcomes are distinguishable via:

    * :attr:`no_sitemaps_found` -- no sitemap could be discovered at all;
    * :attr:`all_sitemaps_failed` -- sitemaps were found but every one of
      them failed (parse error or request error);
    * a mix of statuses in :attr:`sitemap_attempts` with
    :attr:`total_urls_after_dedup` greater than zero -- partial failure with
    usable results.
    """

    #: Number of candidate sitemap URLs discovered (common paths + robots.txt).
    sitemaps_found: int = 0
    #: True when discovery did not find any sitemap candidate.
    no_sitemaps_found: bool = False
    #: Every sitemap passed to the parser, in attempt order.
    sitemap_attempts: List[SitemapAttempt] = field(default_factory=list)
    #: Raw URL count across all successfully parsed sitemaps (with repeats).
    total_urls_before_dedup: int = 0
    #: Unique URL count after first-occurrence-order deduplication.
    total_urls_after_dedup: int = 0
    pages_succeeded: int = 0
    pages_failed: int = 0

    @property
    def pages_fetched(self) -> int:
        return self.pages_succeeded + self.pages_failed

    @property
    def duplicates_removed(self) -> int:
        return max(
            0, self.total_urls_before_dedup - self.total_urls_after_dedup
        )

    @property
    def sitemaps_attempted(self) -> int:
        return len(self.sitemap_attempts)

    def _count(self, status: str) -> int:
        return sum(1 for a in self.sitemap_attempts if a.status == status)

    @property
    def sitemaps_succeeded(self) -> int:
        return self._count(SITEMAP_STATUS_SUCCESS)

    @property
    def sitemaps_parse_failed(self) -> int:
        return self._count(SITEMAP_STATUS_PARSE_FAILED)

    @property
    def sitemaps_request_failed(self) -> int:
        return self._count(SITEMAP_STATUS_REQUEST_FAILED)

    @property
    def sitemaps_skipped(self) -> int:
        return self._count(SITEMAP_STATUS_SKIPPED)

    @property
    def sitemaps_failed(self) -> int:
        return self.sitemaps_parse_failed + self.sitemaps_request_failed

    @property
    def all_sitemaps_failed(self) -> bool:
        """True when every sub-sitemap that should provide URLs failed.

        A successfully parsed index document whose children all failed still
        counts as a total failure: at least one non-skipped attempt failed and
        no successful sitemap produced any page URLs.
        """
        non_skipped = [
            a for a in self.sitemap_attempts if a.status != SITEMAP_STATUS_SKIPPED
        ]
        if not non_skipped:
            return False
        has_failure = any(a.status in _FAILURE_STATUSES for a in non_skipped)
        produced_urls = any(
            a.status == SITEMAP_STATUS_SUCCESS and a.url_count > 0
            for a in non_skipped
        )
        return has_failure and not produced_urls


class SitemapCrawler:
    def __init__(self, base_url: str, timeout: int = 10):
        parsed = urlparse(base_url)
        if parsed.scheme not in ["http", "https"]:
            if parsed.scheme:
                base_url = base_url.replace(f"{parsed.scheme}://", "https://", 1)
            else:
                base_url = f"https://{base_url}"

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.visited_sitemaps: Set[str] = set()
        self.summary: CrawlSummary = CrawlSummary()
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": "Mozilla/5.0 (compatible; SitemapCrawler/1.0)"}
        )

    def get_sitemap_urls(self) -> List[str]:
        """Try common sitemap locations."""
        common_paths = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemap1.xml",
            "/sitemaps.xml",
            "/sitemap/",
        ]

        sitemaps = []
        for path in common_paths:
            url = urljoin(self.base_url, path)
            try:
                response = self.session.head(
                    url, timeout=self.timeout, allow_redirects=True
                )
                if response.status_code == 200:
                    sitemaps.append(url)
                    print(f"Found sitemap: {url}", file=sys.stderr)
            except requests.RequestException:
                pass

        try:
            robots_url = urljoin(self.base_url, "/robots.txt")
            response = self.session.get(robots_url, timeout=self.timeout)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        if sitemap_url not in sitemaps:
                            sitemaps.append(sitemap_url)
                            print(
                                f"Found sitemap in robots.txt: {sitemap_url}",
                                file=sys.stderr,
                            )
        except requests.RequestException:
            pass

        return sitemaps

    def _record_sitemap(
        self,
        sitemap_url: str,
        status: str,
        url_count: int = 0,
        error: Optional[str] = None,
    ) -> None:
        self.summary.sitemap_attempts.append(
            SitemapAttempt(
                url=sitemap_url,
                status=status,
                url_count=url_count,
                error=error,
            )
        )

    def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse sitemap XML and return list of URLs. Handles sitemap indexes recursively."""
        if sitemap_url in self.visited_sitemaps:
            # Same sitemap referenced more than once: parse it only once and
            # never count its URLs again.
            self._record_sitemap(sitemap_url, SITEMAP_STATUS_SKIPPED)
            return []

        self.visited_sitemaps.add(sitemap_url)
        urls = []

        try:
            response = self.session.get(sitemap_url, timeout=self.timeout)
            response.raise_for_status()

            root = ET.fromstring(response.content)

            namespace = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            sitemaps = root.findall(".//ns:sitemap/ns:loc", namespace)
            if sitemaps:
                print(
                    f"Found sitemap index with {len(sitemaps)} sitemaps",
                    file=sys.stderr,
                )
                for sitemap in sitemaps:
                    nested_urls = self.parse_sitemap(sitemap.text)
                    urls.extend(nested_urls)
                # An index contributes no page URLs of its own.
                self._record_sitemap(sitemap_url, SITEMAP_STATUS_SUCCESS)
            else:
                url_elements = root.findall(".//ns:url/ns:loc", namespace)
                urls = [elem.text for elem in url_elements if elem.text]
                print(f"Extracted {len(urls)} URLs from {sitemap_url}", file=sys.stderr)
                self._record_sitemap(
                    sitemap_url,
                    SITEMAP_STATUS_SUCCESS,
                    url_count=len(urls),
                )

        except ET.ParseError as e:
            print(f"XML parse error for {sitemap_url}: {e}", file=sys.stderr)
            self._record_sitemap(
                sitemap_url, SITEMAP_STATUS_PARSE_FAILED, error=str(e)
            )
        except requests.RequestException as e:
            print(f"Request error for {sitemap_url}: {e}", file=sys.stderr)
            self._record_sitemap(
                sitemap_url, SITEMAP_STATUS_REQUEST_FAILED, error=str(e)
            )

        return urls

    def extract_metadata(self, url: str) -> Dict[str, str]:
        """Fetch URL and extract metadata from HTML."""
        metadata = {"url": url}

        try:
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            title_tag = soup.find("title")
            metadata["title"] = title_tag.string.strip() if title_tag else ""

            meta_tags = soup.find_all("meta")
            for tag in meta_tags:
                name = tag.get("name", "").lower() or tag.get("property", "").lower()
                content = tag.get("content", "")

                if name and content:
                    if name in ["description", "og:description", "twitter:description"]:
                        if "description" not in metadata or not metadata["description"]:
                            metadata["description"] = content
                    elif name in ["keywords"]:
                        metadata["keywords"] = content
                    elif name in ["author"]:
                        metadata["author"] = content
                    elif name in ["og:title", "twitter:title"]:
                        if "og_title" not in metadata:
                            metadata["og_title"] = content
                    elif name in ["og:image", "twitter:image"]:
                        if "image" not in metadata:
                            metadata["image"] = content
                    elif name in ["og:type"]:
                        metadata["og_type"] = content

                    elif name not in ["viewport", "charset"]:
                        metadata[name] = content

            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                metadata["canonical"] = canonical["href"]

        except requests.RequestException as e:
            print(f"Error fetching {url}: {e}", file=sys.stderr)
            metadata["error"] = str(e)
        except Exception as e:
            print(f"Error parsing {url}: {e}", file=sys.stderr)
            metadata["error"] = str(e)

        return metadata

    def get_summary(self) -> CrawlSummary:
        """Return the auditable summary of the most recent :meth:`crawl` run."""
        return self.summary

    def crawl(self) -> List[Dict[str, str]]:
        """Main crawl function."""
        # Reset per-run state so repeated crawl() calls produce coherent
        # summaries instead of accumulating stale records.
        self.visited_sitemaps = set()
        self.summary = CrawlSummary()

        sitemap_urls = self.get_sitemap_urls()
        self.summary.sitemaps_found = len(sitemap_urls)

        if not sitemap_urls:
            self.summary.no_sitemaps_found = True
            print("No sitemaps found", file=sys.stderr)
            return []

        all_urls = []
        for sitemap_url in sitemap_urls:
            urls = self.parse_sitemap(sitemap_url)
            all_urls.extend(urls)

        # Deduplicate while preserving the order of first appearance.
        self.summary.total_urls_before_dedup = len(all_urls)
        all_urls = list(dict.fromkeys(all_urls))
        self.summary.total_urls_after_dedup = len(all_urls)
        print(f"\nTotal unique URLs found: {len(all_urls)}", file=sys.stderr)

        results = []
        for i, url in enumerate(all_urls, 1):
            print(f"Processing {i}/{len(all_urls)}: {url}", file=sys.stderr)
            metadata = self.extract_metadata(url)
            if "error" in metadata:
                self.summary.pages_failed += 1
            else:
                self.summary.pages_succeeded += 1
            results.append(metadata)

        return results
