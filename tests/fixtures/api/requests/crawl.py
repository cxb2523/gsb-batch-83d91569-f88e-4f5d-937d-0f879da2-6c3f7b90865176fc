
########################################
# --- Create Crawl Request Fixtures ---
########################################


START_URL = {
    "param_name": "start_url",
    "param_type": str,
    "param_values": {
        "valids": ["https://example.com"],
        "invalids": ["invalid", 1000],
    },
}

MINIMAL_REQUEST_BODY = {
    "start_url": START_URL["param_values"]["valids"][0],
    "max_pages": 3,
}


MAX_PAGES = {
    "param_name": "max_pages",
    "param_type": int,
    "param_values": {
        "valids": [1, 10, 100],
        "invalids": [0, -1, "ten"],
    },
}


INCLUDE_URLS = {
    "param_name": "include_urls",
    "param_type": list[str],
    "param_values": {
        "valids": [["/**"], ["/blog/**", "/docs/**"], ["*.html"]],
        "invalids": [1000, "not_a_list", {"invalid": "object"}],
    },
}


EXCLUDE_URLS = {
    "param_name": "exclude_urls",
    "param_type": list[str],
    "param_values": {
        "valids": [["/admin/**"], ["/private/**", "/temp/**"]],
        "invalids": [1000, "not_a_list", {"invalid": "object"}],
    },
}


MAX_DEPTH = {
    "param_name": "max_depth",
    "param_type": int,
    "param_values": {
        "valids": [1, 3, 5],
        "invalids": [0, -1, "three"],
    },
}


INCLUDE_EXTERNAL = {
    "param_name": "include_external",
    "param_type": bool,
    "param_values": {
        "valids": [True, False],
        "invalids": ["invalid_string", {"invalid": "object"}, []],
    },
}


INCLUDE_SUBDOMAIN = {
    "param_name": "include_subdomain",
    "param_type": bool,
    "param_values": {
        "valids": [True, False],
        "invalids": ["invalid_string", {"invalid": "object"}, []],
    },
}


FOLLOW_ROBOTS_TXT = {
    "param_name": "follow_robots_txt",
    "param_type": bool,
    "param_values": {
        "valids": [True, False],
        "invalids": ["invalid_string", {"invalid": "object"}, []],
    },
}


SEARCH_QUERY = {
    "param_name": "search_query",
    "param_type": str,
    "param_values": {
        "valids": ["blog posts", "documentation", "tutorials"],
        "invalids": [1000, {"invalid": "object"}],
    },
}


TOP_N = {
    "param_name": "top_n",
    "param_type": int,
    "param_values": {
        "valids": [1, 10, 50],
        "invalids": [0, -1, "ten"],
    },
}


WEBHOOK_URL = {
    "param_name": "webhook_url",
    "param_type": str,
    "param_values": {
        "valids": ["http://example.com/webhook", "https://api.example.com/callback"],
        "invalids": [1000, {"invalid": "object"}, [], "not_an_url"],
    },
}


########################################
# --- Get Crawl Info Request Fixtures ---
########################################

GET_CRAWL_INFO_REQUEST_ID = {
    "param_name": "crawl_id",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value,
        "invalids": ["non_existing_crawl_id"],
    },
}


########################################
# --- Get Crawl Pages Request Fixtures ---
########################################

GET_CRAWL_PAGES_REQUEST_ID = {
    "param_name": "crawl_id",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value,
        "invalids": ["non_existing_crawl_id"],
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


CRAWL_SEARCH_QUERY = {
    "param_name": "search_query",
    "param_type": str,
    "param_values": {
        "valids": ["blog", "documentation", "tutorial"],
        "invalids": [1000, {"invalid": "object"}],
    },
}

WORKFLOW_REQUEST_BODY = {
    "start_url": "https://www.bbc.com/",
    "max_pages": 50,
    "max_depth": 10,
    "follow_robots_txt": False,
}
