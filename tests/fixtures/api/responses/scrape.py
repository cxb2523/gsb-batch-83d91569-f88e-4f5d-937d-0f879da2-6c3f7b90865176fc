# CreateScrapeResponse with basic content
CREATE_SCRAPE_RESPONSE = {
    "id": "scrape_123",
    "object": "scrape",
    "created": 1703001600,
    "retrieve_id": "ret_123",
    "url": "https://example.com",
    "result": {
        "html_content": "<html><body>Hello World</body></html>",
        "markdown_content": "# Hello World",
        "size_exceeded": False
    }
}

# GetScrapeResponse with content
GET_SCRAPE_RESPONSE = {
    "id": "scrape_456",
    "object": "scrape", 
    "created": 1703001600,
    "retrieve_id": "ret_456",
    "url": "https://example.com",
    "result": {
        "html_content": "<html><body>Hello World</body></html>",
        "markdown_content": "# Hello World",
        "size_exceeded": False
    }
}

# RetrieveResponse with content
RETRIEVE_RESPONSE = {
    "html_content": "<html><body>Hello World</body></html>",
    "markdown_content": "# Hello World",
    "size_exceeded": False
}