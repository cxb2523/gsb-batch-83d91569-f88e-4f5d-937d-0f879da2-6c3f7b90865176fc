from __future__ import annotations

import pytest

from ehentai_crawler import parse
from ehentai_crawler.errors import LayoutError

from .fake_site import render

BASE = "https://site.test/"


def test_list_page_reads_every_gallery_row():
    page = parse.parse_list_page(render("list_page.html", BASE=BASE), BASE)

    assert [e.gallery_id for e in page.entries] == [1005, 1004, 1003]  # the advert row is ignored
    first = page.entries[0]
    assert first == parse.ListEntry(
        1005, "0a1b2c3d4e", "Misc", "Sample Gallery One", "2026-01-03 10:00", "uploader-a", 3
    )
    assert page.entries[1].pages == 1  # "1 page", singular
    assert page.skipped_rows == 0


def test_list_page_reads_disowned_uploader_from_plain_text():
    page = parse.parse_list_page(render("list_page.html", BASE=BASE), BASE)
    assert page.entries[2].uploader == "(Disowned)"


def test_list_page_follows_next_link_and_stops_on_last_page():
    first = parse.parse_list_page(render("list_page.html", BASE=BASE), BASE)
    last = parse.parse_list_page(render("list_page_last.html", BASE=BASE), BASE + "?next=1003")

    assert first.next_url == BASE + "?next=1003"
    assert last.next_url is None
    assert [e.gallery_id for e in last.entries] == [1002, 1001]


def test_list_page_resolves_relative_next_link():
    html = render("list_page.html", BASE="/")
    assert parse.parse_list_page(html, BASE).next_url == BASE + "?next=1003"


def test_list_page_skips_a_row_it_cannot_read():
    html = render("list_page.html", BASE=BASE).replace('id="posted_1004"', 'id="something_else"')
    page = parse.parse_list_page(html, BASE)
    assert [e.gallery_id for e in page.entries] == [1005, 1003]
    assert page.skipped_rows == 1


def test_list_page_without_table_is_a_layout_error():
    with pytest.raises(LayoutError, match=r"table.itg"):
        parse.parse_list_page("<html><body>nothing here</body></html>", BASE)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://e-hentai.org/g/123456/0123456789/", (123456, "0123456789")),
        ("https://exhentai.org/g/42/abcdef0123", (42, "abcdef0123")),
    ],
)
def test_parse_gallery_url(url, expected):
    assert parse.parse_gallery_url(url) == expected


@pytest.mark.parametrize("url", ["https://e-hentai.org/", "https://e-hentai.org/g/abc/def/", "not a url"])
def test_parse_gallery_url_rejects_other_urls(url):
    with pytest.raises(ValueError, match="not a gallery URL"):
        parse.parse_gallery_url(url)


def test_gallery_info():
    info = parse.parse_gallery_info(render("gallery_multi.html", BASE=BASE, GID=1005, HASH="0a1b2c3d4e"))
    assert info == parse.GalleryInfo(
        tags={"sample": ["alpha", "beta two"], "other": ["gamma"]},
        favorited_time=1012,
        rating_count=7,
        average_score=4.25,
    )


def test_gallery_info_without_tags_favourites_or_rating():
    info = parse.parse_gallery_info(render("gallery_single.html", BASE=BASE, GID=1004))
    assert info == parse.GalleryInfo(tags={}, favorited_time=0, rating_count=0, average_score=0.0)


def test_favourited_once():
    html = render("gallery_single.html", BASE=BASE, GID=1004).replace(">Never<", ">Once<")
    assert parse.parse_gallery_info(html).favorited_time == 1


def test_gallery_info_missing_field_is_a_layout_error():
    html = render("gallery_single.html", BASE=BASE, GID=1004).replace('id="favcount"', "")
    with pytest.raises(LayoutError, match=r"#favcount"):
        parse.parse_gallery_info(html)


def test_thumbnails_in_current_layout():
    page = parse.parse_thumbnail_page(render("gallery_multi.html", BASE=BASE, GID=1005, HASH="0a1b2c3d4e"), BASE)
    assert (page.first, page.last, page.total) == (1, 2, 3)
    assert page.thumbnails == [
        parse.Thumbnail(1, BASE + "s/aa11bb22cc/1005-1", "page 001.jpg"),
        parse.Thumbnail(2, BASE + "s/dd33ee44ff/1005-2", "page 002.jpg"),
    ]


def test_thumbnails_in_older_gdtm_layout():
    page = parse.parse_thumbnail_page(render("gallery_multi_p1.html", BASE=BASE, GID=1005), BASE)
    assert (page.first, page.last, page.total) == (3, 3, 3)
    assert page.thumbnails == [parse.Thumbnail(3, BASE + "s/0f0f0f0f0f/1005-3", "page 003.jpg")]


def test_thumbnail_counts_with_thousands_separator():
    html = render("gallery_multi.html", BASE=BASE, GID=1, HASH="ab").replace("1 - 2 of 3", "1 - 40 of 1,234")
    page = parse.parse_thumbnail_page(html, BASE)
    assert (page.first, page.last, page.total) == (1, 40, 1234)


def test_thumbnail_page_without_counts_is_a_layout_error():
    with pytest.raises(LayoutError, match="Showing"):
        parse.parse_thumbnail_page("<html></html>", BASE)


def test_image_page():
    html = render(
        "image_page.html",
        BASE=BASE,
        GID=1005,
        PAGE=2,
        TOTAL=3,
        NAME="page 002.jpg",
        IMAGE="https://images.test/h/abc/page002.jpg",
    )
    assert parse.parse_image_page(html, BASE) == parse.ImagePage(
        "https://images.test/h/abc/page002.jpg", "page 002.jpg"
    )


def test_image_page_without_image_is_a_layout_error():
    with pytest.raises(LayoutError, match=r"img#img"):
        parse.parse_image_page("<html><div>x</div></html>", BASE)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://ehgt.org/g/509.gif", True),
        ("https://site.test/img/509.gif", True),
        ("https://images.test/h/abc/page509.gif", False),
        ("https://images.test/h/abc/001.jpg", False),
    ],
)
def test_quota_placeholder(url, expected):
    assert parse.is_quota_placeholder(url) is expected


def test_content_warning_link():
    html = render("content_warning.html", BASE=BASE, GID=1004, HASH="5f6a7b8c9d")
    assert parse.content_warning_url(html, BASE) == BASE + "g/1004/5f6a7b8c9d/?nw=session"


def test_normal_gallery_is_not_a_content_warning():
    html = render("gallery_multi.html", BASE=BASE, GID=1005, HASH="0a1b2c3d4e")
    assert parse.content_warning_url(html, BASE) is None


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("1 hours and 5 minutes.", 3900), ("59 minutes and 48 seconds", 3588), ("2 days", 172800)],
)
def test_ban_duration(text, seconds):
    assert parse.ban_expires_in(render("banned.html", EXPIRES=text)) == seconds


def test_ban_duration_unknown():
    assert parse.ban_expires_in("banned, no details") is None
