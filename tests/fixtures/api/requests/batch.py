from olostep.models.request import BatchItemsQueryStatus, LinksOnPage

########################################
# --- Create Batch Request Fixtures ---
########################################


ITEMS = {
    "param_name": "items",
    "param_type": list,
    "param_values": {
        "valids": [
            [{"url": "https://example.com", "custom_id": "item1"}],
            [
                {"url": "https://example1.com", "custom_id": "item1"},
                {"url": "https://example2.com", "custom_id": "item2"},
            ],
            [
                {"url": "https://example1.com", "custom_id": "item1"},
                {"url": "https://example2.com", "custom_id": "item2"},
                {"url": "https://example3.com", "custom_id": "item3"},
            ],
        ],
        "invalids": [
            [],  # Empty list should be invalid
            [{"url": "invalid_url", "custom_id": "item1"}],  # Invalid URL
            [{"url": "https://example.com", "wrong_key":"string"}],  # Missing custom_id is OK, but test with it
            [{"custom_id": "item1"}],  # Missing URL
            "not_a_list",
            {"invalid": "object"},
        ],
    },
}

MINIMAL_REQUEST_BODY = {
    "items": [
        {"url": "https://example.com", "custom_id": "item1"},
        {"url": "https://http.cat/200", "custom_id": "item2"},
    ]
}

COUNTRY = {
    "param_name": "country",
    "param_type": str,
    "param_values": {
        # Node countries the API actually accepts (see scrape fixture).
        "valids": [
            "US", "CA", "GB", "IT", "IN", "RU", "JP", "MX", "AU",
            "ID", "UA", "MY", "PH", "SG", "KR", "TW", "TH", "RANDOM",
        ],
        "invalids": ["INVALID", "XX", 1000, {"invalid": "object"}],
    },
}

PARSER = {
    "param_name": "parser",
    "param_type": dict,
    "param_values": {
        "valids": [
            {"id": "@olostep/google-search"},
        ],
        "invalids": [
            {"config": {"extract_images": True}},  # Missing id
            {"id": "@olostep/google-search", "invalid_field": "value"},
            "not_a_dict",
            1000,
        ],
    },
}

LINKS_ON_PAGE = {
    "param_name": "links_on_page",
    "param_type": LinksOnPage,
    "param_values": {
        "valids": [
            {},
            {"absolute_links": False},
            {"include_links": ["*.pdf", "/blog/*"]},
            {"exclude_links": ["/private/*"]},
            {"query_to_order_links_by": "example query"},
            {
                "absolute_links": True,
                "include_links": ["*.html"],
                "exclude_links": ["*.jpg"],
                "query_to_order_links_by": "docs"
            },
        ],
        "invalids": [
            "invalid",
            1000,
            {"include_links": "not-a-list"},  # include_links should be a list
            {"absolute_links": "invalid_bool"},  # absolute_links should be bool
            {"include_links": [123]},         # include_links should be list[str]
        ],
    },
}

# Pages that scrape quickly and reliably: the workflow test checks create -> status -> pagination,
# not how hard a site is to scrape. Bot-protected news homepages made the batch take ~18 min
# and drop URLs, so the test timed out at 300s.
WORKFLOW_REQUEST_BODY = {
    "items": [
        {"url": "https://example.com/", "custom_id": "example"},
        {"url": "https://www.olostep.com/", "custom_id": "olostep_home"},
        {"url": "https://docs.olostep.com/", "custom_id": "olostep_docs"},
        {"url": "https://en.wikipedia.org/wiki/Web_scraping", "custom_id": "wikipedia"},
        {"url": "https://httpbin.org/html", "custom_id": "httpbin"},
    ],
    # "country": "RANDOM",
}


########################################
# --- Get Batch Info Request Fixtures ---
########################################

GET_BATCH_INFO_REQUEST_ID = {
    "param_name": "batch_id",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value,
        "invalids": ["non_existing_batch_id"],
    },
}


########################################
# --- Get Batch Items Request Fixtures ---
########################################

GET_BATCH_ITEMS_REQUEST_ID = {
    "param_name": "batch_id",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value,
        "invalids": ["non_existing_batch_id"],
    },
}

STATUS = {
    "param_name": "status",
    "param_type": str,
    "param_values": {
        "valids": [s.value for s in BatchItemsQueryStatus],
        "invalids": ["invalid_status", "INVALID", 1000, {"invalid": "object"}],
    },
}

CURSOR = {
    "param_name": "cursor",
    "param_type": int,
    "param_values": {
        # "valids": is a dynamic value, acquired as an API response after sending a limit parameter
        "invalids": ["ten", {"invalid": "object"}, []],
    },
}

LIMIT = {
    "param_name": "limit",
    "param_type": int,
    "param_values": {
        # "valids": is a dynamic value, it is dependant on the number of pages requested originally
        "invalids": ["ten", {"invalid": "object"}, []],
    },
}
