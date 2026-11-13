from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gatherradar.cli import build_parser, main
from gatherradar.config import load_sources
from gatherradar.domain import EvidenceBundle, EvidenceKind, Source, SourceType
from gatherradar.domain.evidence import caption_fragment, primary_fragment
from gatherradar.domain.website import WebsiteConfig
from gatherradar.collectors.base import CollectorError, SourceAccessRestrictedError, SourceConfigurationError, SourceUnavailableError
from gatherradar.collectors.website import WebsiteCollector
from gatherradar.collectors.websites.adapters import build_adapter, GenericAdapter
from gatherradar.collectors.websites.html import parse_html, content_text
from gatherradar.collectors.websites.transport import HttpTransport, Page, RobotsPolicy
from gatherradar.collectors.websites.urls import canonical_url, detail_url
from gatherradar.extraction import DiscoveryService, RuleBasedDiscoveryProvider
from gatherradar.grouping import ConservativeGrouping, select_semantic_evidence
from gatherradar.orchestration.website_run import run_website_collection, run_website_discovery, website_output_path
from gatherradar.storage import JsonlRawItemStore

FIXTURES = Path(__file__).parent / 'fixtures' / 'websites'
BASE = 'https://community.example/'
CONFIG = WebsiteConfig(detail_path_prefixes=('/events/',), content_selector='#event',
                       exclude_selectors=('.owner-excluded',))
SOURCE = Source('future_website', 'future', 'Future', SourceType.WEBSITE, BASE, website=CONFIG)
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def html(name):
    return (FIXTURES / name).read_text(encoding='utf-8')


class FakeTransport:
    def __init__(self, pages=None):
        self.pages = pages or {BASE: html('generic-list.html')}
        self.calls = []

    def fetch(self, url, *, allowed=None):
        self.calls.append(url)
        value = self.pages.get(url, html('generic-detail.html'))
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Page) else Page(url, value, 'fake')


def collect(transport=None, limit=1):
    return WebsiteCollector(transport=transport or FakeTransport(), now=lambda: NOW).collect(SOURCE, limit=limit)


