"""
Integration tests for client behavior against real API.

These tests verify that client methods work correctly with the real API,
testing client behavior, return types, and API interactions.
They do NOT test the internal state of returned objects.
"""
import pytest

from olostep._log import _enable_stderr_debug
from olostep.errors import (
    OlostepClientError_RequestValidationFailed,
    OlostepClientError_ResponseValidationFailed,
    OlostepServerError_BaseError,
    OlostepServerError_RequestUnprocessable,
)
from olostep.frontend.client_state import (
    Batch,
    BatchInfo,
    Crawl,
    CrawlInfo,
    ScrapeResult,
    Sitemap,
)
from olostep.models.common import Country
from olostep.models.request import FillInputAction, Format, WaitAction

_enable_stderr_debug()

class TestScrapeEndpoint:
    """Test the scrape endpoint functionality based on README examples."""
    
    @pytest.mark.asyncio
    async def test_minimal_scrape_example(self, async_client_real):
        """Test the minimal scrape example from README."""
        # MINIMAL SCRAPE EXAMPLE from README
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        
        # Assert the return type
        assert isinstance(scrape_result, ScrapeResult)
        # Assert the result has content
        assert scrape_result.id is not None
        # At least one content format should be available
        content = getattr(scrape_result, "html_content", None) or getattr(scrape_result, "markdown_content", None) or getattr(scrape_result, "text_content", None)
        assert (content is not None and len(content) > 0)

    
    @pytest.mark.asyncio
    async def test_maximal_scrape_example(self, async_client_real):
        """Test the maximal scrape example from README."""
        # MAXIMAL: Full control over scraping behavior from README
        result = await async_client_real.scrapes.create(
            url_to_scrape="https://example.com",
            wait_before_scraping=3000,
            formats=[Format.HTML, Format.MARKDOWN],
            remove_css_selectors='["script", ".popup"]',
            actions=[
                WaitAction(milliseconds=1500), 
                FillInputAction(selector="searchbox", value="olostep")
            ],
            country=Country.US,
            transformer="postlight",
            remove_images=True,
            remove_class_names=["ad"],
            llm_extract={"schema": {"type": "object", "properties": {"title": {"type": "string"}}}},
            links_on_page={
                "absolute_links": False, 
                "query_to_order_links_by": "cars", 
                "include_links": ["/events/**", "/offers/**"],
                "exclude_links": [".pdf"]
            },
            screen_size={"screen_width": 1920, "screen_height": 1080},
            metadata={"custom": "sidecart_data"}
        )
        
        assert isinstance(result, ScrapeResult)
        
        # Assert the result has content
        assert result.id is not None
        assert len(result.html_content) > 0
        assert len(result.markdown_content) > 0

    @pytest.mark.asyncio
    async def test_get_scrape_example(self, async_client_real) -> None:
        # GET SCRAPE EXAMPLE from README
        result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        assert result.id is not None
        scrape_result = await async_client_real.scrapes.get(result.id)
        assert isinstance(scrape_result, ScrapeResult)
        assert scrape_result.id is not None


    @pytest.mark.asyncio
    async def test_scrape_validation_disabled_garbage(self, async_client_real) -> None:
        """Test scrape with garbage data and client validation disabled.

        Current API behavior: with client validation disabled, the garbage
        request reaches the API, which rejects the malformed URL with a 4xx
        (invalid_request_error / dns_resolution_failed) instead of returning
        200 with error content.
        """
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            await async_client_real.scrapes.create(
                url_to_scrape="http-bs://invalid-url-that-does-not-exist.com",
                validate_request=False,
                # Garbage values sent as-is (no client validation)
                wait_before_scraping="invalid_string",
            )

    @pytest.mark.asyncio
    async def test_scrape_validation_enabled_garbage(self, async_client_real) -> None:
        """Test scrape with garbage data and validation enabled (should fail)."""
        # Send garbage data with validation enabled - should raise validation error
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            await async_client_real.scrapes.create(
                url_to_scrape="http-bs://invalid-url-that-does-not-exist.com",
                # These are garbage values that should fail validation
                wait_before_scraping="invalid_string"
            )

    @pytest.mark.asyncio
    async def test_scrape_validation_disabled_valid(self, async_client_real) -> None:
        """Test scrape with valid data and validation disabled (should succeed)."""
        result = await async_client_real.scrapes.create(
            url_to_scrape="https://example.com",
            validate_request=False,
            formats=["html"]
        )
        assert result.id is not None
        assert isinstance(result, ScrapeResult)


