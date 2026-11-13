from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from ehentai_crawler.fetch import Fetcher, HostRateLimiter, HttpTransport
from ehentai_crawler.settings import Settings

from .fake_site import FakeSite


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test in an empty folder with no EHENTAI_* variables from the host."""
    monkeypatch.chdir(tmp_path)
    for name in [n for n in os.environ if n.startswith("EHENTAI_")]:
        monkeypatch.delenv(name)


@pytest.fixture
def site() -> Iterator[FakeSite]:
    with FakeSite() as fake:
        yield fake


@pytest.fixture
def settings(site: FakeSite, tmp_path: Path) -> Settings:
    """E-Hentai mode pointed at the fake site, with no waiting between requests."""
    return Settings(
        ex_mode=False,
        ehentai_index=site.base,
        ehentai_gallery=site.base + "g/",
        request_delay=0,
        max_retries=2,
        image_folder_path=tmp_path / "img",
        database_path=tmp_path / "list.db",
    )


@pytest.fixture
def site_env(site: FakeSite, monkeypatch: pytest.MonkeyPatch) -> FakeSite:
    """The same settings as environment variables, for CLI tests."""
    for key, value in {
        "EX_MODE": "false",
        "EHENTAI_INDEX": site.base,
        "EHENTAI_GALLERY": site.base + "g/",
        "REQUEST_DELAY": "0",
        "MAX_RETRIES": "1",
    }.items():
        monkeypatch.setenv(f"EHENTAI_{key}", value)
    return site


@pytest.fixture
def fetcher(settings: Settings) -> Iterator[Fetcher]:
    http = HttpTransport(settings, HostRateLimiter(0))
    fetcher = Fetcher(http, http, max_retries=settings.max_retries, sleep=lambda _: None)
    yield fetcher
    fetcher.close()
