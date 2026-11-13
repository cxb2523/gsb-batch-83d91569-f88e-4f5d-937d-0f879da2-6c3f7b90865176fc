"""360-Degree Architectural 3D Turntable Generator for BuildSite.

Renders multi-angle rotation frames of the estate around the vertical Z-axis
using depth-sorted back-to-front rendering with backface culling, and compiles
them into an animated 3D turntable WebP and multi-frame SVG for direct inline
display in GitHub READMEs.
"""

from __future__ import annotations

import base64
import io
import logging
import math
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

from buildsite.models import PropertyState, UserConfig
from buildsite.progression import calculate_micro_evolution, get_milestone_spec
from buildsite.svg_export import escape_xml_text

logger = logging.getLogger(__name__)

WIDTH = 1280
HEIGHT = 640
ORIGIN_X = 640.0
ORIGIN_Y = 415.0
AXIS_X = (0.866025, 0.48)
AXIS_Y = (-0.866025, 0.48)
AXIS_Z = (0.0, -1.0)

VIEW_DIR = (1.0, 1.0, 1.35)
vmag = math.sqrt(sum(x * x for x in VIEW_DIR))
VIEW_NORM = (VIEW_DIR[0] / vmag, VIEW_DIR[1] / vmag, VIEW_DIR[2] / vmag)

SUN_DIR = (0.55, -0.65, 0.70)
smag = math.sqrt(sum(x * x for x in SUN_DIR))
SUN_NORM = (SUN_DIR[0] / smag, SUN_DIR[1] / smag, SUN_DIR[2] / smag)


class Face:
    def __init__(
        self,
        pts: List[Tuple[float, float, float]],
        normal: Tuple[float, float, float],
        color: Tuple[int, int, int],
        alpha: int = 255,
        ambient: float = 0.45,
    ):
        self.pts = pts
        self.normal = normal
        self.color = color
        self.alpha = alpha
        self.ambient = ambient
        n = len(pts)
        self.cx = sum(p[0] for p in pts) / n
        self.cy = sum(p[1] for p in pts) / n
        self.cz = sum(p[2] for p in pts) / n


def rotate_coords(x: float, y: float, angle_rad: float) -> Tuple[float, float]:
    """Rotate (x, y) coordinates around origin by angle."""
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def project_rot(x: float, y: float, z: float, angle_rad: float) -> Tuple[float, float]:
    """Project 3D coordinates rotated by angle around Z axis."""
    rx, ry = rotate_coords(x, y, angle_rad)
    sx = ORIGIN_X + rx * AXIS_X[0] + ry * AXIS_Y[0] + z * AXIS_Z[0]
    sy = ORIGIN_Y + rx * AXIS_X[1] + ry * AXIS_Y[1] + z * AXIS_Z[1]
    return (sx, sy)


def make_box_faces(
    x: float,
    y: float,
    z: float,
    dx: float,
    dy: float,
    dz: float,
    color: Tuple[int, int, int],
    alpha: int = 255,
    ambient: float = 0.45,
) -> List[Face]:
    """Generate 6 faces for a 3D box."""
    return [
        # Top (+Z)
        Face([(x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)], (0, 0, 1), color, alpha, ambient),
        # Front (+Y)
        Face([(x, y + dy, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)], (0, 1, 0), color, alpha, ambient),
        # Right (+X)
        Face([(x + dx, y, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x + dx, y, z + dz)], (1, 0, 0), color, alpha, ambient),
        # Back (-Y)
        Face([(x, y, z), (x, y, z + dz), (x + dx, y, z + dz), (x + dx, y, z)], (0, -1, 0), color, alpha, ambient),
        # Left (-X)
        Face([(x, y, z), (x, y + dy, z), (x, y + dy, z + dz), (x, y, z + dz)], (-1, 0, 0), color, alpha, ambient),
        # Bottom (-Z)
        Face([(x, y, z), (x + dx, y, z), (x + dx, y + dy, z), (x, y + dy, z)], (0, 0, -1), color, alpha, ambient),
    ]


