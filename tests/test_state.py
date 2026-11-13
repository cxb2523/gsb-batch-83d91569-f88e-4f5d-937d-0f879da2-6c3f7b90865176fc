"""Unit tests for state persistence, reconciliation, and schema migration."""

from pathlib import Path

import pytest

from buildsite.models import ConstructionMilestone, PropertyState
from buildsite.state import CURRENT_SCHEMA_VERSION, has_state_changed, load_state, save_state


def test_save_and_load_state(tmp_path: Path):
    """Verify state can be saved and accurately loaded."""
    state_file = tmp_path / "buildsite_state.json"
    state = PropertyState(
        schema_version=CURRENT_SCHEMA_VERSION,
        user_id=12345,
        login="octocat",
        seed="12345:octocat",
        total_contributions=320,
        active_days=110,
        milestone=ConstructionMilestone.GARDEN,
        progress_ratio=0.15,
        active_layers=["plot_base", "villa_finished", "swimming_pool", "gardens"],
        unlocked_features=["lawn", "cypress"],
        hash_signature="abc123hash"
    )

    save_state(state, state_file)
    assert state_file.is_file()

    loaded = load_state(state_file)
    assert loaded is not None
    assert loaded.user_id == 12345
    assert loaded.login == "octocat"
    assert loaded.total_contributions == 320
    assert loaded.milestone == ConstructionMilestone.GARDEN
    assert loaded.hash_signature == "abc123hash"
    assert loaded.active_layers == ["plot_base", "villa_finished", "swimming_pool", "gardens"]


def test_state_change_detection():
    """Verify has_state_changed detects identical vs updated states."""
    s1 = PropertyState(
        user_id=1,
        login="dev",
        total_contributions=100,
        milestone=ConstructionMilestone.ROOF_ENCLOSURE,
        hash_signature="sig_initial"
    )
    assert has_state_changed(None, s1) is True

    s2 = PropertyState(
        user_id=1,
        login="dev",
        total_contributions=100,
        milestone=ConstructionMilestone.ROOF_ENCLOSURE,
        hash_signature="sig_initial"
    )
    assert has_state_changed(s1, s2) is False

    s3 = PropertyState(
        user_id=1,
        login="dev",
        total_contributions=101,
        milestone=ConstructionMilestone.FINISHING,
        hash_signature="sig_updated"
    )
    assert has_state_changed(s1, s3) is True


def test_load_nonexistent_state(tmp_path: Path):
    """Loading nonexistent state returns None without error."""
    missing = tmp_path / "does_not_exist.json"
    assert load_state(missing) is None


def test_load_corrupt_and_non_dict_state_returns_none(tmp_path: Path):
    """Corrupt JSON or non-object JSON returns None cleanly without logging TypeError."""
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    assert load_state(corrupt) is None

    non_dict = tmp_path / "list_state.json"
    non_dict.write_text('["unexpected", "list"]', encoding="utf-8")
    assert load_state(non_dict) is None
