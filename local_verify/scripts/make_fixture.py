"""
make_fixture.py
---------------
Generate the self-contained local HTML pages used to verify the Playwright
engine's per-round scroll record with NO network at all.

Every page mimics just what the parser and page_flow touch:

  * `[data-id="landing-plp-container"]` holding `[data-base-component="card"]`
    cards whose anchors begin with `/buy-used-cars/` — the real readiness
    selector, so the engine's own wait-for-paint path runs unchanged;
  * Spinny's own heading shape
    (`[data-componentname="HeadingContent"]` with "<n> Used cars in ..."),
    which is the completeness oracle;
  * ten assets.spinny.com references, which is the inverted "served by
    Spinny" heuristic the state classifier uses;
  * an inline lazy-loader that appends a 20-car batch 300 ms after the
    document bottom is scrolled into view — the same trigger shape as the
    real grid, but driven by IntersectionObserver instead of an XHR.

The generator only WRITES files; nothing in it is imported by the scraper,
and it is deliberately kept in a different directory from the HTML it
produces (the downloaded-data sandbox rule applied by hand).

Usage:
    python -I make_fixture.py <output-dir>
"""

import os
import sys

ASSET_REFS = "".join(
    '<img src="https://assets.spinny.com/sp-file-system/public/f%d.jpg"/>' % i
    for i in range(10))


def card_html(car_id: int) -> str:
    """One minimal-but-real Spinny-shaped card for numeric id `car_id`.

    The car link stays RELATIVE, exactly like the real grid's anchors: the
    parser's item-link selector is `a[href^="/buy-used-cars/"]`, which an
    absolute URL would not match. product_parser.car_path() then urljoins
    that relative href against the page URL and only rejects it when the
    link itself CARRIES a non-Spinny host — a relative link carries no host,
    so it passes on the loopback server the same way it passes on
    spinny.com.
    """
    return (
        '<div data-base-component="card" data-componentname="CarListingDesktop">'
        '<a href="/buy-used-cars/delhi/maruti/wagon-r/vxi-2019/%d/">'
        '<h3>2019 Maruti Wagon R %d</h3></a>'
        '<span data-base-component="Pricing">3.50 Lakh</span>'
        '<div id="shortlist_icon" data-price="355000" data-label="%d" '
        'data-category="assured"></div>'
        '<span class="ds-badge-label" data-base-component="text">45.0K km</span>'
        '<span class="ds-badge-label" data-base-component="text">Petrol</span>'
        '<span class="ds-badge-label" data-base-component="text">Manual</span>'
        '<span class="ds-badge-label" data-base-component="text">DL8C</span>'
        '<span class="ds-badge-label" data-base-component="text">Rohini, Delhi</span>'
        '</div>' % (car_id, car_id, car_id))


def grid_html(card_ids):
    return "".join(card_html(i) for i in card_ids)