def make_tree_faces(cx: float, cy: float, cz: float, h: float, radius: float = 14.0) -> List[Face]:
    """Generate pyramidal cypress tree faces."""
    faces = []
    # Trunk
    faces.extend(make_box_faces(cx - 2, cy - 2, cz, 4, 4, 14, (72, 50, 36), ambient=0.35))
    # Foliage pyramid (4 sides)
    tip = (cx, cy, cz + h)
    p_s = (cx, cy + radius, cz + 14)
    p_e = (cx + radius, cy, cz + 14)
    p_n = (cx, cy - radius, cz + 14)
    p_w = (cx - radius, cy, cz + 14)
    c_foliage = (32, 85, 48)
    faces.append(Face([p_s, p_e, tip], (0.7, 0.7, 0.3), c_foliage, ambient=0.5))
    faces.append(Face([p_e, p_n, tip], (0.7, -0.7, 0.3), c_foliage, ambient=0.4))
    faces.append(Face([p_n, p_w, tip], (-0.7, -0.7, 0.3), c_foliage, ambient=0.4))
    faces.append(Face([p_w, p_s, tip], (-0.7, 0.7, 0.3), c_foliage, ambient=0.55))
    return faces


def build_estate_faces() -> List[Face]:
    """Assemble all 3D architectural geometric faces for Master Luxury Estate."""
    faces: List[Face] = []

    # 1. Base Boundary Lawn
    faces.extend(make_box_faces(-440, -310, -5, 880, 600, 5, (95, 148, 78), ambient=0.62))

    # 2. Raised Architectural Podium / Plinth
    faces.extend(make_box_faces(-330, -225, 0, 660, 430, 4, (118, 172, 96), ambient=0.55))

    # 3. Main Villa Ground Floor Mass
    faces.extend(make_box_faces(-150, -80, 4, 290, 150, 68, (244, 246, 248), ambient=0.52))

    # 4. Slate Accent Feature Wall
    faces.extend(make_box_faces(-165, -88, 4, 40, 162, 150, (68, 74, 82), ambient=0.45))

    # 5. Upper Storey Cantilever
    faces.extend(make_box_faces(-110, -75, 72, 248, 140, 74, (248, 250, 252), ambient=0.55))

    # 6. Panoramic Glass Facades (Front & Back)
    faces.extend(make_box_faces(-102, 66, 6, 120, 2, 64, (65, 155, 205), alpha=210, ambient=0.68))
    faces.extend(make_box_faces(-102, 66, 76, 120, 2, 64, (65, 155, 205), alpha=210, ambient=0.68))
    faces.extend(make_box_faces(-100, -76, 76, 140, 2, 64, (65, 155, 205), alpha=210, ambient=0.68))

    # 7. Cedar Louvers / Brise-Soleil (Front)
    for lx in range(25, 130, 14):
        faces.extend(make_box_faces(lx, 67, 76, 5, 2, 66, (168, 102, 56), ambient=0.50))

    # 8. Modern Architectural Flat Roof Coping
    faces.extend(make_box_faces(-120, -84, 146, 268, 156, 10, (40, 44, 48), ambient=0.38))

    # 9. Double Garage Structure & Sectional Door
    faces.extend(make_box_faces(140, -68, 4, 85, 126, 64, (240, 242, 245), ambient=0.52))
    faces.extend(make_box_faces(148, 59, 4, 68, 2, 58, (48, 52, 58), ambient=0.40))

    # 10. Paved Driveway leading to garage
    faces.extend(make_box_faces(144, 62, 1, 76, 100, 2, (180, 185, 192), ambient=0.56))

    # 11. Luxury Infinity Swimming Pool
    # Deck terrace
    faces.extend(make_box_faces(-188, -22, 4, 145, 130, 7, (188, 132, 84), ambient=0.55))
    # Coping rim
    faces.extend(make_box_faces(-180, -14, 11, 130, 114, 2, (242, 245, 248), ambient=0.65))
    # Crystal turquoise water
    faces.extend(make_box_faces(-174, -8, 12, 118, 102, 1, (0, 210, 245), alpha=235, ambient=0.78))

    # 12. Pergola Lounge Pavilion
    for px, py in [(-30, -20), (40, -20), (-30, 30), (40, 30)]:
        faces.extend(make_box_faces(px - 3, py - 3, 4, 6, 6, 66, (140, 85, 48), ambient=0.48))
    faces.extend(make_box_faces(-35, -23, 70, 80, 6, 6, (152, 94, 55), ambient=0.50))
    faces.extend(make_box_faces(-35, 27, 70, 80, 6, 6, (152, 94, 55), ambient=0.50))
    for lx in range(-30, 45, 14):
        faces.extend(make_box_faces(lx, -24, 76, 5, 58, 4, (140, 85, 48), ambient=0.52))

    # 13. Championship Tennis Court
    faces.extend(make_box_faces(150, -215, 4, 165, 120, 2, (38, 108, 168), ambient=0.58))
    faces.extend(make_box_faces(160, -205, 6, 145, 100, 1, (48, 135, 210), ambient=0.62))
    # Tennis net
    faces.extend(make_box_faces(230, -205, 7, 2, 100, 8, (245, 245, 250), ambient=0.75))

    # 14. Italian Cypress Trees around perimeter
    cypresses = [
        (-270, -70, 4, 88),
        (-270, 0, 4, 94),
        (-270, 70, 4, 90),
        (260, -50, 4, 86),
        (260, 20, 4, 92),
        (-40, -180, 4, 82),
        (80, -180, 4, 85),
    ]
    for cx, cy, cz, h in cypresses:
        faces.extend(make_tree_faces(cx, cy, cz, h))

    return faces


