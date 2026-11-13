"""Functions for web scraping are tested
"""
import asyncio
import json

import aiohttp
import pytest

from app.schemas import UpstreamFailureReason
from app.scraping import (
    UpstreamRequestError,
    get_request,
    make_soup,
    scraping_developers,
    scraping_repositories,
)


@pytest.mark.parametrize(
    "input_html,expected_json",
    [
        pytest.param(
            "data/repodata1.html",
            "data/repodata1.json",
            id="25 typescript repositories, normal data",
        ),
        pytest.param(
            "data/repodata2.html",
            "data/repodata2.json",
            id="4 repositories instead of 25",
        ),
        pytest.param(
            "data/repodata3.html",
            "data/repodata3.json",
            id="Missing description of one repository",
        ),
        pytest.param(
            "data/repodata4.html",
            "data/repodata4.json",
            id="""1 repo which contains neither total_stars nor
            forks and a repo which has no since_stars""",
        ),
    ],
)
def test_repository_scraping(input_html, expected_json):
    """Tests functions which scrape data about repositories from HTML."""
    with open(expected_json) as file:
        correct_repo_json = json.loads(file.read())
    with open(input_html) as file:
        raw_html = file.read()
    soup = make_soup(raw_html)
    repo_json = scraping_repositories(soup, since="daily")
    assert repo_json == correct_repo_json


@pytest.mark.parametrize(
    "input_html,expected_json",
    [
        pytest.param(
            "data/devdata1.html",
            "data/devdata1.json",
            id="25 developers, normal data.",
        ),
        pytest.param(
            "data/devdata2.html",
            "data/devdata2.json",
            id="1 missing popular repository of developer.",
        ),
        pytest.param(
            "data/devdata3.html",
            "data/devdata3.json",
            id="15 developers, description of 1 repo is missing.",
        ),
    ],
)
def test_developer_scraping(input_html, expected_json):
    """Tests functions which scrape data about developers from HTML."""
    with open(expected_json) as file:
        correct_repo_json = json.loads(file.read())
    with open(input_html) as file:
        raw_html = file.read()
    soup = make_soup(raw_html)
    repo_json = scraping_developers(soup, since="daily")
    assert repo_json == correct_repo_json


class _FailingSession:
    """aiohttp.ClientSession stand-in raising a chosen error on GET."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def get(self, *args, **kwargs):
        raise self._error


def test_get_request_classifies_timeout(monkeypatch):
    """Timeout errors keep the timeout failure category, offline."""

    def failing_session(*args, **kwargs):
        return _FailingSession(asyncio.TimeoutError())

    monkeypatch.setattr(aiohttp, "ClientSession", failing_session)

    with pytest.raises(UpstreamRequestError) as exc_info:
        asyncio.run(get_request("https://github.com/trending"))

    assert exc_info.value.failure_reason == UpstreamFailureReason.timeout


def test_get_request_classifies_connection_error(monkeypatch):
    """Connection errors keep the connection_error failure category, offline."""

    def failing_session(*args, **kwargs):
        return _FailingSession(aiohttp.ClientConnectionError())

    monkeypatch.setattr(aiohttp, "ClientSession", failing_session)

    with pytest.raises(UpstreamRequestError) as exc_info:
        asyncio.run(get_request("https://github.com/trending"))

    assert exc_info.value.failure_reason == UpstreamFailureReason.connection_error
