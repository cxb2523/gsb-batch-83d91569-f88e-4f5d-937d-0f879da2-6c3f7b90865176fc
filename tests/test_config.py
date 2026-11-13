import pytest
from buildsite.config import ConfigValidationError, load_config, sanitize_output_dir, validate_hex_color


def test_sanitize_output_dir_blocks_traversal_and_unsafe_paths():
    assert sanitize_output_dir("") == "assets/buildsite"
    assert sanitize_output_dir("  ./out/dir  ") == "out/dir"
    assert sanitize_output_dir("assets\\sub\\dir") == "assets/sub/dir"

    unsafe_inputs = [
        "../outside",
        "assets/../../escape",
        "assets\\..\\..\\escape",
        "/etc/passwd",
        "C:\\Windows\\System32",
        "D:relative_drive",
        "bad\x00dir",
    ]
    for bad in unsafe_inputs:
        with pytest.raises(ConfigValidationError):
            sanitize_output_dir(bad)


def test_validate_hex_color():
    assert validate_hex_color("#0ea5e9") == "#0EA5E9"
    assert validate_hex_color(" #abc ") == "#ABC"
    assert validate_hex_color("#12345678") == "#12345678"
    # CSS injection payloads and invalid hex return safe fallback
    assert validate_hex_color("red; background: url(evil)", fallback="#112233") == "#112233"
    assert validate_hex_color("#GGGGGG") == "#000000"
    assert validate_hex_color(None) == "#000000"


def test_load_config_strict_render_dimension_validation(tmp_path):
    cfg_file = tmp_path / "buildsite.yml"
    cfg_file.write_text(
        "render:\n  width: true\n  height: 600\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match="render.width"):
        load_config(str(cfg_file))

    cfg_bad_int = tmp_path / "buildsite_bad.yml"
    cfg_bad_int.write_text(
        "render:\n  width: 'not_a_number'\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError, match="render.width"):
        load_config(str(cfg_bad_int))

    cfg_ok = tmp_path / "buildsite_ok.yml"
    cfg_ok.write_text(
        "github:\n  username: testuser\nrender:\n  width: 5000\n  height: 100\noutput:\n  directory: dist/svg\n",
        encoding="utf-8",
    )
    loaded = load_config(str(cfg_ok))
    assert loaded.username == "testuser"
    assert loaded.width == 2560
    assert loaded.height == 200
    assert loaded.output_dir == "dist/svg"
