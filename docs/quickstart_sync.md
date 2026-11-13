# Quick Start: Sync Client

The sync client (`Olostep`) provides a blocking interface that's perfect for scripts, beginners, and simple use cases where you don't need async/await syntax.

## Quick Start

```python
from olostep import Olostep

# Provide the API key either via passing in the 'api_key' parameter or
# by setting the OLOSTEP_API_KEY environment variable

# The sync client handles resource management automatically
# No explicit close needed - resources are cleaned up after each operation
client = Olostep(api_key="YOUR_REAL_KEY")
scrape_result = client.scrapes.create(url_to_scrape="https://example.com")
```

## Usage Examples

### Basic Web Scraping

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Simple scraping
result = client.scrapes.create(url_to_scrape="https://example.com")
print(f"Scraped {len(result.html_content)} characters")

# Multiple formats
result = client.scrapes.create(
    url_to_scrape="https://example.com",
    formats=["html", "markdown"]
)
print(f"HTML: {len(result.html_content)} chars")
print(f"Markdown: {len(result.markdown_content)} chars")
```

### Batch Processing

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Process multiple URLs efficiently
batch = client.batches.create(
    urls=[
        "https://www.google.com/search?q=python",
        "https://www.google.com/search?q=javascript",
        "https://www.google.com/search?q=typescript"
    ]
)

# Wait for completion and process results
for item in batch.items():
    content = item.retrieve(["html"])
    print(f"Processed {item.url}: {len(content.html_content)} bytes")
```

### Smart Web Crawling

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Crawl with intelligent filtering
crawl = client.crawls.create(
    start_url="https://www.bbc.com",
    max_pages=100,
    include_urls=["/articles/**", "/blog/**"],
    exclude_urls=["/admin/**"]
)

for page in crawl.pages():
    content = page.retrieve(["html"])
    print(f"Crawled: {page.url}")
```

### Site Mapping

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Extract all links from a website
maps = client.maps.create(url="https://example.com")

# Get all discovered URLs
urls = []
for url in maps.urls():
    urls.append(url)
    if len(urls) >= 10:  # Limit for demo
        break

print(f"Found {len(urls)} URLs")
```

### AI-Powered Answers

```python
from olostep import Olostep

client = Olostep(api_key="your-api-key")

# Get answers from web pages using AI
answer = client.answers.create(
    task="What is the main topic of https://example.com?"
)
print(f"Answer: {answer.answer}")
```
