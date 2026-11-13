# =============================================================================
# MAP RESPONSE FIXTURES
# =============================================================================

MAP_RESPONSE = {
    "urls_count": 5,
    "urls": [
        "https://example.com",
        "https://example.com/about",
        "https://example.com/contact",
        "https://example.com/blog",
        "https://example.com/faq"
    ],
    "id": "map_12345",
    "cursor": None
}

MAP_RESPONSE_WITH_CURSOR = {
    "urls_count": 10,
    "urls": [
        "https://example.com/page6",
        "https://example.com/page7",
        "https://example.com/page8"
    ],
    "id": "map_12345",
    "cursor": "cursor_456"
}

MAP_RESPONSE_NO_ID = {
    "urls_count": 3,
    "urls": [
        "https://example.com",
        "https://example.com/about",
        "https://example.com/contact"
    ],
    "id": None,
    "cursor": None
}

MAP_RESPONSE_EMPTY_CURSOR = {
    "urls_count": 2,
    "urls": [
        "https://example.com/final1",
        "https://example.com/final2"
    ],
    "id": "map_12345",
    "cursor": ""
}


