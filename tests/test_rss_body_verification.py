# -*- coding: utf-8 -*-
"""RSS body verification: no network, page fetch and classification stubbed."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from x_reader.fetchers import rss
from x_reader.fetchers.jina import CrossPlatformRedirect
from x_reader.reader import UniversalReader

STORY = "\n".join(
    f"Paragraph {i} of the story explains another step of the argument in plain words." for i in range(40)
)
LATER = "\n".join(
    f"Later section {i} adds detail that the feed never carried, sentence after sentence." for i in range(80)
)


def _item(**changes):
    item = {"content_kind": "full", "url": "https://e.com/a", "summary": f"<p>{STORY}</p>",
            "title": "A", "source": "F", "published": ""}
    item.update(changes)
    return item


def _page(content, **changes):
    page = {"title": "A", "content": content, "url": "https://e.com/a",
            "embedded_media": 0, "page_signals": []}
    page.update(changes)
    return page


class RssBodyVerificationTest(unittest.TestCase):
    """The four outcomes, judged with a stubbed page read and receipt."""

    def _verify(self, article, page=None, receipt=None, fetch_error=None, hops=()):
        """Run verify_full_body with stubbed page fetch and classification.

        hops: redirect targets the stubbed page read reports to its hop_guard
        before failing, so a cross-platform chain is modelled without network.
        """
        fetched = []

        def fake_fetch(url, hop_guard):
            fetched.append(url)
            for hop in hops:
                hop_guard(hop)  # raises for a cross-platform target, like the real read
            if fetch_error is not None:
                raise fetch_error
            return page

        receipt = receipt if receipt is not None else {"status": "PASS", "reason_code": "text_body_read"}
        with patch.object(rss, "_fetch_article_page", side_effect=fake_fetch), \
                patch.object(rss, "_classify_page", return_value=receipt) as classify, \
                patch.object(rss.logger, "warning") as warned:
            kind = asyncio.run(rss.verify_full_body(article))
        return kind, fetched, classify, warned

    def test_page_passes_and_text_matches_both_ways_is_full(self):
        kind, fetched, classify, warned = self._verify(_item(), page=_page(STORY))
        self.assertEqual(kind, "full")
        self.assertEqual(fetched, ["https://e.com/a"])
        classify.assert_called_once()
        # the page is judged as the text the direct read showed, not as markup
        payload = classify.call_args.args[0]
        self.assertEqual(payload["extra"]["fetch_method"], "direct_html_pinned")
        self.assertEqual(payload["extra"]["embedded_media"], 0)
        self.assertIs(payload["extra"]["body_verified"], True)
        warned.assert_not_called()

    def test_page_passes_but_feed_carries_only_an_excerpt_is_summary(self):
        kind, _fetched, _classify, warned = self._verify(_item(), page=_page(STORY + "\n" + LATER))
        self.assertEqual(kind, "summary")
        warned.assert_not_called()

    def test_gated_page_is_unverified(self):
        for receipt in ({"status": "FAIL", "reason_code": "auth_required"},
                        {"status": "PARTIAL", "reason_code": "paywall_or_teaser"},
                        {"status": "UNKNOWN", "reason_code": "thin_generic_body"}):
            kind, fetched, _classify, warned = self._verify(
                _item(), page=_page("Sign in to continue reading."), receipt=receipt)
            self.assertEqual(kind, "unverified", receipt)
            self.assertEqual(fetched, ["https://e.com/a"])
            warned.assert_called()  # the reason is logged, never raised

    def test_unreadable_page_is_unverified_and_never_raises(self):
        for error in (TimeoutError(), ValueError("HTTP status 403"), OSError("connection reset")):
            kind, _fetched, classify, warned = self._verify(_item(), fetch_error=error)
            self.assertEqual(kind, "unverified")
            classify.assert_not_called()
            warned.assert_called()

    def test_a_failing_receipt_check_is_unverified_not_an_error(self):
        def explode(_payload):
            raise RuntimeError("classifier failed")

        with patch.object(rss, "_fetch_article_page", return_value=_page(STORY)), \
                patch.object(rss, "_classify_page", side_effect=explode), \
                patch.object(rss.logger, "warning") as warned:
            kind = asyncio.run(rss.verify_full_body(_item()))
        self.assertEqual(kind, "unverified")
        warned.assert_called()

    def test_non_web_links_are_unverified_without_fetching(self):
        for url in (
            "https://www.youtube.com/watch?v=abcdefghijk",  # video
            "https://x.com/a/status/1",                      # post
            "https://t.me/chan/1",                           # chat message
            "https://e.com/feed",                            # another feed
            "ftp://e.com/a",                                 # not http(s)
            "mailto:a@e.com",                                # not a web page
            "",                                              # no link at all
        ):
            kind, fetched, classify, warned = self._verify(_item(url=url))
            self.assertEqual(kind, "unverified", url)
            self.assertEqual(fetched, [], url)  # no cross-platform crawl was started
            classify.assert_not_called()
            warned.assert_called()

    def test_a_redirect_into_another_platform_stops_the_check(self):
        kind, _fetched, classify, warned = self._verify(
            _item(), hops=("https://www.youtube.com/watch?v=abcdefghijk"))
        self.assertEqual(kind, "unverified")
        classify.assert_not_called()
        warned.assert_called()

    def test_non_full_items_keep_their_kind_without_fetching(self):
        for kind_in, expected in (("summary", "summary"), ("unverified", "unverified")):
            kind, fetched, classify, warned = self._verify(_item(content_kind=kind_in))
            self.assertEqual(kind, expected)
            self.assertEqual(fetched, [])
            classify.assert_not_called()
            warned.assert_not_called()

    def test_overlapping_text_only_one_way_is_unverified(self):
        # The feed body is mostly on the page, but the page is a different article.
        kind, _fetched, _classify, warned = self._verify(
            _item(summary=f"<p>{STORY}</p><p>{LATER}</p>"), page=_page(STORY))
        self.assertEqual(kind, "unverified")  # the feed body is not this page's text
        warned.assert_called()


class ReaderRssBranchTest(unittest.TestCase):
    """The single-item reader path writes the checked kind back and converts once."""

    def _read(self, article, verified_kind):
        with patch("x_reader.fetchers.rss.fetch_rss", AsyncMock(return_value=[article])), \
                patch("x_reader.fetchers.rss.verify_full_body", AsyncMock(return_value=verified_kind)):
            content = asyncio.run(UniversalReader()._fetch("rss", "https://e.com/feed"))
        self.assertEqual(article["content_kind"], verified_kind)  # written back before conversion
        self.assertEqual(content.extra["rss_content"], verified_kind)  # CLI --json and inbox agree
        return content

    def test_verified_full_body_reaches_the_unified_content(self):
        content = self._read(_item(), "full")
        self.assertEqual(content.source_type.value, "rss")
        self.assertIn(STORY.splitlines()[0], content.content)

    def test_verification_downgrades_are_carried_through(self):
        self.assertEqual(self._read(_item(), "summary").extra["rss_content"], "summary")
        self.assertEqual(self._read(_item(), "unverified").extra["rss_content"], "unverified")

    def test_a_raised_check_still_returns_unverified_content(self):
        article = _item()
        with patch("x_reader.fetchers.rss.fetch_rss", AsyncMock(return_value=[article])), \
                patch("x_reader.fetchers.rss.verify_full_body", AsyncMock(side_effect=RuntimeError("boom")),), \
                patch("x_reader.reader.logger.warning") as warned:
            content = asyncio.run(UniversalReader()._fetch("rss", "https://e.com/feed"))
        self.assertEqual(content.extra["rss_content"], "unverified")
        self.assertEqual(article["content_kind"], "unverified")
        warned.assert_called()


if __name__ == "__main__":
    unittest.main()
