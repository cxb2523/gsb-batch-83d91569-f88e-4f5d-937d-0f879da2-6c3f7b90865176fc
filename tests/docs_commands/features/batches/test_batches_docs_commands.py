"""Docs command tests for docs/features/batches.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/batches.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/batches/test_batches_docs_commands.py -v``
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
class TestBatchesFeatureDocsCommands:
    """Verify Python SDK commands from batches feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_start_batch_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Start a batch" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        batch = client.batches.create(
            urls=[
                {"custom_id": "item-1", "url": "https://www.google.com/search?q=stripe&gl=us&hl=en"},
                {"custom_id": "item-2", "url": "https://www.google.com/search?q=paddle&gl=us&hl=en"},
            ],
            parser="@olostep/google-search",
        )

        assert batch.id is not None
        assert batch.status is not None

    def test_batch_info_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Check batch status" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        batch = client.batches.create(
            urls=[
                {"custom_id": "item-1", "url": "https://www.google.com/search?q=stripe&gl=us&hl=en"},
            ],
            parser="@olostep/google-search",
        )

        info = batch.info()
        assert info.status is not None

    def test_batch_items_and_retrieve_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "## Retrieve content" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        batch = client.batches.create(
            urls=[
                {"custom_id": "item-1", "url": "https://www.google.com/search?q=stripe&gl=us&hl=en"},
                {"custom_id": "item-2", "url": "https://www.google.com/search?q=paddle&gl=us&hl=en"},
            ],
            parser="@olostep/google-search",
        )

        for item in batch.items():
            content = item.retrieve(["json"])
            assert item.url is not None
            assert item.custom_id is not None
            assert content.json_content is not None
            break  # Only test the first item
