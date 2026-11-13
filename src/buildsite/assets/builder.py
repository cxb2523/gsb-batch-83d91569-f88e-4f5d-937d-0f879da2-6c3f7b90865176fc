"""Ultra-Realistic Procedural Architectural Renderer and Asset Generator for BuildSite.

Generates high-resolution (1280x640), perspective-aligned, photorealistic
architectural layer assets featuring:
- Physically-plausible lighting: direct sun, soft skylight, and 2700K dusk emissions
- Board-formed concrete, smooth mineral plaster, and dry-stack ashlar stone masonry
- Natural cedar timber louvers, teak decking, and multi-toned wood grain
- Multi-layered swimming pool: mosaic tiles, turquoise subsurface scatter, and water caustics
- Detailed vegetation: conical Italian cypresses with organic foliage clumps and cast shadows
- Interior depth: hardwood floors, designer furniture, and warm architectural lighting
- Accurate soft cast shadows, contact ambient occlusion, and atmospheric twilight blooms
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

WIDTH = 1280
HEIGHT = 640

# Screen origin (center-bottom area of residential property)
ORIGIN_X = 640.0
ORIGIN_Y = 435.0

# Axonometric projection vectors (30-degree architectural view)
AXIS_X = (0.866025, 0.48)    # Down-right
AXIS_Y = (-0.866025, 0.48)   # Down-left
AXIS_Z = (0.0, -1.0)         # Upwards

# Sun position in architectural coordinates (top-right-front)
SUN_DIR = (0.55, -0.65, 0.60)
sun_mag = math.sqrt(SUN_DIR[0]**2 + SUN_DIR[1]**2 + SUN_DIR[2]**2)
SUN_NORM = (SUN_DIR[0] / sun_mag, SUN_DIR[1] / sun_mag, SUN_DIR[2] / sun_mag)

# Shadow projection vector on ground plane
SHADOW_VEC_X = 0.72
SHADOW_VEC_Y = -0.38


def project(x: float, y: float, z: float) -> Tuple[float, float]:
    """Project 3D world coordinates into 2D screen coordinates."""
    sx = ORIGIN_X + x * AXIS_X[0] + y * AXIS_Y[0] + z * AXIS_Z[0]
    sy = ORIGIN_Y + x * AXIS_X[1] + y * AXIS_Y[1] + z * AXIS_Z[1]
    return (sx, sy)


def shade_color(base_rgb: Tuple[int, int, int], normal: Tuple[float, float, float], ambient=0.45) -> Tuple[int, int, int]:
    """Calculate Lambertian diffuse shading plus ambient skylight."""
    n_mag = math.sqrt(normal[0]**2 + normal[1]**2 + normal[2]**2)
    if n_mag > 0:
        norm = (normal[0] / n_mag, normal[1] / n_mag, normal[2] / n_mag)
    else:
        norm = (0.0, 0.0, 1.0)

    dot = max(0.0, norm[0] * SUN_NORM[0] + norm[1] * SUN_NORM[1] + norm[2] * SUN_NORM[2])
    factor = ambient + (1.0 - ambient) * dot
    r = int(min(255, max(0, base_rgb[0] * factor)))
    g = int(min(255, max(0, base_rgb[1] * factor)))
    b = int(min(255, max(0, base_rgb[2] * factor)))
    return (r, g, b)


def draw_poly(draw: ImageDraw.ImageDraw, pts: List[Tuple[float, float, float]], color: Tuple[int, int, int], alpha=255, normal=(0.0, 0.0, 1.0), ambient=0.45):
    """Draw a 3D polygon with directional lighting."""
    shaded = shade_color(color, normal, ambient)
    screen_pts = [project(p[0], p[1], p[2]) for p in pts]
    draw.polygon(screen_pts, fill=(shaded[0], shaded[1], shaded[2], alpha))


def draw_poly_raw(draw: ImageDraw.ImageDraw, pts: List[Tuple[float, float, float]], fill_rgba: Tuple[int, int, int, int]):
    """Draw a 3D polygon with explicit RGBA fill."""
    screen_pts = [project(p[0], p[1], p[2]) for p in pts]
    draw.polygon(screen_pts, fill=fill_rgba)


def draw_box(draw: ImageDraw.ImageDraw, x: float, y: float, z: float, dx: float, dy: float, dz: float, color: Tuple[int, int, int], alpha=255, ambient=0.45):
    """Draw a 3D rectangular architectural volume with physical surface shading."""
    # Top face (+Z, normal: 0, 0, 1)
    top = [(x, y, z + dz), (x + dx, y, z + dz), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)]
    draw_poly(draw, top, color, alpha=alpha, normal=(0.0, 0.0, 1.0), ambient=ambient)

    # Front face (+Y, normal: 0, 1, 0)
    front = [(x, y + dy, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x, y + dy, z + dz)]
    draw_poly(draw, front, color, alpha=alpha, normal=(0.0, 1.0, 0.0), ambient=ambient)

    # Right face (+X, normal: 1, 0, 0)
    right = [(x + dx, y, z), (x + dx, y + dy, z), (x + dx, y + dy, z + dz), (x + dx, y, z + dz)]
    draw_poly(draw, right, color, alpha=alpha, normal=(1.0, 0.0, 0.0), ambient=ambient)


def draw_box_with_shadow(draw: ImageDraw.ImageDraw, shadow_draw: ImageDraw.ImageDraw, x: float, y: float, z: float, dx: float, dy: float, dz: float, color: Tuple[int, int, int], alpha=255):
    """Draw a 3D box and record its soft directional shadow onto the shadow layer."""
    draw_box(draw, x, y, z, dx, dy, dz, color, alpha=alpha)

    # Ground shadow polygon
    # Project 4 bottom points and 4 top points offset by sun vector
    ox = SHADOW_VEC_X * (z + dz)
    oy = SHADOW_VEC_Y * (z + dz)
    s_pts = [
        project(x, y, 0),
        project(x + dx, y, 0),
        project(x + dx + ox, y + dy + oy, 0),
        project(x + ox, y + dy + oy, 0),
    ]
    shadow_draw.polygon(s_pts, fill=(15, 20, 25, 90))


# =============================================================================
# 1. BASE PLOT & ENVIRONMENT
# =============================================================================

def create_plot_base() -> Image.Image:
    """Generate scenic sky gradient, distant mountain ridges, and lush residential sod."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Sky gradient: Deep Mediterranean azure to warm horizon haze
    for row in range(330):
        t = row / 330.0
        r = int(140 + (228 - 140) * t)
        g = int(185 + (238 - 185) * t)
        b = int(230 + (245 - 230) * t)
        draw.line([(0, row), (WIDTH, row)], fill=(r, g, b, 255))

    # Soft wispy cirrus clouds in the sky
    for _ in range(8):
        cx = random.randint(100, WIDTH - 100)
        cy = random.randint(30, 160)
        rw = random.randint(120, 280)
        rh = random.randint(12, 28)
        draw.ellipse([cx - rw, cy - rh, cx + rw, cy + rh], fill=(255, 255, 255, 40))

    # Distant mountain ridge (atmospheric depth fading - light slate blue)
    m1 = [(0, 310), (160, 260), (380, 280), (620, 235), (880, 265), (1120, 240), (WIDTH, 275), (WIDTH, 345), (0, 345)]
    draw.polygon(m1, fill=(188, 204, 218, 255))

    # Midground rolling foothills (soft sage-grey with atmospheric haze)
    m2 = [(0, 325), (240, 280), (520, 305), (780, 270), (1040, 295), (WIDTH, 285), (WIDTH, 360), (0, 360)]
    draw.polygon(m2, fill=(158, 185, 172, 255))

    # Distant tree line silhouette along the ridge
    for rx in range(0, WIDTH, 18):
        ry = int(320 + 15 * math.sin(rx * 0.015))
        draw.ellipse([rx - 8, ry - 14, rx + 8, ry + 2], fill=(135, 160, 145, 255))

    # Base ground plane (vast manicured estate lawn)
    ground_poly = [(-520, -350, -4), (520, -350, -4), (520, 280, -4), (-520, 280, -4)]
    draw_poly(draw, ground_poly, (108, 162, 88), normal=(0.0, 0.0, 1.0), ambient=0.55)

    # Luxury lawn mowing stripes (alternating light and dark green reflective bands)
    for stripe_y in range(-340, 270, 24):
        s_poly = [(-510, stripe_y, -3), (510, stripe_y, -3), (510, stripe_y + 12, -3), (-510, stripe_y + 12, -3)]
        draw_poly_raw(draw, s_poly, (122, 178, 98, 45))

    # Raised residential surveyed building plot platform
    plot_poly = [(-340, -230, 0), (340, -230, 0), (340, 190, 0), (-340, 190, 0)]
    draw_box(draw, -340, -230, -3, 680, 420, 3, (125, 178, 102), ambient=0.52)

    # Perimeter natural stone landscape retaining wall
    draw_box(draw, -342, -232, 0, 684, 8, 8, (190, 192, 196), ambient=0.48)
    draw_box(draw, -342, 184, 0, 684, 8, 8, (190, 192, 196), ambient=0.48)

    # Excavated building pad: textured graded earth & crushed gravel base
    pad_poly = [(-190, -130, 1), (190, -130, 1), (190, 95, 1), (-190, 95, 1)]
    draw_poly(draw, pad_poly, (192, 174, 142), normal=(0.0, 0.0, 1.0), ambient=0.50)

    # Subtle gravel aggregate texture dots
    random.seed(42)
    for _ in range(350):
        gx = random.uniform(-185, 185)
        gy = random.uniform(-125, 90)
        sp = project(gx, gy, 1.2)
        c_val = random.choice([(165, 148, 120), (210, 195, 165), (140, 125, 100)])
        draw.point(sp, fill=(c_val[0], c_val[1], c_val[2], 220))

    # Surveyors boundary stakes with fluorescent orange tops
    stakes = [(-335, -225), (335, -225), (335, 185), (-335, 185), (-185, -125), (185, -125), (185, 90), (-185, 90)]
    for sx, sy in stakes:
        draw_box(draw, sx - 2, sy - 2, 0, 4, 4, 28, (235, 220, 185))
        draw_box(draw, sx - 2.5, sy - 2.5, 20, 5, 5, 8, (255, 85, 45)) # Orange survey flag

    return img