class WebsiteConfigTests(unittest.TestCase):
    def test_registry_has_four_configured_websites(self):
        self.assertEqual(sum(s.website is not None for s in load_sources()), 4)

    def test_robots_disallowed_davvvat_website_is_disabled_but_kept(self):
        sources = {s.id: s for s in load_sources()}
        self.assertFalse(sources['davvvat_website'].enabled)  # robots.txt disallows GatherRadar
        self.assertEqual(sources['davvvat_website'].website.adapter, 'davvvat')
        self.assertTrue(sources['davvvat_instagram'].enabled)

    def test_instagram_configuration_remains_optional(self):
        self.assertTrue(all(s.website is None for s in load_sources() if s.source_type is SourceType.INSTAGRAM))

    def test_malformed_website_options_rejected(self):
        for value in ([], 'generic', {'unknown': True}, {'detail_path_prefixes': '/events/'},
                      {'detail_path_prefixes': ['https://other.example/']},
                      {'detail_path_prefixes': ['/events/'], 'content_selector': 'article > div'},
                      {'detail_path_prefixes': ['/events/'], 'exclude_selectors': [3]}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                WebsiteConfig.from_mapping(value)

    def test_unknown_adapter_refused(self):
        with self.assertRaises(SourceConfigurationError):
            build_adapter(replace(CONFIG, adapter='not-registered'))

    def test_missing_adapter_configuration_refused(self):
        with self.assertRaises(SourceConfigurationError):
            build_adapter(None)

    def test_unsafe_source_ids_and_urls_rejected(self):
        for changes in ({'id': '../escape'}, {'url': 'file:///tmp/events'},
                        {'url': 'https://user:secret@example.test/'}, {'url': 'https://example.test:bad/'},
                        {'url': 'https://bad host/'}, {'enabled': 'true'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(SOURCE, **changes)

    def test_registry_rejects_invalid_records_and_duplicate_ids(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'sources.yaml'
            for text in ('[]', 'sources: [null]', 'defaults: []\nsources: [3]',
                         'sources: [{id: a, publisher_key: a, name: A, type: unknown, url: https://example.test/}]',
                         'sources:\n' + '\n'.join(['  - {id: a, publisher_key: a, name: A, type: website, url: https://example.test/}'] * 2)):
                path.write_text(text, encoding='utf-8')
                with self.subTest(text=text), self.assertRaises(ValueError):
                    load_sources(path)

    def test_website_options_on_instagram_rejected(self):
        with self.assertRaises(ValueError):
            replace(SOURCE, source_type=SourceType.INSTAGRAM, username='demo')


class WebsiteAdapterTests(unittest.TestCase):
    def test_generic_discovery_keeps_order_deduplicates_and_restricts_urls(self):
        self.assertEqual(build_adapter(CONFIG).discover(Page(BASE, html('generic-list.html')), BASE),
                         (BASE + 'events/alpha?day=1', BASE + 'events/beta'))

    def test_query_identity_preserved_and_only_tracking_removed(self):
        self.assertEqual(canonical_url('/events/a?day=2&utm_source=x&ref=one#book', BASE),
                         BASE + 'events/a?day=2&ref=one')

    def test_declared_navigation_parameter_removed(self):
        self.assertEqual(canonical_url('/event/a?from=%2F&day=2', BASE, ('from',)), BASE + 'event/a?day=2')

    def test_unsafe_and_download_links_rejected(self):
        for url in ('https://other.example/events/a', '//other.example/events/a', '/events/../login',
                    '/events/%2e%2e/admin', '/events/a.pdf', '/events/profile', 'javascript:alert(1)',
                    'mailto:a@example.test', 'https://user:pass@community.example/events/a',
                    '/events/a/b', '/events/%252e%252e', 'http://community.example/events/a'):
            with self.subTest(url=url):
                self.assertIsNone(detail_url(url, BASE, ('/events/',)))

    def test_generic_content_is_only_source_wording(self):
        detail = build_adapter(CONFIG).extract(Page(BASE+'events/a', html('generic-detail.html')), BASE)
        self.assertIn('قیمت: ۲۰۰ هزار تومان', detail.text)
        self.assertIn('جمعه ۱۲ مهر ساعت ۱۸:۳۰', detail.text)
        for absent in ('Another', 'Competing', 'Private', 'Invisible', 'Hidden', 'Tracking', 'Account', 'Owner exclusion', 'https://'):
            self.assertNotIn(absent, detail.text)
        self.assertEqual(detail.links, ('https://tickets.example/reserve/alpha',))
        self.assertTrue(detail.structured_data_present)

    def test_generic_ambiguous_or_missing_region_fails_closed(self):
        for value in ('<main>No article</main>', '<article id="event">A</article><article id="event">B</article>'):
            with self.assertRaises(SourceUnavailableError):
                build_adapter(CONFIG).extract(Page(BASE+'events/a', value), BASE)

    def test_multiple_retained_titles_fail_closed(self):
        with self.assertRaises(SourceUnavailableError):
            build_adapter(CONFIG).extract(Page(BASE+'events/a', '<article id="event"><h1>A</h1><h1>B</h1></article>'), BASE)

    def test_generic_hidden_ancestor_cannot_supply_detail_text(self):
        with self.assertRaises(SourceUnavailableError):
            build_adapter(CONFIG).extract(Page(BASE+'events/a', '<div hidden><article id="event">Hidden event</article></div>'), BASE)

    def test_davvvat_known_streamed_panel_survives_staging_wrapper(self):
        adapter = build_adapter(WebsiteConfig('davvvat', ('/event/',), '.event-detail-right'))
        detail = adapter.extract(Page(BASE+'event/abc', '<div hidden id="S:2">'+html('davvvat-detail.html')+'</div>'), BASE)
        self.assertIn('ایونت رنگ آبی', detail.text)
        self.assertNotIn('Private', detail.text)

    def test_generic_identity_is_url_based_and_query_distinct(self):
        adapter = build_adapter(CONFIG)
        a = adapter.extract(Page(BASE+'events/a?day=1', html('generic-detail.html')), BASE)
        b = adapter.extract(Page(BASE+'events/a?day=2', html('generic-detail.html')), BASE)
        self.assertNotEqual(a.external_id, b.external_id)
        self.assertIsNone(a.native_id)
        self.assertEqual(a, adapter.extract(Page(BASE+'events/a?day=1', html('generic-detail.html')), BASE))

    def test_specialized_adapters_match_registered_keys(self):
        # Jabama version 3 also retains supported embedded session evidence.
        for key, version in (('davvvat', 1), ('vadoostan', 2), ('jabama-events', 3)):
            self.assertEqual(build_adapter(replace(CONFIG, adapter=key)).name, f'{key}/{version}')

    def test_davvvat_excludes_duplicates_and_comment_overlay(self):
        adapter = build_adapter(WebsiteConfig('davvvat', ('/event/',), '.event-detail-right', drop_query_params=('from',)))
        detail = adapter.extract(Page(BASE+'event/abc', html('davvvat-detail.html')), BASE)
        self.assertEqual(detail.native_id, 'abc')
        self.assertEqual(detail.text.count('ایونت رنگ آبی'), 1)
        for absent in ('Mobile', 'Private', 'Login', 'Account', 'Share', 'Different'):
            self.assertNotIn(absent, detail.text)
        self.assertIn('تهران، خیابان نمونه', detail.text)

    def test_vadoostan_stops_before_faq_and_organizer_biography(self):
        adapter = build_adapter(WebsiteConfig('vadoostan', ('/app/experiences/',), 'main'))
        detail = adapter.extract(Page(BASE+'app/experiences/abc', html('vadoostan-detail.html')), BASE)
        self.assertIn('همراه با وسایل نقاشی.', detail.text)
        for absent in ('سوالات متداول', 'Cancellation', 'Organizer', 'Login'):
            self.assertNotIn(absent, detail.text)

    def test_jabama_excludes_reviews_and_retains_price(self):
        adapter = build_adapter(WebsiteConfig('jabama-events', ('/events/',)))
        detail = adapter.extract(Page(BASE+'events/abc', html('jabama-detail.html')), BASE)
        self.assertIn('از ۲۰۰٬۰۰۰ تومان', detail.text)
        for absent in ('Private', 'Reviews', 'Organizer', 'Another', 'Sign in', 'Loading', 'نظر'):
            self.assertNotIn(absent, detail.text)

    def test_jabama_never_borrows_a_distant_recommendation_price(self):
        adapter = build_adapter(WebsiteConfig('jabama-events', ('/events/',)))
        page = '<main><article><h1>کنسرت آبی</h1><p>جمعه</p></article></main><aside><p>۹۹۹ تومان</p><button>خرید بلیت</button></aside>'
        detail = adapter.extract(Page(BASE+'events/a', page), BASE)
        self.assertNotIn('۹۹۹', detail.text)

    def test_jabama_ambiguous_booking_panels_supply_no_price(self):
        adapter = build_adapter(WebsiteConfig('jabama-events', ('/events/',)))
        page = html('jabama-detail.html').replace('</main>', '<aside><p>۹۹۹ تومان</p><button>خرید بلیت</button></aside></main>')
        detail = adapter.extract(Page(BASE+'events/a', page), BASE)
        self.assertNotIn('تومان', detail.text)

    def test_nested_html_is_bounded(self):
        with self.assertRaises(SourceUnavailableError):
            parse_html('<div>' * 200)

    def test_inline_words_and_blocks_preserved(self):
        self.assertEqual(content_text(parse_html('<p>Hello <b>world</b>!</p><p>Next<br>line</p>')), 'Hello world!\nNext\nline')

    def test_flex_gap_preserves_date_and_recurrence_word_boundary(self):
        node = parse_html('<div style="display:inline-flex;gap:6px"><span>از پنجشنبه ۲ مهر</span><span>هفتگی</span></div>')
        self.assertEqual(content_text(node), 'از پنجشنبه ۲ مهر هفتگی')


class WebsiteTransportTests(unittest.TestCase):
    def transport(self, responses):
        transport = HttpTransport(BASE)
        transport._request = unittest.mock.Mock(side_effect=responses)
        return transport

    @staticmethod
    def response(text, mime='text/html', status=200):
        return status, {'content-type': mime}, text.encode('utf-8')

    def test_robots_longest_rule_overrides_broad_allow(self):
        policy = RobotsPolicy('User-agent: *\nAllow: /\nDisallow: /private/\nAllow: /private/public/\n')
        self.assertFalse(policy.allows(BASE+'private/a'))
        self.assertTrue(policy.allows(BASE+'private/public/a'))

    def test_robots_specific_agent_wildcard_end_and_delay(self):
        policy = RobotsPolicy('User-agent: *\nDisallow: /\nUser-agent: GatherRadar\nDisallow: /*?secret=*\nAllow: /events/a$\nCrawl-delay: 2')
        self.assertFalse(policy.allows(BASE+'events/a?secret=yes'))
        self.assertTrue(policy.allows(BASE+'events/a'))
        self.assertEqual(policy.delay, 2)

    def test_excessive_robots_delay_refuses_run(self):
        with self.assertRaises(SourceAccessRestrictedError):
            RobotsPolicy('User-agent: *\nCrawl-delay: 300')

    def test_fetch_checks_robots_and_uses_html(self):
        t = self.transport([self.response('User-agent: *\nAllow: /', 'text/plain'), self.response('<article>Hello</article>')])
        self.assertEqual(t.fetch(BASE+'events/a').html, '<article>Hello</article>')
        self.assertEqual(t._request.call_args_list[0].args, (BASE+'robots.txt',))

    def test_disallowed_page_is_never_requested(self):
        t = self.transport([self.response('User-agent: *\nDisallow: /events/', 'text/plain')])
        with self.assertRaises(SourceAccessRestrictedError):
            t.fetch(BASE+'events/a')
        self.assertEqual(t._request.call_count, 1)

    def test_missing_robots_allows_public_html(self):
        t = self.transport([self.response('', status=404), self.response('page')])
        self.assertEqual(t.fetch(BASE).html, 'page')

    def test_robots_error_fails_closed(self):
        for status in (401, 403, 429, 500):
            t = self.transport([self.response('', status=status)])
            with self.subTest(status=status), self.assertRaises((SourceUnavailableError, SourceAccessRestrictedError)):
                t.fetch(BASE)
            self.assertEqual(t._request.call_count, 1)

    def test_robots_html_challenge_fails_closed(self):
        t = self.transport([self.response('<!doctype html><html>Sign in</html>')])
        with self.assertRaises(SourceUnavailableError):
            t.fetch(BASE)
        self.assertEqual(t._request.call_count, 1)

    def test_robots_encoded_paths_do_not_bypass_restrictions(self):
        policy = RobotsPolicy('User-agent: *\nDisallow: /private/')
        self.assertFalse(policy.allows(BASE+'%70rivate/a'))

    def test_request_errors_are_secret_safe(self):
        from urllib.error import URLError
        transport = HttpTransport(BASE)
        with patch.object(transport._opener, 'open', side_effect=URLError('secret private path')):
            with self.assertRaisesRegex(SourceUnavailableError, '^public HTTP request failed$'):
                transport.fetch(BASE)

    def test_response_size_is_bounded(self):
        from gatherradar.collectors.websites.transport import MAX_BYTES
        transport = HttpTransport(BASE)
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'x' * (MAX_BYTES + 1)
        with patch.object(transport._opener, 'open', return_value=response):
            with self.assertRaisesRegex(SourceUnavailableError, 'size bound'):
                transport.fetch(BASE)
        response.read.assert_called_once_with(MAX_BYTES + 1)

    def test_requests_honor_delay_and_timeout_without_cookies(self):
        transport = HttpTransport(BASE)
        transport._last_request = 100.0
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b''
        response.code = 404
        response.headers = {}
        with patch('gatherradar.collectors.websites.transport.time.monotonic', return_value=100.25), \
             patch('gatherradar.collectors.websites.transport.time.sleep') as sleep, \
             patch.object(transport._opener, 'open', return_value=response) as opened:
            transport._request(BASE)
        sleep.assert_called_once_with(0.75)
        self.assertEqual(opened.call_args.kwargs['timeout'], 15)
        self.assertFalse(opened.call_args.args[0].has_header('Cookie'))

    def test_cross_origin_redirect_is_not_requested(self):
        t = self.transport([self.response('', status=404), (302, {'location':'https://unapproved.example/events/a'}, b'')])
        with self.assertRaises(SourceAccessRestrictedError):
            t.fetch(BASE+'events/a')
        self.assertEqual(t._request.call_count, 2)

    def test_detail_redirect_to_listing_is_refused(self):
        t = self.transport([self.response('', status=404), (302, {'location':'/'}, b'')])
        with self.assertRaises(SourceAccessRestrictedError):
            t.fetch(BASE+'events/a', allowed=lambda url: '/events/' in url)
        self.assertEqual(t._request.call_count, 2)

    def test_redirect_target_checked_against_robots(self):
        t = self.transport([self.response('User-agent: *\nDisallow: /events/private', 'text/plain'),
                            (302, {'location':'/events/private'}, b'')])
        with self.assertRaises(SourceAccessRestrictedError):
            t.fetch(BASE+'events/a')
        self.assertEqual(t._request.call_count, 2)

    def test_redirect_loop_is_bounded(self):
        t = self.transport([self.response('', status=404)] + [(302, {'location':'/events/a'}, b'')] * 4)
        with self.assertRaises(SourceUnavailableError):
            t.fetch(BASE+'events/a')
        self.assertEqual(t._request.call_count, 5)

    def test_non_html_or_invalid_encoding_refused(self):
        for response in (self.response('pdf', 'application/pdf'), (200, {'content-type':'text/html'}, b'\xff'),
                         (200, {'content-type':'text/html','content-disposition':'attachment'}, b'page')):
            t = self.transport([self.response('', status=404), response])
            with self.assertRaises((SourceUnavailableError, SourceAccessRestrictedError)):
                t.fetch(BASE)


class WebsitePipelineTests(unittest.TestCase):
    def test_mapping_preserves_text_and_unset_publish_date(self):
        item, = collect().items
        self.assertTrue(item.id.startswith('website:future_website:'))
        self.assertEqual(item.content_type, 'webpage')
        self.assertIsNone(item.published_at)
        self.assertEqual(item.captured_at, NOW)
        self.assertEqual(item.raw_metadata['adapter'], 'generic/1')
        self.assertNotIn('<article', item.raw_text)
        self.assertNotIn('html', item.raw_metadata)

    def test_limit_follows_listing_order(self):
        result = collect(limit=2)
        self.assertEqual([i.content_url for i in result.items], [BASE+'events/alpha?day=1', BASE+'events/beta'])

    def test_failure_does_not_discard_success(self):
        result = collect(FakeTransport({BASE:html('generic-list.html'), BASE+'events/alpha?day=1':RuntimeError('secret')}))
        self.assertEqual(len(result.items), 1)
        self.assertEqual(len(result.failures), 1)
        self.assertNotIn('secret', result.failures[0].reason)
        self.assertEqual(result.items[0].content_url, BASE+'events/beta')

    def test_malformed_detail_is_isolated(self):
        result = collect(FakeTransport({BASE:html('generic-list.html'), BASE+'events/alpha?day=1':'<body>Missing content</body>'}))
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.items), 1)

    def test_detail_attempt_budget_is_bounded(self):
        transport = FakeTransport({BASE: ''.join(f'<a href="/events/{n}">item</a>' for n in range(40))})
        for n in range(40):
            transport.pages[BASE+f'events/{n}'] = RuntimeError('failed')
        result = collect(transport)
        self.assertEqual(len(result.failures), 3)
        self.assertEqual(len(transport.calls), 4)

    def test_no_detail_links_is_clear_source_failure(self):
        with self.assertRaises(SourceUnavailableError):
            collect(FakeTransport({BASE:'<main>Login or JS shell</main>'}))

    def test_replacement_transport_cannot_escape_origin(self):
        result = collect(FakeTransport({BASE:html('generic-list.html'), BASE+'events/alpha?day=1':Page('https://other.example/events/a', html('generic-detail.html'))}))
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(len(result.items), 0)

    def test_access_refusal_stops_source_without_discarding_success(self):
        transport = FakeTransport({BASE: html('generic-list.html')+'<a href="/events/third">Third</a>',
                                   BASE+'events/beta': SourceAccessRestrictedError('public HTTP access refused (429)')})
        result = collect(transport, limit=3)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(len(result.failures), 1)
        self.assertNotIn(BASE+'events/third', transport.calls)

    def test_final_identity_deduplicates_redirect_aliases(self):
        transport = FakeTransport({BASE:html('generic-list.html')})
        for url in (BASE+'events/alpha?day=1', BASE+'events/beta'):
            transport.pages[url] = Page(BASE+'events/final', html('generic-detail.html'))
        self.assertEqual(len(collect(transport, limit=2).items), 1)

    def test_source_and_limit_validation(self):
        for limit in (0, True, 31):
            with self.assertRaises(ValueError):
                collect(limit=limit)
        for source in (replace(SOURCE, enabled=False), replace(SOURCE, source_type=SourceType.INSTAGRAM, website=None, username='demo')):
            with self.assertRaises(CollectorError):
                WebsiteCollector(transport=FakeTransport()).collect(source, limit=1)

    def test_primary_website_evidence_and_current_text_selection(self):
        item, = collect().items
        old = primary_fragment(replace(item, raw_text='Stale old text'))
        bundle = select_semantic_evidence(item, (old, caption_fragment(item)))
        self.assertEqual(bundle.fragments, (primary_fragment(item),))
        self.assertEqual(bundle.fragments[0].kind, EvidenceKind.WEBSITE_TEXT)
        self.assertEqual(EvidenceBundle.from_raw_item(item), bundle)

    def test_unit_and_candidate_identity_stable(self):
        item, = collect().items
        units = ConservativeGrouping().group(EvidenceBundle.from_raw_item(item))
        self.assertEqual(len(units), 1)
        self.assertEqual(units, ConservativeGrouping().group(EvidenceBundle.from_raw_item(item)))
        service = DiscoveryService(RuleBasedDiscoveryProvider())
        first = service.discover_units(item, units)
        self.assertEqual(first, service.discover_units(item, units))
        self.assertIsNotNone(first[0].candidate)
        self.assertEqual(first[0].candidate.raw_item_id, item.id)
        self.assertIsNone(first[0].event.starts_at)
        self.assertIsNone(first[0].event.price_amount)

    def test_discover_primary_website_and_legacy_instagram(self):
        item, = collect().items
        service = DiscoveryService(RuleBasedDiscoveryProvider())
        self.assertIsNotNone(service.discover(item).candidate)
        instagram = replace(item, source_type=SourceType.INSTAGRAM)
        self.assertEqual(primary_fragment(instagram), caption_fragment(instagram))
        self.assertEqual(service.discover(item).discovery_type, service.discover(instagram).discovery_type)

    def test_storage_new_existing_changed_is_append_only(self):
        item, = collect().items
        with TemporaryDirectory() as directory:
            store = JsonlRawItemStore(website_output_path(SOURCE, directory))
            self.assertEqual(store.append_new((item,)).new, 1)
            original = store.path.read_bytes()
            self.assertEqual(store.append_new((replace(item, captured_at=datetime.now(timezone.utc)),)).already_existing, 1)
            self.assertEqual(store.path.read_bytes(), original)
            self.assertEqual(store.append_new((replace(item, raw_text='Changed', content_hash='newhash'),)).changed, 1)
            self.assertEqual(len(store.path.read_text(encoding='utf-8').splitlines()), 2)

    def test_future_source_config_uses_existing_orchestration_and_offline_cli(self):
        with TemporaryDirectory() as directory:
            config = Path(directory)/'sources.yaml'
            config.write_text('sources:\n  - id: future_website\n    publisher_key: future\n    name: Future\n'
                              '    type: website\n    url: https://community.example/\n'
                              '    website:\n      detail_path_prefixes: [/events/]\n'
                              '      content_selector: "#event"\n      exclude_selectors: [.owner-excluded]\n', encoding='utf-8')
            summary = run_website_collection(SOURCE.id, config_path=config, data_dir=directory,
                                            collector=WebsiteCollector(transport=FakeTransport()), limit=2)
            self.assertEqual(summary.new, 2)
            before = summary.output_path.read_bytes()
            with patch.object(HttpTransport, 'fetch', side_effect=AssertionError('network')):
                one = run_website_discovery(SOURCE.id, config_path=config, data_dir=directory, limit=2)
                two = run_website_discovery(SOURCE.id, config_path=config, data_dir=directory, limit=2)
                out = io.StringIO()
                with redirect_stdout(out):
                    code = main(['extract','website',SOURCE.id,'--config',str(config),'--data-dir',directory])
            self.assertEqual(code, 0)
            self.assertIn('website_text', out.getvalue())
            self.assertIn('Nothing was persisted', out.getvalue())
            self.assertEqual(one.items, two.items)
            self.assertEqual(one.unit_count, 2)
            self.assertEqual(summary.output_path.read_bytes(), before)

    def test_cli_parsing_and_type_validation(self):
        self.assertEqual(build_parser().parse_args(['collect','website','davvvat_website']).limit, 5)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(['extract','website','davvvat_instagram']), 1)
            self.assertEqual(main(['collect','website','davvvat_website','--limit','0']), 2)

    def test_offline_discovery_isolates_malformed_and_other_source_records(self):
        from repo_config import FIXTURE_CONFIG
        source = next(s for s in load_sources(FIXTURE_CONFIG) if s.id == 'davvvat_website')
        item, = collect().items
        with TemporaryDirectory() as directory:
            store = JsonlRawItemStore(website_output_path(source, directory))
            store.append_new((item, replace(item, id='website:davvvat_website:a', source_id=source.id)))
            with store.path.open('a', encoding='utf-8') as stream:
                stream.write('not json\n')
            result = run_website_discovery(source.id, data_dir=directory, config_path=FIXTURE_CONFIG)
            self.assertEqual(result.observed, 1)
            self.assertEqual(len(result.malformed), 1)


if __name__ == '__main__':
    unittest.main()