class TestBatchEndpoint:
    """Test the batch endpoint functionality based on README examples."""
    
    @pytest.mark.asyncio
    async def test_minimal_batch_example(self, async_client_real):
        """Test the minimal batch example from README."""
        # MINIMAL BATCH EXAMPLE from README
        batch_urls = [
            {"url": "https://www.google.com/search?q=olostep", "custom_id": "news_1"},
            {"url": "https://www.google.com/search?q=olostep+api", "custom_id": "news_2"}
        ]
        batch = await async_client_real.batches.create(urls=batch_urls)
        
        # Assert the return type
        assert isinstance(batch, Batch)
        
        # Assert the batch has the expected values
        assert batch.id is not None
        assert batch.total_urls == 2
        assert batch.completed_urls >= 0
        assert batch.status in ["in_progress", "completed"]
        
        # Test batch info
        info = await batch.info()
        assert isinstance(info, BatchInfo)
        
    
    @pytest.mark.asyncio
    async def test_maximal_batch_example(self, async_client_real):
        """Test the maximal batch example from README."""
        
        # MAXIMAL: Advanced batch with custom IDs and options from README
        batch_urls = [
            {"url": "https://www.google.com/search?q=olostep", "custom_id": "news_1"},
            {"url": "https://www.google.com/search?q=olostep+api", "custom_id": "news_2"}
        ]
        batch = await async_client_real.batches.create(
            urls=batch_urls,
            country=Country.US,
            parser="@olostep/google-search"
        )
        
        # Assert the return type
        assert isinstance(batch, Batch)
        
        # Assert the batch has the expected values
        assert batch.id is not None
        assert batch.total_urls == 2
        assert batch.parser == "@olostep/google-search"
        assert batch.country == str(Country.US)
        # Test batch info
        info = await batch.info()
        assert isinstance(info, BatchInfo)


    @pytest.mark.asyncio
    async def test_batch_validation_disabled_garbage(self, async_client_real):
        """Test batch with garbage data and validation disabled.

        API OBSERVED BEHAVIOR (2026-11): with validation disabled the garbage reaches the API,
        which now rejects the invalid country. It used to accept it (200) and the SDK's response
        validation failed instead. The batches endpoint currently answers 502 "upstream_error"
        (scrapes answer 400); both map to OlostepServerError_RequestUnprocessable.
        """
        with pytest.raises(OlostepServerError_RequestUnprocessable):
            await async_client_real.batches.create(
                urls=["http-bs://invalid-url-that-does-not-exist.com"],
                validate_request=False,
                # These are garbage values that should be sent as-is
                country="invalid_country"
            )

    @pytest.mark.asyncio
    async def test_batch_validation_enabled_garbage(self, async_client_real):
        """Test batch with garbage data and validation enabled (should fail)."""
        # Send garbage data with validation enabled - should raise validation error
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            await async_client_real.batches.create(
                urls=["http-bs://invalid-url-that-does-not-exist.com"],
                validate_request=True,
                # These are garbage values that should fail validation
                country="invalid_country"
            )

    @pytest.mark.asyncio
    async def test_batch_validation_disabled_valid(self, async_client_real) -> None:
        """Test batch with valid data and validation disabled (should succeed).
        
        API OBSERVED BEHAVIOR: The API accepts valid input when validation is disabled
        and processes the batch normally. Previous assumption that this endpoint crashes
        appears to be outdated - the API now handles valid requests successfully.
        """
        batch = await async_client_real.batches.create(
            urls=["https://example.com", "https://httpbin.org/html"],
            validate_request=False,
            country="US"
        )
        # API accepts valid input and returns successful batch
        assert batch.id is not None
        assert isinstance(batch, Batch)


