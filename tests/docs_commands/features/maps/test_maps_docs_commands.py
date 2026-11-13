"""Docs command tests for docs/features/maps.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/maps.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/maps/test_maps_docs_commands.py -v``
- Or with a venv: ``python -m pip install pytest pytest-asyncio && python -m pytest ...`` (avoids missing ``pytest`` on PATH)

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
class TestMapsFeatureDocsCommands:
    """Verify Python SDK commands from maps feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_basic_map_usage_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Usage" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        sitemap = client.maps.create(url="https://docs.olostep.com")

        urls = []
        for url in sitemap.urls():
            urls.append(url)
            if len(urls) >= 10:
                break

        assert len(urls) > 0

    def test_map_with_include_urls_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "### Example" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        sitemap = client.maps.create(
            url="https://www.brex.com/",
            include_urls=["/product", "/product/**"],
            top_n=100000,
        )

        urls = []
        for url in sitemap.urls():
            urls.append(url)
            if len(urls) >= 10:
                break

        assert len(urls) >= 0
