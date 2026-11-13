from typing import Any

########################################
# --- Create Answer Request Fixtures ---
########################################

TASK = {
    "param_name": "task",
    "param_type": str,
    "param_values": {
        "valids": [
            "list all products on the website",
            "extract contact information",
            "find all blog posts",
            "get product prices",
            "analyze website structure"
        ],
        "invalids": [1000, {"invalid": "object"}, None],
    },
}

MINIMAL_REQUEST_BODY = {
    "task": TASK["param_values"]["valids"][0],
}

JSON_FORMAT = {
    "param_name": "json_format",
    "param_type": dict[str, Any],
    "param_values": {
        "valids": [
            None,
            {"products": [{"name": "", "price": ""}]},
            {"articles": [{"title": "", "url": "", "summary": ""}]},
            {"contacts": {"email": "", "phone": "", "address": ""}},
            {"data": {"items": [], "total": 0}},
        ],
        "invalids": [
            "invalid_string",
            1000,
            {"incomplete_schema": {}},  # Empty schema
        ],
    },
}

# =============================================================================
# --- Get Answer Request Fixtures ---
# =============================================================================

GET_ANSWER_REQUEST_ID = {
    "param_name": "answer_id",
    "param_type": str,
    "param_values": {
        #"valids": is a dynamic value,
        "invalids": ["non_existing_answer_id"],
    },
}
