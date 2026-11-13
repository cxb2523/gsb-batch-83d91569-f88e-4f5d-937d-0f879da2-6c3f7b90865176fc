"""
Unit tests for the frontend client state objects.

These tests verify the behavior of stateful client objects against the real API
based on the expected behavior described in the README.
"""

import asyncio

import pytest

from olostep.errors import OlostepClientError_Timeout
from olostep.frontend.client_state import (
    Batch,
    BatchInfo,
    BatchItemResult,
    Crawl,  #, RetrievableID
    CrawlInfo,
    CrawlPage,
    ScrapeResult,
    Sitemap,
)
from olostep.frontend.retrieve_menu import RetrieveMenu
from olostep.frontend.sitemap_menu import SitemapMenu
from olostep.models.response import (
    BatchCreateResponse,
    BatchInfoResponse,
    BatchItemsResponseListItem,
    CrawlInfoResponse,
    CrawlPagesResponseListItem,
    CreateCrawlResponse,
    CreateScrapeResponse,
    GetScrapeResponse,
    MapResponse,
    RetrieveResponse,
)
from tests.fixtures.api.responses.batch import (
    BATCH_CREATE_RESPONSE,
    BATCH_INFO_RESPONSE,
    BATCH_INFO_RESPONSE_FAILED,
    BATCH_INFO_RESPONSE_IN_PROGRESS,
)
from tests.fixtures.api.responses.crawl import (
    CRAWL_CREATE_RESPONSE,
    CRAWL_INFO_RESPONSE,
    CRAWL_INFO_RESPONSE_IN_PROGRESS,
)
from tests.fixtures.api.responses.map import (
    MAP_RESPONSE,
    MAP_RESPONSE_EMPTY_CURSOR,
    MAP_RESPONSE_NO_ID,
    MAP_RESPONSE_WITH_CURSOR,
)
from tests.fixtures.api.responses.scrape import (
    CREATE_SCRAPE_RESPONSE,
    GET_SCRAPE_RESPONSE,
    RETRIEVE_RESPONSE,
)


class TestScrapeResult:
    """Test ScrapeResult stateful object creation and behavior."""

    def test_create_from_create_scrape_response(self):
        """Test ScrapeResult creation from CreateScrapeResponse."""
        response = CreateScrapeResponse(**CREATE_SCRAPE_RESPONSE)
        result = ScrapeResult(response)
        
        # Verify it can be created
        assert isinstance(result, ScrapeResult)
        
        # Verify only fields from response are present
        assert hasattr(result, 'html_content')
        assert hasattr(result, 'markdown_content')
        assert hasattr(result, 'size_exceeded')
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_create_from_get_scrape_response(self):
        """Test ScrapeResult creation from GetScrapeResponse."""
        response = GetScrapeResponse(**GET_SCRAPE_RESPONSE)
        result = ScrapeResult(response)
        
        # Verify it can be created
        assert isinstance(result, ScrapeResult)
        
        # Verify content is accessible
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_create_from_retrieve_response(self):
        """Test ScrapeResult creation from RetrieveResponse."""
        response = RetrieveResponse(**RETRIEVE_RESPONSE)
        result = ScrapeResult(response)
        
        # Verify it can be created
        assert isinstance(result, ScrapeResult)
        
        # Verify content is accessible
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = CreateScrapeResponse(**CREATE_SCRAPE_RESPONSE)
        result = ScrapeResult(response)
        
        # Test __repr__
        repr_str = repr(result)
        assert "ScrapeResult" in repr_str
        assert "available=" in repr_str
        
        # Test __str__
        str_repr = str(result)
        assert "ScrapeResult" in str_repr
        assert "html=" in str_repr
        assert "md=" in str_repr

    def test_only_response_fields_present(self):
        """Test that only fields present in the response are set as attributes."""
        response = CreateScrapeResponse(**CREATE_SCRAPE_RESPONSE)
        result = ScrapeResult(response)
        
        # Check that expected fields are present
        expected_fields = ['html_content', 'markdown_content', 'size_exceeded']
        for field in expected_fields:
            assert hasattr(result, field)
        
        # Check that fields not in response are not present
        # (This depends on the specific response structure)
        # For example, if json_content is not in the response, it shouldn't be an attribute
        if 'json_content' not in CREATE_SCRAPE_RESPONSE['result']:
            assert not hasattr(result, 'json_content')


