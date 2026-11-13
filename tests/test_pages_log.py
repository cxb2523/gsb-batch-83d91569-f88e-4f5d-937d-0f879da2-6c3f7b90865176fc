"""Tests for the per-run page log written beside the database."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from avherald_scraper.config import RunConfig, load_config
from avherald_scraper.pages_log import BLOCKED, FAILED, OK, PageRecord, write_pages_log
from avherald_scraper.scraper import run


PAGE_TWO = "https://avherald.com/h?list=&opt=0&offset=20260821192052%2B53e33032"


class ScriptedClient:
    """Return a scripted body or raise a scripted error, in order."""

    def __init__(self, steps: dict[str, object], *, attempts: dict[str, int] | None = None):
        # Each URL maps to HTML text or an exception instance.
        self.steps = steps

        # Optional per-URL request counts, as the real client would report.
        self.attempts = attempts or {}

        # Every URL actually requested, in order.
        self.urls: list[str] = []

        # Mirrors the real client's counter for the last get().
        self.last_attempts = 0

    def get(self, url: str) -> str:
        self.urls.append(url)
        self.last_attempts = self.attempts.get(url, 1)
        step = self.steps[url]
        if isinstance(step, BaseException):
            raise step
        return step


def _read_log(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_successful_run_writes_one_entry_per_page(
    tmp_path: Path, list_page_html: str, fixtures_dir: Path
):
    page_two = (fixtures_dir / "list_page_2.html").read_text(encoding="utf-8")
    client = ScriptedClient(
        {"https://avherald.com/": list_page_html, PAGE_TWO: page_two}
    )
    db_path = tmp_path / "avherald.sqlite"

    result = run(
        RunConfig(limit=50, database_path=db_path, start_url="https://avherald.com/"),
        client=client,
    )

    log_path = tmp_path / "avherald.pages.json"
    assert result.pages_log_path == log_path
    assert log_path.is_file()

    payload = _read_log(log_path)
    assert payload["pages"] == [
        {"url": "https://avherald.com/", "status": OK, "attempts": 1, "error": None},
        {"url": PAGE_TWO, "status": OK, "attempts": 1, "error": None},
    ]
    assert payload["resume_url"] is None
    assert datetime.fromisoformat(payload["run_started_at"]).tzinfo is not None


def test_default_path_uses_database_stem_and_folder(tmp_path: Path):
    config = RunConfig(database_path=tmp_path / "store" / "archive.sqlite")
    assert config.resolved_pages_log_path() == tmp_path / "store" / "archive.pages.json"


def test_config_pages_log_and_cli_override(tmp_path: Path):
    ini = tmp_path / "config.ini"
    ini.write_text(
        "[storage]\ndatabase = ./data/x.sqlite\n[crawl]\npages_log = ./logs/from-ini.json\n",
        encoding="utf-8",
    )
    from_ini = load_config(cwd=tmp_path)
    assert from_ini.resolved_pages_log_path() == Path("logs/from-ini.json")

    from_cli = load_config(cli={"pages_log": tmp_path / "cli.json"}, cwd=tmp_path)
    assert from_cli.resolved_pages_log_path() == tmp_path / "cli.json"


def test_blocked_page_is_recorded_and_bookmark_stays_on_it(
    tmp_path: Path, list_page_html: str
):
    from avherald_scraper.http import BlockedError

    db_path = tmp_path / "avherald.sqlite"
    client = ScriptedClient(
        {
            "https://avherald.com/": list_page_html,
            PAGE_TWO: BlockedError("every proxy is blocked"),
        },
        attempts={PAGE_TWO: 2},
    )

    result = run(
        RunConfig(limit=50, database_path=db_path, start_url="https://avherald.com/"),
        client=client,
    )

    assert result.failed is True
    assert client.urls == ["https://avherald.com/", PAGE_TWO]
    assert result.pages_log_path is not None

    payload = _read_log(result.pages_log_path)
    assert [page["status"] for page in payload["pages"]] == [OK, BLOCKED]
    assert payload["pages"][1]["attempts"] == 2
    assert payload["pages"][1]["error"]
    assert payload["resume_url"] == PAGE_TWO

    # The rows from the page that did come back are stored.
    assert result.stored == 2


def test_failed_page_stops_the_walk_and_retries_next_time(
    tmp_path: Path, list_page_html: str, fixtures_dir: Path
):
    import httpx

    page_two = (fixtures_dir / "list_page_2.html").read_text(encoding="utf-8")
    page_three = "https://avherald.com/h?list=&opt=0&offset=third"
    db_path = tmp_path / "avherald.sqlite"

    first = run(
        RunConfig(limit=50, database_path=db_path, start_url="https://avherald.com/"),
        client=ScriptedClient(
            {
                "https://avherald.com/": list_page_html,
                PAGE_TWO: httpx.ConnectError("proxy refused the connection"),
                page_three: page_two,
            }
        ),
    )

    payload = _read_log(first.pages_log_path)
    assert [page["status"] for page in payload["pages"]] == [OK, FAILED]
    assert "proxy refused" in payload["pages"][1]["error"]
    assert payload["resume_url"] == PAGE_TWO

    # The next run picks up at the failed page rather than starting over.
    second_client = ScriptedClient({PAGE_TWO: page_two})
    run(
        RunConfig(limit=50, database_path=db_path, start_url="https://avherald.com/"),
        client=second_client,
    )
    assert second_client.urls == [PAGE_TWO]


def test_dry_run_writes_log_but_not_database(tmp_path: Path, list_page_html: str):
    db_path = tmp_path / "avherald.sqlite"
    result = run(
        RunConfig(
            limit=50,
            max_pages=1,
            database_path=db_path,
            start_url="https://avherald.com/",
            dry_run=True,
        ),
        client=ScriptedClient({"https://avherald.com/": list_page_html}),
    )

    assert not db_path.exists()
    assert result.stored == 0
    payload = _read_log(result.pages_log_path)
    assert payload["pages"][0]["status"] == OK


def test_write_failure_raises_oserror(tmp_path: Path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x", encoding="utf-8")

    with pytest.raises(OSError):
        write_pages_log(
            blocker / "log.json",
            run_started_at=datetime.now(UTC),
            pages=[PageRecord("https://avherald.com/", OK, 1)],
            resume_url=None,
        )


def test_custom_pages_log_path_is_used(tmp_path: Path, list_page_html: str):
    custom = tmp_path / "logs" / "run.json"
    result = run(
        RunConfig(
            limit=50,
            max_pages=1,
            database_path=tmp_path / "avherald.sqlite",
            start_url="https://avherald.com/",
            pages_log=custom,
        ),
        client=ScriptedClient({"https://avherald.com/": list_page_html}),
    )

    assert result.pages_log_path == custom
    assert custom.is_file()
    assert not (tmp_path / "avherald.pages.json").exists()


def test_written_json_is_complete_and_ordered(tmp_path: Path):
    path = write_pages_log(
        tmp_path / "run.pages.json",
        run_started_at=datetime(2026, 11, 14, 12, 30, 5, tzinfo=UTC),
        pages=[
            PageRecord("https://a/", OK, 1),
            PageRecord("https://b/", BLOCKED, 3, "blocked"),
        ],
        resume_url="https://b/",
    )

    payload = _read_log(path)
    assert payload["run_started_at"] == "2026-11-14T12:30:05+00:00"
    assert payload["resume_url"] == "https://b/"
    assert [page["url"] for page in payload["pages"]] == ["https://a/", "https://b/"]
    assert list(payload["pages"][0]) == ["url", "status", "attempts", "error"]
    assert not path.with_name(path.name + ".tmp").exists()
