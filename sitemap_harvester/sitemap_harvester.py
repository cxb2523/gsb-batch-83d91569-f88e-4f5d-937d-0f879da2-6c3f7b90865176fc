#!/usr/bin/env python3

import csv
import sys
import xml.etree.ElementTree as ET
from typing import Dict, List, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


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

    def parse_sitemap(self, sitemap_url: str) -> List[str]:
        """Parse sitemap XML and return list of URLs. Handles sitemap indexes recursively."""
        if sitemap_url in self.visited_sitemaps:
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
            else:
                url_elements = root.findall(".//ns:url/ns:loc", namespace)
                urls = [elem.text for elem in url_elements if elem.text]
                print(f"Extracted {len(urls)} URLs from {sitemap_url}", file=sys.stderr)

        except ET.ParseError as e:
            print(f"XML parse error for {sitemap_url}: {e}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"Request error for {sitemap_url}: {e}", file=sys.stderr)

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

    def crawl(self) -> List[Dict[str, str]]:
        """Main crawl function."""
        sitemap_urls = self.get_sitemap_urls()

        if not sitemap_urls:
            print("No sitemaps found", file=sys.stderr)
            return []

        all_urls = []
        for sitemap_url in sitemap_urls:
            urls = self.parse_sitemap(sitemap_url)
            all_urls.extend(urls)

        all_urls = list(dict.fromkeys(all_urls))
        print(f"\nTotal unique URLs found: {len(all_urls)}", file=sys.stderr)

        results = []
        for i, url in enumerate(all_urls, 1):
            print(f"Processing {i}/{len(all_urls)}: {url}", file=sys.stderr)
            metadata = self.extract_metadata(url)
            results.append(metadata)

        return results
