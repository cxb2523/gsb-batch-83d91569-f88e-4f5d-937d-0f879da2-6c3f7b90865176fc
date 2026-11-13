# Searches response fixture with anonymized sample data

SEARCHES_CREATE_RESPONSE = {
    "id": "search_9bi0sbj9xa",
    "object": "search",
    "created": 1760327323,
    "metadata": {},
    "query": "What's going on with OpenAI's Sora shutting down?",
    "credits_consumed": 10,
    "result": {
        "json_content": "...",
        "json_hosted_url": "https://olostep-storage.s3.us-east-1.amazonaws.com/search_9bi0sbj9xa.json",
        "size_exceeded": False,
        "credits_consumed": 10,
        "links": [
            {
                "url": "https://www.bbc.com/news/articles/c3w3e467ewqo",
                "title": "OpenAI to shut down Sora video platform",
                "description": "OpenAI says it will discontinue its Sora app...",
                "markdown_content": "# OpenAI to shut down Sora video platform\n\nOpenAI says it will discontinue...",
                "html_content": None,
            },
            {
                "url": "https://www.reddit.com/r/OutOfTheLoop/comments/1s2u847/whats_going_on_with_openais_sora_shutting_down/",
                "title": "What's going on with OpenAI's Sora shutting down?",
                "description": "Reddit thread discussing the shutdown.",
                "markdown_content": "# What's going on with OpenAI's Sora shutting down?\n\n...",
                "html_content": None,
            },
        ],
    },
}

SEARCHES_CREATE_RESPONSE_NO_SCRAPE = {
    "id": "search_abc123",
    "object": "search",
    "created": 1760327000,
    "metadata": {},
    "query": "Best Answer Engine Optimization startups",
    "credits_consumed": 5,
    "result": {
        "json_content": None,
        "json_hosted_url": None,
        "size_exceeded": False,
        "credits_consumed": 5,
        "links": [
            {
                "url": "https://example.com/aeo-startups",
                "title": "Top AEO Startups in 2025",
                "description": "A roundup of the best Answer Engine Optimization startups...",
            },
        ],
    },
}
