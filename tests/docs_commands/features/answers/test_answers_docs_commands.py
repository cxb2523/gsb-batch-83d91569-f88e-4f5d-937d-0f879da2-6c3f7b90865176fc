"""Docs command tests for docs/features/answers.mdx Python SDK snippets.

These tests intentionally mirror the Python SDK code blocks from:
docs/features/answers.mdx

Run (from ``olostep-py``):

- ``poetry install && poetry run pytest tests/docs_commands/features/answers/test_answers_docs_commands.py -v``
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
class TestAnswersFeatureDocsCommands:
    """Verify Python SDK commands from answers feature docs."""

    def test_installation_import_command(self) -> None:
        # Equivalent to docs "Installation" Python SDK snippet.
        # pip install olostep
        from olostep import Olostep  # noqa: F401

    def test_basic_answer_with_json_format_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "### Usage" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        answer = client.answers.create(
            task="What is the latest book by J.K. Rowling?",
            json_format={"book_title": "", "author": "", "release_date": ""},
        )

        assert answer.json_content is not None
        assert answer.sources is not None

    def test_flexible_json_parameter_command(self, docs_commands_api_key: str) -> None:
        # Mirrors docs snippet in "### Flexible `json` parameter" (Python SDK).
        client = Olostep(api_key=docs_commands_api_key)

        answer = client.answers.create(
            task="how much did Olostep raise?",
            json_format={"amount": ""},
        )

        assert answer.json_content is not None
