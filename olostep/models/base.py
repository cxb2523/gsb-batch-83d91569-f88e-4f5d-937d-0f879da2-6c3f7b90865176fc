import types
import typing
from enum import Enum
from typing import Any, get_args, get_origin

from pydantic import (
    BaseModel,
    ConfigDict,
)

# ============================================================================
# JSON Schema Generation
# ============================================================================
#
# Why Pydantic doesn't support this out of the box:
#
# 1. **Different Schema Standards**: Pydantic's built-in schema generation
#    produces OpenAPI/JSON Schema that's optimized for API documentation,
#    but doesn't handle complex Union types the way we need (e.g., showing
#    all possible action types in a Union as separate objects).
#
# 2. **Union Type Handling**: Pydantic's default schema generation treats
#    Union types as simple "oneOf" without expanding the individual types
#    with their specific fields. Our custom generator expands each Union
#    member to show its complete structure.
#
# 3. **Optional Field Representation**: Pydantic shows optional fields as
#    "field | None" in the schema, but we want optional fields to just be
#    their base type and let the "required" array handle optionality.
#
# 4. **Literal Type Handling**: Pydantic doesn't use "const" for single
#    literal values, which is more semantically correct in JSON Schema.
#
# 5. **Field Descriptions**: While Pydantic supports field descriptions,
#    our generator ensures they're properly included in the final schema.
#
# 6. **Custom Validation Logic**: Our models have custom validators and
#    serialization logic that affects the schema (e.g., ParserConfig
#    normalization, default handling).
#
# This custom schema generator produces schemas that are:
# - More semantically correct for JSON Schema standards
# - Better suited for API documentation and client generation
# - Properly handle complex Union types and optional fields
# - Include all necessary field descriptions and constraints


def generate_json_schema(model_class) -> dict[str, Any]:
    """Generate a JSON schema for a Pydantic model or Union type.

    This function analyzes the Pydantic model structure to automatically generate
    a comprehensive JSON schema including all nested models.
    """
    if not model_class:
        return {}

    origin = get_origin(model_class)
    if origin is typing.Union or origin is types.UnionType:
        args = get_args(model_class)
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            if len(non_none_types) == 1:
                # Simple union with None
                return _generate_type_schema(non_none_types[0], "union_type")
            else:
                # Complex union
                return {
                    "oneOf": [
                        _generate_type_schema(t, "union_type") for t in non_none_types
                    ]
                }

    # Handle Pydantic models
    if hasattr(model_class, "model_fields"):
        return _generate_json_schema(model_class)

    return {}


def _generate_json_schema(model_class) -> dict[str, Any]:
    """Recursively generate JSON schema for a Pydantic model."""

    from pydantic_core import PydanticUndefined

    schema = {"type": "object", "properties": {}, "required": []}

    # Add model docstring as description if available
    if model_class.__doc__:
        schema["description"] = model_class.__doc__.strip()

    for field_name, field_info in model_class.model_fields.items():
        field_type = field_info.annotation

        # Check if field is required
        is_required = (
            field_info.default is PydanticUndefined
            and field_info.default_factory is None
        )
        if is_required:
            schema["required"].append(field_name)

        # Generate schema for this field
        field_schema = _generate_field_schema(field_name, field_type, field_info)
        schema["properties"][field_name] = field_schema

    return schema


def _generate_field_schema(
    field_name: str, field_type: Any, field_info: Any
) -> dict[str, Any]:
    """Generate JSON schema for a specific field."""

    # Get the base schema for the field type
    base_schema = _generate_type_schema_for_field(field_type, field_name)

    # Add field description if available
    if hasattr(field_info, "description") and field_info.description:
        base_schema["description"] = field_info.description

    return base_schema


def _generate_type_schema_for_field(field_type: Any, field_name: str) -> dict[str, Any]:
    """Generate JSON schema for a specific field type."""
    import types
    import typing
    from typing import get_args, get_origin

    # Handle different field types
    origin = get_origin(field_type)
    args = get_args(field_type)

    if origin is typing.Union or origin is types.UnionType:
        # Handle Union types (e.g., str | None, int | None, list[Format] | None, Action)
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            if len(non_none_types) == 1:
                # Simple union with None (optional field) - just return the base type
                # The optionality is handled by the required array in the parent schema
                return _generate_type_schema_for_field(non_none_types[0], field_name)
            else:
                # Complex union - generate schemas for each type
                union_schemas = []
                for t in non_none_types:
                    union_schemas.append(_generate_type_schema_for_field(t, field_name))
                return {"oneOf": union_schemas}
    elif origin is list:
        # Handle list types (e.g., list[Format], list[Action])
        if args:
            element_type = args[0]
            element_schema = _generate_type_schema_for_field(element_type, field_name)
            schema = {"type": "array", "items": element_schema}
            return schema
    elif origin is dict:
        # Handle dict types (e.g., dict[str, Any])
        return {"type": "object", "additionalProperties": True}
    else:
        # Handle simple types
        return _generate_type_schema(field_type, field_name)

    return {"type": "string"}  # Default fallback


def _generate_type_schema(field_type: Any, field_name: str) -> dict[str, Any]:
    """Generate JSON schema for a specific type."""

    # Handle Union types
    origin = get_origin(field_type)
    if origin is typing.Union or origin is types.UnionType:
        args = get_args(field_type)
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            if len(non_none_types) == 1:
                # Simple union with None
                return _generate_type_schema(non_none_types[0], field_name)
            else:
                # Complex union
                return {
                    "oneOf": [
                        _generate_type_schema(t, field_name) for t in non_none_types
                    ]
                }

    # Handle Enum types
    if isinstance(field_type, type) and issubclass(field_type, Enum):
        return {
            "type": "string",
            "enum": [e.value for e in field_type],
            "description": f"One of: {', '.join([e.value for e in field_type])}",
        }

    # Handle Literal types
    origin = get_origin(field_type)
    args = get_args(field_type)
    if origin is typing.Literal:
        # Handle Literal types
        if len(args) == 1:
            # Single literal value - use const
            return {"const": args[0]}
        else:
            # Multiple literal values - use enum
            return {
                "type": "string",
                "enum": list(args),
                "description": f"Must be one of: {', '.join(map(str, args))}",
            }

    # Handle list types
    origin = get_origin(field_type)
    args = get_args(field_type)
    if origin is list and args:
            element_type = args[0]
            element_schema = _generate_type_schema_for_field(element_type, field_name)
            return {"type": "array", "items": element_schema}

    # Handle Pydantic model types
    if hasattr(field_type, "model_fields"):
        return _generate_json_schema(field_type)

    # Handle basic types
    if field_type is str:
        return {"type": "string"}
    elif field_type is int:
        return {"type": "integer"}
    elif field_type is bool:
        return {"type": "boolean"}
    elif field_type is float:
        return {"type": "number"}
    elif hasattr(field_type, "__name__") and field_type.__name__ == "HttpUrl":
        return {"type": "string", "format": "uri"}

    # Default fallback
    return {"type": "string"}


# =============================================================================
# BASE MODEL
# =============================================================================


class OlostepBaseModel(BaseModel):
    """Base class for all models."""

    # we want to be very strict with the models to find all unexpected behavior
    model_config = ConfigDict(extra="forbid", exclude_unset=True, exclude_none=True)

    def model_dump(self, **kwargs) -> dict[str, object]:
        # Remove all fields with value None from the output
        data = super().model_dump(**kwargs)
        return {k: v for k, v in data.items() if v is not None}


class OlostepResponseBaseModel(BaseModel):
    """Base class for all response models."""

    model_config = ConfigDict(extra="allow")
