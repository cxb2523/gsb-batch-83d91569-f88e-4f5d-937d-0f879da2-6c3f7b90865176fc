"""Overlay detections that must keep firing: booking engines, PMS, payments, Craft.

The custom overlay (wappalyzer_data/custom_fingerprints.json) is canonical in
flarecrawl and vendored byte-identical into each consumer by flarecrawl's
scripts/sync_overlay.py (see flarecrawl docs/overlay-consolidation.md). These
tests pin the detections the consumers rely on, so a bad re-sync or a loader
change that drops one turns the gate red. Each EMBEDS entry is the markup a
real customer site ships for that vendor, not a string built from the regex.
"""

from __future__ import annotations

import pytest

from flarecrawl.wappalyzer import WappalyzerClient

EMBEDS = {
    'Craft CMS': '<form><input type="hidden" name="CRAFT_CSRF_TOKEN" value="abc123"></form>',
    'Tailwind CSS': (
        '<div class="flex items-center gap-4">'
        '<p class="text-sm font-bold text-gray-700 bg-white">Hi</p></div>'
    ),
    'SevenRooms': '<iframe src="https://www.sevenrooms.com/reservations/thevenue"></iframe>',
    'ResDiary': '<iframe src="https://www.resdiary.com/widget/Standard/TheVenue/123"></iframe>',
    'OpenTable': '<a href="https://www.opentable.com/r/the-venue-melbourne">Book a table</a>',
    'Mr Yum': '<a href="https://www.mryum.com/menu/the-venue">Order now</a>',
    'me&u': '<a href="https://meandu.com/the-venue">Order at the table</a>',
    'Quandoo': '<script src="https://booking-widget.quandoo.com/index.js"></script>',
    'Dimmi': '<a href="https://www.dimmi.com.au/restaurant/the-venue">Book</a>',
    'Lightspeed Restaurant': '<script src="https://cdn.lightspeedhq.com/widget/loader.js"></script>',
    'Square Online': '<script src="https://js.squareup.com/v2/paymentform"></script>',
    'Bento': '<a href="https://thevenue.bfresco.com/menu">Order online</a>',
    'Now Book It': '<iframe src="https://booking.nowbookit.com/?accountid=1&venueid=2"></iframe>',
    'Bopple': '<a href="https://thevenue.bopple.com/">Order</a>',
    'HungryHungry': '<a href="https://order.hungryhungry.com/the-venue">Order</a>',
    'Chewzie': '<a href="https://order.chewzie.com/the-venue">Order</a>',
    'BYTO': '<a href="https://order.byto.com.au/the-venue">Order</a>',
    'Bookeasy': '<script src="https://gadgets.impartmedia.com/gadgets.jsz?key=abc"></script>',
    'Booking Boss': '<iframe src="https://app.bookingboss.com/widget/the-tour"></iframe>',
    'Cobber': '<iframe src="https://book.respax.com/the-tour"></iframe>',
    'Nabooki': '<iframe src="https://www.nabooki.com/book/the-venue"></iframe>',
    'FareHarbor': '<script src="https://fareharbor.com/embeds/api/v1/?autolightframe=yes"></script>',
    'Rezdy': '<iframe src="https://thetour.rezdy.com/widget/123"></iframe>',
    'Checkfront': '<iframe src="https://thetour.checkfront.com/reserve/"></iframe>',
    'Ventrata': '<script src="https://cdn.checkout.ventrata.com/v3/production/ventrata-checkout.min.js"></script>',
    'Bokun': '<script src="https://widgets.bokun.io/assets/javascripts/apps/build/BokunWidgetsLoader.js?bookingChannelUUID=x"></script>',
    'Xola': '<script src="https://xola.com/checkout.js"></script>',
    'TrekkSoft': '<iframe src="https://bw.trekksoft.com/the-tour"></iframe>',
    'Peek Pro': '<script src="https://js.peek.com/widget.js"></script>',
    'Regiondo': '<script src="https://widgets.regiondo.com/product/v1/product-widget.min.js"></script>',
    'Palisis': '<iframe src="https://booking.palisis.com/the-tour"></iframe>',
    'Prioticket': '<iframe src="https://shop.prioticket.com/the-tour"></iframe>',
    'FreeOnlineBooking': '<iframe src="https://www.freeonlinebooking.com/the-tour"></iframe>',
    'ATDW': '<img src="https://atlas.atdw-online.com.au/pixel?productId=1" alt="">',
    'Tourism Exchange Australia': '<iframe src="https://book.txa.com.au/v4/the-tour"></iframe>',
    'RedBalloon': '<a href="https://www.redballoon.com.au/product/the-tour">Gift it</a>',
    'Adrenaline': '<a href="https://www.adrenaline.com.au/the-tour">Gift it</a>',
    'Experience Oz': '<a href="https://www.experienceoz.com.au/the-tour">Book</a>',
    'SiteMinder': '<iframe src="https://app.thebookingbutton.com/properties/thehotel"></iframe>',
    'Little Hotelier': '<a href="https://app.littlehotelier.com/properties/thehotel">Book</a>',
    'RMS Cloud': '<iframe src="https://bookings.rmscloud.com/obookings3/Search/Index/1/90/"></iframe>',
    'NewBook': '<iframe src="https://thepark.newbook.cloud/online/booking"></iframe>',
    'HiRUM': '<a href="https://www.hirum.com.au/book/thepark">Book</a>',
    'Seekom': '<iframe src="https://web.seekom.com/thehotel"></iframe>',
    'STAAH': '<iframe src="https://bookings.staah.com/thehotel"></iframe>',
    'Update247': '<iframe src="https://www.bookings247.com.au/thehotel"></iframe>',
    'iVvy': '<iframe src="https://thevenue.ivvy.com/event/123"></iframe>',
    'Priava': '<iframe src="https://thevenue.priava.com/enquiry"></iframe>',
    'Channex': '<iframe src="https://booking.channex.io/thehotel"></iframe>',
    'Resly': '<iframe src="https://thehotel.resly.com.au/book"></iframe>',
    'MotelMate': '<a href="https://www.motelmate.com.au/book/themotel">Book</a>',
    'RoomBoss': '<iframe src="https://www.roomboss.com/thehotel"></iframe>',
    'Levart': '<a href="https://www.levart.com.au/book/thehotel">Book</a>',
    'Beds24': '<iframe src="https://beds24.com/booking2.php?propid=1"></iframe>',
    'IBIS Technology': '<iframe src="https://www.ibisreservations.com/thehotel"></iframe>',
    'CustomLinc': '<a href="https://thehotel.customlinc.com/book">Book</a>',
    'Windcave': '<form action="https://sec.windcave.com/pxaccess/pxpay.aspx"></form>',
    'eWAY': '<script src="https://secure.ewaypayments.com/scripts/eCrypt.min.js"></script>',
    'SecurePay': '<script src="https://payments.securepay.com.au/sdk/securepay-ui.min.js"></script>',
    'BPOINT': '<iframe src="https://www.bpoint.com.au/webapi/v3/txns/iframe"></iframe>',
}


