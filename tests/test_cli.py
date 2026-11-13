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
