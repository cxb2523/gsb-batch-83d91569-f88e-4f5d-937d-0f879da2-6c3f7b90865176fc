# Quick Start: Async Client

The async client (`AsyncOlostep`) is the default and recommended client for high-performance applications, backend services, and when you need to handle many concurrent requests.

## Quick Start

```python
from olostep import AsyncOlostep

# Provide the API key either via passing in the 'api_key' parameter or
# by setting the OLOSTEP_API_KEY environment variable

# RESOURCE MANAGEMENT
# ===================
# The SDK supports two usage patterns for resource management:

# 1. Context Manager (Recommended for one-off usage):
#    Automatically handles resource cleanup
async with AsyncOlostep(api_key="YOUR_REAL_KEY") as client:
    scrape_result = await client.scrapes.create(url_to_scrape="https://example.com")
# Transport is automatically closed here

# 2. Explicit Close (For long-lived services):
#    Requires manual resource cleanup
client = AsyncOlostep(api_key="YOUR_REAL_KEY")
try:
    scrape_result = await client.scrapes.create(url_to_scrape="https://example.com")
finally:
    await client.close()  # Manually close the transport
```

## Usage Examples

### Basic Web Scraping

```python
import asyncio
from olostep import AsyncOlostep

async def main():
    async with AsyncOlostep(api_key="your-api-key") as client:
        # Simple scraping
        result = await client.scrapes.create(url_to_scrape="https://example.com")
        print(f"Scraped {len(result.html_content)} characters")

        # Multiple formats
        result = await client.scrapes.create(
            url_to_scrape="https://example.com",
            formats=["html", "markdown"]
        )
        print(f"HTML: {len(result.html_content)} chars")
        print(f"Markdown: {len(result.markdown_content)} chars")

asyncio.run(main())
```

### Batch Processing

```python
import asyncio
from olostep import AsyncOlostep

async def main():
    async with AsyncOlostep(api_key="your-api-key") as client:
        # Process multiple URLs efficiently
        batch = await client.batches.create(
            urls=[
                "https://www.google.com/search?q=python",
                "https://www.google.com/search?q=javascript",
                "https://www.google.com/search?q=typescript"
            ]
        )

        # Wait for completion and process results
        async for item in batch.items():
            content = await item.retrieve(["html"])
            print(f"Processed {item.url}: {len(content.html_content)} bytes")

asyncio.run(main())
```

### Smart Web Crawling

```python
import asyncio
from olostep import AsyncOlostep

async def main():
    async with AsyncOlostep(api_key="your-api-key") as client:
        # Crawl with intelligent filtering
        crawl = await client.crawls.create(
            start_url="https://www.bbc.com",
            max_pages=100,
            include_urls=["/articles/**", "/blog/**"],
            exclude_urls=["/admin/**"]
        )

        async for page in crawl.pages():
            content = await page.retrieve(["html"])
            print(f"Crawled: {page.url}")

asyncio.run(main())
```

### Site Mapping

```python
import asyncio
from olostep import AsyncOlostep

async def main():
    async with AsyncOlostep(api_key="your-api-key") as client:
        # Extract all links from a website
        maps = await client.maps.create(url="https://example.com")

        # Get all discovered URLs
        urls = []
        async for url in maps.urls():
            urls.append(url)
            if len(urls) >= 10:  # Limit for demo
                break

        print(f"Found {len(urls)} URLs")

asyncio.run(main())
```

### AI-Powered Answers

```python
import asyncio
from olostep import AsyncOlostep

async def main():
    async with AsyncOlostep(api_key="your-api-key") as client:
        # Get answers from web pages using AI
        answer = await client.answers.create(
            task="What is the main topic of https://example.com?"
        )
        print(f"Answer: {answer.answer}")

asyncio.run(main())
```
