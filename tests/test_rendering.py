"""Tests for image compositing, SVG generation, XML compliance, and accessibility."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from buildsite.composer import composite_property, find_assets_directory
from buildsite.models import ContributionSnapshot, PropertyState, UserConfig
from buildsite.progression import calculate_property_state
from buildsite.svg_export import (
    escape_xml_text,
    export_png_fallback,
    export_svg_to_file,
    generate_svg,
    strip_invalid_xml_chars,
)


def test_composite_property_layers():
    """Verify that compositing active layers produces a valid 1280x640 RGBA image."""
    snap = ContributionSnapshot(user_id=123, login="alice", total_contributions=250, active_days=100)
    cfg = UserConfig()
    state = calculate_property_state(snap, cfg)

    assets_dir = find_assets_directory()
    assert assets_dir.is_dir()

    img = composite_property(state, cfg, assets_dir=assets_dir)
    assert isinstance(img, Image.Image)
    assert img.size == (1280, 640)
    assert img.mode == "RGBA"


def test_svg_valid_xml_and_standards():
    """Verify that generated SVG is well-formed XML and complies with security rules."""
    snap = ContributionSnapshot(user_id=456, login="bob", total_contributions=350, active_days=120)
    cfg = UserConfig()
    state = calculate_property_state(snap, cfg)
    assets_dir = find_assets_directory()
    img = composite_property(state, cfg, assets_dir=assets_dir)

    svg_str = generate_svg(state, cfg, img)

    # 1. XML parse validity
    root = ET.fromstring(svg_str)
    assert "svg" in root.tag.lower()
    assert root.attrib.get("viewBox") == "0 0 1280 640"
    assert root.attrib.get("role") == "img"

    # 2. Accessibility
    assert "aria-labelledby" in root.attrib
    assert "<title" in svg_str
    assert "<desc" in svg_str
    assert "bob" in svg_str
    assert "350" in svg_str

    # 3. Security: No external dependencies or scripts
    assert "<script" not in svg_str.lower()
    assert "<iframe" not in svg_str.lower()
    assert "<foreignobject" not in svg_str.lower()
    # Check that any http(s) URL is only the standard W3C XML namespace
    for word in svg_str.split('"'):
        if word.startswith("http://") or word.startswith("https://"):
            assert "www.w3.org" in word

    # 4. Self-contained image
    assert "data:image/png;base64," in svg_str


def test_animation_and_reduced_motion():
    """Verify CSS animation keyframes and accessibility media query."""
    snap = ContributionSnapshot(user_id=789, login="charlie", total_contributions=500, active_days=180)
    cfg_subtle = UserConfig(animation="subtle")
    state = calculate_property_state(snap, cfg_subtle)
    assets_dir = find_assets_directory()
    img = composite_property(state, cfg_subtle, assets_dir=assets_dir)

    svg_subtle = generate_svg(state, cfg_subtle, img)
    assert "@keyframes" in svg_subtle
    assert "prefers-reduced-motion" in svg_subtle

    # When animation is none
    cfg_none = UserConfig(animation="none")
    svg_none = generate_svg(state, cfg_none, img)
    assert "@keyframes" not in svg_none


def test_png_fallback_export(tmp_path: Path):
    """Verify PNG fallback export creates valid image file on disk."""
    snap = ContributionSnapshot(user_id=999, login="diana", total_contributions=75, active_days=40)
    cfg = UserConfig()
    state = calculate_property_state(snap, cfg)
    assets_dir = find_assets_directory()
    img = composite_property(state, cfg, assets_dir=assets_dir)

    out_png = tmp_path / "fallback.png"
    export_png_fallback(img, out_png)

    assert out_png.is_file()
    loaded = Image.open(out_png)
    assert loaded.size == (1280, 640)


def test_fixture_progression_visuals(tmp_path: Path):
    """Visual regression test verifying property evolution at key contribution counts:
    0, 1, 10, 50, 100, 250, 500, 1,000, and 10,000.
    """
    counts = [0, 1, 10, 50, 100, 250, 500, 1000, 10000]
    assets_dir = find_assets_directory()
    cfg = UserConfig()

    for c in counts:
        snap = ContributionSnapshot(user_id=1000 + c, login=f"dev-{c}", total_contributions=c, active_days=min(c, 200))
        state = calculate_property_state(snap, cfg)
        img = composite_property(state, cfg, assets_dir=assets_dir)
        svg_str = generate_svg(state, cfg, img)

        out_svg = tmp_path / f"buildsite_{c}.svg"
        export_svg_to_file(svg_str, out_svg)
        assert out_svg.is_file()
        assert out_svg.stat().st_size > 1000


def test_responsive_hud_layout_on_narrow_viewports():
    """Verify that narrow canvas widths stack HUD cards vertically to prevent overlap."""
    snap = ContributionSnapshot(user_id=123, login="alice", total_contributions=150, active_days=50)
    cfg_narrow = UserConfig(width=600, height=400)
    state = calculate_property_state(snap, cfg_narrow)
    img_narrow = Image.new("RGBA", (600, 400), (30, 40, 50, 255))

    svg_narrow = generate_svg(state, cfg_narrow, img_narrow)
    root = ET.fromstring(svg_narrow)
    assert root.attrib.get("viewBox") == "0 0 600 400"
    assert 'transform="translate(32, 148)"' in svg_narrow

    # Standard wide view
    cfg_wide = UserConfig(width=1280, height=640)
    img_wide = Image.new("RGBA", (1280, 640), (30, 40, 50, 255))
    svg_wide = generate_svg(state, cfg_wide, img_wide)
    assert f'transform="translate({1280 - 240}, 28)"' in svg_wide


def test_svg_xml_entity_escaping_no_double_escaping_or_injection():
    """Verify XML special characters are escaped cleanly in a single pass across all text nodes."""
    malicious_login = 'O\'Neil & "Dev"</text><script>alert(1)</script>'
    snap = ContributionSnapshot(user_id=77, login=malicious_login, total_contributions=250, active_days=60)
    cfg = UserConfig()
    state = calculate_property_state(snap, cfg)
    img = Image.new("RGBA", (1280, 640), (30, 40, 50, 255))

    svg_str = generate_svg(state, cfg, img)

    # Injection tags must remain escaped text, not raw elements
    assert "<script>" not in svg_str
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in svg_str
    # Must never double-escape in <desc>
    assert "&amp;amp;" not in svg_str
    assert "&amp;lt;" not in svg_str
    assert "&amp;apos;" not in svg_str
    assert "&amp;#x27;" not in svg_str

    root = ET.fromstring(svg_str)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    title_el = root.find("svg:title", ns)
    desc_el = root.find("svg:desc", ns)
    assert title_el is not None and title_el.text is not None
    assert desc_el is not None and desc_el.text is not None
    assert malicious_login in title_el.text
    assert malicious_login in desc_el.text


def test_svg_strips_xml_forbidden_control_characters():
    """Verify illegal XML 1.0 control characters are stripped so ET parsing never crashes."""
    assert strip_invalid_xml_chars("\x00\x07\x1f", fallback="Developer") == "Developer"
    assert escape_xml_text("a\x00&\x0b'b\"c<d>e") == "a&amp;&apos;b&quot;c&lt;d&gt;e"

    cfg = UserConfig()
    for raw_login, expected in [
        ("ali\x00ce\x07", "alice"),
        ("\x00\x08\x0c\x1f\x7f", "Developer"),
    ]:
        snap = ContributionSnapshot(user_id=88, login=raw_login, total_contributions=120, active_days=30)
        state = calculate_property_state(snap, cfg)
        img = Image.new("RGBA", (1280, 640), (30, 40, 50, 255))

        svg_str = generate_svg(state, cfg, img)
        root = ET.fromstring(svg_str)
        ns = {"svg": "http://www.w3.org/2000/svg"}
        title_el = root.find("svg:title", ns)
        assert title_el is not None and title_el.text is not None
        assert expected in title_el.text
