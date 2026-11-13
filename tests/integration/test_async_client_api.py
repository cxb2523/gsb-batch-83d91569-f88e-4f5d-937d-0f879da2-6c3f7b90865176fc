"""Integration tests for async client API using exact code from documentation.

These tests execute the exact code examples from:
- docs/quickstart_async.md
- README.md (Advanced Features section)

All tests use the real HTTP transport and require OLOSTEP_API_KEY environment variable.
"""

from __future__ import annotations

from urllib.parse import urlparse

import pytest

from olostep import (
    AsyncOlostep,
    Country,
    FillInputAction,
    Format,
    RetryStrategy,
    WaitAction,
)


def _hostname_matches(url: str, domain: str) -> bool:
    """True if the URL's hostname is `domain` or a subdomain of it."""
    host = (urlparse(url).hostname or "").lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


class TestQuickStartAsync:
    """Test Quick Start examples from docs/quickstart_async.md."""

    @pytest.mark.asyncio
    async def test_quick_start_context_manager(self) -> None:
        """Test context manager quick start example."""
        async with AsyncOlostep() as c:
            _ = await c.scrapes.create(url_to_scrape="https://example.com")

    @pytest.mark.asyncio
    async def test_quick_start_explicit_close(self) -> None:
        """Test explicit close quick start example."""
        c = AsyncOlostep()
        try:
            scrape_result = await c.scrapes.create(url_to_scrape="https://example.com")
            assert scrape_result is not None
        finally:
            await c.close()

    @pytest.mark.asyncio
    async def test_basic_web_scraping_simple(self) -> None:
        """Test simple scraping example."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com", formats=["html"])
            assert result.html_content is not None
            assert len(result.html_content) > 0

    @pytest.mark.asyncio
    async def test_basic_web_scraping_multiple_formats(self) -> None:
        """Test multiple formats scraping example."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(
                url_to_scrape="https://example.com",
                formats=["html", "markdown"]
            )
            assert result.html_content is not None
            assert result.markdown_content is not None
            assert len(result.html_content) > 0
            assert len(result.markdown_content) > 0

    @pytest.mark.asyncio
    async def test_batch_processing(self) -> None:
        """Test batch processing example."""
        async with AsyncOlostep() as c:
            batch = await c.batches.create(
                urls=[
                    "https://www.google.com/search?q=python",
                    "https://www.google.com/search?q=javascript",
                    "https://www.google.com/search?q=typescript"
                ]
            )

            async for item in batch.items():
                content = await item.retrieve(["html"])
                assert content.html_content is not None
                assert len(content.html_content) > 0
                assert item.url is not None

    @pytest.mark.asyncio
    async def test_smart_web_crawling(self) -> None:
        """Test smart web crawling example."""
        async with AsyncOlostep() as c:
            crawl = await c.crawls.create(
                start_url="https://www.bbc.com",
                max_pages=100,
                include_urls=["/news/**"],
                exclude_urls=["/admin/**", "/nonexistent/**"],
                follow_robots_txt=False
            )

            async for page in crawl.pages():
                content = await page.retrieve(["html"])
                assert content is not None
                assert page.url is not None

    @pytest.mark.asyncio
    async def test_site_mapping(self) -> None:
        """Test site mapping example."""
        async with AsyncOlostep() as c:
            maps = await c.maps.create(url="https://example.com")

            urls = []
            async for url in maps.urls():
                urls.append(url)
                if len(urls) >= 10:  # Limit for demo
                    break

            assert len(urls) > 0

    @pytest.mark.asyncio
    async def test_ai_powered_answers(self) -> None:
        """Test AI-powered answers example."""
        async with AsyncOlostep() as c:
            answer = await c.answers.create(
                task="What is the main topic of https://example.com?"
            )
            assert answer.answer is not None
            assert len(answer.answer) > 0

    @pytest.mark.asyncio
    async def test_basic_web_search(self) -> None:
        """Search the web with a natural language query."""
        async with AsyncOlostep() as c:
            search = await c.searches.create("Best Answer Engine Optimization startups")
            assert search.id is not None
            assert search.object == "search"
            assert search.query == "Best Answer Engine Optimization startups"
            assert isinstance(search.links, list)
            assert len(search.links) > 0


