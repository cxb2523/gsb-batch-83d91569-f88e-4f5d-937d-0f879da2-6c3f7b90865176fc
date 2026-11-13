<div align="center">
  <img src="https://www.olostep.com/images/olostep-logo-cropped.svg" alt="Olostep Logo" width="150"/>
  <h2>Python SDK</h2>

✨ [Get a free API key](https://www.olostep.com/?utm_source=python_sdk_readme) • [Full Documentation](https://docs.olostep.com?utm_source=python_sdk_readme) • [GitHub Issues](https://github.com/olostep-api/olostep-py/issues) ✨

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT) [![CI](https://github.com/olostep-api/olostep-py/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/olostep-api/olostep-py/actions/workflows/ci.yml)

  <br>
  </div>
  <h3>A programmatic web access for AI applications</h3>

Olostep provides a **programmatic layer to access and interact with the web**.
Fetch clean, ready-to-use data for your AI from any website in **1–5 seconds**, and scale up to **100K parallel requests in minutes**. You can:

- **Scrape** pages with various output formats including structured data
- **Batch** scrape hundreds of websites simultaneously
- **Crawl** websites with intelligent filtering and depth control
- Create **sitemaps** even for websites with hundreds of thousands of pages
- Get **answers** from web pages using AI-powered extraction
- **Search** the web with natural language queries and optionally embed scraped content per link
  <br>

---

## Table of Contents

- [Breaking Changes in v1.0.0](#️-breaking-changes-in-v100)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [API Reference](#api-reference)
- [Error Handling](#error-handling)
- [Advanced Features](#advanced-features)
- [Olostep via API vs SDK](#olostep-via-api-vs-sdk)
- [Contributing](#contributing)
- [License](#license)

## ⚠️ Breaking Changes in v1.0.0

**Important**: Version 1.0.0 introduces breaking changes from v0.x.x. Please update your code accordingly.

Based on user feedback, release 1.0.0 will not only include more features but also provide a homogenized API that emulates patterns you find in other SDKs you might already be using. This introduces the following three types of breaking changes:

1. client class renaming,
2. and endpoint namespace standardization (plural)
3. endpoint method standardization (create)

### Client Classes

```python
# Change: The async client now uses the "Async" prefix much like other SDKs of similar design. We also took the opportunity to drop the "Client" part

# Old
from olostep import OlostepClient, SyncOlostepClient

# New
from olostep import AsyncOlostep, Olostep

# So
# OlostepClient -> AsyncOlostep and
# SyncOlostepClient -> Olostep
```

### Endpoint Namespaces

```python
# Change: All endpoint namespaces are now plural for consistency. Also, sitemap was renamed to maps.

# Old
result = (await) client.scrape.ENDPOINT
batch = (await) client.batch.ENDPOINT
crawl = (await) client.crawl.ENDPOINT
sitemap = (await) client.sitemap.ENDPOINT
content = (await) client.retrieve.ENDPOINT
answers = (await) client.answers.ENDPOINT

# New
result = (await) client.scrapes.ENDPOINT
batch = (await) client.batches.ENDPOINT
crawl = (await) client.crawls.ENDPOINT
maps = (await) client.maps.ENDPOINT
content = (await) client.retrieve.ENDPOINT
answers = (await) client.answers.ENDPOINT
```

### Endpoint Methods

```python
# Change: All creation methods now use .create() for consistency. Previously, batch and crawl used .start(). Scrape, answers, and sitemap/maps already used .create() and remain unchanged.

# Old
batch = (await) client.batch.start(urls)
crawl = (await) client.crawl.start(url)

# New
batch = (await) client.batches.create(urls)
crawl = (await) client.crawls.create(url)
```

## Installation

### PyPI (Recommended)

```bash
pip install olostep
```

### From Source

```bash
git clone https://github.com/olostep-api/olostep-py.git
cd olostep-python
pip install -e .
```

### Requirements

- Python 3.11+
- API key from [olostep.com](https://www.olostep.com/?utm_source=python_sdk_readme)

## Quick Start

The SDK provides two client options depending on your use case:

<table>
<tr>
<td width="50%">

### 📝 Sync Client (`Olostep`)

**Best for:** Scripts, beginners, and simple use cases where you prefer blocking operations.

The sync client provides a simpler, blocking interface that's easier to get started with if you're new to async/await.

👉 **[See Sync Quick Start Guide](docs/quickstart_sync.md)**

</td>
<td width="50%">

### 🚀 Async Client (`AsyncOlostep`)

**Best for:** Performance-critical applications, backend services, and handling many concurrent requests.

The async client provides non-blocking operations and is the recommended choice for production applications that need high throughput.

👉 **[See Async Quick Start Guide](docs/quickstart_async.md)**

</td>
</tr>
</table>

## API Reference

### Method Structure

Both SDK clients provide the same clean, pythonic interface organized into logical namespaces:

| Namespace  | Purpose               | Key Methods                     |
| ---------- | --------------------- | ------------------------------- |
| `scrapes`  | Single URL extraction | `create()`, `get()`             |
| `batches`  | Multi-URL processing  | `create()`, `info()`, `items()` |
| `crawls`   | Website traversal     | `create()`, `info()`, `pages()` |
| `maps`     | Link extraction       | `create()`, `urls()`            |
| `answers`  | AI-powered extraction | `create()`, `get()`             |
| `searches` | Web search            | `create()`, `get()`             |
| `retrieve` | Content retrieval     | `get()`                         |
| `monitors` | Scheduled change monitoring | `create()`, `get()`, `list()`, `pause()`, `resume()`, `delete()`, `events()` |

Each operation returns stateful objects with ergonomic methods for follow-up operations.

## Error Handling

Catch all SDK errors using the base exception class:

```python
from olostep import Olostep, Olostep_BaseError

client = Olostep(api_key="your-api-key")

try:
    result = client.scrapes.create(url_to_scrape="https://example.com")
except Olostep_BaseError as e:
    print(f"Error has occurred: {type(e).__name__}")
    print(f"Error message: {e}")
```

For detailed error handling information, including the full exception hierarchy and granular error handling options, see [Error Handling](docs/error_handling.md).

### Automatic Retries

The SDK automatically retries on transient errors (network issues, temporary server problems) based on the `RetryStrategy` configuration. You can customize the retry behavior by passing a `RetryStrategy` instance when creating the client:

```python
from olostep import Olostep, RetryStrategy

retry_strategy = RetryStrategy(
    max_retries=3,
    initial_delay=1.0,
    jitter_min=0.2,
    jitter_max=0.8
)

client = Olostep(api_key="your-api-key", retry_strategy=retry_strategy)
result = client.scrapes.create("https://example.com")
```

For detailed retry configuration options and best practices, see [Retry Strategy](docs/retry_strategy.md).

## Advanced Features

### Smart Input Coercion

The SDK intelligently handles various input formats for maximum convenience:

```python
from olostep import Olostep, Country

client = Olostep(api_key="your-api-key")

# Formats: string, list, or enum
client.scrapes.create(url_to_scrape="https://example.com", formats="html")
client.scrapes.create(url_to_scrape="https://example.com", formats=["html", "markdown"])

# Countries: case-insensitive strings or enums
client.scrapes.create(url_to_scrape="https://example.com", country="us")
client.scrapes.create(url_to_scrape="https://example.com", country=Country.US)

# Lists: single values or lists
client.batches.create(urls="https://example.com")    # Single URL
client.batches.create(urls=["https://a.com", "https://b.com"])  # Multiple URLs
```

### Advanced Scraping Options

```python
from olostep import Olostep, Format, Country, WaitAction, FillInputAction

client = Olostep(api_key="your-api-key")

# Full control over scraping behavior
result = client.scrapes.create(
    url_to_scrape="https://news.google.com/",
    wait_before_scraping=3000,
    formats=[Format.HTML, Format.MARKDOWN],
    remove_css_selectors=["script", ".popup"],
    actions=[
        WaitAction(milliseconds=1500),
        FillInputAction(selector="searchbox", value="olostep")
    ],
    parser="@olostep/google-news",
    country=Country.US,
    remove_images=True
)
```

### Batch Processing with Custom IDs

```python
from olostep import Olostep, Country

client = Olostep(api_key="your-api-key")

batch = client.batches.create([
    {"url": "https://www.google.com/search?q=python", "custom_id": "search_1"},
    {"url": "https://www.google.com/search?q=javascript", "custom_id": "search_2"},
    {"url": "https://www.google.com/search?q=typescript", "custom_id": "search_3"}
],
country=Country.US,
parser="@olostep/google-search"
)

# Process results by custom ID
# When using a parser, retrieve JSON content instead of HTML
for item in batch.items():
    if item.custom_id == "search_2":
        content = item.retrieve(["json"])
        print(f"Search result: {content.json_content}")
```

### Intelligent Crawling

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Crawl with intelligent filtering
crawl = client.crawls.create(
    start_url="https://www.bbc.com",
    max_pages=1000,
    max_depth=3,
    include_urls=["/articles/**", "/news/**"],
    exclude_urls=["/ads/**", "/tracking/**"],
    include_external=False,
    include_subdomain=True,
)

for page in crawl.pages():
    content = page.retrieve(["html"])
    print(f"Crawled: {page.url}")
```

### Site Mapping with Filters

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Extract all links with advanced filtering
maps = client.maps.create(
    url="https://www.bbc.com",
    include_subdomain=True,
    include_urls=["/articles/**", "/news/**"],
    exclude_urls=["/ads/**", "/tracking/**"]
)

# Get filtered URLs
urls = []
for url in maps.urls():
    urls.append(url)

print(f"Found {len(urls)} relevant URLs")
```

### Answers Retrieval

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# First create an answer
created_answer = client.answers.create(
    task="What is the main topic of https://example.com?"
)

# Then retrieve it using the ID
answer = client.answers.get(answer_id=created_answer.id)
print(f"Answer: {answer.answer}")
```

### Search

Search the web with a natural language query and get back a deduplicated list of relevant links. Optionally scrape every returned URL in one round-trip and embed `markdown_content` / `html_content` directly on each link.

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Basic search
search = client.searches.create("Best Answer Engine Optimization startups")
print(f"{len(search.links)} links")
for link in search.links:
    print(link["url"], "-", link["title"])

# Limit + domain filtering
filtered = client.searches.create(
    query="OpenAI Sora shutdown analysis",
    limit=5,
    include_domains=["bbc.com", "nytimes.com"],
    exclude_domains=["pinterest.com"],
)

# Search + inline scrape (markdown content embedded on each link)
enriched = client.searches.create(
    query="What's going on with OpenAI's Sora shutting down?",
    limit=5,
    scrape_options={"formats": ["markdown"], "timeout": 25},
)
for link in enriched.links:
    chars = len(link.get("markdown_content") or "")
    print(link["url"], "-", chars, "chars")

# Idempotent get (no rebill, no rescrape)
fetched = client.searches.get(search_id=search.id)
```

Async usage:

```python
from olostep import AsyncOlostep

async with AsyncOlostep(api_key="your-api-key") as client:
    search = await client.searches.create(
        query="best vector databases",
        limit=10,
        scrape_options={"formats": ["markdown"], "timeout": 25},
    )
    for link in search.links:
        print(link["url"])
```

`scrape_options.formats` only supports `"html"` and `"markdown"`. `timeout` bounds the entire scrape phase (1-60 seconds) - links that don't finish in time return with `markdown_content` / `html_content` set to `None`.

### Scheduled Monitors

Watch a page or a query on a schedule and get notified when something changes. A monitor provisions in the background and runs on its own:

```python
# Create a monitor from a natural-language query
monitor = client.monitors.create(
    "Alert me when the Stripe status page reports an incident",
    frequency="every 30 minutes",
    notification={"channels": [{"type": "email", "target": "you@example.com"}]},
)
print(monitor.id, monitor.status)  # monitor_..., "provisioning"

# Read, list, pause, and resume
info = client.monitors.get(monitor.id)
monitors = client.monitors.list()
client.monitors.pause(monitor.id)
client.monitors.resume(monitor.id)

# Review the change history, then delete when you are done
events = client.monitors.events(monitor.id)
client.monitors.delete(monitor.id)
```

The same calls work on `AsyncOlostep` with `await`.

### Content Retrieval

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Get content by retrieve ID
result = client.retrieve.get(retrieve_id="ret_123")

# Get multiple formats
result = client.retrieve.get(retrieve_id="ret_123", formats=["html", "markdown", "text", "json"])
```

## Olostep via API vs SDK

The Olostep Python SDK offers significant advantages over direct API usage:

| Feature              | SDK Advantage                                 | Direct API              |
| -------------------- | --------------------------------------------- | ----------------------- |
| **Interface**        | Discoverable dot-notation namespaces          | REST endpoints          |
| **Type Safety**      | Full Pydantic validation & type hints         | Manual validation       |
| **State Management** | Stateful return objects with rich `__repr__`s | Manual state tracking   |
| **Error Handling**   | Automatic retries & connection management     | Manual implementation   |
| **Pagination**       | Elegant `(async) for` loops                   | Manual cursor handling  |
| **Input Coercion**   | Smart type coercion & validation              | Manual data preparation |
| **Performance**      | Async-first with sync facade                  | HTTP request overhead   |

### Key Benefits

- **Developer Experience**: Type-safe, ergonomic Python API with intelligent input handling
- **Production Ready**: Automatic retries, connection pooling, and error recovery
- **AI-Optimized**: Clean, structured data extraction perfect for LLM applications
- **Enterprise Scale**: Handle 100K+ concurrent requests with robust error handling
- **Future-Proof**: Built on modern Python patterns (async/await, type hints, dataclasses)

## Logging

Enable logging to debug issues:

```python
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("olostep")
logger.setLevel(logging.INFO)  # Use DEBUG for verbose output
```

**Log Levels**: `INFO` (recommended), `DEBUG` (verbose), `WARNING`, `ERROR`

## Configuration

### Environment Variables

| Variable               | Description               | Default                      |
| ---------------------- | ------------------------- | ---------------------------- |
| `OLOSTEP_API_KEY`      | Your API key              | Required                     |
| `OLOSTEP_BASE_API_URL` | API base URL              | `https://api.olostep.com/v1` |
| `OLOSTEP_API_TIMEOUT`  | Request timeout (seconds) | `150`                        |

### Getting Help

- [Full Documentation](https://docs.olostep.com)
- [Report Issues](https://github.com/olostep-api/olostep-py/issues)
- [Community Slack](https://join.slack.com/t/olostep-users/shared_invite/zt-2pn2ce0uu-~591qIdhAfJy~LXCWQS5UQ)
- [Support Email](mailto:info@olostep.com)

## Contributing

We love contributions! Here's how you can help improve the Olostep Python SDK:

### Development Setup

```bash
git clone https://github.com/olostep-api/olostep-py/issues.git
cd olostep-python
pip install -e ".[dev]"
```

### Running Tests

```bash
# Run all tests
pytest

# Run specific test categories
pytest tests/unit/

pytest tests/docs_commands/ -v
# DO NOT RUN THE API CONTRACT TEST!
```

### Code Style

```bash
# Format code
ruff format olostep/

# Lint code
ruff check olostep/
mypy olostep/
```

### Submitting Changes

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-enhancement`)
3. Make your changes with comprehensive tests
4. Run the full test suite
5. Update documentation for API changes
6. Submit a pull request with a clear description

### Guidelines

- Follow PEP 8 and existing code style
- Add type hints for new functions
- Write comprehensive tests for new functionality
- Update documentation for API changes
- Use conventional commit messages

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**Built with ❤️ by the Olostep team**

</div>
