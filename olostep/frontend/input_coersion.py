"""This file contains helper functions that enable the frontend layer to
offer nice input coercion to the user.
Input validation is a non-goal! Coersion happens before validation.
"""

import json
import logging
import uuid
from typing import Any

from pydantic import BaseModel

from ..models.request import BatchItem

logger = logging.getLogger("olostep.frontend.input_coersion")


def coerce_to_list(value: Any) -> list[Any]:
    if value is None:
        return value
    if not isinstance(value, list):
        return [value]
    return value


def coerce_to_batch_items(value: Any) -> list[dict[str, Any]]:
    """Convert various input formats to a list of batch item dictionaries.

    Supports:
    - Single string URL -> [{"url": "url", "custom_id": "auto-generated-id"}]
    - List of strings -> [{"url": "url1", "custom_id": "auto-generated-id1"}, ...]
    - Single BatchItem -> [{"url": "url", "custom_id": "existing-id-or-auto-generated"}]
    - List of BatchItems -> [{"url": "url1", "custom_id": "existing-id-or-auto-generated"}, ...]
    - List of dictionaries -> [{"url": "url1", "custom_id": "existing-id-or-auto-generated"}, ...]

    Automatically generates custom_id values if missing or None (logged as debug).
    Preserves existing custom_id values when present.

    Args:
        value: Input to convert

    Returns:
        List of dictionaries representing batch items
    """
    if value is None:
        return value

    # Handle single item
    if not isinstance(value, list):
        return [_coerce_single_batch_item(value, 0)]

    # Handle list of items
    return [_coerce_single_batch_item(item, index) for index, item in enumerate(value)]


def _coerce_single_batch_item(item: Any, index: int = 0) -> dict[str, Any]:
    """Convert a single item to a batch item dictionary.

    Args:
        item: Single item to convert (string, dict, or BatchItem)
        index: Index of the item in the list (for generating unique IDs)

    Returns:
        Dictionary representation of batch item
    """
    if isinstance(item, str):
        # Simple URL string -> {"url": "string", "custom_id": "auto-generated"}
        result = {"url": item}
        if "custom_id" not in result:
            auto_id = f"auto_{uuid.uuid4().hex[:8]}"
            result["custom_id"] = auto_id
            logger.debug(
                f"Auto-generated custom_id '{auto_id}' for URL '{item}' (index {index})"
            )
        return result
    elif isinstance(item, dict):
        # Already a dictionary -> ensure custom_id exists
        result = item.copy()
        if "custom_id" not in result or result["custom_id"] is None:
            auto_id = f"auto_{uuid.uuid4().hex[:8]}"
            result["custom_id"] = auto_id
            logger.debug(
                f"Auto-generated custom_id '{auto_id}' for URL '{result.get('url', 'unknown')}' (index {index})"
            )
        return result
    elif BatchItem and isinstance(item, BatchItem):
        # BatchItem -> convert to dict
        result = item.model_dump()
        if "custom_id" not in result or result["custom_id"] is None:
            auto_id = f"auto_{uuid.uuid4().hex[:8]}"
            result["custom_id"] = auto_id
            logger.debug(
                f"Auto-generated custom_id '{auto_id}' for BatchItem URL '{result.get('url', 'unknown')}' (index {index})"
            )
        return result
    else:
        # Try to treat as URL string as fallback
        result = {"url": str(item)}
        auto_id = f"auto_{uuid.uuid4().hex[:8]}"
        result["custom_id"] = auto_id
        logger.debug(
            f"Auto-generated custom_id '{auto_id}' for fallback URL '{str(item)}' (index {index})"
        )
        return result


def coerce_to_key_in_dict(value: Any, key: str) -> dict[str, Any] | BaseModel | None:
    if value is None:
        return value
    if isinstance(value, BaseModel):
        return value
    if not isinstance(value, dict):
        return {key: value}
    return value


def coerce_to_string(value: Any) -> str:
    if value is None:
        return value
    if isinstance(value, list):
        return json.dumps(value)
        # catch at end
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, str):
        return value
    raise ValueError(f"Cannot coerce {value} to string")


def coerce_country(value: Any) -> Any:
    """Coerce country value to Country enum or uppercase string.
    
    Handles case-insensitive string conversion (e.g., "us" -> "US").
    """
    if value is None:
        return value
    if isinstance(value, str):
        # Convert lowercase to uppercase for country codes
        return value.upper()
    return value
