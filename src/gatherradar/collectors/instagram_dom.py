from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse

# Pure HTML extraction for the browser-backed Instagram collector. Everything here works
# on page HTML strings (Playwright's page.content()), so it is testable offline against
# local fixtures. Selection relies on URL patterns, semantic elements (a[href], article,
# ul/li, h1, time[datetime], dir="auto", Open Graph meta), and the relationship between
# text and the source author's profile link — never on Instagram's generated CSS class
# names, which change frequently.

ORIGIN_POST = "post"
ORIGIN_REEL = "reel"

PROFILE_PRIVATE = "private"
PROFILE_UNAVAILABLE = "unavailable"
PROFILE_UNKNOWN = "unknown"

_INSTAGRAM_HOSTS = frozenset({"instagram.com", "www.instagram.com"})
_MEDIA_PATH = re.compile(
    r"^/(?:(?P<owner>[A-Za-z0-9._]+)/)?(?P<segment>p|reel)/(?P<shortcode>[A-Za-z0-9_-]+)/?$"
)
_PROFILE_PATH = re.compile(r"^/(?P<username>[A-Za-z0-9._]+)/?$")
_RESERVED_PATHS = frozenset(
    {"about", "accounts", "api", "challenge", "developer", "direct", "explore", "legal", "p", "reel", "reels", "stories", "tv", "web"}
)
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)
_NON_VISIBLE_TAGS = frozenset({"script", "style", "noscript", "template"})
_LIST_TAGS = frozenset({"ul", "ol", "li"})
_CAPTION_SKIPPED_TAGS = _NON_VISIBLE_TAGS | {
    "button", "time", "svg", "img", "video", "picture", "header", "nav", "footer", "input", "textarea", "select",
}
_DIR_AUTO_TAGS = frozenset({"span", "div", "p", "h1"})
_DIR_AUTO_SKIPPED_TAGS = _CAPTION_SKIPPED_TAGS | _LIST_TAGS | {"h2", "h3", "h4", "h5", "h6"}
_INTERACTIVE_ROLES = frozenset({"button", "link", "navigation", "menu", "menuitem", "tab", "tablist"})
_MAX_AUTHOR_LINKS = 5
_MAX_AUTHOR_BLOCK_DEPTH = 6

# Whole text nodes that are Instagram interface chrome rather than caption wording.
_UI_LABELS = frozenset(
    {
        "•", "·", "…", "...", "more", "… more", "...more", "less", "edited", "verified",
        "follow", "following", "reply", "see translation", "hide translation", "translate",
        "original audio", "paid partnership", "sponsored", "pinned", "view replies",
        "hide replies", "log in", "sign up", "instagram",
        "پاسخ", "دیدن ترجمه", "مشاهده ترجمه", "دنبال کردن", "بیشتر",
    }
)
_UI_NOISE = (
    re.compile(r"[\d.,٬٫۰-۹]+\s*[km]?\s*(?:likes?|views?|plays?|comments?)", re.IGNORECASE),
    re.compile(r"view all [\d.,]+ comments?", re.IGNORECASE),
    re.compile(r"view replies \(\d+\)", re.IGNORECASE),
    re.compile(r"add a comment(?:…|\.\.\.)?", re.IGNORECASE),
    re.compile(r"(?:more posts from|liked by)\b.*", re.IGNORECASE),
)

_METADATA_CAPTION_KEYS = (
    ("og:description", "og:description"),
    ("description", "meta:description"),
    ("og:title", "og:title"),
)
# "12 likes, 3 comments - davvvat on September 9, 2026: "caption"." — the caption is
# whatever follows the first colon-plus-opening-quote; a truncated value may lack the
# closing quote. Localized pages may use curly quotes or guillemets.
_META_QUOTED = re.compile(r":\s*[\"“«](?P<caption>.*)$", re.DOTALL)
_META_CLOSING_QUOTE = re.compile(r"[\"”»]\s*\.?\s*$")
_META_ON_INSTAGRAM = re.compile(r"^.*?\bon instagram\s*:\s*(?P<caption>\S.*)$", re.DOTALL | re.IGNORECASE)

# ‌ (zero-width non-joiner) is a normal part of Persian words and hashtags.
_HASHTAG = re.compile(r"#([\w‌]+)")
_MENTION = re.compile(r"@([A-Za-z0-9._]+)")

