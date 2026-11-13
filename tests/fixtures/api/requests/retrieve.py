from olostep.models.request import RetrieveFormat

########################################
# --- Retrieve Request Fixtures ---
########################################


RETRIEVE_ID = {
    "param_name": "retrieve_id",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value, acquired from scrape/crawl/batch responses
        "invalids": ["non_existing_retrieve_id", "invalid_id", 1000],
    },
}

FORMATS = {
    "param_name": "formats",
    "param_type": list[RetrieveFormat],
    "param_values": {
        "valids": [r.value for r in RetrieveFormat],
        "invalids": [
            ["invalid_format"],
            [1000],
            "not_a_list",
            {"invalid": "object"},
        ],
    },
}

MINIMAL_REQUEST_QUERY = {
    "retrieve_id": "test_retrieve_id",  # Will be replaced with actual ID
    "formats": [RetrieveFormat.HTML],
}

# Test data for different content types
SCRAPE_TEST_URL = "https://example.com"
CRAWL_TEST_URL = "https://www.bbc.com/"
BATCH_TEST_URLS = [
    "https://www.bbc.com/",
    "https://www.cnn.com/",
    "https://www.reuters.com/",
]


