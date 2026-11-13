"""Configuration parser and validator for BuildSite.

Reads and validates user settings from buildsite.yml with strong schema
guarantees and security hardening against path traversal or injection.
"""

from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from buildsite.models import UserConfig


class ConfigValidationError(Exception):
    """Raised when configuration values are invalid or unsafe."""


VALID_LIGHTING_MODES = {"daytime", "dusk", "night"}
VALID_FORMATS = {"svg", "png"}
VALID_ANIMATION_MODES = {"subtle", "none"}
VALID_VISIBILITIES = {"public", "private"}
VALID_STYLES = {"auto", "modern", "minimal", "timber", "slate", "coastal"}
_DRIVE_LETTER_RE = re.compile(r"^[A-Za-z]:")
_HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def validate_hex_color(color: Any, fallback: str = "#000000") -> str:
    """Validate and normalize a CSS hex color string, returning fallback if unsafe."""
    if not isinstance(color, str):
        return fallback
    cleaned = color.strip()
    if _HEX_COLOR_RE.match(cleaned):
        return cleaned.upper()
    return fallback


def _parse_bounded_int(value: Any, default: int, min_val: int, max_val: int, field_name: str) -> int:
    """Parse an integer config value strictly, rejecting booleans and malformed strings."""
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ConfigValidationError(f"Invalid integer value for '{field_name}': {value!r}")
    if isinstance(value, float):
        if value != int(value):
            raise ConfigValidationError(f"Non-integer value for '{field_name}': {value!r}")
        parsed = int(value)
    elif isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError as exc:
            raise ConfigValidationError(f"Invalid integer value for '{field_name}': {value!r}") from exc
    else:
        parsed = int(value)
    return max(min_val, min(max_val, parsed))


def sanitize_output_dir(path_str: str) -> str:
    """Sanitize and validate output directory to prevent path traversal."""
    if not isinstance(path_str, str):
        raise ConfigValidationError("Output directory path must be a string.")
    if "\x00" in path_str:
        raise ConfigValidationError("Output directory path contains null bytes.")
    cleaned = path_str.strip()
    if not cleaned:
        return "assets/buildsite"
    # Normalize slashes across Windows/POSIX before checking traversal or drive roots
    posix_path = cleaned.replace("\\", "/")
    if (
        posix_path.startswith("/")
        or _DRIVE_LETTER_RE.match(posix_path)
        or os.path.isabs(cleaned)
    ):
        raise ConfigValidationError(
            f"Unsafe output directory path '{path_str}'. Path must be relative and within the repository."
        )
    normalized = posixpath.normpath(posix_path)
    if normalized == ".." or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ConfigValidationError(
            f"Unsafe output directory path '{path_str}'. Path must not escape repository root."
        )
    return "assets/buildsite" if normalized == "." else normalized


def load_config(config_path: Optional[str] = None) -> UserConfig:
    """Load and validate UserConfig from YAML file or default search paths."""
    search_paths = []
    if config_path:
        search_paths.append(Path(config_path))
    else:
        search_paths.extend([
            Path("buildsite.yml"),
            Path("buildsite.yaml"),
            Path(".buildsite.yml"),
            Path(".github/buildsite.yml")
        ])

    raw_data: Dict[str, Any] = {}
    found_path: Optional[Path] = None

    for p in search_paths:
        if p.is_file():
            found_path = p
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, dict):
                        raw_data = content
            except Exception as exc:
                raise ConfigValidationError(f"Failed to parse YAML from {p}: {exc}") from exc
            break

    cfg = UserConfig()

    # Extract github section
    gh_sec = raw_data.get("github", {})
    if isinstance(gh_sec, dict):
        cfg.username = str(gh_sec.get("username", "")).strip()
        vis = str(gh_sec.get("visibility", "public")).lower()
        if vis in VALID_VISIBILITIES:
            cfg.visibility = vis

    # Extract property section
    prop_sec = raw_data.get("property", {})
    if isinstance(prop_sec, dict):
        style = str(prop_sec.get("style", "modern")).lower()
        if style in VALID_STYLES:
            cfg.style = style
        cfg.seed = str(prop_sec.get("seed", "auto")).strip()
        cfg.palette = str(prop_sec.get("palette", "natural")).lower()
        cfg.pool = bool(prop_sec.get("pool", True))
        cfg.garden = bool(prop_sec.get("garden", True))
        cfg.garage = bool(prop_sec.get("garage", True))
        lighting = str(prop_sec.get("lighting", "dusk")).lower()
        if lighting in VALID_LIGHTING_MODES:
            cfg.lighting = lighting

    # Extract render section
    render_sec = raw_data.get("render", {})
    if isinstance(render_sec, dict):
        cfg.width = _parse_bounded_int(render_sec.get("width"), 1280, 400, 2560, "render.width")
        cfg.height = _parse_bounded_int(render_sec.get("height"), 640, 200, 1440, "render.height")
        fmt = str(render_sec.get("format", "svg")).lower()
        if fmt in VALID_FORMATS:
            cfg.format = fmt
        anim = str(render_sec.get("animation", "subtle")).lower()
        if anim in VALID_ANIMATION_MODES:
            cfg.animation = anim
        cfg.quality = str(render_sec.get("quality", "high")).lower()

    # Extract progression section
    prog_sec = raw_data.get("progression", {})
    if isinstance(prog_sec, dict):
        cfg.preserve_unlocks = bool(prog_sec.get("preserve_unlocks", True))

    # Extract output section
    out_sec = raw_data.get("output", {})
    if isinstance(out_sec, dict):
        raw_dir = str(out_sec.get("directory", "assets/buildsite"))
        cfg.output_dir = sanitize_output_dir(raw_dir)
        cfg.png_fallback = bool(out_sec.get("png_fallback", True))

    return cfg