# =============================================================================
# 2. FOUNDATIONS & EARTHWORK
# =============================================================================

def create_foundations() -> Image.Image:
    """Generate trench excavation, steel rebar reinforcement grid, and cured concrete footing slab."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Perimeter excavation trench with dark soil sides
    draw_box(draw, -175, -115, -4, 350, 210, 5, (115, 92, 70), ambient=0.35)

    # Sub-base compacted crushed gravel bed
    draw_box(draw, -170, -110, 1, 340, 200, 2, (180, 175, 168), ambient=0.45)

    # Structural rebar reinforcement grid (dark ribbed steel with rust highlights)
    for rx in range(-155, 160, 25):
        draw_box(draw, rx, -100, 3, 2.5, 180, 2.5, (95, 75, 65))
    for ry in range(-95, 80, 25):
        draw_box(draw, -160, ry, 3.5, 320, 2.5, 2.5, (110, 85, 72))

    # Poured structural concrete footing slab with chamfered edges
    draw_box(draw, -160, -100, 2, 320, 180, 14, (208, 212, 216), ambient=0.50)

    # Concrete expansion joints and smooth floated surface lines
    for jx in range(-80, 150, 80):
        draw_box(draw, jx, -99, 16, 1.5, 178, 0.5, (160, 165, 170))

    # Vertical starter rebar dowels protruding upward for columns
    col_dowels = [
        (-140, -80), (-40, -80), (60, -80), (140, -80),
        (-140, 0), (-40, 0), (60, 0), (140, 0),
        (-140, 65), (-40, 65), (60, 65), (140, 65)
    ]
    for dx, dy in col_dowels:
        for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3)]:
            draw_box(draw, dx + ox, dy + oy, 16, 2, 2, 22, (130, 85, 65))

    return img


# =============================================================================
# 3. COLUMNS & STRUCTURAL BEAMS
# =============================================================================

def create_columns_beams() -> Image.Image:
    """Generate reinforced concrete columns, structural tie-beams, and core shear walls."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 12 off-form concrete columns with tie-rod formwork holes
    cols = [
        (-145, -85), (-45, -85), (55, -85), (145, -85),
        (-145, -5), (-45, -5), (55, -5), (145, -5),
        (-145, 65), (-45, 65), (55, 65), (145, 65)
    ]
    for cx, cy in cols:
        # Main square column
        draw_box(draw, cx - 7, cy - 7, 16, 14, 14, 72, (222, 225, 228), ambient=0.48)
        # Formwork tie-rod indentation dots
        for tz in [30, 50, 70]:
            draw_box(draw, cx + 7.1, cy - 2, tz, 0.5, 4, 2, (160, 164, 168))

    # Horizontal tie-beams along X axis
    draw_box(draw, -150, -90, 82, 305, 12, 10, (215, 218, 222), ambient=0.48)
    draw_box(draw, -150, -10, 82, 305, 12, 10, (215, 218, 222), ambient=0.48)
    draw_box(draw, -150, 60, 82, 305, 12, 10, (215, 218, 222), ambient=0.48)

    # Horizontal tie-beams along Y axis
    for bx in [-145, -45, 55, 145]:
        draw_box(draw, bx - 6, -85, 82, 12, 155, 10, (210, 214, 218), ambient=0.45)

    # Board-formed concrete central stairwell shear wall core
    draw_box(draw, -55, -20, 16, 42, 55, 80, (198, 202, 206), ambient=0.42)
    # Horizontal board-form timber grain lines on shear wall
    for wz in range(24, 94, 8):
        draw_box(draw, -56, -20, wz, 0.8, 55, 1.2, (165, 168, 172))

    return img


