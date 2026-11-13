"""Audit regressions: exercise the shared flow without network or paid tasks."""
import asyncio
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import unquote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import page_flow as flow
import page_parser as parser
import playwright_scraper as playwright
import puppeteer_scraper as puppeteer
import selenium_scraper as selenium
import diff_runs

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/perplexity_article_discover_live_20260930.json').read_text())
BLOCK = (Path(__file__).parent / 'fixtures/perplexity_cloudflare_block_real.html').read_text()


def url(n):
    return 'https://www.perplexity.ai/page/article-' + str(n).zfill(22)


def article(n):
    data = copy.deepcopy(FIXTURE)
    data['entries'][0]['thread_url_slug'] = 'article-' + str(n).zfill(22)
    return data


class Session:
    def __init__(self, engine):
        self.engine, self.url = engine, ''

    async def goto(self, target):
        self.url = target
        if self.engine.mode == 'navigation_error':
            raise RuntimeError('navigation failed')
        return 200

    async def content(self):
        if self.engine.mode == 'content_error' and self.url == url(2):
            raise RuntimeError('navigation raced with content')
        if self.engine.mode == 'feed_challenge_race' and self.url == parser.DISCOVER_URL:
            self.engine.content_calls += 1
            if self.engine.content_calls == 1:
                return BLOCK
            if self.engine.content_calls == 2:
                raise RuntimeError('navigation raced with content')
        return ''

    async def fetch_json(self, target):
        e = self.engine
        if '/rest/discover/feed' in target:
            e.feed_calls += 1
            if e.mode == 'feed_blocked' or e.feed_calls > 1:
                return 403, None, 'challenge'
            if e.mode == 'bad_feed':
                return 200, {'unexpected': []}, None
            return 200, {'items': [{'slug': 'article-' + str(1).zfill(22)}], 'next_token': 'more'}, None
        n = 2 if self.url == url(2) else 1
        e.article_calls += 1
        if e.mode == 'timeout':
            return 0, None, 'timeout'
        if e.mode == 'not_found':
            return 404, {'detail': 'missing'}, None
        if e.mode == 'recover_500' and e.article_calls == 1:
            return 500, {'detail': 'unavailable'}, None
        if e.mode in ('api500', 'rate_limited') and n == 2:
            return (429 if e.mode == 'rate_limited' else 500), {'detail': 'unavailable'}, None
        data = article(n)
        if e.mode == 'bad_article' and n == 2:
            data['entries'][0]['social_info'] = 'unexpected'
        return 200, data, None

    async def wait(self, seconds):
        pass

    async def close(self):
        self.engine.closed += 1
        if self.engine.mode == 'close_error':
            raise RuntimeError('cleanup failed')


class Engine:
    name = 'regression'
    readiness_s = 0

    def __init__(self, mode):
        self.mode = mode
        self.feed_calls = self.article_calls = self.closed = self.content_calls = 0

    async def open(self, proxy):
        return Session(self)

    async def sleep(self, seconds):
        pass

    async def solve_captcha(self, *args, **kwargs):
        raise AssertionError('no paid solving in regression tests')


class FeedSession:
    """page_flow.PageSession over a scripted list of feed answers and
    synthetic article responses — no network, no credentials."""

    def __init__(self, engine):
        self.engine, self.closed = engine, False

    async def goto(self, target):
        return 200

    async def content(self):
        return ''

    async def fetch_json(self, target):
        e = self.engine
        if '/rest/discover/feed' in target:
            e.feed_calls += 1
            answer = e.feeds[min(e.feed_calls, len(e.feeds)) - 1]
            e.feed_urls.append(target)
            return answer
        ref = unquote(target.split('/rest/article/')[1].split('?')[0])
        e.article_calls += 1
        e.article_refs.append(ref)
        if ref in e.fail_refs or e.article_status != 200:
            return e.article_status, {'detail': 'unavailable'}, 'refused'
        data = copy.deepcopy(FIXTURE)
        data['entries'][0]['thread_url_slug'] = ref
        return 200, data, None

    async def wait(self, seconds):
        pass

    async def close(self):
        self.closed = True