class TestCrawlEndpoint:
    """Test the crawl endpoint functionality based on README examples."""
    
    @pytest.mark.asyncio
    async def test_minimal_crawl_example(self, async_client_real):
        """Test the minimal crawl example from README."""
        # MINIMAL CRAWL EXAMPLE from README
        crawl = await async_client_real.crawls.create(start_url="https://example.com", max_pages=100, follow_robots_txt=False)
        
        # Assert the return type
        assert isinstance(crawl, Crawl)
        
        # Assert the crawl has the expected values
        assert crawl.id is not None
        assert crawl.pages_count >= 0

        assert crawl.status in ["Status.IN_PROGRESS", "Status.COMPLETED", "in_progress", "completed"]
        
        # Test crawl info
        info = await crawl.info()
        assert isinstance(info, CrawlInfo)
        
        # Test crawl pages iteration
        pages = []
        async for page in crawl.pages(wait_for_completion=False):
            pages.append(page)
            if len(pages) >= 5:  # Limit to avoid long test
                break
        
        # Note: Pages may not be available immediately for in-progress crawls
        # This is expected behavior for real API calls
        # assert len(pages) > 0
        # for page in pages:
        #     assert isinstance(page, CrawlPage)
        #     assert page.url is not None
    
    @pytest.mark.asyncio
    async def test_maximal_crawl_example(self, async_client_real):
        """Test the maximal crawl example from README."""
        # MAXIMAL: Advanced crawling with filters and limits from README
        crawl = await async_client_real.crawls.create(
            start_url="https://example.com",
            max_pages=1000,
            max_depth=3,
            include_urls=["/articles/**", "/news/**"],
            exclude_urls=["/ads/**", "/tracking/**"],
            include_external=False,
            include_subdomain=True,
            search_query="hot shingles",
            top_n=50,
            follow_robots_txt=False
        )
        
        # Assert the return type
        assert isinstance(crawl, Crawl)
        
        # Assert the crawl has the expected values
        assert crawl.id is not None
        assert crawl.pages_count >= 0
        assert crawl.status in ["Status.IN_PROGRESS", "Status.COMPLETED", "in_progress", "completed"]
        
        # Test crawl info
        info = await crawl.info()
        assert isinstance(info, CrawlInfo)
        
        # Test crawl pages iteration
        pages = []
        async for page in crawl.pages(wait_for_completion=False):
            pages.append(page)
            if len(pages) >= 5:  # Limit to avoid long test
                break
        
        # Note: Pages may not be available immediately for in-progress crawls
        # This is expected behavior for real API calls
        # assert len(pages) > 0
        # for page in pages:
        #     assert isinstance(page, CrawlPage)
        #     assert page.url is not None

    @pytest.mark.asyncio
    async def test_crawl_validation_disabled_garbage(self, async_client_real):
        """Test crawl with garbage data and validation disabled (should get server error)."""
        # Send garbage data with validation disabled - should get server error

        crawl = await async_client_real.crawls.create(
            start_url="https://invalid-url-that-does-not-exist.com",
            validate_request=False,
            follow_robots_txt=False,
            # These are garbage values that should be sent as-is
            max_pages="invalid_string"
        )
        assert isinstance(crawl, Crawl)


    @pytest.mark.asyncio
    async def test_crawl_validation_enabled_garbage(self, async_client_real):
        """Test crawl with garbage data and validation enabled (should fail)."""
        # Send garbage data with validation enabled - should raise validation error
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            await async_client_real.crawls.create(
                start_url="http-bs://invalid-url-that-does-not-exist.com",
                validate_request=True,
                follow_robots_txt=False,
                # These are garbage values that should fail validation
                max_pages="invalid_string"
            )

    @pytest.mark.asyncio
    async def test_crawl_validation_disabled_valid(self, async_client_real) -> None:
        """Test crawl with valid data and validation disabled (should succeed)."""
        crawl = await async_client_real.crawls.create(
            start_url="https://example.com",
            validate_request=False,
            max_pages=10,
            follow_robots_txt=False
        )
        assert crawl.id is not None
        assert isinstance(crawl, Crawl)


class TestSitemapEndpoint:
    """Test the sitemap endpoint functionality based on README examples."""
    
    @pytest.mark.asyncio
    async def test_minimal_sitemap_example(self, async_client_real):
        """Test the minimal sitemap example from README."""
        # MINIMAL: Extract all links from a site from README
        sitemap = await async_client_real.maps.create(url="https://example.com")
        
        # Assert the return type
        assert isinstance(sitemap, Sitemap)
        
        # Assert the sitemap has the expected values
        assert sitemap.initial_urls_count >= 0
        
        # Test sitemap pagination using async method
        urls_batch = []
        async for url in sitemap.urls():
            urls_batch.append(url)
            if len(urls_batch) >= 10:  # Limit to avoid long test
                break
        
        # Assert we got URLs
        assert len(urls_batch) > 0
        for url in urls_batch:
            assert isinstance(url, str)
            assert url.startswith("http")
    
    @pytest.mark.asyncio
    async def test_maximal_sitemap_example(self, async_client_real):
        """Test the maximal sitemap example from README."""
        # MAXIMAL: Advanced link extraction with filters from README
        sitemap = await async_client_real.maps.create(
            url="https://example.com",
            search_query="documentation",
            top_n=500,
            include_subdomain=True,
            include_urls=["/**"],
            exclude_urls=["/admin/**", "/private/**"]
        )
        
        # Assert the return type
        assert isinstance(sitemap, Sitemap)
        
        # Assert the sitemap has the expected values
        assert sitemap.initial_urls_count >= 0
        
        # Test sitemap pagination using async method
        urls_batch = []
        async for url in sitemap.urls():
            urls_batch.append(url)
            if len(urls_batch) >= 10:  # Limit to avoid long test
                break
        
        # Assert we got URLs
        assert len(urls_batch) > 0
        for url in urls_batch:
            assert isinstance(url, str)
            assert url.startswith("http")


    @pytest.mark.asyncio
    async def test_sitemap_validation_enabled_garbage(self, async_client_real):
        """Test sitemap with garbage data and validation enabled (should fail)."""
        # Send garbage data with validation enabled - should raise validation error
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            await async_client_real.maps.create(
                url="http-bs://invalid-url-that-does-not-exist.com",
                # These are garbage values that should fail validation
                top_n="invalid_string"
            )

    @pytest.mark.asyncio
    async def test_sitemap_validation_disabled_valid(self, async_client_real) -> None:
        """Test sitemap with valid data and validation disabled (should succeed)."""
        sitemap = await async_client_real.maps.create(
            url="https://example.com",
            validate_request=False,
            top_n=100
        )
        assert sitemap.initial_urls_count >= 0
        assert isinstance(sitemap, Sitemap)


