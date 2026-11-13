# =============================================================================
# BATCH RESPONSE FIXTURES
# =============================================================================

BATCH_CREATE_RESPONSE = {
    "id": "batch_abc123",
    "object": "batch",
    "created": 1703001600,
    "status": "in_progress",
    "total_urls": 3,
    "completed_urls": 0,
    "start_date": "2023-12-20T00:00:00Z"
}

BATCH_INFO_RESPONSE = {
    "id": "batch_abc123",
    "status": "completed",
    "created": 1703001600,
    "total_urls": 3,
    "completed_urls": 3,
    "number_retried": 0,
    "parser": "none",
    "start_date": "2023-12-20T00:00:00Z"
}

BATCH_ITEMS_RESPONSE = {
    "id": "batch_abc123",
    "status": "completed",
    "items": [
        {
            "url": "https://example.com",
            "retrieve_id": "ret_12345",
            "custom_id": "example_1"
        },
        {
            "url": "https://httpbin.org/html",
            "retrieve_id": "ret_67890",
            "custom_id": "httpbin_1"
        },
        {
            "url": "https://httpbin.org/json",
            "retrieve_id": "ret_11111",
            "custom_id": "httpbin_2"
        }
    ],
    "items_count": 3,
    "cursor": None
}

BATCH_ITEMS_RESPONSE_WITH_CURSOR = {
    "id": "batch_abc123",
    "status": "completed",
    "items": [
        {
            "url": "https://example.com",
            "retrieve_id": "ret_12345",
            "custom_id": "example_1"
        }
    ],
    "items_count": 5,
    "cursor": 123
}

BATCH_INFO_RESPONSE_IN_PROGRESS = {
    "id": "batch_abc123",
    "status": "in_progress",
    "created": 1703001600,
    "total_urls": 3,
    "completed_urls": 1,
    "number_retried": 0,
    "parser": "none",
    "start_date": "2023-12-20T00:00:00Z"
}

BATCH_INFO_RESPONSE_FAILED = {
    "id": "batch_abc123",
    "status": "completed",
    "created": 1703001600,
    "total_urls": 3,
    "completed_urls": 2,
    "number_retried": 1,
    "parser": "none",
    "start_date": "2023-12-20T00:00:00Z"
}