class FeedEngine:
    name = 'feed'
    readiness_s = 0

    def __init__(self, feeds, *, article_status=200, fail_refs=()):
        self.feeds, self.article_status = list(feeds), article_status
        self.fail_refs = set(fail_refs)
        self.feed_calls = self.article_calls = 0
        self.feed_urls, self.article_refs, self.slept, self.sessions = [], [], [], []

    async def open(self, proxy):
        session = FeedSession(self)
        self.sessions.append(session)
        return session

    async def sleep(self, seconds):
        self.slept.append(seconds)

    async def solve_captcha(self, *args, **kwargs):
        raise AssertionError('no paid solving in regression tests')


def feed(items, next_token=None):
    return {'status': 'success', 'items': [{'slug': it} for it in items], 'next_token': next_token}


def feed_page(items, next_token=None):
    """A local fake feed RESPONSE as page_flow's fetch_json returns it."""
    return (200, feed(items, next_token), None)


def feed_slugs(start, count, next_token=None):
    return feed_page(['article-' + str(n).zfill(22) for n in range(start, start + count)], next_token)


class Regressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def run_flow(self, mode, *, discover=False, numbers=(1, 2), name='result'):
        out = str(Path(self.tmp.name) / (name + '.json'))
        args = playwright.build_arg_parser().parse_args([
            '--url', url(1), '--out', out, '--max-results', '5',
            '--solve-captcha', 'off', '--retries', '0', '--allow-empty'])
        engine = Engine(mode)
        code = asyncio.run(flow.run(engine, args, urls=[url(n) for n in numbers],
                                   discover_topic='top' if discover else None,
                                   proxy_pool=None, client=None, started_at=0))
        return code, json.loads(Path(out + '.meta.json').read_text()), json.loads(Path(out).read_text()), engine, out

    def test_success_and_not_found(self):
        code, meta, rows, _, _ = self.run_flow('good')
        self.assertEqual((code, meta['status'], len(rows)), (0, 'complete', 2))
        self.assertEqual(self.run_flow('not_found')[0], 4)

    def test_partial_article_failures_keep_good_rows(self):
        for mode in ('bad_article', 'api500', 'content_error'):
            with self.subTest(mode=mode):
                code, meta, rows, _, _ = self.run_flow(mode)
                self.assertEqual((code, meta['status'], len(rows)), (6, 'partial', 1))
                self.assertEqual(meta['failed_pages'], [2])
                self.assertEqual(meta['failed_urls'][0]['url'], url(2))

    def test_unread_is_not_empty(self):
        for mode in ('timeout', 'navigation_error'):
            self.assertEqual(self.run_flow(mode)[0], 5)

    def test_500_retry_recovers(self):
        code, _, rows, engine, _ = self.run_flow('recover_500', numbers=(1,))
        self.assertEqual((code, len(rows), engine.article_calls), (0, 1, 2))

    def test_discovery_failure_keeps_rows_and_blocks_diff(self):
        code, meta, rows, engine, out = self.run_flow('feed_partial', discover=True)
        self.assertEqual((code, meta['status'], len(rows)), (6, 'partial', 1))
        self.assertFalse(meta['discovery']['complete'])
        self.assertGreater(engine.feed_calls, 2)
        with self.assertRaises(SystemExit):
            diff_runs.diff(out, out)

    def test_feed_challenge_content_race_is_waited_out(self):
        code, meta, rows, engine, _ = self.run_flow('feed_challenge_race', discover=True)
        self.assertEqual((meta['discovery']['urls_collected'], len(rows)), (1, 1))
        self.assertEqual(engine.content_calls, 3)

    def test_first_feed_block_and_bad_schema(self):
        self.assertEqual(self.run_flow('feed_blocked', discover=True)[0], 3)
        self.assertEqual(self.run_flow('bad_feed', discover=True)[0], 5)

    def test_rate_limit_reason(self):
        code, meta, rows, _, _ = self.run_flow('rate_limited')
        self.assertEqual((code, meta['stop_reason'], len(rows)), (6, 'rate_limited', 1))

    # ------------------------------------------------------------------ #
    # Discover pagination: normal paging, a stuck cursor, and a mid-run
    # throttle — auditable page by page, never silently "complete".
    # ------------------------------------------------------------------ #
    def run_discover(self, feeds, *, max_results=5, article_status=200, fail_refs=(), name='feed'):
        out = str(Path(self.tmp.name) / (name + '.json'))
        args = playwright.build_arg_parser().parse_args([
            '--discover', 'top', '--out', out, '--max-results', str(max_results),
            '--solve-captcha', 'off', '--retries', '0', '--delay-between-pages', '0'])
        engine = FeedEngine(feeds, article_status=article_status, fail_refs=fail_refs)
        code = asyncio.run(flow.run(engine, args, urls=[], discover_topic='top',
                                   proxy_pool=None, client=None, started_at=0))
        meta_path = Path(out + '.meta.json')
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
        rows = json.loads(Path(out).read_text()) if Path(out).exists() else None
        return code, meta, rows, engine, out

    def test_discover_normal_paging_is_complete(self):
        code, meta, rows, engine, _ = self.run_discover([
            feed_slugs(1, 3, next_token='more'), feed_slugs(4, 1),
        ], max_results=4)
        self.assertEqual((code, meta['status'], len(rows)), (0, 'complete', 4))
        discovery = meta['discovery']
        self.assertTrue(discovery['complete'])
        self.assertEqual((discovery['pages_fetched'], discovery['page_items']), (2, [3, 1]))
        self.assertEqual(discovery['offset'], 3)
        self.assertEqual([p['has_more'] for p in discovery['pages']], [True, False])
        self.assertEqual(discovery['written_rows'], 4)
        self.assertEqual(discovery['unfetched_urls'], [])

    def test_discover_duplicate_cursor_stalls_not_blocked(self):
        # Page 2 repeats page 1 verbatim while still claiming there is more.
        code, meta, rows, engine, _ = self.run_discover([
            feed_slugs(1, 2, next_token='more'), feed_slugs(1, 2, next_token='more'),
        ], max_results=5)
        self.assertEqual((code, meta['status'], meta['stop_reason'], len(rows)),
                         (6, 'partial', 'pagination_stalled', 2))
        discovery = meta['discovery']
        self.assertFalse(discovery['complete'])
        self.assertEqual(discovery['stall']['kind'], 'duplicate_cursor')
        self.assertEqual(discovery['stall']['page'], 2)
        self.assertEqual((discovery['pages_fetched'], discovery['page_items']), (2, [2, 2]))
        self.assertEqual(discovery['written_rows'], 2)
        # Not a block, not a throttle, not a success.
        self.assertFalse(discovery['blocked'])
        self.assertFalse(discovery['rate_limited'])
        self.assertEqual(engine.feed_calls, 2, 'a repeating page must stop pagination, not re-ask forever')

    def test_discover_repeat_with_no_more_is_still_a_stall_not_a_clean_end(self):
        # The same page again, this time with next_token=None: "no more" must
        # not launder a stuck cursor into a complete run.
        code, meta, rows, _, _ = self.run_discover([
            feed_slugs(1, 2, next_token='more'), feed_slugs(1, 2, next_token=None),
        ], max_results=5)
        self.assertEqual((code, meta['status'], meta['stop_reason']), (6, 'partial', 'pagination_stalled'))
        self.assertEqual(meta['discovery']['stall']['kind'], 'duplicate_cursor')
        self.assertEqual(len(rows), 2)

    def test_discover_consecutive_empty_pages_stall(self):
        code, meta, rows, _, _ = self.run_discover([
            feed_slugs(1, 2, next_token='more'),
            feed_page([], next_token='more'), feed_page([], next_token='more'),
        ], max_results=5)
        self.assertEqual((code, meta['status'], meta['stop_reason']), (6, 'partial', 'pagination_stalled'))
        discovery = meta['discovery']
        self.assertEqual(discovery['stall']['kind'], 'empty_pages')
        self.assertEqual(discovery['stall']['consecutive_empty'], 2)
        # A single empty page alone is NOT a stall (it may be a gap) — but
        # the URLs from the page before it are still fetched and written.
        self.assertEqual((discovery['pages_fetched'], discovery['page_items']), (3, [2, 0, 0]))
        self.assertEqual(len(rows), 2)

    def test_discover_single_empty_page_is_not_a_stall(self):
        code, meta, rows, _, _ = self.run_discover([
            feed_page([], next_token='more'), feed_slugs(1, 1),
        ], max_results=1)
        self.assertEqual((code, meta['status'], len(rows)), (0, 'complete', 1))
        self.assertEqual(meta['discovery']['page_items'], [0, 1])

    def test_discover_rate_limit_mid_run_keeps_rows_and_is_not_blocked(self):
        code, meta, rows, _, _ = self.run_discover([
            feed_slugs(1, 2, next_token='more'), (429, None, 'rate limited'),
        ], max_results=5)
        self.assertEqual((code, meta['status'], meta['stop_reason'], len(rows)),
                         (6, 'partial', 'rate_limited', 2))
        discovery = meta['discovery']
        self.assertFalse(discovery['complete'])
        self.assertEqual((discovery['pages_fetched'], discovery['page_items']), (1, [2]))
        last = discovery['pages'][-1]
        self.assertEqual((last['page'], last['status'], last['items']), (2, 429, None))
        self.assertFalse(discovery['blocked'], 'a mid-run throttle is a rate limit, never a block')
        self.assertTrue(discovery['rate_limited'])

    def test_discover_first_page_throttle_is_blocked_with_no_rows(self):
        code, meta, rows, _, out = self.run_discover([(429, None, 'rate limited')], max_results=5)
        self.assertEqual((code, meta), (3, None), 'a first-page throttle is a block: no file, no sidecar')
        self.assertFalse(Path(out).exists())

    def test_discover_unfetched_urls_carry_each_reason(self):
        # One feed page finishes, one article of the three is throttled: the
        # file keeps the two good rows and `unfetched_urls` names the third
        # with its own reason. The FEED itself was complete.
        code, meta, rows, engine, _ = self.run_discover([
            feed_slugs(1, 3, next_token='more'), feed_slugs(4, 1),
        ], max_results=4, fail_refs=('article-' + str(2).zfill(22),))
        self.assertEqual((code, meta['status'], len(rows)), (6, 'partial', 3))
        discovery = meta['discovery']
        self.assertTrue(discovery['complete'], 'the FEED finished; only one article was refused')
        self.assertEqual(discovery['written_rows'], 3)
        self.assertEqual(len(discovery['unfetched_urls']), 1)
        entry = discovery['unfetched_urls'][0]
        self.assertIn('article-' + str(2).zfill(22), entry['url'])
        self.assertIn(entry['reason'], ('fetch_error', 'rate_limited', 'blocked'))

    def test_discover_stall_with_no_articles_writes_nothing(self):
        # The feed stalls before offering a single URL: a zero-product
        # partial run must not write — nor leave a stale sidecar behind.
        code, meta, rows, _, out = self.run_discover(
            [feed_page([], next_token='more'), feed_page([], next_token='more')], max_results=5)
        self.assertEqual(code, 5)
        self.assertIsNone(meta)
        self.assertFalse(Path(out).exists())
        self.assertFalse(Path(out + '.meta.json').exists())

    def test_cleanup_failure_preserves_rows(self):
        self.assertEqual(self.run_flow('close_error')[0], 0)

    def test_batch_scope(self):
        a = self.run_flow('good', numbers=(1, 2), name='a')[-1]
        b = self.run_flow('good', numbers=(1, 3), name='b')[-1]
        with self.assertRaises(SystemExit):
            diff_runs.diff(a, b)
        self.assertEqual(diff_runs.diff(a, a)['removed'], [])

    def test_url_validation(self):
        for value in ('https://evilperplexity.ai/page/x', 'file:///page/x', '/page/x',
                      'https://user:pass@www.perplexity.ai/page/x', 'https://www.perplexity.ai:8080/page/x'):
            self.assertFalse(parser.is_page_url(value), value)
        self.assertTrue(parser.is_page_url(url(1)))

    def test_local_solver_never_buys_undeliverable_token(self):
        client = Mock()
        for engine in (playwright, puppeteer):
            result = asyncio.run(engine._maybe_solve_captcha(html='<div class="cf-turnstile" data-sitekey="x"></div>',
                                 url=url(1), client=client, policy='when-blocked'))
            self.assertEqual(result['action'], 'unsupported_delivery')
        result = selenium._maybe_solve_captcha(html='challenge', url=url(1), client=client, policy='always')
        self.assertEqual(result['action'], 'unsupported_delivery')
        self.assertEqual(client.mock_calls, [])


if __name__ == '__main__':
    unittest.main()
