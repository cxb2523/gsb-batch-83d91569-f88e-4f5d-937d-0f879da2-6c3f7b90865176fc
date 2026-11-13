"""
Test file demonstrating the Hacker News fixture.
"""

from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from olostep import AsyncOlostep
from olostep.models.request import Format

# Load environment variables from .env file
load_dotenv()


@pytest.mark.parametrize("hacker_news_urls", [3], indirect=True)
def test_hacker_news_fixture(hacker_news_urls: list[str]) -> None:
    """Test the hacker_news_urls fixture."""
    assert len(hacker_news_urls) == 3
    assert all(url.startswith("https://news.ycombinator.com/item?id=") for url in hacker_news_urls)
    
    for url in hacker_news_urls:
        article_id = int(url.split("id=")[1])
        assert 20000000 <= article_id <= 25000000


def test_hacker_news_default_count(hacker_news_urls: list[str]) -> None:
    """Test default count of 5 URLs."""
    assert len(hacker_news_urls) == 5


@pytest.mark.asyncio
async def test_scrape_random_hacker_news_page(hacker_news_urls: list[str]) -> None:
    """Test scraping a random Hacker News page using the Olostep client."""
    api_key = os.getenv("OLOSTEP_API_KEY")
    if not api_key:
        pytest.skip("OLOSTEP_API_KEY not set - skipping integration test")
    
    # Use the first URL from the fixture
    test_url = hacker_news_urls[0]
    
    async with AsyncOlostep(api_key=api_key) as client:
        # Scrape the Hacker News page with multiple formats
        result = await client.scrapes.create(
            url=test_url,
            formats=[Format.HTML, Format.MARKDOWN, Format.TEXT]
        )
        
        # Verify we got a result with an ID
        assert result.id is not None
        assert result.id.startswith("scrape_")
        
        # Verify we can access the scraped content
        assert result.html_content is not None
        assert result.markdown_content is not None  
        assert result.text_content is not None
        
        # Basic content validation - should contain Hacker News elements
        html_content = result.html_content
        assert "hacker" in html_content.lower() or "news" in html_content.lower()
        
        # Verify the content is substantial (not just an error page)
        assert len(result.text_content) > 100
        
        print(f"✅ Successfully scraped Hacker News page: {test_url}")
        print(f"   Scrape ID: {result.id}")
        print(f"   Content length: {len(result.text_content)} characters")
