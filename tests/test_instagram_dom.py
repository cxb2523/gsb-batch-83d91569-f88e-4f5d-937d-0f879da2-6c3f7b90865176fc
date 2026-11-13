import unittest
from datetime import datetime, timezone
from pathlib import Path

from gatherradar.collectors.instagram_dom import (
    ORIGIN_POST,
    ORIGIN_REEL,
    PROFILE_PRIVATE,
    PROFILE_UNAVAILABLE,
    PROFILE_UNKNOWN,
    MalformedMediaPageError,
    MediaLink,
    caption_hashtags,
    caption_mentions,
    detect_profile_state,
    discover_media_links,
    merge_media_links,
    parse_media_href,
    parse_media_page,
)

FIXTURES = Path(__file__).parent / "fixtures" / "instagram_browser"

POST1 = MediaLink("POST1", ORIGIN_POST, "https://www.instagram.com/p/POST1/")
REEL1 = MediaLink("REEL1", ORIGIN_REEL, "https://www.instagram.com/reel/REEL1/")


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MediaHrefTests(unittest.TestCase):
    def test_post_link_forms_are_recognized(self) -> None:
        for href in (
            "/p/ABC_1-x/",
            "/davvvat/p/ABC_1-x/",
            "https://www.instagram.com/davvvat/p/ABC_1-x/",
            "https://instagram.com/p/ABC_1-x",
        ):
            with self.subTest(href=href):
                link = parse_media_href(href, "davvvat")
                self.assertEqual(
                    link, MediaLink("ABC_1-x", ORIGIN_POST, "https://www.instagram.com/p/ABC_1-x/")
                )

    def test_reel_link_is_recognized_as_reel(self) -> None:
        link = parse_media_href("/davvvat/reel/XYZ9/", "davvvat")
        self.assertEqual(link, MediaLink("XYZ9", ORIGIN_REEL, "https://www.instagram.com/reel/XYZ9/"))

    def test_owner_prefix_is_matched_case_insensitively(self) -> None:
        self.assertIsNotNone(parse_media_href("/DavVVat/p/ABC/", "davvvat"))

    def test_non_media_and_foreign_links_are_rejected(self) -> None:
        for href in (
            "/davvvat/p/ABC/c/17900000000000001/",
            "/explore/",
            "/davvvat/",
            "/someone_else/p/ABC/",
            "https://evil.example.test/p/ABC/",
            "javascript:alert(1)",
            "mailto:someone@example.test",
        ):
            with self.subTest(href=href):
                self.assertIsNone(parse_media_href(href, "davvvat"))


class DiscoverMediaLinksTests(unittest.TestCase):
    def test_profile_page_yields_posts_and_reels_in_page_order(self) -> None:
        links = discover_media_links(fixture("profile_davvvat.html"), "davvvat")

        self.assertEqual(
            [(link.shortcode, link.kind) for link in links],
            [("POST1", ORIGIN_POST), ("REEL1", ORIGIN_REEL), ("POST2", ORIGIN_POST), ("POST3", ORIGIN_POST)],
        )

    def test_same_shortcode_linked_as_post_and_reel_is_one_reel_link(self) -> None:
        html = '<a href="/davvvat/p/DUP/">a</a><a href="/davvvat/reel/DUP/">b</a>'
        links = discover_media_links(html, "davvvat")
        self.assertEqual(links, [MediaLink("DUP", ORIGIN_REEL, "https://www.instagram.com/reel/DUP/")])

    def test_merge_keeps_first_position_and_prefers_reel(self) -> None:
        first = MediaLink("X", ORIGIN_POST, "https://www.instagram.com/p/X/")
        reel = MediaLink("X", ORIGIN_REEL, "https://www.instagram.com/reel/X/")
        other = MediaLink("Y", ORIGIN_POST, "https://www.instagram.com/p/Y/")

        self.assertEqual(merge_media_links([first], [other, reel]), [reel, other])

    def test_page_without_media_links_yields_nothing(self) -> None:
        self.assertEqual(discover_media_links(fixture("private_profile.html"), "davvvat"), [])


class ProfileStateTests(unittest.TestCase):
    def test_private_notice_is_detected(self) -> None:
        self.assertEqual(detect_profile_state(fixture("private_profile.html")), PROFILE_PRIVATE)

    def test_persian_private_notice_is_detected(self) -> None:
        self.assertEqual(detect_profile_state("<div>این حساب خصوصی است</div>"), PROFILE_PRIVATE)

    def test_unavailable_notice_with_typographic_apostrophe_is_detected(self) -> None:
        self.assertEqual(detect_profile_state(fixture("unavailable_profile.html")), PROFILE_UNAVAILABLE)

    def test_ui_strings_inside_scripts_are_ignored(self) -> None:
        self.assertEqual(detect_profile_state(fixture("profile_davvvat.html")), PROFILE_UNKNOWN)


