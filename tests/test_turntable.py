"""Unit tests for the 360-Degree Architectural 3D Turntable Generator."""

import math
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

from buildsite.models import PropertyState, UserConfig
from buildsite.turntable import (
    HEIGHT,
    WIDTH,
    Face,
    build_estate_faces,
    generate_animated_turntable,
    make_box_faces,
    make_tree_faces,
    project_rot,
    render_scene_at_angle,
    rotate_coords,
)


def test_make_box_faces():
    """Verify 3D box generation creates 6 planar faces with accurate normals."""
    faces = make_box_faces(10, 20, 30, 40, 50, 60, (255, 0, 0), alpha=200, ambient=0.5)
    assert len(faces) == 6

    normals = [f.normal for f in faces]
    assert (0, 0, 1) in normals   # Top
    assert (0, 1, 0) in normals   # Front
    assert (1, 0, 0) in normals   # Right
    assert (0, -1, 0) in normals  # Back
    assert (-1, 0, 0) in normals  # Left
    assert (0, 0, -1) in normals  # Bottom

    for f in faces:
        assert len(f.pts) == 4
        assert f.color == (255, 0, 0)
        assert f.alpha == 200
        assert f.ambient == 0.5


def test_make_tree_faces():
    """Verify pyramidal tree generation produces trunk and canopy faces."""
    faces = make_tree_faces(0, 0, 0, 50, radius=10.0)
    # 6 trunk faces + 4 canopy pyramid sides = 10 faces
    assert len(faces) == 10
    assert any(len(f.pts) == 3 for f in faces)  # Triangular canopy faces


def test_build_estate_faces():
    """Verify complete architectural estate assembly produces all structural elements."""
    faces = build_estate_faces()
    assert len(faces) > 100

    # Ensure all faces have valid vertices and colors
    for f in faces:
        assert len(f.pts) >= 3
        assert len(f.color) == 3
        assert 0 <= f.alpha <= 255
        assert 0.0 <= f.ambient <= 1.0


def test_coordinate_rotation_and_projection():
    """Verify 2D rotation geometry and isometric screen projection."""
    # 0 radians: (x, y) unchanged
    rx, ry = rotate_coords(10.0, 20.0, 0.0)
    assert pytest.approx(rx, 1e-4) == 10.0
    assert pytest.approx(ry, 1e-4) == 20.0

    # 90 degrees (pi/2): (x, y) -> (-y, x)
    rx90, ry90 = rotate_coords(10.0, 20.0, math.pi / 2)
    assert pytest.approx(rx90, 1e-4) == -20.0
    assert pytest.approx(ry90, 1e-4) == 10.0

    # 180 degrees (pi): (x, y) -> (-x, -y)
    rx180, ry180 = rotate_coords(10.0, 20.0, math.pi)
    assert pytest.approx(rx180, 1e-4) == -10.0
    assert pytest.approx(ry180, 1e-4) == -20.0

    # Isometric projection onto viewport
    sx, sy = project_rot(0.0, 0.0, 0.0, 0.0)
    assert sx == 640.0
    assert sy == 415.0


def test_render_scene_at_angle():
    """Verify rendering scene at an angle produces a full-frame RGBA image."""
    faces = make_box_faces(-50, -50, 0, 100, 100, 50, (200, 100, 50))
    img = render_scene_at_angle(faces, 0.0)

    assert isinstance(img, Image.Image)
    assert img.size == (WIDTH, HEIGHT)
    assert img.mode == "RGBA"

    # Verify not completely transparent
    extrema = img.getextrema()
    # Alpha channel should have opaque values
    assert extrema[3][1] > 0


def test_generate_animated_turntable(tmp_path: Path):
    """Verify turntable generation creates animated WebP and valid SVG files."""
    state = PropertyState(
        login="architect",
        total_contributions=1650,
        milestone=7,
    )
    config = UserConfig(username="architect")

    webp_path = tmp_path / "renders" / "turntable.webp"
    svg_path = tmp_path / "renders" / "turntable.svg"

    # Run with 2 frames for fast test execution
    generate_animated_turntable(state, config, webp_path, svg_path, num_frames=2)

    assert webp_path.is_file()
    assert webp_path.stat().st_size > 0
    assert svg_path.is_file()
    assert svg_path.stat().st_size > 0

    # Verify SVG content and XML structure
    svg_content = svg_path.read_text(encoding="utf-8")
    assert "<svg" in svg_content
    assert "BuildSite 360" in svg_content
    assert "architect" in svg_content
    assert "1,650" in svg_content
    assert "@keyframes showFrame0" in svg_content
    assert "@keyframes showFrame1" in svg_content
    assert "prefers-reduced-motion" in svg_content

    # Parse XML to guarantee strict well-formedness
    root = ET.fromstring(svg_content)
    assert "svg" in root.tag.lower()


def test_generate_animated_turntable_invalid_frames(tmp_path: Path):
    """Verify error handling when invalid frame counts are requested."""
    state = PropertyState(login="tester", total_contributions=100, milestone=3)
    config = UserConfig(username="tester")

    with pytest.raises(ValueError, match="num_frames must be at least 1"):
        generate_animated_turntable(
            state, config, tmp_path / "out.webp", tmp_path / "out.svg", num_frames=0
        )


def test_generate_animated_turntable_xml_escaping_and_control_chars(tmp_path: Path):
    """Verify 360 turntable SVG safely escapes entities and strips invalid XML control chars."""
    raw_login = 'A&B\x00<img src="x">'
    state = PropertyState(login=raw_login, total_contributions=500, milestone=5)
    config = UserConfig(username="tester")

    webp_path = tmp_path / "safe.webp"
    svg_path = tmp_path / "safe.svg"
    generate_animated_turntable(state, config, webp_path, svg_path, num_frames=1)

    svg_content = svg_path.read_text(encoding="utf-8")
    assert "<img " not in svg_content
    root = ET.fromstring(svg_content)
    ns = {"svg": "http://www.w3.org/2000/svg"}
    title_el = root.find("svg:title", ns)
    assert title_el is not None and title_el.text is not None
    assert 'A&B<img src="x">' in title_el.text
