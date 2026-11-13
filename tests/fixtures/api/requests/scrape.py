from typing import Any

from olostep.models.request import Format, LinksOnPage, ScreenSize

########################################
# --- Create Scrape Request Fixtures ---
########################################


URL_TO_SCRAPE = {
    "param_name": "url_to_scrape",
    "param_type": str,
    "param_values": {
        "valids": ["https://example.com"],
        "invalids": ["invalid", 1000],
    },
}

MINIMAL_REQUEST_BODY = {
    "url_to_scrape": URL_TO_SCRAPE["param_values"]["valids"][0],
}



WAIT_BEFORE_SCRAPING = {
    "param_name": "wait_before_scraping",
    "param_type": int,
    "param_values": {
        "valids": [1000],
        "invalids": [-1000, "one_day"],
    },
}


FORMATS = {
    "param_name": "formats",
    "param_type": list[Format],
    "param_values": {
        "valids": [f.value for f in Format],
        "invalids": ["invalid_value", 1000],
    },
}


REMOVE_CSS_SELECTORS = {
    "param_name": "remove_css_selectors",
    "param_type": "enum",
    "param_values": {
        "valids": [None, "default", "none", '["nav","footer","script"]'],
        "invalids": [1000],
    },
}

ACTIONS = {
    "param_name": "actions",
    "param_type": "list",
    "param_values": {
        "valid": [
            {"type": "wait", "milliseconds": 1000}, 
            {"type": "click", "selector": "button"}, 
            {"type": "fill_input", "selector": "input", "value": "test"}, 
            {"type": "scroll", "direction": "up", "amount": 100},
            {"type": "scroll", "direction": "down", "amount": 100},
            {"type": "scroll", "direction": "left", "amount": 100},
            {"type": "scroll", "direction": "right", "amount": 100}
            ],
        "invalids": [
            {"totally_invalid_object": "invalid"},
            "not_even_an_object",
            1000,
            {"type": "wait", "milliseconds": -1000},
            {"type": "click", "milliseconds": 1000},
        ],
    },
}

COUNTRY = {
    "param_name": "country",
    "param_type": str,
    "param_values": {
        # Node countries the API actually accepts. The SDK Country type allows
        # any ISO code, but the scrape API only proxies through these locations.
        "valids": [
            "US", "CA", "GB", "IT", "IN", "RU", "JP", "MX", "AU",
            "ID", "UA", "MY", "PH", "SG", "KR", "TW", "TH", "RANDOM",
        ],
        "invalids": ["invalid", 1000, "ZZ"],
    },
}

TRANSFORMER = {
    "param_name": "transformer",
    "param_type": str,
    "param_values": {
        "valids": ["postlight"],
        "invalids": ["invalid", 1000],
    },
}

REMOVE_IMAGES = {
    "param_name": "remove_images",
    "param_type": bool,
    "param_values": {
        "valids": [True, False],
        "invalids": ["invalid", 1000],
    },
}

REMOVE_CLASS_NAMES = {
    "param_name": "remove_class_names",
    "param_type": list[str],
    "param_values": {
        "valids": ["class1", "class2"],
        "invalids": [1000, {"invalid": "object"}],
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
            {"config": {"weird_key": True}},  # Missing id
            {"id": "@olostep/google-search", "invalid_field": "value"},
            "not_a_dict",
            1000,
        ],
    },
}

LLM_EXTRACT = {
    "param_name": "llm_extract",
    "param_type": dict[str, Any],
    "param_values": {
        "valids": [{"schema": {"type": "string"}}],
        "invalids": ["invalid", 1000],
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

SCREEN_SIZE = {
    "param_name": "screen_size",
    "param_type": ScreenSize,
    "param_values": {
        "valids": [
            {"screen_width": 1000, "screen_height": 1000},
            {"screen_type": "desktop"},
            {"screen_type": "mobile"},
            {"screen_type": "default"},
        ],
        "invalids": [
            {"screen_width": -100, "screen_height": 1000},  # negative width
            {"screen_width": 1000},  # missing height
            {"screen_height": 1000},  # missing width
            {"screen_type": "desktop", "screen_width": 1000, "screen_height": 1000},  # both type and dims
            {"screen_type": "invalid_type"},  # invalid type
            "invalid",
            1000,
        ],
    },
}

METADATA = {
    "param_name": "metadata",
    "param_type": dict[str, Any],
    "param_values": {
        "valids": [{"key": "value"}],
        "invalids": ["invalid", 1000],
    },
}


########################################
# --- Get Scrape Request Fixtures ---
########################################

GET_SCRAPE_REQUEST_ID = {
    "param_name": "scrape_id",
    "param_type": str,
    "param_values": {
        #"valids": is a dynamic value,
        "invalids": ["non_existing_scrape_id"],
    },
}