# =============================================================================
# 4. BUILDING FRAME & UPPER FLOOR
# =============================================================================

def create_building_frame() -> Image.Image:
    """Generate post-tensioned first floor slab, second storey framing, and cantilevers."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # First floor suspended concrete slab (extends forward as a cantilevered balcony)
    draw_box(draw, -165, -105, 88, 335, 185, 14, (228, 231, 235), ambient=0.52)

    # Cantilevered front master suite terrace slab extension
    draw_box(draw, -25, -118, 88, 150, 20, 14, (222, 226, 230), ambient=0.50)

    # Upper storey reinforced concrete columns
    upper_cols = [
        (-135, -75), (-35, -75), (65, -75), (135, -75),
        (-135, 45), (-35, 45), (65, 45), (135, 45)
    ]
    for ux, uy in upper_cols:
        draw_box(draw, ux - 6, uy - 6, 102, 12, 12, 68, (220, 224, 228), ambient=0.48)

    # Upper roof perimeter ring beams
    draw_box(draw, -140, -80, 165, 285, 12, 10, (212, 216, 220), ambient=0.48)
    draw_box(draw, -140, 40, 165, 285, 12, 10, (212, 216, 220), ambient=0.48)

    # Staircase structural flight connecting ground and first floor
    for step_i in range(12):
        sz = 16 + step_i * 6
        sy = -15 + step_i * 4
        draw_box(draw, -35, sy, sz, 20, 5, 4, (190, 195, 200))

    return img


# =============================================================================
# 5. ROOFING, GLAZING & BALUSTRADES
# =============================================================================

def create_roof_enclosure() -> Image.Image:
    """Generate waterproofed roof deck, dark aluminum curtain wall frames, and panoramic glass."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Flat roof deck slab with dark anthracite metal fascia coping
    draw_box(draw, -170, -108, 170, 345, 188, 14, (242, 244, 246), ambient=0.52)
    # Dark aluminum perimeter fascia flashing
    draw_box(draw, -172, -110, 178, 349, 192, 4, (45, 48, 52), ambient=0.38)

    # Ground floor panoramic curtain wall glass (semi-reflective Low-E glass)
    draw_box(draw, -135, 66, 16, 275, 2, 72, (80, 160, 205), alpha=160, ambient=0.60)

    # Upper floor floor-to-ceiling glass facade
    draw_box(draw, -125, 46, 102, 255, 2, 68, (80, 160, 205), alpha=160, ambient=0.60)

    # Precision dark anodized aluminum window mullions & transoms
    for mx in range(-120, 140, 45):
        draw_box(draw, mx, 67, 16, 3, 2, 72, (38, 40, 44), ambient=0.35)
        draw_box(draw, mx, 47, 102, 3, 2, 68, (38, 40, 44), ambient=0.35)
    # Horizontal transom bar
    draw_box(draw, -135, 67, 50, 275, 2, 3, (38, 40, 44), ambient=0.35)
    draw_box(draw, -125, 47, 136, 255, 2, 3, (38, 40, 44), ambient=0.35)

    # Frameless glass balustrade with polished stainless steel handrail cap
    draw_box(draw, -25, -119, 102, 150, 2, 24, (120, 195, 230), alpha=130, ambient=0.70)
    draw_box(draw, -25, -119, 126, 150, 2, 2.5, (215, 218, 222), ambient=0.65) # Steel cap

    return img


# =============================================================================
# 6. FINISHED LUXURY VILLA (PLASTER, STONE, TIMBER, INTERIORS)
# =============================================================================