def listing_page(total_cards: int, advertised, initial: int = 22,
                 batch: int = 20) -> str:
    """A one-page infinite-scroll listing.

    `total_cards` is how many cars the lazy loader will ever render;
    `advertised` is the heading count (None omits the heading node, 0 writes
    a literal 0). The gap between them is exactly what distinguishes a clean
    exhaustion from a stalled lazy load.

    The grid container (`[data-id="landing-plp-container"]`) holds the cards
    as direct descendants: product_parser rejects any card that CONTAINS
    another card, the guard against recommendation carousels nested inside a
    tile, so wrapping them in an extra card-marked element would silently
    drop every row.
    """
    first = list(range(1, initial + 1))
    if advertised is None:
        heading = ""
    else:
        # The count lives ONLY in the span; the h1 is the label. Putting the
        # number in both makes BeautifulSoup's get_text read "80 80 Used
        # cars in ...", which fails the parser's heading regex and returns no
        # total — matching the real markup is what keeps total_available
        # honest here.
        heading = ('<div data-componentname="HeadingContent"><span>%d</span>'
                   '<h1>Used cars in Delhi NCR</h1></div>'
                   % advertised)
    # The sentinel sits under the grid; scrolling it into view asks for the
    # next batch, exactly like the real page's bottom-of-grid trigger.
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>local listing</title></head>
<body>
%(assets)s
%(heading)s
<div data-id="landing-plp-container">%(grid)s</div>
<div id="lazy-sentinel" style="height:4px"></div>
<script>
(function () {
    var TOTAL = %(total)d, BATCH = %(batch)d, next = %(initial)d;
    var grid = document.querySelector('[data-id="landing-plp-container"]');
    function card(id) {
        var wrap = document.createElement('div');
        wrap.setAttribute('data-base-component', 'card');
        wrap.innerHTML =
            '<a href="/buy-used-cars/delhi/maruti/wagon-r/vxi-2019/' + id
            + '/">'
            + '<h3>2019 Maruti Wagon R ' + id + '</h3></a>'
            + '<span data-base-component="Pricing">3.50 Lakh</span>'
            + '<div id="shortlist_icon" data-price="355000" data-label="' + id
            + '" data-category="assured"></div>'
            + '<span data-base-component="text">45.0K km</span>'
            + '<span data-base-component="text">Petrol</span>'
            + '<span data-base-component="text">Manual</span>'
            + '<span data-base-component="text">DL8C</span>'
            + '<span data-base-component="text">Rohini, Delhi</span>';
        return wrap;
    }
    var timer = null;
    function appendBatch() {
        if (timer || next >= TOTAL) return;
        // Deferred like the real XHR hydration: the scroll round observes the
        // bottom BEFORE these nodes exist, so growth lands on a later round.
        timer = setTimeout(function () {
            timer = null;
            var stop = Math.min(TOTAL, next + BATCH);
            for (var id = next + 1; id <= stop; id++) grid.appendChild(card(id));
            next = stop;
            document.body.setAttribute('data-rendered', String(next));
        }, 300);
    }
    var observer = new IntersectionObserver(appendBatch,
        {root: null, rootMargin: "0px", threshold: 0});
    observer.observe(document.getElementById('lazy-sentinel'));
    document.body.setAttribute('data-rendered', String(next));
})();
</script>
</body></html>""" % {
        "assets": ASSET_REFS,
        "heading": heading,
        "grid": grid_html(first),
        "total": total_cards,
        "batch": batch,
        "initial": initial,
    }


DETAIL_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<script type="application/ld+json">{"@context":"https://schema.org","@type":["Product","Car"],"name":"Hyundai Grand i10 Sportz","model":"Grand i10","fuelType":"petrol","numberOfPreviousOwners":1,"modelDate":"2019-04-01T00:00:00.000Z","vehicleModelDate":2019,"vehicleSeatingCapacity":5,"mileageFromOdometer":{"@type":"QuantitativeValue","value":63417,"unitCode":"KMT"},"color":"grey","url":"https://www.spinny.com/buy-used-cars/faridabad/hyundai/grand-i10/sportz-12-kappa-vtvt-2019/31483859/","vehicleTransmission":"manual","brand":"Hyundai","productID":31483859,"offers":{"@type":"Offer","priceCurrency":"INR","Price":392000,"url":"https://www.spinny.com/buy-used-cars/faridabad/hyundai/grand-i10/sportz-12-kappa-vtvt-2019/31483859/","availability":"http://schema.org/InStock"},"additionalProperty":[{"@type":"PropertyValue","name":"RTO","unitText":"HR26"},{"@type":"PropertyValue","name":"Registration Year","unitText":2019},{"@type":"PropertyValue","name":"Registration Month","unitText":"August"}]}</script>
</head><body>
%(assets)s
<span data-base-component="Pricing">3.88 Lakh</span>
<div><span data-base-component="text">Make Year</span><span data-base-component="text">Apr 2019</span></div>
<div><span data-base-component="text">Registration Year</span><span data-base-component="text">Aug 2019</span></div>
<div><span data-base-component="text">Fuel Type</span><span data-base-component="text">petrol (BSIV)</span></div>
<div><span data-base-component="text">Km driven</span><span data-base-component="text">63K km</span></div>
<div><span data-base-component="text">Transmission</span><span data-base-component="text">manual (regular)</span></div>
<div><span data-base-component="text">No. of Owner</span><span data-base-component="text">1st Owner</span></div>
<div><span data-base-component="text">Insurance Validity</span><span data-base-component="text">Jul  2027</span></div>
<div><span data-base-component="text">Insurance Type</span><span data-base-component="text">Third Party</span></div>
<div><span data-base-component="text">RTO</span><span data-base-component="text">HR26</span></div>
<div><span data-base-component="text">Car Location</span><span data-base-component="text">Sector-27, Faridabad</span></div>
<div data-base-component="text">1573 parts evaluated by 5 automotive experts</div>
</body></html>""" % {"assets": ASSET_REFS}


def main(argv):
    out_dir = argv[1]
    os.makedirs(out_dir, exist_ok=True)
    fixtures = {
        # Reaches its --pages target mid-grid while more catalogue remains.
        "target_reached.html": listing_page(total_cards=80, advertised=200),
        # The whole advertised catalogue renders and the grid then settles.
        "exhausted.html": listing_page(total_cards=80, advertised=80),
        # The lazy loader dies early while the heading still promises 200.
        "stalled.html": listing_page(total_cards=62, advertised=200),
        # Same early death, but no heading at all: no usable advertised total.
        "stalled_no_total.html": listing_page(total_cards=62,
                                              advertised=None),
        # A heading that reads 0 beside a grid that actually holds cars.
        "stalled_zero_total.html": listing_page(total_cards=62,
                                                advertised=0),
        "detail.html": DETAIL_PAGE,
    }
    for name, html in fixtures.items():
        path = os.path.join(out_dir, name)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("wrote %s (%d bytes)" % (path, len(html)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
