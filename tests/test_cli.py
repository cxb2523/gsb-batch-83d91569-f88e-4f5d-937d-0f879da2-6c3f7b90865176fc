"""Unit tests for the BuildSite Command-Line Interface."""

from pathlib import Path
from unittest.mock import patch

import pytest

from buildsite.cli import cmd_demo, cmd_init, cmd_status, cmd_validate, main


def test_cli_init_command(tmp_path: Path, monkeypatch):
    """Verify 'buildsite init' generates a valid buildsite.yml."""
    monkeypatch.chdir(tmp_path)

    with patch("sys.argv", ["buildsite", "init", "--user", "testpilot"]):
        exit_code = main()
        assert exit_code == 0

    cfg_file = tmp_path / "buildsite.yml"
    assert cfg_file.is_file()
    content = cfg_file.read_text(encoding="utf-8")
    assert "testpilot" in content
    assert "property:" in content


def test_cli_validate_command(tmp_path: Path, monkeypatch):
    """Verify 'buildsite validate' passes on valid repository assets."""
    repo_assets = Path(__file__).resolve().parent.parent / "assets"
    monkeypatch.setenv("BUILDSITE_ASSETS_DIR", str(repo_assets))
    monkeypatch.chdir(tmp_path)

    # Init config first
    with patch("sys.argv", ["buildsite", "init", "--user", "validator"]):
        main()

    with patch("sys.argv", ["buildsite", "validate"]):
        exit_code = main()
        assert exit_code == 0


def test_cli_demo_command(tmp_path: Path, monkeypatch):
    """Verify 'buildsite demo' generates SVG and PNG output files."""
    repo_assets = Path(__file__).resolve().parent.parent / "assets"
    monkeypatch.setenv("BUILDSITE_ASSETS_DIR", str(repo_assets))
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "out_demo"

    with patch("sys.argv", ["buildsite", "demo", "--count", "350", "--output-dir", str(out_dir)]):
        exit_code = main()
        assert exit_code == 0

    svg_file = out_dir / "buildsite.svg"
    png_file = out_dir / "buildsite.png"
    state_file = out_dir / "buildsite_state.json"

    assert svg_file.is_file()
    assert png_file.is_file()
    assert state_file.is_file()

    # Test status command on generated state
    with patch("sys.argv", ["buildsite", "status", "--output-dir", str(out_dir)]):
        stat_code = main()
        assert stat_code == 0


def test_generate_returns_nonzero_when_all_channels_fail(tmp_path: Path, caplog):
    """generate must fail loudly (non-zero) instead of building from bogus data."""
    import argparse
    import logging

    from buildsite.cli import cmd_generate
    from buildsite.github_api import GitHubAPIError
    from buildsite.models import UserConfig

    args = argparse.Namespace(
        config=None,
        user="ghost-architect",
        token=None,
        output_dir=str(tmp_path / "out"),
        demo=False,
        force=False,
    )

    with patch("buildsite.cli.load_config", return_value=UserConfig(username="ghost-architect")), \
         patch("buildsite.cli.fetch_contributions_public_calendar", side_effect=GitHubAPIError("no total")), \
         patch("buildsite.cli.fetch_contributions_graphql", side_effect=GitHubAPIError("graphql down")), \
         patch("buildsite.cli.fetch_contributions_rest_fallback", side_effect=GitHubAPIError("rest down")):
        with caplog.at_level(logging.ERROR, logger="buildsite"):
            exit_code = cmd_generate(args)

    assert exit_code != 0
    assert "All contribution retrieval methods failed" in caplog.text
    assert not (tmp_path / "out" / "buildsite_state.json").exists()


def test_generate_logs_selected_source_and_marks_rest_as_estimate(tmp_path: Path, caplog):
    """generate logs the adopted channel and labels REST results as estimates."""
    import argparse
    import logging

    from buildsite.cli import cmd_generate
    from buildsite.github_api import GitHubAPIError
    from buildsite.models import ContributionSnapshot, UserConfig

    repo_assets = Path(__file__).resolve().parent.parent / "assets"
    args = argparse.Namespace(
        config=None,
        user="estimate-user",
        token=None,
        output_dir=str(tmp_path / "out"),
        demo=False,
        force=True,
    )
    estimate = ContributionSnapshot(
        user_id=555,
        login="estimate-user",
        total_contributions=85,
        active_days=3,
        source="rest",
        is_estimate=True,
    )

    with patch("buildsite.cli.load_config", return_value=UserConfig(username="estimate-user")), \
         patch("buildsite.cli.find_assets_directory", return_value=repo_assets), \
         patch("buildsite.cli.fetch_contributions_public_calendar", side_effect=GitHubAPIError("no total")), \
         patch("buildsite.cli.fetch_contributions_graphql", side_effect=GitHubAPIError("graphql down")), \
         patch("buildsite.cli.fetch_contributions_rest_fallback", return_value=estimate):
        with caplog.at_level(logging.INFO, logger="buildsite"):
            exit_code = cmd_generate(args)

    assert exit_code == 0
    assert "Contribution source: rest" in caplog.text
    assert "ESTIMATED" in caplog.text
