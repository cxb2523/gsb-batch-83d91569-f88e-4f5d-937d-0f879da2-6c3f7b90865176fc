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

## 🤝 Contributing

Found a bug? Have a feature request? Contributions are welcome! Feel free to open an issue or submit a pull request.

## 📜 License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

---

_Happy harvesting! 🌾_