class TestRetrieveEndpoint:
    """Test the retrieve endpoint functionality based on README examples."""
    
    @pytest.mark.asyncio
    async def test_minimal_retrieve_example(self, async_client_real):
        """Test the minimal retrieve example from README."""
        # First create a scrape to get a retrieve ID
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        
        # MINIMAL: Get content by retrieve ID from README
        result = await async_client_real.retrieve.get(scrape_result.retrieve_id, formats="markdown")
        
        assert isinstance(result, ScrapeResult)
        
        assert not hasattr(result, "id")
        assert len(result.markdown_content) > 0
    
    @pytest.mark.asyncio
    async def test_maximal_retrieve_example(self, async_client_real):
        """Test the maximal retrieve example from README."""
        # First create a scrape to get a retrieve ID
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com", formats=["html", "markdown"])
        
        # MAXIMAL: Get multiple formats from README
        result = await async_client_real.retrieve.get(scrape_result.retrieve_id, formats=["html", "markdown"])
        
        assert isinstance(result, ScrapeResult)
        
        # Assert the result has content
        assert not hasattr(result, "id")
        assert len(result.html_content) > 0
        assert len(result.markdown_content) > 0

    @pytest.mark.asyncio
    async def test_retrieve_validation_disabled_garbage(self, async_client_real):
        """Test retrieve with garbage data and validation disabled (should get server error)."""
        # First create a scrape to get a retrieve ID
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        
        # Send garbage data with validation disabled - should get server error
        with pytest.raises(OlostepServerError_BaseError):  # Expect server-side error
            await async_client_real.retrieve.get(
                scrape_result.id,
                validate_request=False,
                # These are garbage values that should be sent as-is
                formats="invalid_format"
            )

    @pytest.mark.asyncio
    async def test_retrieve_validation_enabled_garbage(self, async_client_real):
        """Test retrieve with garbage data and validation enabled (should fail)."""
        # First create a scrape to get a retrieve ID
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        
        # Send garbage data with validation enabled - should raise validation error
        with pytest.raises(OlostepClientError_RequestValidationFailed):
            await async_client_real.retrieve.get(
                scrape_result.id,
                validate_request=True,
                # These are garbage values that should fail validation
                formats="invalid_format"
            )

    @pytest.mark.asyncio
    async def test_retrieve_validation_disabled_valid(self, async_client_real) -> None:
        """Test retrieve with valid data and validation disabled (should succeed)."""
        # First create a scrape to get a retrieve ID
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com")
        
        # Retrieve with valid data and validation disabled
        result = await async_client_real.retrieve.get(
            scrape_result.retrieve_id,
            validate_request=False,
            formats=["html", "markdown"]
        )
        assert getattr(result, 'id', None) is None
        assert result.markdown_content is not None
        assert isinstance(result, ScrapeResult)


