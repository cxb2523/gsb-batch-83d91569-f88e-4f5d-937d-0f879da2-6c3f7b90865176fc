"""Fake transport implementations for testing."""

from __future__ import annotations

import json as _json
import re
import time
from typing import Any, Iterable
from urllib.parse import urlsplit

from pydantic import BaseModel

from olostep.backend.api_endpoints import CONTRACTS, EndpointContract
from olostep.backend.transport_protocol import RawAPIRequest, RawAPIResponse, Transport


class FakeTransport(Transport):
    """Simple fake transport for basic testing."""

    def __init__(
        self,
        responses: dict[tuple[str, str], dict[str, Any]] | None = None,
        *,
        fail: dict[tuple[str, str], dict[str, Any]] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._fail = fail or {}

    async def request(
        self,
        request: RawAPIRequest,
    ) -> RawAPIResponse:

        # Convert query to params for existing logic
        params = request.query
        split = urlsplit(request.url)
        path = split.path
        key = (request.method.upper(), path)

        if key in self._fail:
            cfg = self._fail[key]
            if "exception" in cfg:
                exc = cfg["exception"]
                if exc == "connection":
                    raise ConnectionError("Simulated connection error")
                if exc == "timeout":
                    raise TimeoutError("Simulated timeout")
                if exc == "session":
                    raise RuntimeError("Simulated session error")
            status = int(cfg.get("status", 500))
            body = cfg.get("body", {})
            return RawAPIResponse(
                status_code=status,
                headers={},
                body=_json.dumps(body) if isinstance(body, dict) else str(body)
            )

        if key in self._responses:
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(self._responses[key])
            )

        if path.endswith("/scrapes") and request.method.upper() == "POST":
            body = {
                "id": "scrape_fake_1",
                "object": "scrape",
                "created": 1,
                "retrieve_id": "ret_1",
                "url": (request.json or {}).get("url_to_scrape", ""),
                "result": {"html_content": "<html></html>", "size_exceeded": False},
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if "/scrapes/" in path and request.method.upper() == "GET":
            sid = path.rsplit("/", 1)[-1]
            body = {
                "id": sid,
                "object": "scrape",
                "created": 1,
                "retrieve_id": "ret_1",
                "url": "https://example.com",
                "result": {"html_content": "<html></html>", "size_exceeded": False},
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if path.endswith("/batches") and request.method.upper() == "POST":
            body = {
                "id": "batch_fake_1",
                "object": "batch",
                "status": "in_progress",
                "created": 1,
                "total_urls": len((request.json or {}).get("items", [])),
                "completed_urls": 0,
                "parser": {"id": (request.json or {}).get("parser", {}).get("id", "default")},
                "country": (request.json or {}).get("country", "US"),
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if "/batches/" in path and request.method.upper() == "GET":
            parts = path.strip("/").split("/")
            if parts[-1] != "items":
                body = {
                    "id": parts[-1],
                    "object": "batch",
                    "status": "in_progress",
                    "created": 1,
                    "total_urls": 2,
                    "completed_urls": 1,
                    "number_retried": 0,
                    "parser": "default",
                    "start_date": "2024-01-01T00:00:00Z",
                }
            else:
                body = {
                    "id": parts[-2],
                    "object": "batch",
                    "status": "in_progress",
                    "items": [
                        {"custom_id": "item1", "retrieve_id": "ret_1", "url": "https://a"},
                        {"custom_id": "item2", "retrieve_id": "ret_2", "url": "https://b"},
                    ],
                    "items_count": 2,
                    "cursor": 1,
                }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if path.endswith("/crawls") and request.method.upper() == "POST":
            body = {
                "id": "crawl_fake_1",
                "object": "crawl",
                "status": "in_progress",
                "created": 1,
                "start_date": "2024-01-01T00:00:00Z",
                "start_url": (request.json or {}).get("start_url", ""),
                "max_pages": (request.json or {}).get("max_pages", 10),
                "max_depth": (request.json or {}).get("max_depth"),
                "exclude_urls": (request.json or {}).get("exclude_urls"),
                "include_urls": (request.json or {}).get("include_urls", ["/**"]),
                "include_external": (request.json or {}).get("include_external", False),
                "search_query": (request.json or {}).get("search_query"),
                "top_n": (request.json or {}).get("top_n"),
                "current_depth": 0,
                "pages_count": 0,
                "webhook_url": (request.json or {}).get("webhook_url"),
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if path.endswith("/pages") and "/crawls/" in path and request.method.upper() == "GET":
            cid = path.split("/")[-3] if path.endswith("/pages") else path.split("/")[-2]
            body = {
                "id": cid,
                "object": "crawl",
                "status": "in_progress",
                "search_query": (params or {}).get("search_query"),
                "pages_count": 2,
                "pages": [
                    {"id": "p1", "retrieve_id": "ret_1", "url": "https://p1", "is_external": False},
                    {"id": "p2", "retrieve_id": "ret_2", "url": "https://p2", "is_external": True},
                ],
                "metadata": {"external_urls": ["https://p2"], "failed_urls": []},
                "cursor": 1,
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if "/crawls/" in path and request.method.upper() == "GET":
            cid = path.strip("/").split("/")[-1]
            body = {
                "id": cid,
                "object": "crawl",
                "status": "in_progress",
                "created": 1,
                "start_date": "2024-01-01T00:00:00Z",
                "start_url": "https://example.com",
                "max_pages": 10,
                "max_depth": None,
                "exclude_urls": None,
                "include_urls": ["/**"],
                "include_external": False,
                "search_query": None,
                "top_n": None,
                "current_depth": 1,
                "pages_count": 1,
                "webhook_url": None,
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if path.endswith("/maps") and request.method.upper() == "POST":
            body = {
                "urls_count": 3,
                "urls": ["https://a", "https://b", "https://c"],
                "id": "map_1",
                "cursor": "next_1",
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )
        if path.endswith("/retrieve") and request.method.upper() == "GET":
            body = {
                "html_content": None,
                "markdown_content": None,
                "json_content": {},
                "html_hosted_url": None,
                "markdown_hosted_url": None,
                "json_hosted_url": None,
                "size_exceeded": False,
            }
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(body)
            )

        return RawAPIResponse(
            status_code=200,
            headers={},
            body="{}"
        )

    async def close(self) -> None:
        """Close method for protocol compliance. No-op for fake transport."""
        pass


class FakeTransportSmart(Transport):
    """Schema-driven smart fake transport for advanced testing."""
    
    def __init__(
        self,
        contracts: Iterable[EndpointContract] | None = None,
        *,
        overrides: dict[tuple[str, str], dict[str, Any]] | None = None,
        fail: dict[tuple[str, str], dict[str, Any]] | None = None,
        seed: int | None = None,
    ) -> None:
        self._contracts = list(contracts) if contracts is not None else list(CONTRACTS.values())
        self._overrides = overrides or {}
        self._fail = fail or {}
        self._seed = seed or 0
        self._compiled = [self._compile_pattern(c) for c in self._contracts]

    def _compile_pattern(self, c: EndpointContract) -> tuple[EndpointContract, re.Pattern[str]]:
        # Build a regex that matches any prefix before the path and captures path params
        # Example: /batches/{batch_id}/items -> ^.*/batches/(?P<batch_id>[^/]+)/items$
        pattern = re.sub(r"{([^}]+)}", lambda m: f"(?P<{m.group(1)}>[^/]+)", c.path)
        regex = re.compile(rf"^.*/?{pattern.lstrip('/')}$")
        return c, regex

    def _auto_value(self, annotation: Any, name: str) -> Any:
        try:
            from enum import Enum
            from typing import get_args, get_origin
        except Exception:
            return None
        origin = get_origin(annotation)
        args = get_args(annotation)
        if origin is None:
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                return self._auto_model(annotation)
            if isinstance(annotation, type) and issubclass(annotation, Enum):
                return list(annotation)[0]
            if annotation in (str,):
                return f"fake_{name}"
            if annotation in (int,):
                return 1
            if annotation in (float,):
                return 1.0
            if annotation in (bool,):
                return False
            if annotation in (dict,):
                return {}
            if annotation in (list,):
                return []
            return None
        if origin in (list, list[Any]):
            return []
        if origin in (dict, dict[str, Any]):
            return {}
        # Optional/Union -> pick first non-None
        if origin is None and annotation is None:
            return None
        if origin is not None and args:
            non_none = [a for a in args if a is not type(None)]  # noqa: E721
            if non_none:
                return self._auto_value(non_none[0], name)
        return None

    def _auto_model(self, model_type: type[BaseModel]) -> BaseModel:
        kwargs: dict[str, Any] = {}
        for fname, field in model_type.model_fields.items():
            if field.default is not None:
                kwargs[fname] = field.default
                continue
            val = self._auto_value(field.annotation, fname)
            if val is None and field.is_required():
                # basic defaults for common primitives
                if field.annotation in (str,):
                    val = f"fake_{fname}"
                elif field.annotation in (int,):
                    val = 1
                elif field.annotation in (bool,):
                    val = False
                elif field.annotation in (dict,):
                    val = {}
                elif field.annotation in (list,):
                    val = []
                else:
                    # For unknown types, try to provide a placeholder
                    # _enrich will replace it with proper values
                    val = f"fake_{fname}"
            if val is not None:
                kwargs[fname] = val
        try:
            return model_type(**kwargs)  # type: ignore[call-arg]
        except Exception:
            # If validation fails, create with minimal required fields
            # _enrich will populate them properly
            minimal_kwargs: dict[str, Any] = {}
            for fname, field in model_type.model_fields.items():
                if field.default is not None:
                    minimal_kwargs[fname] = field.default
                elif field.is_required():
                    if field.annotation in (str,):
                        minimal_kwargs[fname] = f"fake_{fname}"
                    elif field.annotation in (int,):
                        minimal_kwargs[fname] = 1
                    elif field.annotation in (bool,):
                        minimal_kwargs[fname] = False
                    elif field.annotation in (dict,):
                        minimal_kwargs[fname] = {}
                    elif field.annotation in (list,):
                        minimal_kwargs[fname] = []
                    else:
                        minimal_kwargs[fname] = None
            return model_type(**minimal_kwargs)  # type: ignore[call-arg]

    def _enrich_value(
        self,
        field_name: str,
        field_annotation: Any,
        *,
        path_params: dict[str, str],
        query: dict[str, Any],
        body: dict[str, Any],
    ) -> Any:
        """Generate a value for a field based on its name and type, using request data when available."""
        from typing import get_args, get_origin

        # Try to get value from request data first (path params, query, body)
        if field_name in path_params:
            return path_params[field_name]
        if field_name in query:
            return query[field_name]
        if field_name in body:
            return body[field_name]

        # Try common field name patterns
        if field_name == "id":
            # Generate ID based on path params if available
            for param_name in ["scrape_id", "batch_id", "crawl_id", "answer_id", "retrieve_id", "map_id"]:
                if param_name in path_params:
                    return path_params[param_name]
            return f"{field_name}_fake_{self._seed}"
        if field_name == "created":
            return int(time.time())
        if field_name.endswith("_id") and field_name != "id":
            return f"ret_{self._seed}"
        if field_name in ["url_to_scrape", "start_url", "url"]:
            # Try to get from body with various possible names
            for key in ["url_to_scrape", "start_url", "url"]:
                if key in body:
                    return body[key]
            return "https://example.com"
        if field_name == "status":
            return "in_progress"
        if field_name == "object":
            # Try to infer from endpoint key
            return "unknown"
        if field_name in ["total_urls", "items_count", "pages_count", "urls_count"]:
            # Try to get from body
            if "items" in body and isinstance(body["items"], list):
                return len(body["items"])
            if "urls" in body and isinstance(body["urls"], list):
                return len(body["urls"])
            return 2  # Default count
        if field_name == "completed_urls":
            return 0
        if field_name == "cursor":
            # Check if cursor should be string or int based on field type
            from typing import get_args, get_origin
            origin = get_origin(field_annotation)
            args = get_args(field_annotation)
            # If it's Optional[str] or str, return string
            if origin is not None:  # Optional or Union
                non_none = [a for a in args if a is not type(None)]  # noqa: E721
                if non_none and non_none[0] == str:
                    return "next_1"
                elif non_none and non_none[0] == int:
                    return 1
            elif field_annotation == str:
                return "next_1"
            elif field_annotation == int:
                return 1
            # Default: try to infer from field name or return string
            return "next_1"
        if field_name == "start_date":
            return "2024-01-01T00:00:00Z"
        if field_name == "size_exceeded":
            return False
        if field_name in ["html_content", "markdown_content", "text_content"]:
            # Check if formats were requested
            formats = query.get("formats") or body.get("formats") or []
            if isinstance(formats, str):
                formats = [formats]
            format_name = field_name.replace("_content", "")
            if format_name in formats or "all" in formats:
                if format_name == "html":
                    return "<html><body>Hello World</body></html>"
                if format_name == "markdown":
                    return "# Hello World"
                if format_name == "text":
                    return "Hello World"
            return None
        if field_name == "json_content":
            formats = query.get("formats") or body.get("formats") or []
            if isinstance(formats, str):
                formats = [formats]
            if "json" in formats or "all" in formats:
                return {}
            return None
        if field_name == "result":
            # This is a nested model, generate it
            origin = get_origin(field_annotation)
            args = get_args(field_annotation)
            if origin is None and isinstance(field_annotation, type) and issubclass(field_annotation, BaseModel):
                return self._auto_model(field_annotation)
            if args:
                # Try first arg if it's a model
                for arg in args:
                    if isinstance(arg, type) and issubclass(arg, BaseModel):
                        return self._auto_model(arg)
        if field_name in ["items", "pages", "urls"]:
            # Generate a list of items
            origin = get_origin(field_annotation)
            args = get_args(field_annotation)
            if origin is list and args:
                item_type = args[0]
                if isinstance(item_type, type) and issubclass(item_type, BaseModel):
                    # Generate 2 sample items
                    return [self._auto_model(item_type), self._auto_model(item_type)]
                elif isinstance(item_type, type) and item_type == str:
                    return ["https://example.com/1", "https://example.com/2"]
                else:
                    # Try to generate dict items
                    return [
                        {"id": "item1", "url": "https://example.com/1"},
                        {"id": "item2", "url": "https://example.com/2"},
                    ]
            return []
        if field_name == "metadata":
            return {}
        if field_name in ["include_urls", "exclude_urls"]:
            return body.get(field_name, ["/**"])
        if field_name in ["include_external", "include_subdomain", "remove_images"]:
            return body.get(field_name, False)
        if field_name == "max_pages":
            return body.get("max_pages", 10)
        if field_name == "max_depth":
            return body.get("max_depth", 3)
        if field_name == "top_n":
            return body.get("top_n", 10)
        if field_name == "search_query":
            return query.get("search_query") or body.get("search_query")
        if field_name == "answer":
            return "This is a generated answer."
        if field_name == "task":
            return body.get("task", "Generated task")
        if field_name == "json_content" and "answer" in str(field_annotation).lower():
            # For AnswersResult.json_content, return a JSON string
            return '{"answer": "This is a generated answer."}'

        # Fall back to auto_value for type-based generation
        return self._auto_value(field_annotation, field_name)

    def _enrich(self, c: EndpointContract, *, path_params: dict[str, str], query: dict[str, Any], body: dict[str, Any], model: BaseModel | None) -> BaseModel:
        """Enrich model with values derived from request data and field patterns."""
        if c.response_model is None:
            raise ValueError("Response model is required for enrichment")

        response_model = c.response_model  # type: ignore[assignment]
        update: dict[str, Any] = {}

        # Generate values for all fields in the response model
        for field_name, field in response_model.model_fields.items():
            # Skip if field already has a default and we have a model with that value
            if model and hasattr(model, field_name):
                existing_value = getattr(model, field_name, None)
                if existing_value is not None and field.default is not None:
                    continue

            # Generate value for this field
            value = self._enrich_value(
                field_name,
                field.annotation,
                path_params=path_params,
                query=query,
                body=body,
            )
            if value is not None:
                update[field_name] = value

        # Create or update the model
        if update:
            if model is None:
                # Create model from scratch with update values
                return response_model(**update)  # type: ignore[call-arg]
            try:
                return model.model_copy(update=update)
            except Exception:
                # fallback: reconstruct
                try:
                    data = model.model_dump(mode="python")
                    data.update(update)
                    return model.__class__(**data)
                except Exception:
                    # Final fallback: create new model with update
                    return response_model(**update)  # type: ignore[call-arg]
        if model is None:
            # No update but model is None, create minimal model
            return self._auto_model(response_model)  # type: ignore[arg-type]
        return model

    async def request(
        self,
        request: RawAPIRequest,
    ) -> RawAPIResponse:

        # Convert query to params for existing logic
        params = request.query
        split = urlsplit(request.url)
        path = split.path

        # overrides / failures by exact (method, path)
        if (request.method.upper(), path) in self._fail:
            cfg = self._fail[(request.method.upper(), path)]
            if "exception" in cfg:
                exc = cfg["exception"]
                if exc == "connection":
                    raise ConnectionError("Simulated connection error")
                if exc == "timeout":
                    raise TimeoutError("Simulated timeout")
                if exc == "session":
                    raise RuntimeError("Simulated session error")
            status = int(cfg.get("status", 500))
            body = cfg.get("body", {})
            return RawAPIResponse(
                status_code=status,
                headers={},
                body=_json.dumps(body) if isinstance(body, dict) else str(body)
            )
        if (request.method.upper(), path) in self._overrides:
            return RawAPIResponse(
                status_code=200,
                headers={},
                body=_json.dumps(self._overrides[(request.method.upper(), path)])
            )

        # match contract
        matched: EndpointContract | None = None
        path_params: dict[str, str] = {}
        for c, rx in self._compiled:
            if c.method.upper() != request.method.upper():
                continue
            m = rx.match(path)
            if m:
                matched = c
                path_params = m.groupdict()
                break
        if not matched or not matched.response_model:
            return RawAPIResponse(
            status_code=200,
            headers={},
            body="{}"
        )

        # Parse request body
        body_json: dict[str, Any] = {}
        if request.json:
            body_json = request.json

        # build model - let _enrich handle it since it knows what values to use
        try:
            model = self._auto_model(matched.response_model)  # type: ignore[arg-type]
        except Exception:
            # If auto_model fails, create empty dict and let _enrich populate everything
            model = None
        model = self._enrich(matched, path_params=path_params, query=(params or {}), body=body_json, model=model)
        return RawAPIResponse(
            status_code=200,
            headers={},
            body=model.model_dump_json()  # type: ignore[call-arg]
        )

    async def close(self) -> None:
        """Close method for protocol compliance. No-op for fake transport."""
        pass