class MediaPageTests(unittest.TestCase):
    def test_caption_heading_is_extracted_with_line_breaks_and_linked_text(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)

        self.assertEqual(data.caption, "کارگاه طراحی شهری\nجمعه ساعت ۱۷ #رویداد با @venue.tehran")
        # Labels now name the scope and strategy ("article:h1"); previously just "h1".
        self.assertEqual(data.caption_source, "article:h1")

    def test_published_at_comes_from_the_time_linking_to_the_media_not_a_comment(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)

        self.assertEqual(data.published_at, datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc))
        self.assertEqual(data.published_at_source, "time[datetime]:media-link")

    def test_thumbnail_comes_from_open_graph(self) -> None:
        data = parse_media_page(fixture("post_page.html"), POST1)
        self.assertEqual(data.image_url, "https://cdn.example.test/post1-thumb.jpg")

    def test_open_graph_caption_is_only_a_fallback(self) -> None:
        data = parse_media_page(fixture("reel_page_og_only.html"), REEL1)

        self.assertEqual(data.caption, "Rooftop concert: Friday 19:00")
        self.assertEqual(data.caption_source, "og:description")
        self.assertIsNone(data.published_at)
        self.assertEqual(data.published_at_source, "none")

    def test_reel_link_is_classified_as_reel(self) -> None:
        self.assertEqual(parse_media_page(fixture("reel_page_og_only.html"), REEL1).kind, ORIGIN_REEL)

    def test_post_redirected_to_a_reel_url_is_classified_as_reel(self) -> None:
        data = parse_media_page(
            fixture("post_page.html"), POST1, final_url="https://www.instagram.com/reel/POST1/?igsh=x"
        )
        self.assertEqual(data.kind, ORIGIN_REEL)

    def test_post_link_stays_a_post(self) -> None:
        data = parse_media_page(
            fixture("post_page.html"), POST1, final_url="https://www.instagram.com/p/POST1/"
        )
        self.assertEqual(data.kind, ORIGIN_POST)

    def test_article_timestamp_is_used_when_no_media_link_carries_one(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><time datetime="2026-09-09T10:00:00+03:30"></time></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))

        self.assertEqual(data.published_at, datetime(2026, 9, 9, 6, 30, tzinfo=timezone.utc))
        self.assertEqual(data.published_at_source, "time[datetime]:article")

    def test_naive_timestamp_is_not_assigned_a_timezone(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><a href="/p/X1/"><time datetime="2026-09-09T14:30:00"></time></a></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))
        self.assertIsNone(data.published_at)

    def test_comment_timestamp_alone_is_never_used(self) -> None:
        html = (
            '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
            '<article><a href="/p/X1/c/1/"><time datetime="2026-09-10T08:00:00Z"></time></a></article>'
        )
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))
        self.assertIsNone(data.published_at)

    def test_missing_caption_stays_null(self) -> None:
        html = '<meta property="og:url" content="https://www.instagram.com/p/X1/">'
        data = parse_media_page(html, MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/"))

        self.assertIsNone(data.caption)
        self.assertEqual(data.caption_source, "none")

    def test_page_without_media_content_is_malformed(self) -> None:
        with self.assertRaises(MalformedMediaPageError):
            parse_media_page(fixture("malformed_media_page.html"), POST1)

    def test_page_showing_different_media_is_malformed(self) -> None:
        with self.assertRaises(MalformedMediaPageError):
            parse_media_page(fixture("post_page.html"), REEL1)


AUTHOR_LIST_CAPTION = "جمعه ۲۱ شهریور دورهمی دعوت داریم 🎉\nبرای ثبت نام به @venue پیام بدید\n#رویداد #تهران"
DIR_AUTO_CAPTION = "دورهمی کتابخوانی 📚\nپنجشنبه ساعت ۱۸ در کافه @cafe.tehran"
REEL_CAPTION = "Rooftop concert 🎶 Friday 19:00\nTickets: #concert @music.hall"

LIST1 = MediaLink("LIST1", ORIGIN_POST, "https://www.instagram.com/p/LIST1/")
ITEM1 = MediaLink("ITEM1", ORIGIN_POST, "https://www.instagram.com/p/ITEM1/")
DIR1 = MediaLink("DIR1", ORIGIN_POST, "https://www.instagram.com/p/DIR1/")
REELCAP1 = MediaLink("REELCAP1", ORIGIN_REEL, "https://www.instagram.com/reel/REELCAP1/")
NOCAP1 = MediaLink("NOCAP1", ORIGIN_POST, "https://www.instagram.com/p/NOCAP1/")
X1 = MediaLink("X1", ORIGIN_POST, "https://www.instagram.com/p/X1/")
OG_URL_X1 = '<meta property="og:url" content="https://www.instagram.com/p/X1/">'

RENDERED_CAPTION_FIXTURES = (
    ("caption_author_list.html", LIST1),
    ("caption_dir_auto.html", DIR1),
    ("reel_caption.html", REELCAP1),
    ("caption_list_item.html", ITEM1),
)


def page(head: str, body: str = "") -> str:
    return f"<html><head>{head}</head><body>{body}</body></html>"


class RenderedCaptionTests(unittest.TestCase):
    def parse(self, name: str, link: MediaLink):
        return parse_media_page(fixture(name), link, username="davvvat")

    def test_caption_inside_article_h1(self) -> None:
        data = self.parse("post_page.html", POST1)

        self.assertTrue(data.caption.startswith("کارگاه طراحی شهری"))
        self.assertEqual(data.caption_source, "article:h1")

    def test_caption_inside_first_caption_list_item(self) -> None:
        data = self.parse("caption_list_item.html", ITEM1)

        self.assertEqual(data.caption, "Rooftop jazz night 🎷\nThursday 20:00 tickets.example.test/jazz")
        self.assertEqual(data.caption_source, "article:caption-item")

    def test_caption_inside_author_associated_block(self) -> None:
        data = self.parse("caption_author_list.html", LIST1)

        self.assertEqual(data.caption, AUTHOR_LIST_CAPTION)
        self.assertEqual(data.caption_source, "main:author-block")

    def test_caption_inside_span_dir_auto(self) -> None:
        data = self.parse("caption_dir_auto.html", DIR1)

        self.assertEqual(data.caption, DIR_AUTO_CAPTION)
        self.assertEqual(data.caption_source, "article:dir-auto")

    def test_reel_caption(self) -> None:
        data = parse_media_page(
            fixture("reel_caption.html"),
            REELCAP1,
            username="davvvat",
            final_url="https://www.instagram.com/reel/REELCAP1/",
        )

        self.assertEqual(data.caption, REEL_CAPTION)
        self.assertEqual(data.caption_source, "main:author-block")
        self.assertEqual(data.kind, ORIGIN_REEL)

    def test_persian_multiline_emoji_caption_is_preserved(self) -> None:
        caption = self.parse("caption_author_list.html", LIST1).caption

        self.assertIn("جمعه ۲۱ شهریور دورهمی دعوت داریم", caption)
        self.assertIn("🎉", caption)
        self.assertEqual(caption.count("\n"), 2)

    def test_persian_hashtags_and_mentions_come_from_the_rendered_caption(self) -> None:
        caption = self.parse("caption_author_list.html", LIST1).caption

        self.assertEqual(caption_hashtags(caption), ("رویداد", "تهران"))
        self.assertEqual(caption_mentions(caption), ("venue",))

    def test_caption_excludes_the_source_username_prefix(self) -> None:
        for name, link in RENDERED_CAPTION_FIXTURES:
            with self.subTest(fixture=name):
                self.assertFalse(self.parse(name, link).caption.startswith("davvvat"))

    def test_caption_excludes_comments_and_comment_usernames(self) -> None:
        for name, link, comment, commenter in (
            ("caption_author_list.html", LIST1, "چه برنامه خوبی", "commenter.one"),
            ("caption_list_item.html", ITEM1, "Count me in", "someone.else"),
        ):
            with self.subTest(fixture=name):
                caption = self.parse(name, link).caption
                self.assertNotIn(comment, caption)
                self.assertNotIn(commenter, caption)

    def test_caption_excludes_timestamps_like_counts_and_ui_labels(self) -> None:
        noise = ("2d", "1w", "Edited", "Reply", "See translation", "likes", "Follow", "•", "September", "More posts", "Original audio")
        for name, link in RENDERED_CAPTION_FIXTURES:
            caption = self.parse(name, link).caption
            for text in noise:
                with self.subTest(fixture=name, text=text):
                    self.assertNotIn(text, caption)

    def test_rendered_caption_wins_over_truncated_metadata(self) -> None:
        data = self.parse("caption_author_list.html", LIST1)
        self.assertNotIn("truncated metadata caption", data.caption)

    def test_dir_auto_text_attributed_to_another_account_is_not_a_caption(self) -> None:
        html = page(OG_URL_X1, '<main><a href="/other.user/">other.user</a><span dir="auto">Not the caption</span></main>')
        data = parse_media_page(html, X1, username="davvvat")

        self.assertIsNone(data.caption)
        self.assertEqual(data.caption_source, "none")

    def test_legitimate_no_caption_media_stays_empty(self) -> None:
        data = self.parse("caption_no_caption.html", NOCAP1)

        self.assertIsNone(data.caption)
        self.assertEqual(data.caption_source, "none")

    def test_published_at_and_image_url_are_still_extracted(self) -> None:
        expected = {
            "caption_author_list.html": (LIST1, datetime(2026, 9, 11, 10, 0, tzinfo=timezone.utc), "list1"),
            "caption_list_item.html": (ITEM1, datetime(2026, 9, 5, 18, 0, tzinfo=timezone.utc), "item1"),
            "caption_dir_auto.html": (DIR1, datetime(2026, 9, 12, 14, 30, tzinfo=timezone.utc), "dir1"),
            "reel_caption.html": (REELCAP1, datetime(2026, 9, 13, 8, 0, tzinfo=timezone.utc), "reelcap1"),
            "caption_no_caption.html": (NOCAP1, datetime(2026, 9, 10, 9, 0, tzinfo=timezone.utc), "nocap1"),
        }
        for name, (link, published_at, image) in expected.items():
            with self.subTest(fixture=name):
                data = self.parse(name, link)
                self.assertEqual(data.published_at, published_at)
                self.assertEqual(data.published_at_source, "time[datetime]:media-link")
                self.assertEqual(data.image_url, f"https://cdn.example.test/{image}-thumb.jpg")


class MetadataCaptionFallbackTests(unittest.TestCase):
    def parse(self, head: str):
        return parse_media_page(page(OG_URL_X1 + head), X1, username="davvvat")

    def test_open_graph_caption_decodes_html_entities(self) -> None:
        data = self.parse(
            '<meta property="og:description" content="12 likes, 3 comments - davvvat on September 10, 2026: &quot;Tom &amp; Jerry night&quot;. ">'
        )
        self.assertEqual(data.caption, "Tom & Jerry night")
        self.assertEqual(data.caption_source, "og:description")

    def test_truncated_open_graph_caption_without_closing_quote(self) -> None:
        data = self.parse(
            '<meta property="og:description" content="120 likes, 1 comments - davvvat on September 11, 2026: &quot;Long caption that was cut">'
        )
        self.assertEqual(data.caption, "Long caption that was cut")

    def test_localized_metadata_with_guillemets(self) -> None:
        data = self.parse('<meta property="og:description" content="۱۲۰ پسند، ۱ دیدگاه - davvvat در ۱۱ سپتامبر ۲۰۲۶: «دورهمی جمعه #رویداد»">')
        self.assertEqual(data.caption, "دورهمی جمعه #رویداد")

    def test_meta_name_description_fallback(self) -> None:
        data = self.parse(
            '<meta property="og:description" content="45 likes, 2 comments - davvvat on September 7, 2026">'
            '<meta name="description" content="45 likes, 2 comments - davvvat on September 7, 2026: &quot;Book club night 📚 #کتاب&quot;. ">'
        )
        self.assertEqual(data.caption, "Book club night 📚 #کتاب")
        self.assertEqual(data.caption_source, "meta:description")

    def test_unquoted_open_graph_title_fallback(self) -> None:
        data = self.parse('<meta property="og:title" content="davvvat on Instagram: Rooftop concert tonight">')
        self.assertEqual(data.caption, "Rooftop concert tonight")
        self.assertEqual(data.caption_source, "og:title")

    def test_likes_and_comments_prefix_is_never_saved_as_a_caption(self) -> None:
        data = self.parse('<meta property="og:description" content="12 likes, 3 comments - davvvat on September 9, 2026">')
        self.assertIsNone(data.caption)
        self.assertEqual(data.caption_source, "none")

    def test_empty_quoted_caption_stays_null(self) -> None:
        data = self.parse('<meta property="og:description" content="12 likes, 3 comments - davvvat on September 9, 2026: &quot;&quot;. ">')
        self.assertIsNone(data.caption)


class CaptionTokenTests(unittest.TestCase):
    def test_hashtags_include_persian_words_with_zero_width_non_joiner(self) -> None:
        self.assertEqual(caption_hashtags("#رویداد و #کارگاه‌ها #event"), ("رویداد", "کارگاه‌ها", "event"))

    def test_mentions_are_instagram_usernames(self) -> None:
        self.assertEqual(caption_mentions("با @venue.tehran و @jabama.events"), ("venue.tehran", "jabama.events"))

    def test_missing_caption_has_no_tokens(self) -> None:
        self.assertEqual(caption_hashtags(None), ())
        self.assertEqual(caption_mentions(None), ())


if __name__ == "__main__":
    unittest.main()
