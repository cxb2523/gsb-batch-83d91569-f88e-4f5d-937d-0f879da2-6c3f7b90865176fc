# =============================================================================
# CRAWL RESPONSE FIXTURES
# =============================================================================

CRAWL_CREATE_RESPONSE = {
    "id": "crawl_xyz789",
    "object": "crawl",
    "created": 1703001600,
    "status": "in_progress",
    "start_date": "2023-12-20T00:00:00Z",
    "start_url": "https://example.com",
    "include_external": False,
    "pages_count": 0
}

CRAWL_INFO_RESPONSE = {
    "id": "crawl_xyz789",
    "status": "completed",
    "created": 1703001600,
    "start_date": "2023-12-20T00:00:00Z",
    "start_url": "https://example.com",
    "include_external": False,
    "pages_count": 5
}

CRAWL_INFO_RESPONSE_IN_PROGRESS = {
    "id": "crawl_xyz789",
    "status": "in_progress",
    "created": 1703001600,
    "start_date": "2023-12-20T00:00:00Z",
    "start_url": "https://example.com",
    "include_external": False,
    "pages_count": 2
}

CRAWL_PAGES_RESPONSE = {
    "id": "crawl_xyz789",
    "object": "crawl",
    "status": "completed",
    "search_query": None,
    "pages_count": 3,
    "pages": [
        {
            "id": "page_1",
            "url": "https://example.com",
            "retrieve_id": "ret_crawl_1",
            "is_external": False
        },
        {
            "id": "page_2",
            "url": "https://example.com/about",
            "retrieve_id": "ret_crawl_2",
            "is_external": False
        },
        {
            "id": "page_3",
            "url": "https://example.com/contact",
            "retrieve_id": "ret_crawl_3",
            "is_external": False
        }
    ],
    "metadata": {
        "external_urls": [],
        "failed_urls": []
    },
    "cursor": None
}

CRAWL_PAGES_RESPONSE_WITH_CURSOR = {
    "id": "crawl_xyz789",
    "object": "crawl",
    "status": "completed",
    "search_query": None,
    "pages_count": 5,
    "pages": [
        {
            "id": "page_4",
            "url": "https://example.com",
            "retrieve_id": "ret_crawl_1",
            "is_external": False
        }
    ],
    "metadata": {
        "external_urls": [],
        "failed_urls": []
    },
    "cursor": 456
}
