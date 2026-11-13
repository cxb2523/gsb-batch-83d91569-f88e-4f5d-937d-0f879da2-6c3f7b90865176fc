# -*- coding: utf-8 -*-
"""RSS/Atom feed fetcher.

The feed is downloaded with the pinned, per-hop validated public fetcher and
only then parsed by feedparser, so feedparser never opens network connections
or follows redirects itself.
"""

import asyncio
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

import feedparser
from loguru import logger

from x_reader.fetchers.jina import fetch_public_bytes

FEED_TYPES = {
    "application/rss+xml", "application/atom+xml", "application/rdf+xml",
    "application/xml", "text/xml", "application/x-rss+xml",
    "application/feed+json", "application/json",
}


def looks_like_feed(body: bytes) -> bool:
    """True for RSS/Atom/RDF XML or a JSON Feed, whatever Content-Type it came with."""
    head = body[:2048].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"{"):
        return b"jsonfeed.org" in head
    return head.startswith(b"<?xml") or any(tag in head for tag in (b"<rss", b"<feed", b"<rdf:rdf"))


def _is_full_body(html_body: str) -> bool:
    """A feed item may carry the article only if its visible text is substantial and not a teaser."""
    from x_reader.evidence import (
        MIN_GENERIC_BODY_CHARS, _PAYWALL_PHRASES, _ends_with_read_more, prose_chars, visible_text,
    )

    text = visible_text(html_body)
    lowered = text.lower()
    return (
        prose_chars(text) >= MIN_GENERIC_BODY_CHARS
        and not _ends_with_read_more(text)
        and not any(phrase in lowered for phrase in _PAYWALL_PHRASES)
    )


# A feed body counts as full when it covers this share of the article page's
# text, counted in overlapping word runs (with repeats), not just length...
FULL_BODY_COVERAGE = 0.8
# ...and when this share of the feed body actually appears on the page.
FEED_ON_PAGE_SHARE = 0.7


def _fetch_article_page(url: str, hop_guard) -> dict:
    """Open the linked article page over pinned, per-hop validated hops.

    A seam tests replace to judge feed bodies without a network.
    """
    from x_reader.fetchers.jina import fetch_html_page

    return fetch_html_page(url, hop_guard=hop_guard)


def _classify_page(payload: dict) -> dict:
    """Judge the article page with the generic-page evidence rules (a test seam)."""
    from x_reader.evidence import classify_payload

    return classify_payload(payload)


async def verify_full_body(article: Dict[str, Any]) -> str:
    """Check a "full" feed body against the article page it links to.

    An unmarked excerpt looks like a full body until it is set against the
    article. The item link must lead to a generic web article (a video, a post
    or a feed is not opened cross-platform); the page itself must pass as a
    readable article (no login, paywall or thin shell); then the feed body must
    appear on the page and the page's text must mostly appear in the feed body.
    Returns "full", "summary" (an excerpt of the page) or "unverified"; every
    failed check is logged as a warning and never raises, so one bad item
    cannot fail the whole feed read.
    """
    from x_reader.evidence import PASS, visible_text
    from x_reader.fetchers.jina import CrossPlatformRedirect
    from x_reader.routing import detect_platform
    from x_reader.utils.textmatch import overlap

    kind = article.get("content_kind", "summary")
    if kind != "full":
        return kind

    def article_pages_only(hop: str) -> None:
        platform = detect_platform(hop)
        if platform != "generic":
            raise CrossPlatformRedirect(hop, platform)

    link = str(article.get("url") or article.get("link") or "")
    # Only an http(s) URL the generic reader handles has an article page to
    # compare with; videos, posts and non-web links must not be crawled.
    try:
        web_link = urlparse(link).scheme.lower() in ("http", "https") and detect_platform(link) == "generic"
    except ValueError:
        web_link = False
    if not web_link:
        logger.warning(f"RSS item link is not a readable web article ({link[:80] or 'empty'}); body unverified")
        return "unverified"
    try:
        page = await asyncio.to_thread(_fetch_article_page, link, article_pages_only)
    except Exception as exc:
        logger.warning(f"RSS article page not readable ({type(exc).__name__}); body unverified")
        return "unverified"

    try:
        page_receipt = _classify_page({
            "source_type": "manual",
            "title": page["title"],
            "content": page["content"],
            "url": page.get("url") or link,
            # A missing media count is not treated as "none found": the generic
            # rules then leave the page unverified instead of passing it.
            "extra": {"fetch_method": "direct_html_pinned", "redirects_verified": True, "body_verified": True,
                      "embedded_media": page.get("embedded_media"),
                      "page_signals": page.get("page_signals") or []},
        })
    except Exception as exc:  # a malformed page read must not fail the whole feed
        logger.warning(f"RSS article page could not be judged ({type(exc).__name__}); body unverified")
        return "unverified"
    if not isinstance(page_receipt, dict) or page_receipt.get("status") != PASS:
        reason = page_receipt.get("reason_code") if isinstance(page_receipt, dict) else "unclassified"
        logger.warning(f"RSS article page is not a readable article ({reason}); body unverified")
        return "unverified"  # gated, thin or media-carrying article: nothing solid to compare

    # (the page read directly is the words it shows: nothing in it is markup)
    try:
        shares = overlap(visible_text(article.get("summary") or ""), visible_text(page["content"], markup=False))
    except Exception as exc:
        logger.warning(f"RSS feed body could not be compared with the page ({type(exc).__name__}); body unverified")
        return "unverified"
    if shares is None:
        logger.warning("RSS feed body or article page is too short to compare; body unverified")
        return "unverified"
    feed_on_page, page_in_feed = shares
    if feed_on_page < FEED_ON_PAGE_SHARE:
        logger.warning("RSS feed body is not the article page's text; body unverified")
        return "unverified"  # the feed body is not this page's text
    return "full" if page_in_feed >= FULL_BODY_COVERAGE else "summary"


async def fetch_rss(url: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch and parse an RSS/Atom feed.

    Returns a list of article dicts with: title, summary, url, source, published,
    content_kind ("full" when the feed carries the article body, else "summary").
    """
    logger.info(f"Fetching RSS: {url}")
    body, content_type, final_url = await asyncio.to_thread(
        fetch_public_bytes, url, FEED_TYPES, sniff=looks_like_feed,
    )
    feed = feedparser.parse(
        body,
        resolve_relative_uris=False,
        response_headers={"content-type": content_type, "content-location": final_url},
    )

    if feed.bozo and not feed.entries:
        raise ValueError(f"Failed to parse RSS feed: {type(feed.bozo_exception).__name__}")

    source_name = feed.feed.get("title", final_url)
    articles = []
    for entry in feed.entries[:limit]:
        full = ""
        if getattr(entry, "content", None):
            full = entry.content[0].get("value", "") or ""
        summary = getattr(entry, "summary", "") or ""
        # players, frames and audio or video enclosures the item carries (not read)
        media = len(re.findall(r"<(?:audio|video|iframe|embed|object)\b", full or summary, re.IGNORECASE)) + sum(
            1 for enclosure in entry.get("enclosures") or []
            if str(enclosure.get("type") or "").lower().startswith(("audio/", "video/")))
        articles.append({
            "title": entry.get("title", ""),
            "summary": full or summary,
            "content_kind": "full" if full and _is_full_body(full) else "summary",
            "url": entry.get("link", ""),
            "source": source_name,
            "published": entry.get("published", ""),
            "platform": "rss",
            "embedded_media": media,
        })

    logger.info(f"RSS: {len(articles)} articles from {source_name}")
    return articles