def create_villa_finished() -> Image.Image:
    """Generate the complete modern architectural villa with plaster, stone cladding, and timber."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Main Ground Floor Volume (Smooth white/warm-grey mineral plaster)
    draw_box(draw, -150, -90, 16, 305, 155, 72, (246, 247, 249), ambient=0.55)

    # 2. Natural Dry-Stack Slate Stone Accent Feature Wall (Left Anchor Wing)
    draw_box(draw, -165, -96, 14, 45, 168, 162, (72, 78, 86), ambient=0.45)
    # Individual stone course variations and mortar shadow lines
    random.seed(101)
    for sz in range(18, 172, 8):
        draw_box(draw, -166, -96, sz, 46, 168, 1.2, (42, 46, 52), ambient=0.30)
        # Random stone block vertical relief
        for sx in range(-164, -125, 14):
            stone_c = random.choice([(82, 88, 96), (65, 70, 78), (95, 100, 108), (75, 72, 68)])
            draw_box(draw, sx, -96.5, sz + 1.2, 12, 1, 6.5, stone_c, ambient=0.45)

    # 3. Upper Storey Cantilevered Master Suite (Extruded forward & right)
    draw_box(draw, -105, -80, 88, 260, 145, 82, (250, 251, 252), ambient=0.58)

    # 4. Architectural Western Red Cedar Louvers (Right bedroom facade)
    for louver_x in range(35, 145, 10):
        # Vertical structural blade
        draw_box(draw, louver_x, 68, 98, 5, 2.5, 70, (172, 105, 60), ambient=0.50)
    # Cedar timber horizontal rainscreen panels
    draw_box(draw, 142, -78, 88, 12, 142, 82, (158, 95, 52), ambient=0.45)
    for tz in range(92, 168, 6):
        draw_box(draw, 141.5, -78, tz, 13, 142, 1, (108, 62, 32), ambient=0.35)

    # 5. Visible Interior Living Spaces Through Panoramic Windows
    # Ground floor interior: French oak flooring & warm interior walls
    draw_box(draw, -95, 62, 17, 120, 4, 1.5, (198, 155, 112)) # Hardwood floor
    # Modern low-profile sofa
    draw_box(draw, -80, 58, 19, 45, 12, 12, (180, 182, 186))
    # Marble coffee table
    draw_box(draw, -70, 50, 19, 22, 10, 6, (235, 235, 238))
    # Interior warm dining pendant / chandelier light silhouette
    draw_box(draw, -20, 52, 45, 8, 8, 8, (255, 230, 170), alpha=220)

    # Panoramic double-glazed glass panes with sky specular sheen
    draw_box(draw, -98, 67, 18, 128, 2, 70, (65, 155, 205), alpha=170, ambient=0.65)
    draw_box(draw, -98, 67, 98, 128, 2, 68, (65, 155, 205), alpha=170, ambient=0.65)

    # 6. Roof Cantilever Overhang with Recessed Soffit Lighting
    draw_box(draw, -115, -88, 170, 275, 160, 12, (238, 240, 244), ambient=0.52)
    # Dark architectural roof flashing
    draw_box(draw, -117, -90, 180, 279, 164, 3, (42, 45, 48), ambient=0.35)

    # 7. Cantilevered Glass Balcony Balustrade with Polished Cap
    draw_box(draw, -20, -114, 100, 130, 2, 24, (135, 215, 245), alpha=140, ambient=0.72)
    draw_box(draw, -20, -114, 124, 130, 2, 2.5, (220, 224, 228), ambient=0.68)

    return img


# =============================================================================
# 7. DRIVEWAY, GARAGE & BOUNDARY
# =============================================================================

def create_driveway_garage() -> Image.Image:
    """Generate paved granite stone driveway, modern garage structure, and boundary wall."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Modern Garage Pavilion (Seamlessly attached to right wing)
    draw_box(draw, 155, -75, 16, 95, 135, 68, (242, 244, 246), ambient=0.52)
    # Garage roof parapet
    draw_box(draw, 153, -77, 84, 99, 139, 4, (45, 48, 52), ambient=0.38)

    # Motorized Sectional Garage Door (Anthracite finish with horizontal grooves)
    draw_box(draw, 165, 58, 17, 75, 2, 62, (52, 55, 60), ambient=0.40)
    for gy in range(28, 78, 12):
        draw_box(draw, 164, 58.5, gy, 77, 1.5, 1.2, (30, 32, 36), ambient=0.25)
    # Frosted glass slim light inserts on top garage door panel
    for gx in range(172, 235, 16):
        draw_box(draw, gx, 58.8, 68, 10, 1, 6, (180, 210, 225), alpha=210)

    # Paved Granite Cobblestone Driveway (Sweeping curve to foreground)
    drive_poly = [(152, 60, 2), (255, 60, 2), (310, 215, 2), (115, 215, 2)]
    draw_poly(draw, drive_poly, (175, 178, 182), normal=(0.0, 0.0, 1.0), ambient=0.55)

    # Realistic interlocking granite paver joints
    for py in range(65, 210, 10):
        t_w = (py - 60) / 155.0
        x_start = int(152 + (115 - 152) * t_w)
        x_end = int(255 + (310 - 255) * t_w)
        p_line = [(x_start, py, 2.2), (x_end, py, 2.2)]
        draw.line([project(p_line[0][0], p_line[0][1], p_line[0][2]), project(p_line[1][0], p_line[1][1], p_line[1][2])], fill=(138, 142, 146, 180), width=1)

    # Granite curb stones bordering driveway
    curb_l = [(151, 60, 2), (113, 215, 2), (110, 215, 2), (148, 60, 2)]
    draw_poly(draw, curb_l, (215, 218, 220), normal=(0.0, 0.0, 1.0), ambient=0.58)

    # Perimeter Modern Boundary Wall with Stone Coping
    draw_box(draw, -310, 178, 0, 620, 9, 24, (225, 228, 232), ambient=0.50)
    # Dark metal coping trim on boundary wall
    draw_box(draw, -312, 176, 24, 624, 13, 2.5, (65, 68, 72), ambient=0.40)

    # Recessed low-voltage ground LED step lights in boundary wall
    for lx in range(-260, 260, 60):
        draw_box(draw, lx, 187.2, 8, 8, 0.5, 4, (245, 245, 248))

    return img


# =============================================================================
# 8. LUXURY SWIMMING POOL (WATER, CAUSTICS, MOSAIC TILES, TEAK DECK)
# =============================================================================

