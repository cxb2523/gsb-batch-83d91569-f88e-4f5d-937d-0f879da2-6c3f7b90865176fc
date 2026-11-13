"""
Answers operations with rich IDE support and smart input coercion.
"""

from __future__ import annotations

from typing import Any

from .._log import get_logger
from ..backend.api_endpoints import ANSWERS_CREATE
from ..backend.caller import EndpointCaller
from ..frontend.client_state import AnswersResult
from ..models.response import AnswersResponse

logger = get_logger("frontend.answers_menu")


class AnswersMenu:
    """Answers operations with rich IDE support and smart input coercion.

    This class provides methods for generating answers to tasks with various
    configuration options. It supports smart input coercion, validation,
    and provides rich type hints for better IDE support.
    """

    def __init__(self, caller: EndpointCaller, validate_request: bool = True) -> None:
        self._caller = caller
        self._validate_request = validate_request

    async def create(
        self,
        task: str,
        *,
        json_format: dict[str, Any] | None = None,
        validate_request: bool | None = None,
    ) -> AnswersResult:
        """Generate an answer for a given task with optional JSON format specification.

        Creates a new answer generation job for the specified task. Supports
        optional JSON format specification for structured output.

        Args:
            task: The task to be performed (e.g., "list all products on the website").
            json_format: Optional JSON schema for structured output.
                Should be a dictionary specifying the desired format with empty values as placeholders.
            validate_request: Override the global validation setting for this request.
                If None, uses the instance's default validation setting.

        Returns:
            AnswersResult: The generated answer with metadata and content.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Basic task answering
            result = await client.answers.create("What is the capital of France?")
            print(f"Answer: {result.json_content}")

            # Task with structured output format
            result = await client.answers.create(
                task="Extract all product names and prices from the webpage",
                json_format={
                    "products": [
                        {"name": "", "price": ""}
                    ]
                }
            )
            print(f"Products: {result.json_content}")
        """
        body_params = {
            "task": task,
            "json_format": json_format,
        }

        # local validation setting overrides global validation setting
        validate_request = (
            self._validate_request if validate_request is None else validate_request
        )

        res: AnswersResponse = await self._caller.invoke(
            ANSWERS_CREATE, body_params=body_params, validate_request=validate_request
        )

        return AnswersResult(res)

    __call__ = create  # shorthand for create

    async def get(self, answer_id: str) -> AnswersResult:
        """Get an existing answer result by ID.

        Retrieves a previously created answer result using its unique identifier.
        Useful for accessing answer results that were created earlier or
        by other processes.

        Args:
            answer_id: The unique identifier of the answer to retrieve.
                This is returned when creating an answer with the create() method.

        Returns:
            AnswersResult: The answer content and metadata.

        Raises:
            Exception: If the API request fails.

        Examples:
            # Get existing answer result
            result = await client.answers.get("answer_123")
            print(f"Task: {result.task}")
            print(f"Content: {result.json_content}")
        """
        from ..backend.api_endpoints import ANSWERS_GET

        path_params = {"answer_id": answer_id}
        res: AnswersResponse = await self._caller.invoke(
            ANSWERS_GET,
            path_params=path_params,
            validate_request=self._validate_request,
        )
        return AnswersResult(res)
