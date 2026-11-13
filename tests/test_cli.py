from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from ehentai_crawler import __version__
from ehentai_crawler.cli import EXIT_BANNED, build_parser, main

from .fake_site import GALLERIES

REPO = Path(__file__).resolve().parents[1]
ORIGINAL_OPTIONS = [
    "-c",
    "--crawl_list",
    "-u",
    "--update_crawl_list",
    "-p",
    "--crawl_each_page",
    "-to",
    "--crawl_tag_only",
    "-cu",
    "--crawl_with_url",
    "-ds",
    "--database_sync",
]


def rows(db: Path, query: str) -> list[tuple]:
    with closing(sqlite3.connect(db)) as conn, conn:
        return list(conn.execute(query))


def test_no_options_prints_help(capsys):
    assert main([]) == 0
    out = capsys.readouterr().out
    for option in ORIGINAL_OPTIONS:
        assert option in out
    assert not Path("list.db").exists()  # nothing to do, nothing created


@pytest.mark.parametrize(
    ("argv", "dest", "value"),
    [
        (["-c"], "crawl_list", True),
        (["--crawl_list"], "crawl_list", True),
        (["-c", "yes"], "crawl_list", True),
        (["-c", "False"], "crawl_list", False),  # the 2019 version read this as True
        (["-to"], "crawl_tag_only", True),
        (["-u", "0"], "update_crawl_list", False),
        (["-cu", "https://e-hentai.org/g/1/ab/"], "gallery_url", "https://e-hentai.org/g/1/ab/"),
        (["-ds", "other.db"], "other_database_path", Path("other.db")),
    ],
)
def test_original_options_parse_the_same_way(argv, dest, value):
    assert getattr(build_parser().parse_args(argv), dest) == value


def test_settings_flags_are_generated_from_the_schema():
    args = build_parser().parse_args(
        ["--no-ex-mode", "--number-of-thread", "3", "--fetcher", "browser", "--database-path", "x.db"]
    )
    assert (args.ex_mode, args.number_of_thread, args.fetcher, args.database_path) == (
        False,
        3,
        "browser",
        Path("x.db"),
    )
    assert build_parser().parse_args([]).ex_mode is None  # not given: the file or env decides


def test_cookies_have_no_flags(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--ipb-member-id", "1"])
    assert "unrecognized arguments" in capsys.readouterr().err


def test_bad_flag_value_is_a_usage_error(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["-c", "--number-of-thread", "lots"])
    assert caught.value.code == 2
    assert "invalid literal" in capsys.readouterr().err


def test_bad_gallery_url_is_rejected_before_anything_runs(site_env, capsys):
    with pytest.raises(SystemExit) as caught:
        main(["-cu", "https://example.test/not-a-gallery"])
    assert caught.value.code == 2
    assert "not a gallery URL" in capsys.readouterr().err
    assert site_env.requests == []


def test_exhentai_without_cookies_says_how_to_fix_it(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["-c"])  # EX_MODE is on by default, as in 2019
    assert caught.value.code == 2
    err = capsys.readouterr().err
    assert "EHENTAI_IPB_MEMBER_ID" in err and "--no-ex-mode" in err


def test_full_run_list_then_pages(site_env):
    assert main(["-c"]) == 0
    assert {r[0] for r in rows(Path("list.db"), "SELECT gallery_id FROM hentai_list")} == set(GALLERIES)

    assert main(["-p"]) == 0
    assert rows(Path("list.db"), "SELECT gallery_id FROM hentai_list WHERE removed = 1") == [(1003,)]
    assert rows(Path("list.db"), "SELECT COUNT(*) FROM page_information WHERE all_downloaded_check = 1") == [(4,)]
    assert sorted(p.name for p in Path("img/1005").iterdir()) == ["page001.jpg", "page002.jpg", "page003.jpg"]


def test_tag_only_run(site_env):
    assert main(["-c", "-to"]) == 0  # both in one run, list first, as in 2019
    assert rows(Path("list.db"), "SELECT COUNT(*) FROM page_information") == [(4,)]
    assert not Path("img").exists()


def test_crawl_with_url(site_env, caplog):
    assert main(["-cu", site_env.gallery_url(1005)]) == 0
    assert len(list(Path("img/1005").iterdir())) == 3
    assert not Path("list.db").exists()
    assert "3 of 3 images saved" in caplog.text


def test_database_sync(site_env, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert main(["-c", "--database-path", str(other / "list.db")]) == 0
    assert main(["-ds", str(other / "list.db")]) == 0
    assert len(rows(Path("list.db"), "SELECT * FROM hentai_list")) == len(GALLERIES)


def test_database_sync_with_missing_file(capsys):
    with pytest.raises(SystemExit) as caught:
        main(["-ds", "missing.db"])
    assert caught.value.code == 2
    assert "database to merge not found" in capsys.readouterr().err


def test_ban_during_gallery_crawl_exits_255(site_env, caplog):
    assert main(["-c"]) == 0
    for gid, gallery in GALLERIES.items():
        site_env.ban[f"/g/{gid}/{gallery.url_hash}/"] = "2 hours."
    assert main(["-to", "--number-of-thread", "1"]) == EXIT_BANNED
    assert "run the same command again later" in caplog.text


def test_site_unreachable_is_a_clear_error(monkeypatch, caplog):
    monkeypatch.setenv("EHENTAI_EX_MODE", "false")
    monkeypatch.setenv("EHENTAI_EHENTAI_INDEX", "http://127.0.0.1:9/")
    monkeypatch.setenv("EHENTAI_MAX_RETRIES", "0")
    assert main(["-c"]) == 1
    assert "gave up on http://127.0.0.1:9/ after 1 attempt " in caplog.text


def test_ctrl_c_exits_130_with_a_hint(site_env, monkeypatch, caplog):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr("ehentai_crawler.cli.crawl_list", interrupted)
    assert main(["-c"]) == 130
    assert "run the same command again" in caplog.text


@pytest.mark.parametrize("command", [["main.py"], ["-m", "ehentai_crawler"]])
def test_entry_points(command, tmp_path):
    done = subprocess.run(
        [sys.executable, *command, "--version"], cwd=REPO, capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f"ehentai-crawler {__version__}"
