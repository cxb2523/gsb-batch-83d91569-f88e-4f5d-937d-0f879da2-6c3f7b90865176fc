"""
Tests for the async client with fake transport and menu items.
"""


import pytest

from olostep.clients.async_client import AsyncOlostep
from olostep.frontend.batch_menu import BatchMenu
from olostep.frontend.crawl_menu import CrawlMenu
from olostep.frontend.retrieve_menu import RetrieveMenu
from olostep.frontend.scrape_menu import ScrapeMenu
from olostep.frontend.sitemap_menu import SitemapMenu


class TestOlostepClient:
    """Test the main AsyncOlostep functionality."""
    
    def test_client_initialization(self, async_client_fake: AsyncOlostep) -> None:
        """Test that client initializes with all menu items."""
        assert hasattr(async_client_fake, 'scrapes')
        assert hasattr(async_client_fake, 'batches')
        assert hasattr(async_client_fake, 'crawls')
        assert hasattr(async_client_fake, 'maps')
        assert hasattr(async_client_fake, 'retrieve')
        
        # Verify menu items are the correct types
        assert isinstance(async_client_fake.scrapes, ScrapeMenu)
        assert isinstance(async_client_fake.batches, BatchMenu)
        assert isinstance(async_client_fake.crawls, CrawlMenu)
        assert isinstance(async_client_fake.maps, SitemapMenu)
        assert isinstance(async_client_fake.retrieve, RetrieveMenu)
    
    def test_client_context_manager(self, async_client_fake: AsyncOlostep) -> None:
        """Test client as context manager."""
        import asyncio
        
        async def _test_context():
            async with async_client_fake as client:
                assert client is async_client_fake
                # Test that we can access menu items within context
                assert hasattr(client, 'scrapes')
                assert hasattr(client, 'batches')
        
        asyncio.run(_test_context())
    
    def test_client_with_fake_transport(self, fake_transport) -> None:
        """Test client initialization with fake transport."""
        client = AsyncOlostep(_transport=fake_transport)
        assert client._transport is fake_transport
        assert hasattr(client, 'scrapes')
        assert hasattr(client, 'batches')
    
    def test_client_with_api_key(self) -> None:
        """Test client initialization with API key."""
        client = AsyncOlostep(api_key="test_key")
        assert client._api_key == "test_key"
        assert hasattr(client, 'scrapes')
    
    def test_client_with_base_url(self) -> None:
        """Test client initialization with custom base URL."""
        client = AsyncOlostep(api_key="test_key", _base_url="https://custom.api.com")
        assert client._base_url == "https://custom.api.com"
        assert hasattr(client, 'scrapes')
    
    def test_client_without_api_key_raises_error(self) -> None:
        """Test that client raises error when no API key is provided."""
        from unittest.mock import patch
        
        # Patch the API_KEY_ENV constant where it's imported in the client module
        with patch('olostep.clients.async_client.API_KEY_ENV', None):
            with pytest.raises(ValueError, match="API key is required when using the real HTTP transport"):
                AsyncOlostep()
    
    def test_client_menu_access(self, async_client_fake: AsyncOlostep) -> None:
        """Test that all menu items are accessible and have expected methods."""
        # Test scrape menu
        assert hasattr(async_client_fake.scrapes, 'create')
        assert hasattr(async_client_fake.scrapes, 'get')
        
        # Test batch menu
        assert hasattr(async_client_fake.batches, 'create')
        assert hasattr(async_client_fake.batches, 'info')
        assert hasattr(async_client_fake.batches, 'items')
        
        # Test crawl menu
        assert hasattr(async_client_fake.crawls, 'create')
        assert hasattr(async_client_fake.crawls, 'info')
        assert hasattr(async_client_fake.crawls, 'pages')
        
        # Test map menu
        assert hasattr(async_client_fake.maps, 'create')
        
        # Test retrieve menu
        assert hasattr(async_client_fake.retrieve, 'get')


class TestScrapeMenu:
    """Test the ScrapeMenu functionality."""
    
    @pytest.mark.asyncio
    async def test_scrape_basic(self, async_client_fake: AsyncOlostep) -> None:
        """Test basic scraping functionality."""
        # This test will use the fake transport
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_scrape_with_formats(self, async_client_fake: AsyncOlostep) -> None:
        """Test scraping with different formats."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_scrape_with_country(self, async_client_fake: AsyncOlostep) -> None:
        """Test scraping with country parameter."""
        pytest.skip("Test implementation needed")


class TestBatchMenu:
    """Test the BatchMenu functionality."""
    
    @pytest.mark.asyncio
    async def test_batch_single_url(self, async_client_fake: AsyncOlostep) -> None:
        """Test batch processing with single URL."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_batch_multiple_urls(self, async_client_fake: AsyncOlostep) -> None:
        """Test batch processing with multiple URLs."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_batch_with_custom_ids(self, async_client_fake: AsyncOlostep) -> None:
        """Test batch processing with custom IDs."""
        pytest.skip("Test implementation needed")


class TestCrawlMenu:
    """Test the CrawlMenu functionality."""
    
    @pytest.mark.asyncio
    async def test_crawl_basic(self, async_client_fake: AsyncOlostep) -> None:
        """Test basic crawling functionality."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_crawl_with_depth(self, async_client_fake: AsyncOlostep) -> None:
        """Test crawling with depth limits."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_crawl_with_filters(self, async_client_fake: AsyncOlostep) -> None:
        """Test crawling with URL filters."""
        pytest.skip("Test implementation needed")


class TestSitemapMenu:
    """Test the SitemapMenu functionality."""
    
    @pytest.mark.asyncio
    async def test_sitemap_basic(self, async_client_fake: AsyncOlostep) -> None:
        """Test basic sitemap creation."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_sitemap_with_search(self, async_client_fake: AsyncOlostep) -> None:
        """Test sitemap with search query."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_sitemap_with_filters(self, async_client_fake: AsyncOlostep) -> None:
        """Test sitemap with URL filters."""
        pytest.skip("Test implementation needed")


class TestRetrieveMenu:
    """Test the RetrieveMenu functionality."""
    
    @pytest.mark.asyncio
    async def test_retrieve_basic(self, async_client_fake: AsyncOlostep) -> None:
        """Test basic content retrieval."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_retrieve_multiple_formats(self, async_client_fake: AsyncOlostep) -> None:
        """Test retrieval with multiple formats."""
        pytest.skip("Test implementation needed")
    
    @pytest.mark.asyncio
    async def test_retrieve_list_ids(self, async_client_fake: AsyncOlostep) -> None:
        """Test listing retrievable IDs."""
        pytest.skip("Test implementation needed")

