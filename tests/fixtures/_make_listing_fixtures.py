#!/usr/bin/env python3
"""Generate the committed listing fixtures under tests/fixtures/listing/.

Run once from the repo root; the output is committed. The fixtures are
deliberately tiny but structurally real: a category grid container with
`data-testid="lnkProductContainer"` anchors and `divProductWrapper` tiles,
which is the markup `product_parser` actually scopes on.

Each tile block is numbered from a per-file `start`, so fixtures used on
different PAGES of one simulated run carry different `sku`s — a shared sku
would make the engine stop on `no_new_products` before the page under test
was ever reached.

The tiles sit between `<!--TILES_START-->` / `<!--TILES_END-->` markers so a
test can rebuild the same document with only the first N tiles painted, which
is how Tokopedia's lazy hydration is simulated without a browser.

Not part of the offline suite; kept beside the fixtures so the shapes can be
regenerated rather than hand-edited.
"""

import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "listing")

SHELL = """<!doctype html>
<html lang="id">
<head>
<title>Kopi Bubuk Pilihan Terlengkap - Harga Terbaik | Tokopedia</title>
<link rel="stylesheet" href="https://assets.tokopedia-static.net/x.css">
</head>
<body>
<div data-ssr="productsCategoryL2/L3SSR">
<!--TILES_START-->
{tiles}
<!--TILES_END-->
</div>
</body>
</html>
"""

TILE = """<a data-testid="lnkProductContainer" href="/tokofixture/kopi-fixture-{n}-17299503120394{n:04d}">
        <div data-testid="divProductWrapper">
          <img alt="Kopi Fixture {n}" src="https://p16-images-sign-sg.tokopedia-static.net/tos-alisg/tile{n}~tplv-aphluv4xwc-white-pad-v1:200:200.jpeg"/>
          <span>Kopi Fixture {n}</span>
          <span>Rp{price}</span>
          <img alt="Toko Fixture" src="https://p16-images-comn-sg.tokopedia-static.net/tos-alisg-i-zr7vqa5nfb-sg/img/official_store/badge_os.png~tplv-zr7vqa5nfb-image.image"/>
        </div>
      </a>"""


def page(name, count, start):
    tiles = "\n".join(TILE.format(n=n, price="%d.000" % (n * 10))
                      for n in range(start, start + count))
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        f.write(SHELL.format(tiles=tiles))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    page("page_full_a.html", 6, 1)          # a full 6-row page
    page("page_full_b.html", 6, 7)          # another full 6-row page
    page("page_full_c.html", 6, 13)         # a third, for the middle-short case
    page("page_last_short.html", 2, 13)     # a short LAST page (legitimate)
    page("page_middle_short.html", 2, 7)    # a short page that is NOT last
    # 60 tiles exist in the markup, but the simulated hydration adds only a
    # few per round, so the scroll round budget runs out with the grid still
    # growing — the case that must be reported as a floor. 60, not 30, so the
    # growth never reaches the end of the fixture and cannot accidentally
    # settle on the last round.
    page("page_still_growing.html", 60, 7)
