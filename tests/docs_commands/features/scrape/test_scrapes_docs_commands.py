"""Docs command tests for docs/features/scrapes.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/scrapes.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/scrape/test_scrapes_docs_commands.py -v``
- Or with a venv: ``python -m pip install pytest pytest-asyncio && python -m pytest ...`` (avoids missing ``pytest`` on PATH)

Live API tests need ``OLOSTEP_API_KEY``; without it they are skipped.
"""

from __future__ import annotations

import os

import pytest

from olostep import FillInputAction, LLMExtract, Olostep, WaitAction


@pytest.fixture
def docs_commands_api_key() -> str:
    """API key for doc-snippet parity tests; skip when unset (no setup error)."""
    key = os.getenv("OLOSTEP_API_KEY")
    if not key:
        pytest.skip(
            "OLOSTEP_API_KEY is not set; export it to run live API doc-snippet tests."
        )
    return key


@pytest.mark.integration
@pytest.mark.api
class TestScrapesFeatureDocsCommands:
    """Verify Python SDK commands from scrape feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_basic_scrape_usage_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "### Usage" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        result = client.scrapes.create(
            url_to_scrape="https://en.wikipedia.org/wiki/Alexander_the_Great",
            formats=["markdown", "html"],
        )

        assert result.markdown_content is not None
        assert result.html_content is not None

    def test_structured_extraction_parser_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "Using a Parser" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        result = client.scrapes.create(
            url_to_scrape="https://www.google.com/search?q=alexander+the+great&gl=us&hl=en",
            formats=["json"],
            parser="@olostep/google-search",
        )

        assert result.json_content is not None

    def test_llm_extraction_schema_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "Using LLM extraction" (Python SDK schema example).
        client = Olostep(api_key=docs_commands_api_key)

        result = client.scrapes.create(
            url_to_scrape="https://www.berklee.edu/events/stefano-marchese-friends",
            formats=["markdown", "json"],
            llm_extract=LLMExtract(
                # The API requires a JSON Schema object at the top level.
                schema={
                    "type": "object",
                    "properties": {
                        "event": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "date": {"type": "string"},
                                "description": {"type": "string"},
                                "venue": {"type": "string"},
                                "address": {"type": "string"},
                                "start_time": {"type": "string"},
                            },
                        }
                    },
                }
            ),
        )

        assert result.json_content is not None

    def test_actions_interaction_flow_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "Interacting with the page with Actions" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        result = client.scrapes.create(
            url_to_scrape="https://example.com/login",
            formats=["markdown"],
            actions=[
                FillInputAction(selector="input[type=email]", value="john@example.com"),
                WaitAction(milliseconds=500),
                FillInputAction(selector="input[type=password]", value="secret"),
                {"type": "click", "selector": "button[type=\"submit\"]"},
                WaitAction(milliseconds=1500),
            ],
        )

        assert result.markdown_content is not None