_PRIVATE_MARKERS = ("this account is private", "این حساب خصوصی است")
_UNAVAILABLE_MARKERS = ("sorry, this page isn't available", "این صفحه در دسترس نیست")


class MediaExtractionError(ValueError):
    """One media item could not be read; the rest of the run continues."""


class MalformedMediaPageError(MediaExtractionError):
    """A media page loaded but did not show recognizable content for the expected media."""


@dataclass(frozen=True, slots=True)
class MediaLink:
    shortcode: str
    kind: str
    url: str


@dataclass(frozen=True, slots=True)
class MediaPageData:
    caption: str | None
    caption_source: str
    published_at: datetime | None
    published_at_source: str
    image_url: str | None
    kind: str


@dataclass(eq=False, slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: _Node | None = None
    children: list[_Node | str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _TimeElement:
    value: str
    link_href: str | None
    in_article: bool


@dataclass(slots=True)
class _Document:
    root: _Node
    hrefs: list[str]
    meta: dict[str, str]
    times: list[_TimeElement]
    visible_text: str


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#document", {})
        self._open: list[_Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = self._append(tag, attrs)
        if tag not in _VOID_TAGS:
            self._open.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._append(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._open) - 1, 0, -1):
            if self._open[index].tag == tag:
                del self._open[index:]
                return

    def handle_data(self, data: str) -> None:
        self._open[-1].children.append(data)

    def _append(self, tag: str, attrs: list[tuple[str, str | None]]) -> _Node:
        parent = self._open[-1]
        node = _Node(tag, {name: value or "" for name, value in attrs}, parent)
        parent.children.append(node)
        return node


def _elements(
    node: _Node, *, skip: frozenset[str] = frozenset(), leaves: frozenset[str] = frozenset()
) -> Iterator[_Node]:
    """Descendant elements in document order. `skip` tags are neither yielded nor
    entered; `leaves` tags are yielded but not entered."""
    stack = [child for child in reversed(node.children) if isinstance(child, _Node)]
    while stack:
        current = stack.pop()
        if current.tag in skip:
            continue
        yield current
        if current.tag not in leaves:
            stack.extend(child for child in reversed(current.children) if isinstance(child, _Node))


def _text(node: _Node, separator: str = "") -> str:
    pieces: list[str] = []
    stack: list[_Node | str] = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            pieces.append(current)
        elif current.tag not in _NON_VISIBLE_TAGS:
            stack.extend(reversed(current.children))
    return separator.join(pieces)


def _parse(html: str) -> _Document:
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root

    hrefs: list[str] = []
    meta: dict[str, str] = {}
    times: list[_TimeElement] = []
    for element in _elements(root):
        if element.tag == "a" and element.attrs.get("href"):
            hrefs.append(element.attrs["href"])
        elif element.tag == "meta":
            key = (element.attrs.get("property") or element.attrs.get("name") or "").lower()
            if key and "content" in element.attrs:
                meta.setdefault(key, element.attrs["content"])
        elif element.tag == "time" and element.attrs.get("datetime"):
            link_href = None
            in_article = False
            ancestor = element.parent
            while ancestor is not None:
                if link_href is None and ancestor.tag == "a" and ancestor.attrs.get("href"):
                    link_href = ancestor.attrs["href"]
                in_article = in_article or ancestor.tag == "article"
                ancestor = ancestor.parent
            times.append(_TimeElement(element.attrs["datetime"], link_href, in_article))

    visible_text = " ".join(_text(root, " ").split())
    return _Document(root=root, hrefs=hrefs, meta=meta, times=times, visible_text=visible_text)


def parse_media_href(href: str, username: str | None = None) -> MediaLink | None:
    """Recognize an Instagram post or reel link (`/p/<code>/`, `/reel/<code>/`, or the
    owner-prefixed `/<username>/p/<code>/` form). When `username` is given, links
    explicitly owned by another account are rejected."""
    parsed = urlparse(href.strip())
    if parsed.scheme not in ("", "http", "https"):
        return None
    if parsed.netloc and parsed.netloc.lower() not in _INSTAGRAM_HOSTS:
        return None
    match = _MEDIA_PATH.match(parsed.path)
    if match is None:
        return None
    owner = match.group("owner")
    if username is not None and owner is not None and owner.lower() != username.strip().lower():
        return None
    segment = match.group("segment")
    shortcode = match.group("shortcode")
    return MediaLink(
        shortcode=shortcode,
        kind=ORIGIN_REEL if segment == "reel" else ORIGIN_POST,
        url=f"https://www.instagram.com/{segment}/{shortcode}/",
    )


def merge_media_links(*groups: Iterable[MediaLink]) -> list[MediaLink]:
    """One link per shortcode in first-seen order, preferring the reel form when the
    same media is linked both ways."""
    merged: dict[str, MediaLink] = {}
    for group in groups:
        for link in group:
            current = merged.get(link.shortcode)
            if current is None or (link.kind == ORIGIN_REEL and current.kind != ORIGIN_REEL):
                merged[link.shortcode] = link
    return list(merged.values())


def discover_media_links(html: str, username: str) -> list[MediaLink]:
    links = (parse_media_href(href, username) for href in _parse(html).hrefs)
    return merge_media_links(link for link in links if link is not None)


def detect_profile_state(html: str) -> str:
    """Read Instagram's visible private/unavailable notices (English or Persian UI).
    Script and style contents are ignored so bundled UI strings cannot match."""
    text = _parse(html).visible_text.lower().replace("’", "'")
    if any(marker in text for marker in _PRIVATE_MARKERS):
        return PROFILE_PRIVATE
    if any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return PROFILE_UNAVAILABLE
    return PROFILE_UNKNOWN


def parse_media_page(
    html: str,
    link: MediaLink,
    *,
    username: str | None = None,
    final_url: str | None = None,
) -> MediaPageData:
    """Extract caption, publish time, and thumbnail from one post/reel page.

    `username` is the source account; it attributes the caption to its author and keeps
    other accounts' comments out. Raises MalformedMediaPageError when the page shows
    different media or carries none of the expected caption, timestamp, or Open Graph
    evidence. Missing individual facts stay None rather than being guessed.
    """
    document = _parse(html)

    og_url = document.meta.get("og:url")
    og_link = parse_media_href(og_url) if og_url else None
    if og_link is not None and og_link.shortcode != link.shortcode:
        raise MalformedMediaPageError(
            f"media page for {link.shortcode} showed media {og_link.shortcode} instead"
        )

    caption, caption_source = _extract_caption(document, username, link.shortcode)
    published_at, published_at_source = _extract_published_at(document, link.shortcode)
    image_url = document.meta.get("og:image") or None

    if caption is None and published_at is None and image_url is None and og_link is None:
        raise MalformedMediaPageError(
            f"media page for {link.shortcode} had no recognizable caption, timestamp, or metadata"
        )

    final_link = parse_media_href(final_url) if final_url else None
    is_reel = link.kind == ORIGIN_REEL or (final_link is not None and final_link.kind == ORIGIN_REEL)

    return MediaPageData(
        caption=caption,
        caption_source=caption_source,
        published_at=published_at,
        published_at_source=published_at_source,
        image_url=image_url,
        kind=ORIGIN_REEL if is_reel else ORIGIN_POST,
    )


def _extract_caption(document: _Document, username: str | None, shortcode: str) -> tuple[str | None, str]:
    """Rendered-DOM strategies first (inside article, then main, then the page), metadata
    last. The returned source names the scope and strategy that produced the caption."""
    author = username.strip().lower() if username and username.strip() else None
    strategies = (_heading_caption, _list_item_caption, _author_block_caption, _dir_auto_caption)
    for scope_name, scope in _caption_scopes(document.root):
        for strategy in strategies:
            found = strategy(scope, author, shortcode)
            if found is not None:
                source, caption = found
                return caption, f"{scope_name}:{source}"

    for key, source in _METADATA_CAPTION_KEYS:
        caption = _metadata_caption(document.meta.get(key, ""))
        if caption:
            return caption, source
    return None, "none"


def _caption_scopes(root: _Node) -> list[tuple[str, _Node]]:
    scopes: list[tuple[str, _Node]] = []
    for tag in ("article", "main"):
        node = next((element for element in _elements(root, skip=_NON_VISIBLE_TAGS) if element.tag == tag), None)
        if node is not None:
            scopes.append((tag, node))
    scopes.append(("page", root))
    return scopes


def _heading_caption(scope: _Node, author: str | None, shortcode: str) -> tuple[str, str] | None:
    last_owner = None
    for element in _elements(scope, skip=_NON_VISIBLE_TAGS):
        if _is_media_link(element, shortcode):
            return None
        owner = _profile_owner(element)
        if owner is not None:
            last_owner = owner
        elif element.tag == "h1" and (last_owner is None or _matches_author(last_owner, author)):
            caption = _caption_text(element, author, shortcode)
            if caption:
                return "h1", caption
    return None


def _list_item_caption(scope: _Node, author: str | None, shortcode: str) -> tuple[str, str] | None:
    # A comment list is a list carrying timestamps; its first item is the caption when it
    # is unattributed or attributed to the author, and a comment otherwise.
    comment_list = next(
        (
            element
            for element in _elements(scope, skip=_NON_VISIBLE_TAGS)
            if element.tag in ("ul", "ol") and any(child.tag == "time" for child in _elements(element))
        ),
        None,
    )
    if comment_list is None:
        return None

    for item in _elements(comment_list, leaves=frozenset({"li"})):
        if item.tag != "li":
            continue
        owners = [owner for owner in map(_profile_owner, _elements(item, skip=_LIST_TAGS)) if owner]
        caption = _caption_text(item, author, shortcode, skip=_LIST_TAGS)
        if not owners and not caption:
            continue
        if owners and not _matches_author(owners[0], author):
            return None
        if not caption:
            return None
        return ("author-block" if owners else "caption-item"), caption
    return None


def _author_block_caption(scope: _Node, author: str | None, shortcode: str) -> tuple[str, str] | None:
    # Climb from the author's profile link to the smallest block holding caption text,
    # stopping before the block grows to include lists or another account's content.
    if author is None:
        return None

    author_links: list[_Node] = []
    for element in _elements(scope, skip=_NON_VISIBLE_TAGS):
        if _is_media_link(element, shortcode):
            break
        if _profile_owner(element) == author:
            author_links.append(element)

    for link in author_links[:_MAX_AUTHOR_LINKS]:
        node = link.parent
        for _ in range(_MAX_AUTHOR_BLOCK_DEPTH):
            if node is None:
                break
            if not _within(node, "header", scope):
                if _contains_tag(node, _LIST_TAGS) or _has_other_owner(node, author):
                    break
                caption = _caption_text(node, author, shortcode)
                if caption:
                    return "author-block", caption
            if node is scope:
                break
            node = node.parent
    return None


def _dir_auto_caption(scope: _Node, author: str | None, shortcode: str) -> tuple[str, str] | None:
    last_owner = None
    for element in _elements(scope, skip=_DIR_AUTO_SKIPPED_TAGS, leaves=frozenset({"a"})):
        if element.tag == "a":
            if _is_media_link(element, shortcode):
                return None
            owner = _profile_owner(element)
            if owner is not None:
                last_owner = owner
            continue
        if element.attrs.get("dir") != "auto" or element.tag not in _DIR_AUTO_TAGS:
            continue
        if _has_interactive_role(element, scope):
            continue
        if last_owner is None and scope.tag != "article":
            continue
        if last_owner is not None and not _matches_author(last_owner, author):
            continue
        caption = _caption_text(element, author, shortcode)
        if caption:
            return "dir-auto", caption
    return None


def _caption_text(
    block: _Node, author: str | None, shortcode: str, skip: frozenset[str] = frozenset()
) -> str:
    """Caption wording inside `block`: keeps text, line breaks, hashtag/mention and
    external link text; drops profile/navigation links, timestamps, buttons, media, UI
    labels, and anything after the media's own permalink."""
    skipped = _CAPTION_SKIPPED_TAGS | skip
    pieces: list[str] = []
    stack: list[_Node | str] = list(reversed(block.children))
    while stack:
        current = stack.pop()
        if isinstance(current, str):
            if not _is_noise_text(current, author):
                pieces.append(current)
            continue
        if _is_media_link(current, shortcode):
            break
        if current.tag in skipped or current.attrs.get("aria-hidden") == "true":
            continue
        if current.tag == "br":
            pieces.append("\n")
            continue
        if current.tag == "a" and not _is_caption_link(current):
            continue
        stack.extend(reversed(current.children))
    return "".join(pieces).strip()


def _is_noise_text(text: str, author: str | None) -> bool:
    stripped = text.strip()
    if not stripped:
        # Indentation from pretty-printed markup, not an intentional line break.
        return "\n" in text and bool(text.replace("\n", ""))
    lowered = stripped.lower()
    if lowered in _UI_LABELS or (author is not None and lowered == author):
        return True
    return any(pattern.fullmatch(stripped) for pattern in _UI_NOISE)


def _is_caption_link(link: _Node) -> bool:
    if _text(link).strip().startswith(("#", "@")):
        return True
    netloc = urlparse(link.attrs.get("href", "").strip()).netloc.lower()
    return bool(netloc) and netloc not in _INSTAGRAM_HOSTS


def _profile_owner(element: _Node) -> str | None:
    """Username of a plain profile link such as `/davvvat/`; caption @mentions are not owners."""
    if element.tag != "a":
        return None
    parsed = urlparse(element.attrs.get("href", "").strip())
    if parsed.scheme not in ("", "http", "https"):
        return None
    if parsed.netloc and parsed.netloc.lower() not in _INSTAGRAM_HOSTS:
        return None
    match = _PROFILE_PATH.match(parsed.path)
    if match is None or match.group("username").lower() in _RESERVED_PATHS:
        return None
    if _text(element).strip().startswith("@"):
        return None
    return match.group("username").lower()


def _matches_author(owner: str, author: str | None) -> bool:
    return author is None or owner == author


def _is_media_link(element: _Node, shortcode: str) -> bool:
    if element.tag != "a":
        return False
    link = parse_media_href(element.attrs.get("href", ""))
    return link is not None and link.shortcode == shortcode


def _has_other_owner(node: _Node, author: str) -> bool:
    return any(
        owner is not None and owner != author for owner in map(_profile_owner, _elements(node))
    )


def _contains_tag(node: _Node, tags: frozenset[str]) -> bool:
    return any(element.tag in tags for element in _elements(node))


def _within(node: _Node, tag: str, scope: _Node) -> bool:
    current: _Node | None = node
    while current is not None:
        if current.tag == tag:
            return True
        if current is scope:
            return False
        current = current.parent
    return False


def _has_interactive_role(node: _Node, scope: _Node) -> bool:
    current: _Node | None = node
    while current is not None and current is not scope:
        if current.attrs.get("role") in _INTERACTIVE_ROLES:
            return True
        current = current.parent
    return False


def _metadata_caption(value: str) -> str | None:
    match = _META_QUOTED.search(value)
    if match:
        caption = _META_CLOSING_QUOTE.sub("", match.group("caption"), count=1).strip()
        return caption or None
    match = _META_ON_INSTAGRAM.match(value)
    return match.group("caption").strip() if match else None


def _extract_published_at(document: _Document, shortcode: str) -> tuple[datetime | None, str]:
    for element in document.times:
        link = parse_media_href(element.link_href) if element.link_href else None
        if link is not None and link.shortcode == shortcode:
            parsed = _parse_timestamp(element.value)
            if parsed is not None:
                return parsed, "time[datetime]:media-link"

    for element in document.times:
        # Comment timestamps link to /p/<code>/c/<id>/ permalinks; never use them.
        if element.in_article and not (element.link_href and "/c/" in element.link_href):
            parsed = _parse_timestamp(element.value)
            if parsed is not None:
                return parsed, "time[datetime]:article"

    return None, "none"


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def caption_hashtags(caption: str | None) -> tuple[str, ...]:
    return tuple(_HASHTAG.findall(caption or ""))


def caption_mentions(caption: str | None) -> tuple[str, ...]:
    return tuple(_MENTION.findall(caption or ""))


__all__ = [
    "ORIGIN_POST",
    "ORIGIN_REEL",
    "PROFILE_PRIVATE",
    "PROFILE_UNAVAILABLE",
    "PROFILE_UNKNOWN",
    "MediaExtractionError",
    "MalformedMediaPageError",
    "MediaLink",
    "MediaPageData",
    "parse_media_href",
    "merge_media_links",
    "discover_media_links",
    "detect_profile_state",
    "parse_media_page",
    "caption_hashtags",
    "caption_mentions",
]
