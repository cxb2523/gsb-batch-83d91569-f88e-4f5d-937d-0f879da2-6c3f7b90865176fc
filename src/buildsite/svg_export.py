"""SVG and PNG export engine for BuildSite.

Generates self-contained, standards-compliant SVG documents containing
base64-embedded photorealistic architectural renderings, crisp native vector HUD
overlays, accessible metadata, and declarative CSS keyframe animations.
"""

from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from typing import Optional
from xml.sax.saxutils import escape as xml_escape

# XML 1.0 valid character ranges exclude C0 controls (except TAB, LF, CR),
# DEL/C1 controls (except NEL), UTF-16 surrogates, and U+FFFE/U+FFFF noncharacters.
_XML_INVALID_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f\ud800-\udfff\ufdd0-\ufdef\ufffe\uffff]"
)
_XML_ENTITY_MAP = {"'": "&apos;", '"': "&quot;"}


def strip_invalid_xml_chars(text: Optional[str], fallback: str = "") -> str:
    """Remove characters forbidden by XML 1.0 and return fallback if empty."""
    cleaned = _XML_INVALID_CHARS_RE.sub("", text or "")
    return cleaned if cleaned else fallback


def escape_xml_text(text: Optional[str], fallback: str = "") -> str:
    """Strip invalid XML 1.0 control characters and escape all XML entities once."""
    cleaned = strip_invalid_xml_chars(text, fallback=fallback)
    return xml_escape(cleaned, entities=_XML_ENTITY_MAP)

from PIL import Image

from buildsite.models import PropertyState, UserConfig
from buildsite.progression import calculate_micro_evolution, get_milestone_spec


def image_to_base64_data_uri(image: Image.Image, format: str = "PNG") -> str:
    """Encode Pillow image into base64 data URI."""
    buf = io.BytesIO()
    # JPEG optimization for background photography if opaque, PNG for alpha
    if format.upper() == "JPEG":
        rgb_img = image.convert("RGB")
        rgb_img.save(buf, format="JPEG", quality=90, optimize=True)
        mime = "image/jpeg"
    else:
        image.save(buf, format="PNG", optimize=True)
        mime = "image/png"
    b64_str = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:{mime};base64,{b64_str}"