def render_scene_at_angle(faces: List[Face], angle_rad: float) -> Image.Image:
    """Render a single full-estate architectural frame at given rotation angle."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Sky gradient (Twilight / Modern Sky)
    for row in range(320):
        t = row / 320.0
        r = int(140 + (228 - 140) * t)
        g = int(185 + (238 - 185) * t)
        b = int(230 + (245 - 230) * t)
        draw.line([(0, row), (WIDTH, row)], fill=(r, g, b, 255))

    # Process and depth-sort all faces
    render_list = []
    for f in faces:
        # Rotated normal
        nx, ny = rotate_coords(f.normal[0], f.normal[1], angle_rad)
        nz = f.normal[2]
        dot_v = nx * VIEW_NORM[0] + ny * VIEW_NORM[1] + nz * VIEW_NORM[2]
        if dot_v <= 0.001:
            # Backface culled
            continue

        # Rotated centroid for depth sorting
        cx, cy = rotate_coords(f.cx, f.cy, angle_rad)
        cz = f.cz
        depth = cx * VIEW_NORM[0] + cy * VIEW_NORM[1] + cz * VIEW_NORM[2]

        # Sunlight shading
        dot_s = max(0.0, nx * SUN_NORM[0] + ny * SUN_NORM[1] + nz * SUN_NORM[2])
        factor = f.ambient + (1.0 - f.ambient) * dot_s
        r = int(min(255, max(0, f.color[0] * factor)))
        g = int(min(255, max(0, f.color[1] * factor)))
        b = int(min(255, max(0, f.color[2] * factor)))

        s_pts = [project_rot(p[0], p[1], p[2], angle_rad) for p in f.pts]
        render_list.append((depth, s_pts, (r, g, b, f.alpha)))

    # Sort back-to-front (Painter's algorithm)
    render_list.sort(key=lambda item: item[0])
    for _, s_pts, color in render_list:
        draw.polygon(s_pts, fill=color)

    return img


def generate_animated_turntable(
    state: PropertyState,
    config: UserConfig,
    output_webp: Path,
    output_svg: Path,
    num_frames: int = 16,
):
    """Generate 16-frame 360-degree rotating 3D architectural animation."""
    if num_frames < 1:
        raise ValueError("num_frames must be at least 1")

    output_webp.parent.mkdir(parents=True, exist_ok=True)
    output_svg.parent.mkdir(parents=True, exist_ok=True)

    estate_faces = build_estate_faces()
    frames: List[Image.Image] = []
    logger.info("Rendering %d depth-sorted 3D rotation frames for 360 turntable...", num_frames)

    for i in range(num_frames):
        angle = (2.0 * math.pi * i) / num_frames
        logger.debug("  Frame %d/%d (angle: %d deg)...", i + 1, num_frames, int(math.degrees(angle)))
        frame_img = render_scene_at_angle(estate_faces, angle)
        frames.append(frame_img)

    # 1. Save Animated WebP (smooth 350ms/frame)
    frames[0].save(
        output_webp,
        save_all=True,
        append_images=frames[1:],
        duration=350,
        loop=0,
        optimize=True,
        quality=85,
    )
    logger.info("Saved Animated 360 Turntable WebP: %s (%d KB)", output_webp, output_webp.stat().st_size // 1024)

    # 2. Build Multi-Frame Animated SVG with CSS keyframes
    spec = get_milestone_spec(state.milestone)
    login_safe = escape_xml_text(state.login, fallback="Developer")
    milestone_title_safe = escape_xml_text(spec.title)
    contributions_str = f"{state.total_contributions:,}"

    # Encode frames
    b64_frames = []
    for f in frames:
        buf = io.BytesIO()
        f.save(buf, format="PNG", optimize=True)
        b64_frames.append(base64.b64encode(buf.getvalue()).decode("ascii"))

    total_duration = 5.6  # 5.6 seconds for full 360-degree loop
    keyframe_css = []
    for i in range(num_frames):
        start_pct = (i / num_frames) * 100
        end_pct = ((i + 1) / num_frames) * 100
        keyframe_css.append(f"""
    .frame-{i} {{
      animation: showFrame{i} {total_duration}s infinite step-end;
    }}
    @keyframes showFrame{i} {{
      0%, 100% {{ opacity: {'1' if i == 0 else '0'}; }}
      {start_pct:.2f}% {{ opacity: 1; }}
      {end_pct:.2f}% {{ opacity: 0; }}
    }}