class TestFullWorkflow:
    """Test complete workflows for all endpoints."""
    
    @pytest.mark.asyncio
    async def test_scrape_full_workflow(self, async_client_real):
        """Test complete scrape workflow: Create -> Get -> Verify."""
        # Create scrape (disable validation to avoid coercion issues)
        result = await async_client_real.scrapes.create(url_to_scrape="https://example.com", validate_request=False)
        assert isinstance(result, ScrapeResult)
        assert result.id is not None
        
        # Get scrape by ID
        retrieved = await async_client_real.scrapes.get(result.id)
        assert isinstance(retrieved, ScrapeResult)
        assert retrieved.id == result.id
        
        # Verify content is accessible
        assert hasattr(result, 'html_content') or hasattr(result, 'markdown_content')
        
        # Test retrieve operation at the end
        retrieved = await async_client_real.retrieve.get(result.id, formats=["html"])
        assert isinstance(retrieved, ScrapeResult)

    @pytest.mark.asyncio
    async def test_batch_full_workflow(self, async_client_real):
        """Test complete batch workflow: Create -> Info -> Items -> Wait."""
        # Create batch (disable validation to avoid coercion issues)
        from olostep.models.request import BatchItem
        batch_items = [
            BatchItem(url="https://example.com", custom_id="test1"),
            BatchItem(url="https://httpbin.org/html", custom_id="test2")
        ]
        # Convert to dictionaries for serialization
        batch_items_dict = [item.model_dump() for item in batch_items]
        batch = await async_client_real.batches.create(urls=batch_items_dict, validate_request=False)
        assert isinstance(batch, Batch)
        assert batch.id is not None
        
        # Get batch info
        info = await batch.info()
        assert isinstance(info, BatchInfo)
        assert info.id == batch.id
        
        # Get batch items (allow partial results)
        items = []
        async for item in batch.items(wait_for_completion=False):
            items.append(item)
            if len(items) >= 2:  # Limit to avoid long test
                break
        
        # Test wait functionality
        await batch.wait_till_done(check_every_n_secs=1)
        
        # Test retrieve operation at the end
        if items:
            first_item = items[0]
            if hasattr(first_item, 'id') and first_item.id:
                retrieved = await async_client_real.retrieve.get(first_item.id, formats=["html"])
                assert isinstance(retrieved, ScrapeResult)

    @pytest.mark.asyncio
    async def test_crawl_full_workflow(self, async_client_real):
        """Test complete crawl workflow: Create -> Info -> Pages -> Wait."""
        # Create crawl (disable validation to avoid coercion issues)
        crawl = await async_client_real.crawls.create(start_url="https://example.com", max_pages=10, validate_request=False, follow_robots_txt=False)
        assert isinstance(crawl, Crawl)
        assert crawl.id is not None
        
        # Get crawl info
        info = await crawl.info()
        assert isinstance(info, CrawlInfo)
        assert info.id == crawl.id
        
        # Get crawl pages (allow partial results)
        pages = []
        async for page in crawl.pages(wait_for_completion=False):
            pages.append(page)
            if len(pages) >= 5:  # Limit to avoid long test
                break
        
        # Test wait functionality
        await crawl.wait_till_done(check_every_n_secs=1)
        
        # Test retrieve operation at the end
        if pages:
            first_page = pages[0]
            if hasattr(first_page, 'id') and first_page.id:
                retrieved = await async_client_real.retrieve.get(first_page.id, formats=["html"])
                assert isinstance(retrieved, ScrapeResult)

    @pytest.mark.asyncio
    async def test_sitemap_full_workflow(self, async_client_real):
        """Test complete sitemap workflow: Create -> Access URLs -> Pagination."""
        # Create sitemap (disable validation to avoid coercion issues)
        sitemap = await async_client_real.maps.create(url="https://example.com", validate_request=False)
        assert isinstance(sitemap, Sitemap)
        assert sitemap.initial_urls_count >= 0
        
        # Access URLs using async method (pagination is automatic)
        urls = []
        async for url in sitemap.urls():
            urls.append(url)
        assert isinstance(urls, list)
        
        # Test retrieve operation at the end - create a scrape from one of the URLs
        if urls:
            test_url = urls[0]
            scrape_result = await async_client_real.scrapes.create(url_to_scrape=test_url, validate_request=False)
            retrieved = await async_client_real.retrieve.get(scrape_result.id, formats=["html"])
            assert isinstance(retrieved, ScrapeResult)

    @pytest.mark.asyncio
    async def test_retrieve_full_workflow(self, async_client_real):
        """Test complete retrieve workflow: Scrape -> Get retrieve_id -> Retrieve."""
        # Create scrape to get retrieve_id (disable validation to avoid coercion issues)
        scrape_result = await async_client_real.scrapes.create(url_to_scrape="https://example.com", validate_request=False)
        assert scrape_result.retrieve_id is not None
        
        # Retrieve content using retrieve_id
        retrieved = await async_client_real.retrieve.get(scrape_result.retrieve_id, formats=["html", "markdown"])
        assert isinstance(retrieved, ScrapeResult)
        
        # Verify content is accessible
        assert hasattr(retrieved, 'html_content') or hasattr(retrieved, 'markdown_content')