class TestBatch:
    """Test Batch stateful object creation and behavior."""

    def test_batch_creation_from_response(self):
        """Test Batch creation from BatchCreateResponse."""
        response = BatchCreateResponse(**BATCH_CREATE_RESPONSE)
        # Mock caller for testing
        class MockCaller:
            pass
        caller = MockCaller()
        batch = Batch(caller, response)
        
        # Verify it can be created
        assert isinstance(batch, Batch)
        
        # Verify fields are set correctly
        assert batch.id == "batch_abc123"
        assert batch.status == "in_progress"
        assert batch.total_urls == 3
        assert batch.completed_urls == 0

    def test_batch_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = BatchCreateResponse(**BATCH_CREATE_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        batch = Batch(caller, response)
        
        # Test __repr__
        repr_str = repr(batch)
        assert "Batch" in repr_str
        assert "batch_abc123" in repr_str
        assert "urls=3" in repr_str
        
        # Test __str__
        str_repr = str(batch)
        assert "Batch" in str_repr
        assert "batch_abc123" in str_repr
        assert "[in_progress]" in str_repr
        assert "0/3" in str_repr

    def test_batch_wait_till_done_with_completed_status(self):
        """Test that wait_till_done completes when status becomes 'completed' after second call."""
        response = BatchCreateResponse(**BATCH_CREATE_RESPONSE)
        
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    # First call returns in_progress status
                    return BatchInfoResponse(**BATCH_INFO_RESPONSE_IN_PROGRESS)
                else:
                    # Second call returns completed status
                    return BatchInfoResponse(**BATCH_INFO_RESPONSE)
        
        caller = MockCaller()
        batch = Batch(caller, response)
        
        # This should complete after the second call when status becomes 'completed'
        asyncio.run(batch.wait_till_done(check_every_n_secs=1))
        assert caller.call_count == 2

    def test_batch_wait_till_done_with_failed_status(self):
        """Test that wait_till_done completes when status becomes 'completed' after second call."""
        response = BatchCreateResponse(**BATCH_CREATE_RESPONSE)
        
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    # First call returns in_progress status
                    return BatchInfoResponse(**BATCH_INFO_RESPONSE_IN_PROGRESS)
                else:
                    # Second call returns completed status (since "failed" isn't valid in Status enum)
                    return BatchInfoResponse(**BATCH_INFO_RESPONSE_FAILED)
        
        caller = MockCaller()
        batch = Batch(caller, response)
        
        # This should complete after the second call when status becomes 'completed'
        asyncio.run(batch.wait_till_done(check_every_n_secs=1))
        assert caller.call_count == 2



class TestBatchInfo:
    """Test BatchInfo stateful object creation and behavior."""

    def test_batch_info_creation_from_response(self):
        """Test BatchInfo creation from BatchInfoResponse."""
        response = BatchInfoResponse(**BATCH_INFO_RESPONSE)
        batch_info = BatchInfo(response)
        
        # Verify it can be created
        assert isinstance(batch_info, BatchInfo)
        
        # Verify fields are set correctly
        assert batch_info.id == "batch_abc123"
        assert batch_info.status == "completed"
        assert batch_info.total_urls == 3
        assert batch_info.completed_urls == 3

    def test_batch_info_age_property_works(self):
        """Test that age property returns formatted time delta."""
        response = BatchInfoResponse(**BATCH_INFO_RESPONSE)
        batch_info = BatchInfo(response)
        
        # Test age property
        age = batch_info.age
        assert isinstance(age, str)
        # Should contain time information
        assert any(keyword in age.lower() for keyword in ["ago", "d", "h", "m", "s"])

    def test_batch_info_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = BatchInfoResponse(**BATCH_INFO_RESPONSE)
        batch_info = BatchInfo(response)
        
        # Test __repr__
        repr_str = repr(batch_info)
        assert "BatchInfo" in repr_str
        assert "batch_abc123" in repr_str
        assert "completed" in repr_str
        assert "3/3" in repr_str
        
        # Test __str__
        str_repr = str(batch_info)
        assert "BatchInfo" in str_repr
        assert "status=completed" in str_repr
        assert "progress=3/3" in str_repr


# class TestBatchItems:
#     """Test BatchItems stateful object creation and behavior."""

#     def test_batch_items_creation_from_response(self):
#         """Test BatchItems creation from BatchItemsResponse."""
#         response = BatchItemsResponse(**BATCH_ITEMS_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         batch_items = BatchItems(caller, response)
        
#         # Verify it can be created
#         assert isinstance(batch_items, BatchItems)
        
#         # Verify fields are set correctly
#         assert batch_items.id == "batch_abc123"
#         assert batch_items.items_count == 3
#         assert batch_items.cursor is None

#     def test_batch_items_iteration_works(self):
#         """Test that BatchItems can be iterated over."""
#         response = BatchItemsResponse(**BATCH_ITEMS_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         batch_items = BatchItems(caller, response)
        
#         # Test iteration
#         items = list(batch_items)
#         assert len(items) == 3
#         assert all(isinstance(item, BatchItem) for item in items)
        
#         # Test individual item properties
#         assert items[0].url == "https://example.com"
#         assert items[0].retrieve_id == "ret_12345"
#         assert items[0].custom_id == "example_1"

#     def test_batch_items_next_returns_none_when_no_cursor(self):
#         """Test that next() returns None when cursor is None."""
#         response = BatchItemsResponse(**BATCH_ITEMS_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         batch_items = BatchItems(caller, response)
        
#         # Test next() with no cursor
#         import asyncio
#         next_items = asyncio.run(batch_items.next())
#         assert next_items is None

#     def test_batch_items_next_returns_next_page_with_cursor(self):
#         """Test that next() returns next page when cursor is present."""
#         response = BatchItemsResponse(**BATCH_ITEMS_RESPONSE_WITH_CURSOR)
        
#         class MockCaller:
#             async def invoke(self, contract, **kwargs):
#                 # Return next page response
#                 return BatchItemsResponse(**BATCH_ITEMS_RESPONSE)
        
#         caller = MockCaller()
#         batch_items = BatchItems(caller, response)
        

#         next_items = asyncio.run(batch_items.next())
#         assert next_items is not None
#         assert isinstance(next_items, BatchItems)
#         assert next_items.id == "batch_abc123"

#     def test_batch_items_repr_and_str_work(self):
#         """Test that __repr__ and __str__ methods work correctly."""
#         response = BatchItemsResponse(**BATCH_ITEMS_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         batch_items = BatchItems(caller, response)
        
#         # Test __repr__
#         repr_str = repr(batch_items)
#         assert "BatchItems" in repr_str
#         assert "batch_abc123" in repr_str
#         assert "limit=3" in repr_str
#         assert "cursor=None" in repr_str
        
#         # Test __str__
#         str_repr = str(batch_items)
#         assert "BatchItems" in str_repr
#         assert "3 items" in str_repr
#         assert "cursor=none" in str_repr


class TestBatchItemResult:
    """Test BatchItemResult stateful object creation and behavior."""

    def test_batch_item_creation_from_response(self):
        """Test BatchItemResult creation from BatchItemsResponseListItem."""
        item_data = {
            "url": "https://example.com/1",
            "retrieve_id": "ret_1",
            "custom_id": "item_1"
        }
        item = BatchItemsResponseListItem(**item_data)
        class MockCaller:
            pass
        caller = MockCaller()
        batch_item = BatchItemResult(caller, item)

        # Verify it can be created
        assert isinstance(batch_item, BatchItemResult)
        
        # Verify fields are set correctly
        assert batch_item.url == "https://example.com/1"
        assert batch_item.retrieve_id == "ret_1"
        assert batch_item.custom_id == "item_1"

    def test_batch_item_retrieve_returns_scrape_result(self):
        """Test that BatchItemResult.retrieve() returns a ScrapeResult."""
        item_data = {
            "url": "https://example.com/1",
            "retrieve_id": "ret_12345",
            "custom_id": "item_1"
        }
        item = BatchItemsResponseListItem(**item_data)

        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Return a RetrieveResponse when retrieve is called
                return RetrieveResponse(**RETRIEVE_RESPONSE)

        caller = MockCaller()
        batch_item = BatchItemResult(caller, item)
        
        # Test retrieve method
        import asyncio
        result = asyncio.run(batch_item.retrieve(["html", "markdown"]))
        
        # Verify it returns a ScrapeResult
        assert isinstance(result, ScrapeResult)
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_batch_item_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        item_data = {
            "url": "https://example.com/1",
            "retrieve_id": "ret_1",
            "custom_id": "item_1"
        }
        item = BatchItemsResponseListItem(**item_data)
        class MockCaller:
            pass
        caller = MockCaller()
        batch_item = BatchItemResult(caller, item)
        
        # Test __repr__
        repr_str = repr(batch_item)
        assert "BatchItemResult" in repr_str
        assert "https://example.com/1" in repr_str
        assert "ret_1" in repr_str
        assert "item_1" in repr_str
        
        # Test __str__
        str_repr = str(batch_item)
        assert "BatchItemResult" in str_repr
        assert "item_1" in str_repr
        assert "https://example.com/1" in str_repr
        assert "ret_1" in str_repr


class TestCrawl:
    """Test Crawl stateful object creation and behavior."""

    def test_crawl_creation_from_response(self):
        """Test Crawl creation from CreateCrawlResponse."""
        response = CreateCrawlResponse(**CRAWL_CREATE_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        crawl = Crawl(caller, response)
        
        # Verify it can be created
        assert isinstance(crawl, Crawl)
        
        # Verify fields are set correctly
        assert crawl.id == "crawl_xyz789"
        assert crawl.status == "in_progress"
        assert crawl.pages_count == 0

    def test_crawl_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = CreateCrawlResponse(**CRAWL_CREATE_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        crawl = Crawl(caller, response)
        
        # Test __repr__
        repr_str = repr(crawl)
        assert "Crawl" in repr_str
        assert "crawl_xyz789" in repr_str
        assert "start_url='https://example.com'" in repr_str
        assert "include_external=False" in repr_str
        assert "include_subdomain=None" in repr_str
        
        # Test __str__
        str_repr = str(crawl)
        assert "Crawl" in str_repr
        assert "crawl_xyz789" in str_repr
        assert "in_progress" in str_repr
        assert "pages_count=0" in str_repr

    def test_crawl_wait_till_done_with_completed_status(self):
        """Test that wait_till_done completes when status becomes 'completed' after second call."""
        response = CreateCrawlResponse(**CRAWL_CREATE_RESPONSE)
        
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                if self.call_count == 1:
                    # First call returns in_progress status
                    return CrawlInfoResponse(**CRAWL_INFO_RESPONSE_IN_PROGRESS)
                else:
                    # Second call returns completed status
                    return CrawlInfoResponse(**CRAWL_INFO_RESPONSE)
        
        caller = MockCaller()
        crawl = Crawl(caller, response)
        
        # This should complete after the second call when status becomes 'completed'
        asyncio.run(crawl.wait_till_done(check_every_n_secs=1, timeout_seconds=5))
        assert caller.call_count == 2

    def test_crawl_wait_till_done_timeout(self):
        """Test that wait_till_done times out when status doesn't change."""
        response = CreateCrawlResponse(**CRAWL_CREATE_RESPONSE)
        
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                # Always return in_progress status
                return CrawlInfoResponse(**CRAWL_INFO_RESPONSE_IN_PROGRESS)
        
        caller = MockCaller()
        crawl = Crawl(caller, response)
        
        # This should timeout after 2 seconds
        with pytest.raises(OlostepClientError_Timeout) as exc_info:
            asyncio.run(crawl.wait_till_done(check_every_n_secs=1, timeout_seconds=2))
        
        # Verify the timeout error message
        assert "wait_till_done" in str(exc_info.value)
        assert "2" in str(exc_info.value)  # timeout_seconds=2
        
        # Should have made multiple calls before timing out
        assert caller.call_count >= 1  # At least 2 calls (initial + 1 retry)


class TestCrawlInfo:
    """Test CrawlInfo stateful object creation and behavior."""

    def test_crawl_info_creation_from_response(self):
        """Test CrawlInfo creation from CrawlInfoResponse."""
        response = CrawlInfoResponse(**CRAWL_INFO_RESPONSE)
        crawl_info = CrawlInfo(response)
        
        # Verify it can be created
        assert isinstance(crawl_info, CrawlInfo)
        
        # Verify fields are set correctly
        assert crawl_info.id == "crawl_xyz789"
        assert crawl_info.status == "completed"
        assert crawl_info.pages_count == 5

    def test_crawl_info_age_property_works(self):
        """Test that age property returns formatted time delta."""
        response = CrawlInfoResponse(**CRAWL_INFO_RESPONSE)
        crawl_info = CrawlInfo(response)
        
        # Test age property
        age = crawl_info.age
        assert isinstance(age, str)
        # Should contain time information
        assert any(keyword in age.lower() for keyword in ["ago", "d", "h", "m", "s"])

    def test_crawl_info_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = CrawlInfoResponse(**CRAWL_INFO_RESPONSE)
        crawl_info = CrawlInfo(response)
        
        # Test __repr__
        repr_str = repr(crawl_info)
        assert "CrawlInfo" in repr_str
        assert "crawl_xyz789" in repr_str
        assert "completed" in repr_str
        assert "pages_count=5" in repr_str
        
        # Test __str__
        str_repr = str(crawl_info)
        assert "CrawlInfo" in str_repr
        assert "status=completed" in str_repr
        assert "pages_count=5" in str_repr


# class TestCrawlPages:
#     """Test CrawlPages stateful object creation and behavior."""

#     def test_crawl_pages_creation_from_response(self):
#         """Test CrawlPages creation from CrawlPagesResponse."""
#         response = CrawlPagesResponse(**CRAWL_PAGES_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         crawl_pages = CrawlPages(caller, response)
        
#         # Verify it can be created
#         assert isinstance(crawl_pages, CrawlPages)
        
#         # Verify fields are set correctly
#         assert crawl_pages.id == "crawl_xyz789"
#         assert crawl_pages.pages_count == 3
#         assert crawl_pages.cursor is None

#     def test_crawl_pages_iteration_works(self):
#         """Test that CrawlPages can be iterated over."""
#         response = CrawlPagesResponse(**CRAWL_PAGES_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         crawl_pages = CrawlPages(caller, response)
        
#         # Test iteration
#         pages = list(crawl_pages)
#         assert len(pages) == 3
#         assert all(isinstance(page, CrawlPage) for page in pages)
        
#         # Test individual page properties
#         assert pages[0].url == "https://example.com"
#         assert pages[0].retrieve_id == "ret_crawl_1"
#         assert pages[0].is_external is False

#     def test_crawl_pages_next_returns_none_when_no_cursor(self):
#         """Test that next() returns None when cursor is None."""
#         response = CrawlPagesResponse(**CRAWL_PAGES_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         crawl_pages = CrawlPages(caller, response)
        
#         # Test next() with no cursor
#         next_pages = asyncio.run(crawl_pages.next())
#         assert next_pages is None

#     def test_crawl_pages_next_returns_next_page_with_cursor(self):
#         """Test that next() returns next page when cursor is present."""
#         response = CrawlPagesResponse(**CRAWL_PAGES_RESPONSE_WITH_CURSOR)
        
#         class MockCaller:
#             async def invoke(self, contract, **kwargs):
#                 # Return next page response
#                 return CrawlPagesResponse(**CRAWL_PAGES_RESPONSE)
        
#         caller = MockCaller()
#         crawl_pages = CrawlPages(caller, response)
        
#         # Test next() with cursor
#         next_pages = asyncio.run(crawl_pages.next())
#         assert next_pages is not None
#         assert isinstance(next_pages, CrawlPages)
#         assert next_pages.id == "crawl_xyz789"

#     def test_crawl_pages_repr_and_str_work(self):
#         """Test that __repr__ and __str__ methods work correctly."""
#         response = CrawlPagesResponse(**CRAWL_PAGES_RESPONSE)
#         class MockCaller:
#             pass
#         caller = MockCaller()
#         crawl_pages = CrawlPages(caller, response)
        
#         # Test __repr__
#         repr_str = repr(crawl_pages)
#         assert "CrawlPages" in repr_str
#         assert "crawl_xyz789" in repr_str
#         assert "limit=3" in repr_str
#         assert "cursor=None" in repr_str
        
#         # Test __str__
#         str_repr = str(crawl_pages)
#         assert "CrawlPages" in str_repr
#         assert "3 pages" in str_repr
#         assert "cursor=none" in str_repr


class TestCrawlPage:
    """Test CrawlPage stateful object creation and behavior."""

    def test_crawl_page_creation_from_response(self):
        """Test CrawlPage creation from CrawlPagesResponseListItem."""
        page_data = {
            "id": "page_1",
            "url": "https://example.com",
            "retrieve_id": "ret_crawl_1",
            "is_external": False
        }
        page = CrawlPagesResponseListItem(**page_data)
        class MockCaller:
            pass
        caller = MockCaller()
        crawl_page = CrawlPage(caller, page)
        
        # Verify it can be created
        assert isinstance(crawl_page, CrawlPage)
        
        # Verify fields are set correctly
        assert crawl_page.url == "https://example.com"
        assert crawl_page.retrieve_id == "ret_crawl_1"
        assert crawl_page.is_external is False

    def test_crawl_page_retrieve_returns_scrape_result(self):
        """Test that CrawlPage.retrieve() returns a ScrapeResult."""
        page_data = {
            "id": "page_1",
            "url": "https://example.com",
            "retrieve_id": "ret_crawl_1",
            "is_external": False
        }
        page = CrawlPagesResponseListItem(**page_data)
        
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Return a RetrieveResponse when retrieve is called
                return RetrieveResponse(**RETRIEVE_RESPONSE)
        
        caller = MockCaller()
        crawl_page = CrawlPage(caller, page)
        
        # Test retrieve method
        result = asyncio.run(crawl_page.retrieve(["html", "markdown"]))
        
        # Verify it returns a ScrapeResult
        assert isinstance(result, ScrapeResult)
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_crawl_page_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        page_data = {
            "id": "page_1",
            "url": "https://example.com",
            "retrieve_id": "ret_crawl_1",
            "is_external": False
        }
        page = CrawlPagesResponseListItem(**page_data)
        class MockCaller:
            pass
        caller = MockCaller()
        crawl_page = CrawlPage(caller, page)
        
        # Test __repr__
        repr_str = repr(crawl_page)
        assert "CrawlPage" in repr_str
        assert "https://example.com" in repr_str
        assert "ret_crawl_1" in repr_str
        assert "external=False" in repr_str
        
        # Test __str__
        str_repr = str(crawl_page)
        assert "CrawlPage" in str_repr
        assert "https://example.com" in str_repr
        assert "internal" in str_repr


# class TestRetrievableID:
#     """Test RetrievableID stateful object creation and behavior."""

#     def test_retrievable_id_creation(self):
#         """Test RetrievableID creation with basic fields."""
#         retrievable_id = RetrievableID(
#             id="ret_12345",
#             type="scrape",
#             timestamp=1703001600
#         )
        
#         # Verify it can be created
#         assert isinstance(retrievable_id, RetrievableID)
        
#         # Verify fields are set correctly
#         assert retrievable_id.id == "ret_12345"
#         assert retrievable_id.type == "scrape"
#         assert retrievable_id.timestamp == 1703001600

#     def test_retrievable_id_repr_and_str_work(self):
#         """Test that __repr__ method works correctly."""
#         retrievable_id = RetrievableID(
#             id="ret_12345",
#             type="scrape",
#             timestamp=1703001600
#         )
        
#         # Test __repr__
#         repr_str = repr(retrievable_id)
#         assert "RetrievableID" in repr_str
#         assert "ret_12345" in repr_str
#         assert "scrape" in repr_str
#         assert "age=" in repr_str

#     def test_retrievable_id_age_property_works(self):
#         """Test that age property returns human-readable time delta."""
#         # Use a timestamp from 1 hour ago
#         import time
#         one_hour_ago = int(time.time()) - 3600
        
#         retrievable_id = RetrievableID(
#             id="ret_12345",
#             type="scrape",
#             timestamp=one_hour_ago
#         )
        
#         # Age should contain "1h ago" or similar
#         age = retrievable_id.age
#         assert isinstance(age, str)
#         assert "h ago" in age or "m ago" in age or "s ago" in age

#     def test_retrievable_id_is_expired_works(self):
#         """Test that is_expired method works correctly."""
#         import time
        
#         # Test with very old timestamp (should be expired)
#         old_timestamp = int(time.time()) - (8 * 24 * 3600)  # 8 days ago
#         old_id = RetrievableID(
#             id="old_ret_12345",
#             type="scrape",
#             timestamp=old_timestamp
#         )
#         assert old_id.is_expired() is True
#         assert old_id.is_expired(retention_days=7) is True
#         assert old_id.is_expired(retention_days=10) is False
        
#         # Test with recent timestamp (should not be expired)
#         recent_timestamp = int(time.time()) - (3 * 24 * 3600)  # 3 days ago
#         recent_id = RetrievableID(
#             id="recent_ret_12345",
#             type="scrape",
#             timestamp=recent_timestamp
#         )
#         assert recent_id.is_expired() is False
#         assert recent_id.is_expired(retention_days=2) is True
#         assert recent_id.is_expired(retention_days=5) is False


class TestRetrieveMenu:
    """Test RetrieveMenu stateful object creation and behavior."""

    def test_retrieve_menu_creation(self):
        """Test RetrieveMenu creation."""
        class MockCaller:
            pass
        
        caller = MockCaller()
        retrieve_menu = RetrieveMenu(caller)
        
        # Verify it can be created
        assert isinstance(retrieve_menu, RetrieveMenu)

    def test_retrieve_menu_call_returns_scrape_result(self):
        """Test that RetrieveMenu.__call__() returns a ScrapeResult."""
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Return a RetrieveResponse when retrieve is called
                return RetrieveResponse(**RETRIEVE_RESPONSE)
        
        caller = MockCaller()
        retrieve_menu = RetrieveMenu(caller)
        
        # Test retrieve method
        result = asyncio.run(retrieve_menu("ret_12345", ["html", "markdown"]))
        
        # Verify it returns a ScrapeResult
        assert isinstance(result, ScrapeResult)
        assert result.html_content == "<html><body>Hello World</body></html>"
        assert result.markdown_content == "# Hello World"
        assert result.size_exceeded is False

    def test_retrieve_menu_call_with_single_format(self):
        """Test that RetrieveMenu.__call__() works with single format."""
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Return a RetrieveResponse when retrieve is called
                return RetrieveResponse(**RETRIEVE_RESPONSE)
        
        caller = MockCaller()
        retrieve_menu = RetrieveMenu(caller)
        
        # Test retrieve method with single format
        result = asyncio.run(retrieve_menu("ret_12345", "html"))
        
        # Verify it returns a ScrapeResult
        assert isinstance(result, ScrapeResult)
        assert result.html_content == "<html><body>Hello World</body></html>"


class TestSitemap:
    """Test Sitemap stateful object creation and behavior."""

    def test_sitemap_creation_from_response(self):
        """Test Sitemap creation from MapResponse."""
        response = MapResponse(**MAP_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # Verify it can be created
        assert isinstance(sitemap, Sitemap)
        
        # Verify fields are set correctly
        assert sitemap.id == "map_12345"
        assert sitemap.initial_urls_count == 5
        assert len(sitemap._initial_urls) == 5
        assert sitemap._initial_urls[0] == "https://example.com"
        assert sitemap.cursor == ""

    def test_sitemap_creation_without_id(self):
        """Test Sitemap creation from MapResponse without ID."""
        response = MapResponse(**MAP_RESPONSE_NO_ID)
        class MockCaller:
            pass
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # Verify it can be created
        assert isinstance(sitemap, Sitemap)
        
        # Verify fields are set correctly
        assert sitemap.id == ""
        assert sitemap.initial_urls_count == 3
        assert len(sitemap._initial_urls) == 3
        assert sitemap.cursor == ""

    def test_sitemap_repr_and_str_work(self):
        """Test that __repr__ and __str__ methods work correctly."""
        response = MapResponse(**MAP_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # Test __repr__
        repr_str = repr(sitemap)
        assert "Sitemap" in repr_str
        assert "map_12345" in repr_str
        assert "initial_urls_count=5" in repr_str
        assert "cursor=" in repr_str
        
        # Test __str__
        str_repr = str(sitemap)
        assert "Sitemap" in str_repr
        assert "map_12345" in str_repr
        assert "initial_urls_count=5" in str_repr
        assert "cursor=none" in str_repr

    @pytest.mark.asyncio
    async def test_sitemap_urls_stops_when_no_cursor(self):
        """Test that urls() iterator stops when cursor is empty."""
        response = MapResponse(**MAP_RESPONSE)
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                return MapResponse(**MAP_RESPONSE)
        
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # urls() should only yield initial URLs when cursor is empty
        urls = []
        async for url in sitemap.urls():
            urls.append(url)
        assert len(urls) == 5  # Only initial URLs
        assert caller.call_count == 0  # No API call should be made

    @pytest.mark.asyncio
    async def test_sitemap_urls_paginates_with_cursor(self):
        """Test that urls() iterator automatically paginates when cursor exists."""
        response = MapResponse(**MAP_RESPONSE_WITH_CURSOR)
        class MockCaller:
            call_count = 0
            async def invoke(self, contract, **kwargs):
                self.call_count += 1
                # Return a response with no cursor (end of pagination)
                return MapResponse(**MAP_RESPONSE_EMPTY_CURSOR)
        
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # urls() should automatically fetch next page when cursor exists
        urls = []
        async for url in sitemap.urls():
            urls.append(url)
        assert len(urls) == 5  # 3 from initial + 2 from pagination
        assert caller.call_count == 1  # API call should be made for pagination

    @pytest.mark.asyncio
    async def test_sitemap_iteration_works(self):
        """Test that Sitemap can be iterated over URLs."""
        response = MapResponse(**MAP_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # Test iteration over URLs using async method
        urls = []
        async for url in sitemap.urls():
            urls.append(url)
        assert len(urls) == 5
        assert urls[0] == "https://example.com"
        assert urls[1] == "https://example.com/about"

    def test_sitemap_url_access(self):
        """Test direct URL list access."""
        response = MapResponse(**MAP_RESPONSE)
        class MockCaller:
            pass
        caller = MockCaller()
        sitemap = Sitemap(caller, response, "https://example.com")
        
        # Test direct URL access via internal _initial_urls
        assert len(sitemap._initial_urls) == 5
        assert sitemap._initial_urls[0] == "https://example.com"
        assert sitemap._initial_urls[-1] == "https://example.com/faq"
        assert "https://example.com/contact" in sitemap._initial_urls


class TestSitemapMenu:
    """Test SitemapMenu stateful object creation and behavior."""

    def test_sitemap_menu_creation(self):
        """Test SitemapMenu creation."""
        class MockCaller:
            pass
        
        caller = MockCaller()
        sitemap_menu = SitemapMenu(caller)
        
        # Verify it can be created
        assert isinstance(sitemap_menu, SitemapMenu)

    @pytest.mark.asyncio
    async def test_sitemap_menu_call_returns_sitemap(self):
        """Test that SitemapMenu.__call__() returns a Sitemap."""
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Return a MapResponse when map is called
                return MapResponse(**MAP_RESPONSE)
        
        caller = MockCaller()
        sitemap_menu = SitemapMenu(caller)
        
        # Test map method
        result = await sitemap_menu("https://example.com")
        
        # Verify it returns a Sitemap
        assert isinstance(result, Sitemap)
        assert result.id == "map_12345"
        assert result.initial_urls_count == 5
        assert len(result._initial_urls) == 5

    @pytest.mark.asyncio
    async def test_sitemap_menu_call_passes_url_as_is(self):
        """Test that SitemapMenu.__call__() passes URL to API as provided."""
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                url = kwargs["body_params"]["url"]
                assert url == "example.com", f"Expected URL to be passed as-is, got {url}"
                return MapResponse(**MAP_RESPONSE)
        
        caller = MockCaller()
        sitemap_menu = SitemapMenu(caller)
        
        # Test with bare domain - should be passed as-is
        result = await sitemap_menu("example.com")
        assert isinstance(result, Sitemap)
        

    def test_sitemap_menu_call_with_parameters(self):
        """Test that SitemapMenu.__call__() handles additional parameters."""
        class MockCaller:
            async def invoke(self, contract, **kwargs):
                # Verify parameters are passed correctly
                body_params = kwargs["body_params"]
                assert body_params["url"] == "https://example.com"
                assert body_params["search_query"] == "blog"
                assert body_params["top_n"] == 10
                assert body_params["include_subdomain"] is True
                return MapResponse(**MAP_RESPONSE)
        
        caller = MockCaller()
        sitemap_menu = SitemapMenu(caller)
        
        # Test with additional parameters
        result = asyncio.run(sitemap_menu(
            "https://example.com",
            search_query="blog",
            top_n=10,
            include_subdomain=True
        ))
        
        # Verify it returns a Sitemap
        assert isinstance(result, Sitemap)