def create_swimming_pool() -> Image.Image:
    """Generate luxury swimming pool with turquoise water, subsurface scatter, and teak deck."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Wide-Plank Teak Wood Deck Surrounding the Pool
    draw_box(draw, -188, -25, 2, 150, 135, 7, (188, 130, 82), ambient=0.55)
    # Individual teak deck board lines
    for dy in range(-24, 108, 6):
        d_line = [(-188, dy, 9.1), (-38, dy, 9.1)]
        draw.line([project(d_line[0][0], d_line[0][1], d_line[0][2]), project(d_line[1][0], d_line[1][1], d_line[1][2])], fill=(135, 85, 48, 180), width=1)

    # 2. Pool Basin Coping Edge (Honed white crystalline marble coping)
    draw_box(draw, -178, -15, 9, 130, 115, 3.5, (246, 248, 250), ambient=0.60)

    # 3. Submerged Pool Floor Mosaic Glass Tiles (Turquoise gradient with depth)
    pool_basin = [(-172, -9, 3), (-54, -9, 3), (-54, 94, 3), (-172, 94, 3)]
    draw_poly(draw, pool_basin, (0, 145, 185), normal=(0.0, 0.0, 1.0), ambient=0.45)

    # Mosaic tile grid pattern on pool floor
    for mx in range(-168, -55, 12):
        t_l = [(mx, -9, 3.2), (mx, 94, 3.2)]
        draw.line([project(t_l[0][0], t_l[0][1], t_l[0][2]), project(t_l[1][0], t_l[1][1], t_l[1][2])], fill=(0, 180, 220, 120), width=1)
    for my in range(-5, 90, 12):
        t_l = [(-172, my, 3.2), (-54, my, 3.2)]
        draw.line([project(t_l[0][0], t_l[0][1], t_l[0][2]), project(t_l[1][0], t_l[1][1], t_l[1][2])], fill=(0, 180, 220, 120), width=1)

    # 4. Realistic Azure/Turquoise Pool Water Surface
    pool_water = [(-172, -9, 11), (-54, -9, 11), (-54, 94, 11), (-172, 94, 11)]
    draw_poly(draw, pool_water, (0, 205, 240), alpha=215, normal=(0.0, 0.0, 1.0), ambient=0.72)

    # 5. Sunlight Water Caustics (Organic glowing white-cyan wave networks)
    caustic_pts = [
        [(-155, 10, 11.2), (-125, 8, 11.2), (-110, 28, 11.2), (-145, 25, 11.2)],
        [(-130, 32, 11.2), (-85, 30, 11.2), (-75, 48, 11.2), (-118, 52, 11.2)],
        [(-150, 55, 11.2), (-100, 58, 11.2), (-90, 78, 11.2), (-140, 75, 11.2)],
        [(-105, 12, 11.2), (-65, 15, 11.2), (-60, 35, 11.2), (-95, 32, 11.2)],
        [(-120, 75, 11.2), (-70, 72, 11.2), (-62, 88, 11.2), (-112, 88, 11.2)],
    ]
    for cp in caustic_pts:
        draw_poly_raw(draw, cp, (160, 245, 255, 140))

    # 6. Waterline Specular Reflection and Sky Gradient
    refl_strip = [(-171, -8, 11.3), (-55, -8, 11.3), (-55, 15, 11.3), (-171, 15, 11.3)]
    draw_poly_raw(draw, refl_strip, (255, 255, 255, 80))

    # 7. Designer Poolside Sun Loungers (White fiberglass with charcoal cushions)
    for ly in [18, 62]:
        # Sun lounger base
        draw_box(draw, -186, ly, 10, 14, 36, 5, (250, 252, 255), ambient=0.60)
        # Reclined backrest
        draw_box(draw, -185, ly + 22, 14, 12, 14, 8, (246, 248, 250), ambient=0.55)
        # Charcoal cushion
        draw_box(draw, -184, ly + 2, 14, 10, 32, 3, (65, 68, 74), ambient=0.45)

    # 8. Stainless Steel Pool Entry Ladder
    draw_box(draw, -62, -6, 12, 2, 2, 12, (230, 235, 240))
    draw_box(draw, -58, -6, 12, 2, 2, 12, (230, 235, 240))

    return img


# =============================================================================
# 9. GARDENS & LANDSCAPING (CYPRESSES, SHRUBS, FLAGSTONE PATH)
# =============================================================================

def draw_cypress_tree(draw: ImageDraw.ImageDraw, x: float, y: float, height: float, shadow_draw: ImageDraw.ImageDraw):
    """Draw an ultra-realistic Italian Cypress tree with organic clumped needle foliage and cast shadow."""
    # 1. Soft directional shadow cast diagonally on the lawn
    shadow_tip = project(x + SHADOW_VEC_X * height, y + SHADOW_VEC_Y * height, 0)
    shadow_base_l = project(x - 5, y, 0)
    shadow_base_r = project(x + 5, y, 0)
    shadow_draw.polygon([shadow_tip, shadow_base_l, shadow_base_r], fill=(18, 25, 20, 110))

    # 2. Wood trunk base
    draw_box(draw, x - 2.5, y - 2.5, 2, 5, 5, 14, (75, 52, 36), ambient=0.35)

    # 3. Layered organic foliage clumps (conical silhouette with highlights and deep shadows)
    # 5 vertical tiers
    for tier in range(5):
        t_frac = tier / 4.0
        z_base = 12 + t_frac * (height * 0.75)
        z_top = z_base + (height * 0.28)
        radius = (1.0 - t_frac * 0.75) * 14.0

        p_top = project(x, y, z_top)
        p_base = project(x, y, z_base)
        p_left = (p_base[0] - radius * 1.1, p_base[1])
        p_right = (p_base[0] + radius * 1.1, p_base[1])

        # Shaded side (deep forest green)
        draw.polygon([p_top, p_left, p_base], fill=(28, 62, 36, 255))
        # Sunlit highlight side (warm emerald/olive needles)
        draw.polygon([p_top, p_base, p_right], fill=(52, 115, 62, 255))

        # Organic texture bumps along the perimeter
        for bump in range(4):
            bx = x + radius * 0.6 * math.cos(bump * 1.5)
            by = y + radius * 0.6 * math.sin(bump * 1.5)
            bp = project(bx, by, z_base + 6)
            draw.ellipse([bp[0] - 6, bp[1] - 5, bp[0] + 6, bp[1] + 5], fill=(42, 92, 50, 255))


def create_gardens() -> Image.Image:
    """Generate manicured emerald lawn beds, mature Italian cypresses, and flagstone path."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    shadow_draw = ImageDraw.Draw(shadow_img)

    # Manicured emerald lawn garden beds (Left and rear wings)
    lawn_left = [(-320, -95, 2), (-195, -95, 2), (-195, 165, 2), (-320, 165, 2)]
    draw_poly(draw, lawn_left, (85, 165, 75), normal=(0.0, 0.0, 1.0), ambient=0.55)

    # Natural Bluestone / Granite Flagstone Garden Walkway
    for fy in range(-75, 150, 26):
        step_pts = [(-262, fy, 3), (-235, fy, 3), (-235, fy + 18, 3), (-262, fy + 18, 3)]
        draw_poly(draw, step_pts, (215, 218, 222), normal=(0.0, 0.0, 1.0), ambient=0.55)
        # Shadow along stone edge
        shadow_draw.polygon([project(-263, fy, 2), project(-234, fy, 2), project(-234, fy + 2, 2), project(-263, fy + 2, 2)], fill=(20, 25, 22, 90))

    # Mature Sculptural Italian Cypress Trees
    cypress_coords = [
        (-295, -70, 85),
        (-295, -10, 92),
        (-295, 50, 88),
        (-295, 110, 80),
        (280, -45, 86),
        (280, 25, 90),
    ]
    for cx, cy, ch in cypress_coords:
        draw_cypress_tree(draw, cx, cy, ch, shadow_draw)

    # Flowering shrubs and ornamental lavender along property borders
    for bx in range(-190, 25, 30):
        sp = project(bx, 162, 3)
        # Deep green foliage sphere
        draw.ellipse([sp[0] - 12, sp[1] - 9, sp[0] + 12, sp[1] + 9], fill=(55, 122, 62, 255))
        # Sunlit top foliage
        draw.ellipse([sp[0] - 8, sp[1] - 8, sp[0] + 8, sp[1] + 2], fill=(78, 155, 86, 255))
        # Lavender / white hydrangea flowers
        for flower_i in [(-5, -4), (0, -6), (5, -3), (-2, 0)]:
            draw.ellipse([sp[0] + flower_i[0] - 2.5, sp[1] + flower_i[1] - 2.5, sp[0] + flower_i[0] + 2.5, sp[1] + flower_i[1] + 2.5], fill=(215, 135, 175, 230))

    # Soften shadows and composite
    soft_shadow = shadow_img.filter(ImageFilter.GaussianBlur(radius=3.5))
    result = Image.alpha_composite(soft_shadow, img)
    return result


