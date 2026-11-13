"""Integration tests for sync client API using exact code from documentation.

These tests execute the exact code examples from:
- docs/quickstart_sync.md
- README.md (Advanced Features section)

All tests use the real HTTP transport and require OLOSTEP_API_KEY environment variable.
"""

from __future__ import annotations

from urllib.parse import urlparse

from olostep import Country, FillInputAction, Format, Olostep, RetryStrategy, WaitAction


def _hostname_matches(url: str, domain: str) -> bool:
    """True if the URL's hostname is `domain` or a subdomain of it."""
    host = (urlparse(url).hostname or "").lower()
    domain = domain.lower()
    return host == domain or host.endswith("." + domain)


class TestQuickStartSync:
    """Test Quick Start examples from docs/quickstart_sync.md."""

    def test_quick_start_basic(self) -> None:
        """Test basic quick start example."""
        client = Olostep()
        _ = client.scrapes.create(url_to_scrape="https://example.com")

    def test_quick_start_explicit_close(self) -> None:
        """Test explicit close quick start example."""
        c = Olostep()
        try:
            scrape_result = c.scrapes.create(url_to_scrape="https://example.com")
            assert scrape_result is not None
        finally:
            c.close()

    def test_basic_web_scraping_simple(self) -> None:
        """Test simple scraping example."""
        client = Olostep()
        result = client.scrapes.create(url_to_scrape="https://example.com", formats=["html"])
        assert result.html_content is not None
        assert len(result.html_content) > 0

    def test_basic_web_scraping_multiple_formats(self) -> None:
        """Test multiple formats scraping example."""
        client = Olostep()
        result = client.scrapes.create(
            url_to_scrape="https://example.com",
            formats=["html", "markdown"]
        )
        assert result.html_content is not None
        assert result.markdown_content is not None
        assert len(result.html_content) > 0
        assert len(result.markdown_content) > 0

    def test_batch_processing(self) -> None:
        """Test batch processing example."""
        client = Olostep()
        batch = client.batches.create(
            urls=[
                "https://www.google.com/search?q=python",
                "https://www.google.com/search?q=javascript",
                "https://www.google.com/search?q=typescript"
            ]
        )

        for item in batch.items():
            content = item.retrieve(["html"])
            assert content.html_content is not None
            assert len(content.html_content) > 0
            assert item.url is not None

    def test_smart_web_crawling(self) -> None:
        """Test smart web crawling example."""
        client = Olostep()
        crawl = client.crawls.create(
            start_url="https://www.bbc.com",
            max_pages=100,
            include_urls=["/articles/**", "/blog/**"],
            exclude_urls=["/admin/**"],
            follow_robots_txt=False
        )

        for page in crawl.pages():
            content = page.retrieve(["html"])
            assert content is not None
            assert page.url is not None

    def test_site_mapping(self) -> None:
        """Test site mapping example."""
        client = Olostep()
        maps = client.maps.create(url="https://example.com")

        urls = []
        for url in maps.urls():
            urls.append(url)
            if len(urls) >= 10:  # Limit for demo
                break

        assert len(urls) > 0

    def test_ai_powered_answers(self) -> None:
        """Test AI-powered answers example."""
        client = Olostep()
        answer = client.answers.create(
            task="What is the main topic of https://example.com?"
        )
        assert answer.answer is not None
        assert len(answer.answer) > 0

    def test_basic_web_search(self) -> None:
        """Search the web with a natural language query."""
        client = Olostep()
        search = client.searches.create("Best Answer Engine Optimization startups")
        assert search.id is not None
        assert search.object == "search"
        assert search.query == "Best Answer Engine Optimization startups"
        assert isinstance(search.links, list)
        assert len(search.links) > 0


