"""Browser backend contract: no network or live credential changes."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from webmirage.platforms.reddit.browser import BrowserRedditClient, runtime_status, worker_call
from webmirage.platforms.reddit.client import RedditClient, RedditError
from webmirage.platforms.reddit.tools import RedditTools
from webmirage.checks import configuration_revision


class BrowserContractTests(unittest.TestCase):
    def test_factory_preserves_http_default_and_invalidates_cached_client_on_change(self):
        config = {'reddit_cookie': 'reddit_session=PRIVATE'}
        with patch('webmirage.platforms.reddit.tools.cfg.get_config', return_value=config):
            tools = RedditTools()
            self.assertIsInstance(tools._get_client(), RedditClient)
            config['reddit_backend'] = 'opencli'
            self.assertIsInstance(tools._get_client(), BrowserRedditClient)
            config['reddit_backend'] = 'http'
            self.assertIsInstance(tools._get_client(), RedditClient)

    def test_queries_preserve_formatted_result_contract_and_valid_empty_results(self):
        result = [{'id': 'abc', 'title': 'Example', 'subreddit': 'python'}]
        with patch('webmirage.platforms.reddit.browser.worker_call', return_value={'ok': True, 'rows': result}) as call:
            client = BrowserRedditClient('reddit_session=PRIVATE')
            self.assertEqual(client.search('python'), result)
            self.assertEqual(call.call_args.args[0]['tool'], 'reddit_search')
            self.assertEqual(client.get_subreddit_posts('python'), (result, ''))
        with patch('webmirage.platforms.reddit.browser.worker_call', return_value={'ok': True, 'rows': []}):
            self.assertEqual(BrowserRedditClient().search('no matches'), [])

    def test_unsupported_actions_never_silently_use_http(self):
        with patch('webmirage.platforms.reddit.browser.worker_call') as call:
            client = BrowserRedditClient()
            for fn in (lambda: client.get_post('x'), lambda: client.get_user_profile('x'),
                       lambda: client.get_subreddit_posts('python', after='cursor')):
                with self.assertRaises(RedditError): fn()
            call.assert_not_called()

    def test_missing_worker_and_passive_status_do_not_leak_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(RedditError) as error:
                worker_call({'action': 'query', 'cookie': 'PRIVATE'}, path=str(Path(folder) / 'absent.sock'))
            self.assertNotIn('PRIVATE', str(error.exception))
        with patch('webmirage.platforms.reddit.browser.worker_call', side_effect=RedditError('PRIVATE')):
            status = runtime_status({'reddit_backend': 'opencli', 'reddit_cookie': 'PRIVATE'})
            self.assertFalse(status['available'])
            self.assertNotIn('PRIVATE', json.dumps(status))

    def test_backend_switch_changes_only_reddit_health_revision(self):
        config = {'reddit_cookie': 'PRIVATE'}
        before = configuration_revision(config, 'reddit')
        github = configuration_revision(config, 'github')
        config['reddit_backend'] = 'opencli'
        self.assertNotEqual(before, configuration_revision(config, 'reddit'))
        self.assertEqual(github, configuration_revision(config, 'github'))