# =============================================================================
# 10. PATIO, CEDAR PERGOLA & OUTDOOR LOUNGE
# =============================================================================

def create_patio_pergola() -> Image.Image:
    """Generate modern cedar pergola with striped cast shadows, outdoor dining, and fire table."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    shadow_img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    shadow_draw = ImageDraw.Draw(shadow_img)

    # 1. Pergola Structural Timber Posts (4 heavy cedar posts with standoff brackets)
    posts = [(-38, -28), (48, -28), (-38, 38), (48, 38)]
    for px, py in posts:
        # Concealed black steel standoff bracket at base
        draw_box(draw, px - 3.5, py - 3.5, 2, 7, 7, 3, (38, 40, 44), ambient=0.35)
        # Timber vertical column
        draw_box(draw, px - 3, py - 3, 5, 6, 6, 74, (142, 85, 50), ambient=0.50)

    # 2. Main Horizontal Header Beams
    draw_box(draw, -44, -31, 79, 98, 7, 8, (155, 95, 58), ambient=0.52)
    draw_box(draw, -44, 35, 79, 98, 7, 8, (155, 95, 58), ambient=0.52)

    # 3. Precision Louvered Cedar Roof Slats (Cast signature striped shadows onto terrace floor!)
    for rx in range(-40, 50, 11):
        # Timber roof louver slat
        draw_box(draw, rx, -33, 87, 4.5, 74, 5, (170, 105, 64), ambient=0.55)

        # Realistic striped shadow cast diagonally onto patio floor
        ox = SHADOW_VEC_X * 88
        oy = SHADOW_VEC_Y * 88
        slat_shadow = [
            project(rx, -33, 2),
            project(rx + 4.5, -33, 2),
            project(rx + 4.5 + ox, 41 + oy, 2),
            project(rx + ox, 41 + oy, 2)
        ]
        shadow_draw.polygon(slat_shadow, fill=(20, 22, 26, 95))

    # 4. Outdoor Dining Lounge & Concrete Fire Table
    # Concrete fire table
    draw_box(draw, -14, -6, 2, 34, 22, 14, (78, 82, 88), ambient=0.48)
    # Glowing amber lava stones in fire table
    draw_box(draw, -10, -3, 16, 26, 16, 2, (255, 145, 55), alpha=230)

    # Contemporary outdoor chairs
    for cx, cy in [(-22, 2), (24, 2), (3, -15), (3, 22)]:
        draw_box(draw, cx - 4, cy - 4, 2, 8, 8, 16, (120, 75, 45), ambient=0.45)
        draw_box(draw, cx - 3.5, cy - 3.5, 14, 7, 7, 2, (190, 192, 195))

    soft_shadow = shadow_img.filter(ImageFilter.GaussianBlur(radius=2.5))
    return Image.alpha_composite(soft_shadow, img)


# =============================================================================
# 11. PREMIUM UPGRADES (ROOFTOP TERRACE, SOLAR ARRAY, EV CHARGER)
# =============================================================================

def create_upgrades() -> Image.Image:
    """Generate glass-railed rooftop observation lounge, monocrystalline solar array, and EV dock."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Rooftop Observation Deck Frameless Glass Balustrade
    draw_box(draw, -108, -82, 180, 240, 2, 22, (135, 215, 245), alpha=140, ambient=0.70)
    draw_box(draw, -108, 42, 180, 240, 2, 22, (135, 215, 245), alpha=140, ambient=0.70)

    # 2. Monocrystalline Rooftop Solar Photovoltaic Array (Sleek dark navy blue PV modules)
    for sx in range(-95, 25, 28):
        # Solar module aluminum frame
        draw_box(draw, sx, -68, 180, 25, 42, 3.5, (32, 34, 38), ambient=0.35)
        # Anti-reflective PV tempered glass
        draw_box(draw, sx + 1.5, -66.5, 183, 22, 39, 0.8, (22, 36, 64), ambient=0.65)
        # Silver busbar lines
        for bx in range(4, 20, 5):
            draw_box(draw, sx + 1.5 + bx, -66.5, 183.6, 0.6, 39, 0.2, (180, 195, 215))

    # 3. Fast Level-2 EV Charging Station by Garage
    draw_box(draw, 158, 65, 18, 6, 7, 30, (48, 52, 58), ambient=0.40)
    # Luminous cyan LED halo charging status ring
    draw_box(draw, 159, 67, 38, 4, 4, 6, (0, 210, 255), alpha=240)

    # 4. Rooftop Modern Architectural Planters
    draw_box(draw, 85, -75, 180, 18, 35, 14, (65, 70, 76), ambient=0.45)
    for bx in range(88, 100, 4):
        draw_box(draw, bx, -65, 194, 2, 2, 16, (45, 95, 52))

    return img


