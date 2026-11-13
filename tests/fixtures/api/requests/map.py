
########################################
# --- Create Map Request Fixtures ---
########################################

URL = {
    "param_name": "url",
    "param_type": str,
    "param_values": {
        "valids": [
            "https://www.bbc.com/",
        ],
        "invalids": [
            "invalid_url",
            "not_a_url",
            "ftp://example.com",  # Wrong protocol
            "http://",  # Incomplete URL
            "",
            None,
            1000,
            {"invalid": "object"},
        ],
    },
}

SEARCH_QUERY = {
    "param_name": "search_query",
    "param_type": str,
    "param_values": {
        "valids": [
            "news",
        ],
        "invalids": [
            1000,
            {"invalid": "object"},
            [],
        ],
    },
}

TOP_N = {
    "param_name": "top_n",
    "param_type": int,
    "param_values": {
        "valids": [1, 5, 10],
        "invalids": [
            0,  # Must be positive
            -1,  # Must be positive
            -10,  # Must be positive
            "ten",  # Wrong type
            {"invalid": "object"},
            [],
        ],
    },
}

INCLUDE_SUBDOMAIN = {
    "param_name": "include_subdomain",
    "param_type": bool,
    "param_values": {
        "valids": [True, False],
        "invalids": [
            "random_string",
            "true",  # String instead of bool
            "false",  # String instead of bool
            1,  # Int instead of bool
            0,  # Int instead of bool
            {"invalid": "object"},
            [],
        ],
    },
}

INCLUDE_URLS = {
    "param_name": "include_urls",
    "param_type": list,
    "param_values": {
        "valids": [
            ["/blog/**"],
            ["/articles/**", "/news/**"],
            ["*.html"],
            ["/docs/**", "/api/**"],
            ["/products/**", "/services/**", "/about/**"],
        ],
        "invalids": [
            ["/blog/**", 123],  # Mixed types
            "not_a_list",
            {"invalid": "object"},
            1000,
        ],
    },
}

EXCLUDE_URLS = {
    "param_name": "exclude_urls",
    "param_type": list,
    "param_values": {
        "valids": [
            ["/admin/**"],
            ["/private/**", "/internal/**"],
            ["*.jpg", "*.png"],
            ["/admin/**", "/private/**", "/internal/**"],
            ["/temp/**", "/cache/**", "/logs/**"],
        ],
        "invalids": [
            ["/admin/**", 123],  # Mixed types
            "not_a_list",
            {"invalid": "object"},
            1000,
        ],
    },
}

CURSOR = {
    "param_name": "cursor",
    "param_type": str,
    "param_values": {
        # "valids": is a dynamic value, acquired as an API response after sending a request
        "invalids": [123, {"invalid": "object"}, []],
    },
}

MINIMAL_REQUEST_BODY = {
    "url": "https://example.com",
}

PAGINATION_REQUEST_BODY = {
    "url": "https://www.bbc.com/", #let her rip
}

