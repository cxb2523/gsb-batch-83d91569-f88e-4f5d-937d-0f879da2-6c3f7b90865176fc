"""Turn the site's HTML into plain data.

Nothing here touches the network: every function takes the page text, which is
what makes the parser testable with small hand-written fixtures. The selectors
anchor on things that survive layout changes (link shapes, element ids, text
patterns) rather than on "the 12th div in the row".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup, Tag

from .errors import LayoutError

log = logging.getLogger(__name__)

HTML_PARSER = "html.parser"
#: How the site prints times in the list, and how the database stores them.
TIME_FORMAT = "%Y-%m-%d %H:%M"

GALLERY_LINK = re.compile(r"/g/(\d+)/([0-9a-f]+)/?")
IMAGE_PAGE_LINK = re.compile(r"/s/[0-9a-f]+/(\d+)-(\d+)")
POSTED_ID = re.compile(r"^posted_(\d+)$")
PAGE_COUNT = re.compile(r"^([\d,]+) pages?$")
THUMB_TITLE = re.compile(r"^Page\s+(\d+):\s*(.+)$")
SHOWING = re.compile(r"Showing\s+([\d,]+)\s*-\s*([\d,]+)\s+of\s+([\d,]+)\s+images?")
IMAGE_INFO = re.compile(r"^(.+?)\s+::\s+\d+\s+x\s+\d+")
NUMBER = re.compile(r"[\d,]+(?:\.\d+)?")
#: Ids of the "Next >" links above and below the gallery list.
NEXT_LINK_IDS = ("dnext", "unext")
#: Favourite counts the site spells out instead of "N times".
FAVORITED_WORDS = {"never": 0, "once": 1}

# Pages the site serves instead of the content we asked for.
BAN_MARKER = "Your IP address has been temporarily banned"
SERVICE_UNAVAILABLE_MARKER = "Error 503 Service Unavailable"
UNAVAILABLE_MARKERS = ("This gallery has been removed or is unavailable", "Gallery not found")
CONTENT_WARNING_MARKER = "Content Warning"
#: File name of the placeholder image served once the image quota is used up.
QUOTA_PLACEHOLDER = "509.gif"
BAN_DURATION_PART = re.compile(r"(\d+)\s+(day|hour|minute|second)s?")
SECONDS_PER = {"day": 86400, "hour": 3600, "minute": 60, "second": 1}


@dataclass(frozen=True)
class ListEntry:
    """One row of the gallery list (the ``hentai_list`` table)."""

    gallery_id: int
    url_hash: str
    big_tag: str
    title: str
    timestamp: str
    uploader: str
    pages: int

    @property
    def posted(self) -> datetime:
        return datetime.strptime(self.timestamp, TIME_FORMAT)


@dataclass(frozen=True)
class ListPage:
    entries: list[ListEntry]
    next_url: str | None
    #: Rows that had a gallery link but could not be read.
    skipped_rows: int = 0


@dataclass(frozen=True)
class GalleryInfo:
    """Metadata from a gallery page (the ``page_information`` table)."""

    tags: dict[str, list[str]]
    favorited_time: int
    rating_count: int
    average_score: float


@dataclass(frozen=True)
class Thumbnail:
    page_number: int
    page_url: str
    #: Original file name, when the thumbnail tooltip shows it (lets resume skip a request).
    file_name: str | None


@dataclass(frozen=True)
class ThumbnailPage:
    first: int
    last: int
    total: int
    thumbnails: list[Thumbnail]


@dataclass(frozen=True)
class ImagePage:
    image_url: str
    file_name: str | None


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, HTML_PARSER)


def _text(tag: Tag | None) -> str:
    return tag.get_text(" ", strip=True) if tag is not None else ""


def _int(text: str) -> int:
    match = NUMBER.search(text)
    if match is None:
        raise ValueError(f"no number in {text!r}")
    return int(match.group().replace(",", "").split(".")[0])


# --- gallery list ------------------------------------------------------------------


def parse_gallery_url(url: str) -> tuple[int, str]:
    """Return ``(gallery id, token)`` from ``…/g/<id>/<token>/``."""
    match = GALLERY_LINK.search(urlsplit(url).path)
    if match is None:
        raise ValueError(f"not a gallery URL: {url}")
    return int(match.group(1)), match.group(2)


def parse_list_page(html: str, base_url: str) -> ListPage:
    soup = _soup(html)
    table = soup.find("table", class_="itg")
    if not isinstance(table, Tag):
        raise LayoutError("the gallery list table (table.itg) is missing; the site layout may have changed")

    entries: list[ListEntry] = []
    skipped = 0
    for row in table.find_all("tr"):
        if row.find_parent("table") is not table:
            continue
        link = row.find("a", href=GALLERY_LINK)
        if not isinstance(link, Tag):
            continue  # header or advert row
        gallery_id, url_hash = parse_gallery_url(str(link["href"]))
        try:
            entries.append(_list_entry(row, link, gallery_id, url_hash))
        except (LayoutError, ValueError) as exc:
            skipped += 1
            log.warning("list row for gallery %s skipped: %s", gallery_id, exc)
    return ListPage(entries, _next_url(soup, base_url), skipped)


def _list_entry(row: Tag, link: Tag, gallery_id: int, url_hash: str) -> ListEntry:
    posted = row.find(id=POSTED_ID)
    if posted is None:
        raise LayoutError("no posted time")
    timestamp = _text(posted)
    datetime.strptime(timestamp, TIME_FORMAT)  # reject anything the database could not compare

    page_divs = [div for div in row.find_all("div") if PAGE_COUNT.match(_text(div))]
    if not page_divs:
        raise LayoutError("no page count")
    pages_div = page_divs[-1]  # the uploader column comes last; earlier ones are in the hover popup

    uploader_link = row.find("a", href=re.compile(r"/uploader/"))
    if uploader_link is not None:
        uploader = _text(uploader_link)
    else:  # disowned galleries: plain text right before the page count
        before = pages_div.find_previous_sibling("div")
        uploader = _text(before)

    title_tag = row.find(class_="glink") or link
    category = row.find("div", class_=["cn", "cs"])
    return ListEntry(
        gallery_id=gallery_id,
        url_hash=url_hash,
        big_tag=_text(category),
        title=_text(title_tag),
        timestamp=timestamp,
        uploader=uploader,
        pages=_int(_text(pages_div)),
    )


def _next_url(soup: BeautifulSoup, base_url: str) -> str | None:
    for link_id in NEXT_LINK_IDS:
        link = soup.find("a", id=link_id)
        if isinstance(link, Tag) and link.get("href"):
            return urljoin(base_url, str(link["href"]))
    return None


# --- gallery page ------------------------------------------------------------------


def content_warning_url(html: str, base_url: str) -> str | None:
    """If this is the "Content Warning" interstitial, return the link that skips it."""
    soup = _soup(html)
    if CONTENT_WARNING_MARKER not in soup.get_text() or soup.find(id="taglist") or soup.find(id="favcount"):
        return None
    link = soup.find("a", href=re.compile(r"[?&]nw="))
    return urljoin(base_url, str(link["href"])) if isinstance(link, Tag) else None


def parse_gallery_info(html: str) -> GalleryInfo:
    soup = _soup(html)
    return GalleryInfo(
        tags=_tags(soup),
        favorited_time=_favorited(_required(soup, "favcount")),
        rating_count=_int(_required(soup, "rating_count")),
        average_score=_score(_required(soup, "rating_label")),
    )


def _required(soup: BeautifulSoup, element_id: str) -> str:
    tag = soup.find(id=element_id)
    if tag is None:
        raise LayoutError(f"gallery page has no #{element_id}; the site layout may have changed")
    return _text(tag)


def _tags(soup: BeautifulSoup) -> dict[str, list[str]]:
    taglist = soup.find(id="taglist")
    tags: dict[str, list[str]] = {}
    if not isinstance(taglist, Tag):
        return tags
    for row in taglist.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        namespace = _text(cells[0]).replace(":", "")
        tags[namespace] = [_text(a) for a in row.find_all("a")]
    return tags


def _favorited(text: str) -> int:
    word = text.split(" ")[0].lower()
    return FAVORITED_WORDS[word] if word in FAVORITED_WORDS else _int(text)


def _score(text: str) -> float:
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group()) if match else 0.0  # "Not Yet Rated"


def parse_thumbnail_page(html: str, base_url: str) -> ThumbnailPage:
    soup = _soup(html)
    showing = SHOWING.search(soup.get_text(" "))
    if showing is None:
        raise LayoutError("gallery page has no 'Showing a - b of n images' line")
    first, last, total = (int(group.replace(",", "")) for group in showing.groups())

    area = soup.find(id="gdt") or soup
    thumbnails: dict[int, Thumbnail] = {}
    for link in area.find_all("a", href=IMAGE_PAGE_LINK):
        match = IMAGE_PAGE_LINK.search(str(link["href"]))
        assert match is not None  # the href filter above guarantees it
        number = int(match.group(2))
        if number not in thumbnails:
            thumbnails[number] = Thumbnail(number, urljoin(base_url, str(link["href"])), _thumb_name(link))
    return ThumbnailPage(first, last, total, list(thumbnails.values()))


def _thumb_name(link: Tag) -> str | None:
    for tag in (link, *link.find_all(title=True)):
        match = THUMB_TITLE.match(str(tag.get("title", "")))
        if match:
            return match.group(2).strip()
    return None


# --- image page --------------------------------------------------------------------


def parse_image_page(html: str, base_url: str) -> ImagePage:
    soup = _soup(html)
    image = soup.find("img", id="img")
    if not isinstance(image, Tag) or not image.get("src"):
        raise LayoutError("image page has no img#img; the site layout may have changed")
    return ImagePage(urljoin(base_url, str(image["src"])), _image_name(soup))


def _image_name(soup: BeautifulSoup) -> str | None:
    for div in soup.find_all("div"):
        if div.find(True) is None:  # leaf divs only, so parents don't swallow other text
            match = IMAGE_INFO.match(_text(div))
            if match:
                return match.group(1)
    return None


def is_quota_placeholder(image_url: str) -> bool:
    return urlsplit(image_url).path.rsplit("/", 1)[-1] == QUOTA_PLACEHOLDER


# --- error pages -------------------------------------------------------------------


def ban_expires_in(text: str) -> float | None:
    """Seconds left on a ban, from "The ban expires in 2 hours and 5 minutes"."""
    _, found, rest = text.partition("expires in")
    if not found:
        return None
    sentence = rest.split(".")[0]
    seconds = sum(int(n) * SECONDS_PER[unit] for n, unit in BAN_DURATION_PART.findall(sentence))
    return float(seconds) or None