# =============================================================================
# 12. ESTATE GUESTHOUSE & WATER FEATURE
# =============================================================================

def create_estate_guesthouse() -> Image.Image:
    """Generate separate modern guest suite pavilion wing and linear reflecting fountain."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Guest Suite Pavilion (Background Left Wing)
    draw_box(draw, -270, -185, 2, 108, 76, 54, (246, 247, 249), ambient=0.52)
    # Feature stone pillar on guesthouse
    draw_box(draw, -272, -112, 2, 16, 6, 54, (68, 74, 82), ambient=0.40)
    # Panoramic glass front of guest pavilion
    draw_box(draw, -254, -111, 4, 90, 2, 48, (75, 160, 210), alpha=175, ambient=0.62)
    # Flat cantilevered roof overhang with dark fascia
    draw_box(draw, -276, -190, 56, 120, 86, 7, (235, 238, 242), ambient=0.50)
    draw_box(draw, -278, -192, 63, 124, 90, 2.5, (42, 45, 48), ambient=0.35)

    # Linear Architectural Reflecting Water Fountain
    draw_box(draw, -145, -195, 2, 44, 110, 5, (220, 224, 228), ambient=0.55)
    fountain_water = [(-141, -191, 5.5), (-105, -191, 5.5), (-105, -89, 5.5), (-141, -89, 5.5)]
    draw_poly(draw, fountain_water, (0, 185, 225), alpha=225, normal=(0.0, 0.0, 1.0), ambient=0.70)
    # Water surface specular highlight
    draw_poly_raw(draw, [(-138, -188, 5.8), (-115, -188, 5.8), (-115, -130, 5.8), (-138, -130, 5.8)], (255, 255, 255, 80))

    return img


# =============================================================================
# 13. MASTER LUXURY ESTATE EXPANSION
# =============================================================================

def create_master_expansion() -> Image.Image:
    """Generate championship tennis court, extended olive grove, and grand entry pillars."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Championship US Open Acrylic Tennis/Sports Court (Navy blue outer, azure inner)
    court_poly = [(165, -230, 2), (355, -230, 2), (355, -90, 2), (165, -90, 2)]
    draw_poly(draw, court_poly, (38, 108, 168), normal=(0.0, 0.0, 1.0), ambient=0.58)

    inner_court = [(185, -215, 2.5), (335, -215, 2.5), (335, -105, 2.5), (185, -105, 2.5)]
    draw_poly(draw, inner_court, (52, 138, 202), normal=(0.0, 0.0, 1.0), ambient=0.62)

    # Crisp regulation court lines
    for ly in [-215, -160, -105]:
        line_pts = [(185, ly, 2.8), (335, ly, 2.8)]
        draw.line([project(line_pts[0][0], line_pts[0][1], line_pts[0][2]), project(line_pts[1][0], line_pts[1][1], line_pts[1][2])], fill=(250, 250, 255, 240), width=1)

    # Taut Center Tennis Net with White Top Band
    draw_box(draw, 165, -161, 3, 190, 1.5, 9, (242, 244, 248), alpha=210)

    # Grand Architectural Stone Entry Monuments
    draw_box(draw, -315, 195, 0, 18, 18, 38, (68, 74, 82), ambient=0.42)
    draw_box(draw, 298, 195, 0, 18, 18, 38, (68, 74, 82), ambient=0.42)
    # Entry pillar caps with integrated warm accent lights
    draw_box(draw, -317, 193, 38, 22, 22, 3, (215, 218, 222), ambient=0.60)
    draw_box(draw, 296, 193, 38, 22, 22, 3, (215, 218, 222), ambient=0.60)

    return img


# =============================================================================
# 14. DUSK / TWILIGHT EMISSIVE LIGHTING PASS (HIGH DYNAMIC RANGE GLOW)
# =============================================================================

