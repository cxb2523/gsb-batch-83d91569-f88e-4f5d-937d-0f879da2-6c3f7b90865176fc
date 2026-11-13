"""Docs command tests for docs/features/search.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/search.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/searches/test_searches_docs_commands.py -v``
- Or with a venv: ``python -m pip install pytest pytest-asyncio && python -m pytest ...``

Live API tests need ``OLOSTEP_API_KEY``; without it they are skipped.
"""

from __future__ import annotations

import os

import pytest

from olostep import Olostep


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
class TestSearchesFeatureDocsCommands:
    """Verify Python SDK commands from search feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_basic_usage_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Basic usage" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        search = client.searches.create("Best Answer Engine Optimization startups")

        assert search.id is not None
        assert isinstance(search.links, list)
        assert len(search.links) > 0

    def test_example_with_scraping_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "### Example with scraping" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        search = client.searches.create(
            query="What's going on with OpenAI's Sora shutting down?",
            limit=5,
            scrape_options={"formats": ["markdown"], "timeout": 25},
        )

        assert len(search.links) > 0
        # At least one link should have markdown_content (parallel scrape worked)
        assert any(link.get("markdown_content") for link in search.links)

    def test_retrieving_a_past_search_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Retrieving a past search" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        # Create one first so we have a real id to fetch
        created = client.searches.create("AI agent frameworks")

        search = client.searches.get(search_id=created.id)
        assert search.id == created.id
        assert isinstance(search.links, list)