def generate_svg(state: PropertyState, config: UserConfig, rendered_image: Image.Image) -> str:
    """Generate self-contained standards-compliant SVG document.

    Args:
        state: Current property state with contributions and progress.
        config: User configuration.
        rendered_image: Composite property image from composer.

    Returns:
        Complete SVG XML string.
    """
    width = max(1, int(config.width))
    height = max(1, int(config.height))
    micro = calculate_micro_evolution(state.total_contributions)
    spec = get_milestone_spec(state.milestone)

    # Encode rendered photographic architectural layer
    data_uri = image_to_base64_data_uri(rendered_image, format="PNG")

    # Strip invalid XML control chars cleanly before single-pass entity escaping
    login_clean = strip_invalid_xml_chars(state.login, fallback="Developer")
    milestone_clean = strip_invalid_xml_chars(spec.title)
    next_clean = strip_invalid_xml_chars(micro.next_upgrade_title)

    login_safe = escape_xml_text(login_clean)
    milestone_title_safe = escape_xml_text(milestone_clean)
    next_title_safe = escape_xml_text(next_clean)
    contributions_str = f"{state.total_contributions:,}"
    to_next_str = f"{micro.contributions_to_next:,}"
    percent_int = int(round(micro.progress_ratio * 100))

    # Responsive HUD positioning: stack cards vertically on narrow screens (<680px)
    hud_counter_transform = f"translate({width - 240}, 28)" if width >= 680 else "translate(32, 148)"

    # Accessible description built from unescaped text, then XML-escaped once at insertion
    alt_desc = (
        f"BuildSite architectural residence for {login_clean}. "
        f"Stage: {milestone_clean}. Verified Contributions: {contributions_str}. "
        f"Progress to next milestone: {percent_int}%. Next upgrade: {next_clean}."
    )

    # Declarative animation styles (active only when subtle animation enabled)
    animation_css = ""
    if config.animation == "subtle":
        animation_css = """
      @keyframes pulseGlow {
        0%, 100% { opacity: 0.85; filter: drop-shadow(0 0 4px rgba(0, 220, 255, 0.4)); }
        50% { opacity: 1.0; filter: drop-shadow(0 0 10px rgba(0, 220, 255, 0.8)); }
      }
      @keyframes breatheDot {
        0%, 100% { transform: scale(1.0); opacity: 0.9; }
        50% { transform: scale(1.25); opacity: 1.0; }
      }
      .anim-glow {
        animation: pulseGlow 4s ease-in-out infinite;
      }
      .anim-dot {
        animation: breatheDot 2.5s ease-in-out infinite;
        transform-origin: 48px 48px;
      }
"""

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 {width} {height}"
     width="{width}"
     height="{height}"
     role="img"
     aria-labelledby="title desc">
  <title id="title">BuildSite — {login_safe}'s Evolving Home</title>
  <desc id="desc">{escape_xml_text(alt_desc)}</desc>

  <defs>
    <linearGradient id="cardGrad" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="#0F172A" stop-opacity="0.90"/>
      <stop offset="100%" stop-color="#1E293B" stop-opacity="0.95"/>
    </linearGradient>
    <linearGradient id="barGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0EA5E9"/>
      <stop offset="50%" stop-color="#38BDF8"/>
      <stop offset="100%" stop-color="#2DD4BF"/>
    </linearGradient>
    <filter id="cardShadow" x="-10%" y="-10%" width="120%" height="130%">
      <feDropShadow dx="0" dy="8" stdDeviation="12" flood-color="#000000" flood-opacity="0.35"/>
    </filter>
  </defs>

  <style>
    .font-sans {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }}
    .text-title {{ font-size: 14px; font-weight: 700; fill: #F8FAFC; letter-spacing: 0.5px; }}
    .text-subtitle {{ font-size: 11px; font-weight: 500; fill: #94A3B8; }}
    .text-value {{ font-size: 15px; font-weight: 700; fill: #38BDF8; }}
    .text-label {{ font-size: 10px; font-weight: 600; text-transform: uppercase; fill: #64748B; letter-spacing: 0.8px; }}
    .text-badge {{ font-size: 10px; font-weight: 700; fill: #2DD4BF; letter-spacing: 0.6px; }}
{animation_css}
    @media (prefers-reduced-motion: reduce) {{
      .anim-glow, .anim-dot {{
        animation: none !important;
      }}
    }}
  </style>

  <!-- Base Photorealistic Architectural Render Layer -->
  <image href="{data_uri}" width="{width}" height="{height}" preserveAspectRatio="xMidYMid meet" />

  <!-- Subtle Outer Border Frame -->
  <rect x="1" y="1" width="{max(1, width - 2)}" height="{max(1, height - 2)}" rx="12" fill="none" stroke="#334155" stroke-width="1.5" stroke-opacity="0.6"/>

  <!-- Top-Left Architectural Status Badge HUD -->
  <g class="font-sans" transform="translate(32, 28)" filter="url(#cardShadow)">
    <!-- HUD Backdrop Card -->
    <rect x="0" y="0" width="370" height="112" rx="10" fill="url(#cardGrad)" stroke="#334155" stroke-width="1" stroke-opacity="0.8"/>

    <!-- Status Indicator Dot -->
    <circle class="anim-dot" cx="22" cy="22" r="5" fill="#2DD4BF"/>

    <!-- Brand & Username -->
    <text x="36" y="24" class="text-title">BuildSite</text>
    <text x="108" y="24" class="text-subtitle">• @{login_safe}</text>

    <!-- Project & Milestone -->
    <text x="20" y="48" class="text-label">Active Project</text>
    <text x="20" y="66" class="text-title">{milestone_title_safe}</text>

    <!-- Progress Bar Track -->
    <rect x="20" y="78" width="330" height="6" rx="3" fill="#334155" fill-opacity="0.7"/>
    <!-- Progress Bar Fill -->
    <rect x="20" y="78" width="{min(330, max(6, int(330 * micro.progress_ratio)))}" height="6" rx="3" fill="url(#barGrad)"/>

    <!-- Next Unlock Indicator -->
    <text x="20" y="98" class="text-subtitle">Next: {next_title_safe} ({to_next_str} to unlock)</text>
    <text x="350" y="98" text-anchor="end" class="text-badge">{percent_int}%</text>
  </g>

  <!-- Contribution Counter HUD Card (stacked below status card on viewports < 680px) -->
  <g class="font-sans" transform="{hud_counter_transform}" filter="url(#cardShadow)">
    <rect x="0" y="0" width="208" height="68" rx="10" fill="url(#cardGrad)" stroke="#334155" stroke-width="1" stroke-opacity="0.8"/>
    <text x="18" y="24" class="text-label">Verified Contributions</text>
    <text x="18" y="50" class="text-value">{contributions_str}</text>
    <text x="190" y="50" text-anchor="end" class="text-subtitle">GitHub verified</text>
  </g>

  <!-- Bottom-Right Watermark / Tagline -->
  <g class="font-sans" transform="translate({width - 230}, {height - 24})">
    <text x="200" y="0" text-anchor="end" font-size="11" font-weight="500" fill="#CBD5E1" fill-opacity="0.75">
      Your GitHub Builds Your Home
    </text>
  </g>
</svg>"""
    return svg_content


def export_svg_to_file(
    svg_string: str,
    output_path: Path
) -> Path:
    """Save SVG string to designated path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(svg_string)
    return output_path


def export_png_fallback(
    rendered_image: Image.Image,
    output_path: Path
) -> Path:
    """Export fallback PNG image."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_image.save(output_path, format="PNG", optimize=True)
    return output_path