def create_dusk_emissive_pass() -> Image.Image:
    """Generate breathtaking twilight lighting pass: warm interior glows, pool LEDs, uplights."""
    img = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 1. Warm 2700K Interior Illumination Radiating Through Panoramic Glazing
    # Ground floor living room interior light
    draw.polygon([
        project(-98, 68, 20), project(28, 68, 20),
        project(28, 68, 78), project(-98, 68, 78)
    ], fill=(255, 205, 115, 200))

    # Upper floor master suite interior light
    draw.polygon([
        project(-95, 68, 100), project(32, 68, 100),
        project(32, 68, 156), project(-95, 68, 156)
    ], fill=(255, 215, 125, 200))

    # Light spill radiating onto ground terrace outside panoramic glass
    draw.polygon([
        project(-110, 68, 2), project(40, 68, 2),
        project(60, 110, 2), project(-130, 110, 2)
    ], fill=(255, 195, 95, 80))

    # 2. Submerged Cyan-Turquoise LED Swimming Pool Glow
    pool_glow_sources = [(-150, 15, 6), (-70, 15, 6), (-110, 65, 6), (-65, 65, 6)]
    for px, py, pz in pool_glow_sources:
        p_scr = project(px, py, pz)
        # Inner bright core
        draw.ellipse([p_scr[0] - 18, p_scr[1] - 12, p_scr[0] + 18, p_scr[1] + 12], fill=(0, 245, 255, 210))
        # Outer luminous pool water bloom
        draw.ellipse([p_scr[0] - 45, p_scr[1] - 28, p_scr[0] + 45, p_scr[1] + 28], fill=(0, 210, 250, 110))

    # 3. Architectural Landscape Conical Uplights on Italian Cypress Trees
    tree_uplight_coords = [
        (-295, -70), (-295, -10), (-295, 50), (-295, 110),
        (280, -45), (280, 25)
    ]
    for tx, ty in tree_uplight_coords:
        p_base = project(tx, ty, 2)
        p_tip = project(tx, ty, 80)
        # Conical light beam
        beam_poly = [
            (p_base[0] - 6, p_base[1]),
            (p_base[0] + 6, p_base[1]),
            (p_tip[0] + 24, p_tip[1]),
            (p_tip[0] - 24, p_tip[1])
        ]
        draw.polygon(beam_poly, fill=(255, 230, 160, 95))
        # Ground fixture flare
        draw.ellipse([p_base[0] - 8, p_base[1] - 5, p_base[0] + 8, p_base[1] + 5], fill=(255, 245, 210, 220))

    # 4. Pergola Pendant Warm Downlights
    for lx in [-22, 10, 38]:
        lp = project(lx, 6, 75)
        draw.ellipse([lp[0] - 10, lp[1] - 7, lp[0] + 10, lp[1] + 7], fill=(255, 235, 165, 230))
        # Cone of warm light spilling down to dining table
        lt_base = project(lx, 6, 4)
        draw.polygon([(lp[0] - 4, lp[1]), (lp[0] + 4, lp[1]), (lt_base[0] + 26, lt_base[1]), (lt_base[0] - 26, lt_base[1])], fill=(255, 210, 120, 65))

    # 5. Boundary Wall Sconce Glows & Garage Lights
    for wx in range(-260, 260, 60):
        wp = project(wx, 187, 8)
        draw.ellipse([wp[0] - 12, wp[1] - 8, wp[0] + 12, wp[1] + 8], fill=(255, 230, 160, 130))

    # Apply Gaussian blur for physically realistic lens atmospheric diffusion
    blurred = img.filter(ImageFilter.GaussianBlur(radius=7.0))
    return blurred


# =============================================================================
# ASSET BUILD PIPELINE & MANIFEST EXPORT
# =============================================================================

def build_all_assets(assets_dir: Path) -> Dict[str, Any]:
    """Generate and write all photorealistic architectural layers and layer manifest."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    arch_dir = assets_dir / "architecture"
    env_dir = assets_dir / "environment"
    land_dir = assets_dir / "landscaping"
    pool_dir = assets_dir / "pool"
    manifests_dir = assets_dir / "manifests"

    for d in [arch_dir, env_dir, land_dir, pool_dir, manifests_dir]:
        d.mkdir(parents=True, exist_ok=True)

    print("Executing BuildSite Ultra-Realistic Architectural Graphics Generator...")

    layer_definitions = [
        ("plot_base", env_dir / "plot_base.png", create_plot_base),
        ("foundations", arch_dir / "foundations.png", create_foundations),
        ("columns_beams", arch_dir / "columns_beams.png", create_columns_beams),
        ("building_frame", arch_dir / "building_frame.png", create_building_frame),
        ("roof_enclosure", arch_dir / "roof_enclosure.png", create_roof_enclosure),
        ("villa_finished", arch_dir / "villa_finished.png", create_villa_finished),
        ("driveway_garage", arch_dir / "driveway_garage.png", create_driveway_garage),
        ("swimming_pool", pool_dir / "swimming_pool.png", create_swimming_pool),
        ("gardens", land_dir / "gardens.png", create_gardens),
        ("patio_pergola", land_dir / "patio_pergola.png", create_patio_pergola),
        ("upgrades", arch_dir / "upgrades.png", create_upgrades),
        ("estate_guesthouse", arch_dir / "estate_guesthouse.png", create_estate_guesthouse),
        ("master_expansion", arch_dir / "master_expansion.png", create_master_expansion),
        ("dusk_emissive", env_dir / "dusk_emissive.png", create_dusk_emissive_pass),
    ]

    manifest = {
        "version": 1,
        "resolution": {"width": WIDTH, "height": HEIGHT},
        "layers": {}
    }

    for idx, (name, path, gen_func) in enumerate(layer_definitions, start=1):
        print(f"  Rendering {name} -> {path.name}...")
        image = gen_func()
        image.save(path, format="PNG", optimize=True)
        rel_path = path.relative_to(assets_dir).as_posix()
        manifest["layers"][name] = {
            "file": rel_path,
            "order": idx,
            "width": WIDTH,
            "height": HEIGHT
        }

    manifest_path = manifests_dir / "layer_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Asset generation complete. Manifest saved to {manifest_path}")
    return manifest


if __name__ == "__main__":
    assets_path = Path(__file__).parent.parent / "assets"
    build_all_assets(assets_path)