@pytest.fixture(scope="module")
def client():
    return WappalyzerClient()


def _names(client, html: str) -> set[str]:
    return {d.name for d in client.analyze(html=html)}


@pytest.mark.parametrize("tech", sorted(EMBEDS))
def test_overlay_tech_detected_from_customer_embed(client, tech):
    assert tech in _names(client, f"<html><body>{EMBEDS[tech]}</body></html>")


# --- Craft CMS on a fully CDN-cached site (no Craft headers or cookies) ---
# Shape of evolution7.com.au on 2026-10-22: SEOmatic generator, no CSRF input,
# and "Craft CMS" all over the copy because the agency sells Craft.

AGENCY_COPY = (
    "<title>Craft CMS Developers Melbourne | Digital Agency</title>"
    '<meta name="keywords" content="craft cms developers, craft cms agency australia">'
    '<meta name="description" content="Award-winning Craft CMS development agency.">'
)
AGENCY_BODY = (
    '<a href="/expertise/craft-cms">Enterprise Craft CMS Specialists</a>'
    "<p>Craft publishes plugin assets under /cpresources/ on every install.</p>"
)


def test_craft_detected_from_seomatic_generator_on_cdn_cached_page(client):
    # Upstream's SEOmatic tech already implies Craft; the overlay also matches the
    # generator directly so Craft fires on its own evidence.
    html = (
        f'<html><head>{AGENCY_COPY}<meta name="generator" content="SEOmatic">'
        f"</head><body>{AGENCY_BODY}</body></html>"
    )
    assert "Craft CMS" in _names(client, html)


@pytest.mark.parametrize("asset", [
    '<link rel="stylesheet" href="https://www.example.com.au/cpresources/a1b2c3/css/forms.css?v=1">',
    '<script src="/cpresources/9f8e7d/js/freeform.js?v=1700000000"></script>',
])
def test_craft_detected_from_cpresources_asset_path(client, asset):
    assert "Craft CMS" in _names(client, f"<html><head>{asset}</head><body></body></html>")


def test_craft_not_detected_from_agency_copy_that_names_craft(client):
    html = f"<html><head>{AGENCY_COPY}</head><body>{AGENCY_BODY}</body></html>"
    assert "Craft CMS" not in _names(client, html)


def test_quandoo_detected_from_regional_script_host(client):
    # quandoo.com hosts are already caught by the src*='quandoo.com' dom rule;
    # regional hosts (quandoo.de, .it, .nl, ...) need the quandoo\.\w+ scriptSrc.
    html = '<html><head><script src="https://static.quandoo.de/widget/loader.js"></script></head></html>'
    assert "Quandoo" in _names(client, html)


# --- scripts/sync_overlay.py: how consumers get their copy ---


def _sync_module():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "sync_overlay.py"
    spec = importlib.util.spec_from_file_location("sync_overlay", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sync_writes_identical_copy_licence_and_stamp(tmp_path):
    sync = _sync_module()
    assert sync.main([str(tmp_path), "--allow-dirty"]) == 0
    copy = tmp_path / "custom_fingerprints.json"
    assert copy.read_bytes() == sync.OVERLAY.read_bytes()
    assert (tmp_path / "LICENSE.wappalyzer_data").exists()
    assert sync.check(tmp_path)["in_sync"] is True


def test_sync_check_reports_drift_after_hand_edit_in_consumer(tmp_path):
    sync = _sync_module()
    sync.main([str(tmp_path), "--allow-dirty"])
    copy = tmp_path / "custom_fingerprints.json"
    copy.write_text(copy.read_text(encoding="utf-8").replace("SEOmatic", "SEOmatix"), encoding="utf-8")
    assert sync.main([str(tmp_path), "--check"]) == 1
