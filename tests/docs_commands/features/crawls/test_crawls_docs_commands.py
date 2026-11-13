"""Docs command tests for docs/features/crawls.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/crawls.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/crawls/test_crawls_docs_commands.py -v``
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
class TestCrawlsFeatureDocsCommands:
    """Verify Python SDK commands from crawls feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_start_crawl_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Start a crawl" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        crawl = client.crawls.create(
            start_url="https://olostep.com",
            max_pages=5,
            include_urls=["/**"],
            exclude_urls=["/collections/**"],
            include_external=False,
        )

        assert crawl.id is not None
        assert crawl.status is not None

    def test_check_crawl_status_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Check crawl status" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        crawl = client.crawls.create(
            start_url="https://olostep.com",
            max_pages=5,
            include_urls=["/**"],
        )

        info = crawl.info()
        assert info.status is not None

    def test_list_pages_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## List pages" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        crawl = client.crawls.create(
            start_url="https://olostep.com",
            max_pages=5,
            include_urls=["/**"],
        )

        pages = []
        for page in crawl.pages():
            pages.append(page)
            assert page.url is not None
            assert page.retrieve_id is not None
            if len(pages) >= 3:
                break

        assert len(pages) > 0

    def test_retrieve_content_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Retrieve content" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        crawl = client.crawls.create(
            start_url="https://olostep.com",
            max_pages=5,
            include_urls=["/**"],
        )

        for page in crawl.pages():
            content = page.retrieve(["markdown"])
            assert content.markdown_content is not None
            break  # Only test the first page
