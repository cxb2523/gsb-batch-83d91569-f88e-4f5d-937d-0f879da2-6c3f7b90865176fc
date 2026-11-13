# 🗺️ Sitemap Harvester

[![PyPI - Version](https://img.shields.io/pypi/v/sitemap-harvester)](https://pypi.org/project/sitemap-harvester/)
[![Python Support](https://img.shields.io/pypi/pyversions/sitemap-harvester.svg)](https://pypi.org/project/sitemap-harvester/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/sitemap-harvester)](https://pypi.org/project/sitemap-harvester/)

> 🚀 **A blazingly fast Python tool to harvest URLs and metadata from website sitemaps like a digital archaeologist!**

## 🚀 Quick Start

### Installation

```bash
pip install sitemap-harvester
```

### Basic Usage

```bash
# Harvest a website's sitemap
sitemap-harvester --url https://example.com

# Custom output file and timeout
sitemap-harvester --url https://example.com --output my_data.csv --timeout 15
```

## 🎯 What Gets Extracted?

- 📝 **Page Title** - The main title of each page
- 📄 **Meta Description** - SEO descriptions
- 🏷️ **Keywords** - Meta keywords (if present)
- 👤 **Author** - Page author information
- 🔗 **Canonical URL** - Canonical link references
- 🖼️ **Open Graph Data** - Social media metadata
- 🌐 **Custom Meta Tags** - Any additional meta information

## 💡 Pro Tips

- Use `--timeout` for slower websites or large sitemaps
- The tool automatically deduplicates URLs for you
- Check the console output for real-time progress updates
- Large sitemaps? Grab a coffee ☕ and let it work its magic!

## 🧾 Crawl summary

Every run prints a short, auditable summary to **stderr** that matches the
`CrawlSummary` object exposed via `SitemapCrawler.get_summary()`:

- every sitemap that was attempted and its status — `success`,
  `parse_failed` (invalid XML), `request_failed` (non-200 / network error),
  or `skipped` (a sitemap referenced more than once is parsed only once and
  its URLs are not counted again);
- URL counts before and after first-occurrence-order deduplication;
- the number of pages fetched successfully vs. with errors (failed rows keep
  their `url` and `error` columns in the CSV).

The three empty-result outcomes are distinguishable:

- **no sitemap found** — no common path or `robots.txt` `Sitemap:` entry
  resolved (`summary.no_sitemaps_found`);
- **all sub-sitemaps failed** — sitemaps were discovered but none produced
  URLs (`summary.all_sitemaps_failed`); the CLI exits non-zero and states
  the reason;
- **partial failure** — some children failed but healthy ones still yielded
  URLs; the crawl continues and the CSV is written as usual.

A broken child sitemap never aborts parsing of the remaining children.

## 🧪 Tests

The test suite builds static XML/HTML sites in temporary directories and
serves them over real local HTTP (stdlib only, no network mocking):

```bash
pip install -e ".[test]"
python -m pytest tests/ -v
```

It covers normal nested indexes, partial failure, total failure, duplicate
sitemap references, cross-sitemap URL deduplication order, per-page fetch
failures, and the CLI exit codes / CSV column ordering.


## 🤝 Contributing

Found a bug? Have a feature request? Contributions are welcome! Feel free to open an issue or submit a pull request.

## 📜 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

_Happy harvesting! 🌾_