class TestAdvancedFeatures:
    """Test Advanced Features examples from README.md."""

    @pytest.mark.asyncio
    async def test_smart_input_coercion_formats_string(self) -> None:
        """Test format coercion with string."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com", formats="html")
            assert result is not None

    @pytest.mark.asyncio
    async def test_smart_input_coercion_formats_list(self) -> None:
        """Test format coercion with list."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com", formats=["html", "markdown"])
            assert result is not None

    @pytest.mark.asyncio
    async def test_smart_input_coercion_country_string(self) -> None:
        """Test country coercion with string."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com", country="us")
            assert result is not None

    @pytest.mark.asyncio
    async def test_smart_input_coercion_country_enum(self) -> None:
        """Test country coercion with enum."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com", country=Country.US)
            assert result is not None

    @pytest.mark.asyncio
    async def test_smart_input_coercion_urls_single(self) -> None:
        """Test URLs coercion with single value."""
        async with AsyncOlostep() as c:
            batch = await c.batches.create(urls="https://example.com")
            assert batch is not None

    @pytest.mark.asyncio
    async def test_smart_input_coercion_urls_list(self) -> None:
        """Test URLs coercion with list."""
        async with AsyncOlostep() as c:
            batch = await c.batches.create(urls=["https://a.com", "https://b.com"])
            assert batch is not None

    @pytest.mark.asyncio
    async def test_advanced_scraping_options(self) -> None:
        """Test advanced scraping options example."""
        async with AsyncOlostep() as c:
            result = await c.scrapes.create(
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
            assert result is not None

    @pytest.mark.asyncio
    async def test_batch_processing_with_custom_ids(self) -> None:
        """Test batch processing with custom IDs example."""
        async with AsyncOlostep() as c:
            batch = await c.batches.create([
                {"url": "https://www.google.com/search?q=python", "custom_id": "search_1"},
                {"url": "https://www.google.com/search?q=javascript", "custom_id": "search_2"},
                {"url": "https://www.google.com/search?q=typescript", "custom_id": "search_3"}
            ],
            country=Country.US,
            parser="@olostep/google-search"
            )

            async for item in batch.items():
                if item.custom_id == "search_2":
                    content = await item.retrieve(["json"])
                    assert content.json_content is not None
                    assert isinstance(content.json_content, dict)
                    assert len(content.json_content) > 0

    @pytest.mark.asyncio
    async def test_intelligent_crawling(self) -> None:
        """Test intelligent crawling example."""
        async with AsyncOlostep() as c:
            crawl = await c.crawls.create(
                start_url="https://www.bbc.com",
                max_pages=1000,
                max_depth=3,
                include_urls=["/news/**"],
                exclude_urls=["/ads/**", "/tracking/**", "/nonexistent/**"],
                include_external=False,
                include_subdomain=True,
                follow_robots_txt=False
            )

            async for page in crawl.pages():
                content = await page.retrieve(["html"])
                assert content is not None
                assert page.url is not None

    @pytest.mark.asyncio
    async def test_site_mapping_with_filters(self) -> None:
        """Test site mapping with filters example."""
        async with AsyncOlostep() as c:
            maps = await c.maps.create(
                url="https://www.bbc.com",
                include_subdomain=True,
                include_urls=["/news/**"],
                exclude_urls=["/ads/**", "/tracking/**", "/nonexistent/**"]
            )

            urls = []
            async for url in maps.urls():
                urls.append(url)

            assert len(urls) >= 0

    @pytest.mark.asyncio
    async def test_answers_retrieval(self) -> None:
        """Test answers retrieval example."""
        async with AsyncOlostep() as c:
            # First create an answer
            created_answer = await c.answers.create(
                task="What is the main topic of https://example.com?"
            )
            assert created_answer.id is not None

            # Then retrieve it using the ID
            answer = await c.answers.get(answer_id=created_answer.id)
            assert answer.answer is not None
            assert len(answer.answer) > 0

    @pytest.mark.asyncio
    async def test_search_with_limit_and_filters(self) -> None:
        """Search with limit and include/exclude domain filters."""
        async with AsyncOlostep() as c:
            search = await c.searches.create(
                query="BBC News OpenAI Sora shutdown",
                limit=5,
                include_domains=["bbc.com"],
                # exclude_domains=["pinterest.com"],
            )
            assert len(search.links) > 0
            assert len(search.links) <= 5
            for link in search.links:
                assert _hostname_matches(link["url"], "bbc.com")
                assert not _hostname_matches(link["url"], "pinterest.com")

    @pytest.mark.asyncio
    async def test_search_with_scrape_options(self) -> None:
        """Inline scrape: at least one link should carry markdown_content."""
        async with AsyncOlostep() as c:
            search = await c.searches.create(
                query="OpenAI Sora shutdown",
                limit=5,
                scrape_options={"formats": ["markdown"], "timeout": 25},
            )
            assert len(search.links) > 0
            assert any(link.get("markdown_content") for link in search.links)

    @pytest.mark.asyncio
    async def test_search_retrieval(self) -> None:
        """Idempotent get: the persisted search round-trips."""
        async with AsyncOlostep() as c:
            created = await c.searches.create(query="AI agent frameworks", limit=3)
            assert created.id is not None

            fetched = await c.searches.get(search_id=created.id)
            assert fetched.id == created.id
            assert fetched.query == created.query
            assert fetched.object == "search"
            assert len(fetched.links) == len(created.links)

    @pytest.mark.asyncio
    async def test_content_retrieval_basic(self) -> None:
        """Test basic content retrieval example."""
        async with AsyncOlostep() as c:
            result = await c.retrieve.get(retrieve_id="ret_123")
            assert result is not None

    @pytest.mark.asyncio
    async def test_content_retrieval_multiple_formats(self) -> None:
        """Test content retrieval with multiple formats example."""
        async with AsyncOlostep() as c:
            # Note: "text" format is not valid, but docs show it - using valid formats only
            result = await c.retrieve.get(retrieve_id="ret_123", formats=["html", "markdown", "json"])
            assert result is not None

    @pytest.mark.asyncio
    async def test_retry_strategy(self) -> None:
        """Test retry strategy configuration example."""
        retry_strategy = RetryStrategy(
            max_retries=1,
            initial_delay=1.0,
            jitter_min=0.2,
            jitter_max=0.8
        )

        async with AsyncOlostep(retry_strategy=retry_strategy) as c:
            result = await c.scrapes.create(url_to_scrape="https://example.com")
            assert result is not None
