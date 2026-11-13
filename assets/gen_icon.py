#!/usr/bin/env python3
"""Pixel-art icon for token-history: a minted token stamped with a rising chart.

16x16 logical grid rendered as unit rects (crispEdges), so the icon lands on
exact device pixels at 32px (2px/cell) and 96px (6px/cell). Deterministic:
same script -> same bytes. Palette mirrors scripts/render.py THEME.
"""

import os

N = 16

# color keys -> CSS class
K = "k"    # dark neutral outline / baseline
F = "f"    # cream coin face
O = "o"    # brand orange (rim + claude bars)
OL = "ol"  # rim highlight (top-left)
OD = "od"  # rim shade (bottom-right)
B = "b"    # brand blue (codex cap)

LIGHT = {"k": "#141413", "f": "#faf9f5", "o": "#d06a41",
         "ol": "#e59a70", "od": "#9c4a26", "b": "#4382c9"}
DARK = {"k": "#141413", "f": "#faf9f5", "o": "#db7448",
        "ol": "#f0a37a", "od": "#8a4526", "b": "#5b95d6"}

# hand-authored 16x16 pixel circle outline: {row: outline columns}
OUTLINE = {
    0: (5, 6, 7, 8, 9, 10),
    1: (3, 4, 11, 12),
    2: (2, 13),
    3: (1, 14),
    4: (1, 14),
    5: (0, 15), 6: (0, 15), 7: (0, 15),
    8: (0, 15), 9: (0, 15), 10: (0, 15),
    11: (1, 14),
    12: (1, 14),
    13: (2, 13),
    14: (3, 4, 11, 12),
    15: (5, 6, 7, 8, 9, 10),
}
# interior span per row (between the outline columns)
INTERIOR = {
    1: (5, 10), 2: (3, 12), 3: (2, 13), 4: (2, 13),
    5: (1, 14), 6: (1, 14), 7: (1, 14), 8: (1, 14),
    9: (1, 14), 10: (1, 14), 11: (2, 13), 12: (2, 13),
    13: (3, 12), 14: (5, 10),
}


def build_grid():
    g = [[None] * N for _ in range(N)]
    outline = set()
    for y, cols in OUTLINE.items():
        for x in cols:
            outline.add((x, y))
            g[y][x] = K
    # ---- orange rim: interior cells touching the outline (8-neighborhood),
    #      lit toward the top-left, shaded toward the bottom-right
    for y, (x0, x1) in INTERIOR.items():
        for x in range(x0, x1 + 1):
            near = any((x + dx, y + dy) in outline
                       for dx in (-1, 0, 1) for dy in (-1, 0, 1))
            if near:
                s = (x - 7.5) + (y - 7.5)
                g[y][x] = OL if s < -4 else (OD if s > 5 else O)
            else:
                g[y][x] = F
    # ---- die-struck chart: three rising bars in dark ink, blue cap on the peak
    for x in range(4, 6):                # bar 1, h=2
        for y in range(10, 12):
            g[y][x] = K
    for x in range(7, 9):                # bar 2, h=4
        for y in range(8, 12):
            g[y][x] = K
    for x in range(10, 12):              # bar 3, h=6, codex-blue cap
        for y in range(6, 8):
            g[y][x] = B
        for y in range(8, 12):
            g[y][x] = K
    return g


def runs(row):
    """Merge same-color horizontal runs -> (x0, width, color)."""
    out, x = [], 0
    while x < N:
        c = row[x]
        if c is None:
            x += 1
            continue
        x0 = x
        while x < N and row[x] == c:
            x += 1
        out.append((x0, x - x0, c))
    return out


def svg():
    title = "token-history"
    label = "token-history: a pixel token stamped with a rising token chart"
    css = ["rect{shape-rendering:crispEdges}"]
    css.append("".join(".{}{{fill:{}}}".format(k, v) for k, v in LIGHT.items()))
    css.append("@media (prefers-color-scheme: dark){" +
               "".join(".{}{{fill:{}}}".format(k, v) for k, v in DARK.items()) + "}")
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
           'role="img" aria-label="{}">'.format(label),
           "<title>{}</title>".format(title),
           "<style>{}</style>".format("".join(css))]
    for y, row in enumerate(build_grid()):
        for x0, w, c in runs(row):
            out.append('<rect class="{}" x="{}" y="{}" width="{}" height="1"/>'.format(
                c, x0, y, w))
    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "icon.svg")
    with open(path, "w") as f:
        f.write(svg())
    print("wrote", path)