""")

    images_xml = []
    for i, b64 in enumerate(b64_frames):
        images_xml.append(
            f'<image class="frame-{i}" href="data:image/png;base64,{b64}" width="{WIDTH}" height="{HEIGHT}" preserveAspectRatio="xMidYMid meet" opacity="{"1" if i == 0 else "0"}" />'
        )

    svg_anim = f"""<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     viewBox="0 0 {WIDTH} {HEIGHT}"
     width="{WIDTH}"
     height="{HEIGHT}"
     role="img"
     aria-labelledby="title desc">
  <title id="title">BuildSite 360 Turntable — {login_safe}'s Residence</title>
  <desc id="desc">360-degree rotating architectural view of {login_safe}'s Master Luxury Residential Estate with {contributions_str} verified contributions.</desc>

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
    .font-sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    .text-title {{ font-size: 14px; font-weight: 700; fill: #F8FAFC; }}
    .text-subtitle {{ font-size: 11px; font-weight: 500; fill: #94A3B8; }}
    .text-value {{ font-size: 15px; font-weight: 700; fill: #38BDF8; }}
    .text-label {{ font-size: 10px; font-weight: 600; text-transform: uppercase; fill: #64748B; letter-spacing: 0.8px; }}
    .text-badge {{ font-size: 10px; font-weight: 700; fill: #2DD4BF; }}
    {''.join(keyframe_css)}
    @media (prefers-reduced-motion: reduce) {{
      [class^="frame-"] {{ animation: none !important; }}
      .frame-0 {{ opacity: 1 !important; }}
    }}
  </style>

  <!-- 360-Degree Rotating Frames -->
  <g id="turntable-frames">
    {''.join(images_xml)}
  </g>

  <!-- Outer Border Frame -->
  <rect x="1" y="1" width="{WIDTH - 2}" height="{HEIGHT - 2}" rx="12" fill="none" stroke="#334155" stroke-width="1.5" stroke-opacity="0.6"/>

  <!-- Top-Left Status HUD -->
  <g class="font-sans" transform="translate(32, 28)" filter="url(#cardShadow)">
    <rect x="0" y="0" width="370" height="112" rx="10" fill="url(#cardGrad)" stroke="#334155" stroke-width="1" stroke-opacity="0.8"/>
    <circle cx="22" cy="22" r="5" fill="#2DD4BF"/>
    <text x="36" y="24" class="text-title">BuildSite 360</text>
    <text x="135" y="24" class="text-subtitle">• @{login_safe}</text>
    <text x="20" y="48" class="text-label">Active Architecture</text>
    <text x="20" y="66" class="text-title">{milestone_title_safe}</text>
    <rect x="20" y="78" width="330" height="6" rx="3" fill="#334155" fill-opacity="0.7"/>
    <rect x="20" y="78" width="330" height="6" rx="3" fill="url(#barGrad)"/>
    <text x="20" y="98" class="text-subtitle">360° Architectural Turntable Orbit</text>
    <text x="350" y="98" text-anchor="end" class="text-badge">100%</text>
  </g>

  <!-- Top-Right Contribution Counter -->
  <g class="font-sans" transform="translate({WIDTH - 240}, 28)" filter="url(#cardShadow)">
    <rect x="0" y="0" width="208" height="68" rx="10" fill="url(#cardGrad)" stroke="#334155" stroke-width="1" stroke-opacity="0.8"/>
    <text x="18" y="24" class="text-label">Verified Contributions</text>
    <text x="18" y="50" class="text-value">{contributions_str}</text>
    <text x="190" y="50" text-anchor="end" class="text-subtitle">GitHub verified</text>
  </g>

  <!-- Bottom-Right 360 Tagline -->
  <g class="font-sans" transform="translate({WIDTH - 240}, {HEIGHT - 24})">
    <text x="210" y="0" text-anchor="end" font-size="11" font-weight="600" fill="#38BDF8" fill-opacity="0.9">
      🔄 360° Rotating Architectural Estate
    </text>
  </g>
</svg>"""

    with open(output_svg, "w", encoding="utf-8") as f:
        f.write(svg_anim)
    logger.info("Saved Animated 360 Turntable SVG: %s (%d KB)", output_svg, output_svg.stat().st_size // 1024)