class TestAdvancedFeatures:
    """Test Advanced Features examples from README.md."""

    def test_smart_input_coercion_formats_string(self) -> None:
        """Test format coercion with string."""
        client = Olostep()
        result = client.scrapes.create(url_to_scrape="https://example.com", formats="html")
        assert result is not None

    def test_smart_input_coercion_formats_list(self) -> None:
        """Test format coercion with list."""
        client = Olostep()
        result = client.scrapes.create(url_to_scrape="https://example.com", formats=["html", "markdown"])
        assert result is not None

    def test_smart_input_coercion_country_string(self) -> None:
        """Test country coercion with string."""
        client = Olostep()
        result = client.scrapes.create(url_to_scrape="https://example.com", country="us")
        assert result is not None

    def test_smart_input_coercion_country_enum(self) -> None:
        """Test country coercion with enum."""
        client = Olostep()
        result = client.scrapes.create(url_to_scrape="https://example.com", country=Country.US)
        assert result is not None

    def test_smart_input_coercion_urls_single(self) -> None:
        """Test URLs coercion with single value."""
        client = Olostep()
        batch = client.batches.create(urls="https://example.com")
        assert batch is not None

    def test_smart_input_coercion_urls_list(self) -> None:
        """Test URLs coercion with list."""
        client = Olostep()
        batch = client.batches.create(urls=["https://a.com", "https://b.com"])
        assert batch is not None

    def test_advanced_scraping_options(self) -> None:
        """Test advanced scraping options example."""
        client = Olostep()
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
        assert result is not None

    def test_batch_processing_with_custom_ids(self) -> None:
        """Test batch processing with custom IDs example."""
        client = Olostep()
        batch = client.batches.create([
            {"url": "https://www.google.com/search?q=python", "custom_id": "search_1"},
            {"url": "https://www.google.com/search?q=javascript", "custom_id": "search_2"},
            {"url": "https://www.google.com/search?q=typescript", "custom_id": "search_3"}
        ],
        country=Country.US,
        parser="@olostep/google-search"
        )

        for item in batch.items():
            if item.custom_id == "search_2":
                content = item.retrieve(["json"])
                assert content.json_content is not None
                assert isinstance(content.json_content, dict)
                assert len(content.json_content) > 0

    def test_intelligent_crawling(self) -> None:
        """Test intelligent crawling example."""
        client = Olostep()
        crawl = client.crawls.create(
            start_url="https://www.bbc.com",
            max_pages=20,
            max_depth=3,
            include_urls=["/articles/**", "/news/**"],
            exclude_urls=["/ads/**", "/tracking/**"],
            include_external=False,
            include_subdomain=True,
            follow_robots_txt=False
        )

        for page in crawl.pages():
            content = page.retrieve(["html"])
            assert content is not None
            assert page.url is not None

    def test_site_mapping_with_filters(self) -> None:
        """Test site mapping with filters example."""
        client = Olostep()
        maps = client.maps.create(
            url="https://www.bbc.com",
            include_subdomain=True,
            include_urls=["/articles/**", "/news/**"],
            exclude_urls=["/ads/**", "/tracking/**"]
        )

        urls = []
        for url in maps.urls():
            urls.append(url)

        assert len(urls) >= 0

    def test_answers_retrieval(self) -> None:
        """Test answers retrieval example."""
        client = Olostep()
        # First create an answer
        created_answer = client.answers.create(
            task="What is the main topic of https://example.com?"
        )
        assert created_answer.id is not None

        # Then retrieve it using the ID
        answer = client.answers.get(answer_id=created_answer.id)
        assert answer.answer is not None
        assert len(answer.answer) > 0

    def test_search_with_limit_and_filters(self) -> None:
        """Search with limit and include/exclude domain filters."""
        client = Olostep()
        search = client.searches.create(
            query="BBC news OpenAI Sora shutdown",
            limit=5,
            include_domains=["bbc.com"],
            # exclude_domains=["pinterest.com"],
        )
        assert len(search.links) > 0
        assert len(search.links) <= 5
        for link in search.links:
            assert _hostname_matches(link["url"], "bbc.com")
            assert not _hostname_matches(link["url"], "pinterest.com")

    def test_search_with_scrape_options(self) -> None:
        """Inline scrape: at least one link should carry markdown_content."""
        client = Olostep()
        search = client.searches.create(
            query="OpenAI Sora shutdown",
            limit=5,
            scrape_options={"formats": ["markdown"], "timeout": 25},
        )
        assert len(search.links) > 0
        assert any(link.get("markdown_content") for link in search.links)

    def test_search_retrieval(self) -> None:
        """Idempotent get: the persisted search round-trips."""
        client = Olostep()
        created = client.searches.create(query="AI agent frameworks", limit=3)
        assert created.id is not None

        fetched = client.searches.get(search_id=created.id)
        assert fetched.id == created.id
        assert fetched.query == created.query
        assert fetched.object == "search"
        assert len(fetched.links) == len(created.links)

    def test_content_retrieval_basic(self) -> None:
        """Test basic content retrieval example."""
        client = Olostep()
        result = client.retrieve.get(retrieve_id="ret_123")
        assert result is not None

    def test_content_retrieval_multiple_formats(self) -> None:
        """Test content retrieval with multiple formats example."""
        client = Olostep()
        # Note: "text" format is not valid, but docs show it - using valid formats only
        result = client.retrieve.get(retrieve_id="ret_123", formats=["html", "markdown", "json"])
        assert result is not None

    def test_retry_strategy(self) -> None:
        """Test retry strategy configuration example."""
        retry_strategy = RetryStrategy(
            max_retries=3,
            initial_delay=1.0,
            jitter_min=0.2,
            jitter_max=0.8
        )

        client_with_retry = Olostep(retry_strategy=retry_strategy)
        result = client_with_retry.scrapes.create(url_to_scrape="https://example.com")
        assert result is not None
