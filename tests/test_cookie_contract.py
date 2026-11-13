"""Credential contracts, tested with native package dependencies; no network."""
import unittest
import urllib.error
from unittest.mock import Mock
from unittest.mock import patch

from webmirage.checks import classify
from webmirage.platforms.reddit.client import RedditClient, RedditError
from webmirage.platforms.xianyu.client import XianyuClient, XianyuError
from webmirage.platforms.xianyu.credentials import REQUIRED_COOKIE_FIELDS
from webmirage.platforms.xianyu.tools import XianyuTools
from webmirage.platforms.system.tools import SystemTools


class CookieContractTests(unittest.TestCase):
    def test_xianyu_client_rejects_every_missing_required_field_before_network(self):
        complete = {key: 'test-value' for key in REQUIRED_COOKIE_FIELDS}
        self.assertTrue(XianyuClient('; '.join(f'{k}={v}' for k, v in complete.items())).is_configured())
        for missing in REQUIRED_COOKIE_FIELDS:
            cookie = '; '.join(f'{k}={v}' for k, v in complete.items() if k != missing)
            client = XianyuClient(cookie)
            self.assertFalse(client.is_configured())
            with self.assertRaisesRegex(XianyuError, missing):
                client._mtop_request('test.invalid', '1.0', {})

    def test_reddit_403_does_not_claim_that_an_existing_session_is_missing(self):
        for cookie, label in [('reddit_session=PRIVATE; extra_cookie=OTHER', '已提供'), ('', '未提供')]:
            with self.subTest(cookie_present=bool(cookie)):
                client = RedditClient(cookie)
                client._initialized = True
                if cookie:
                    client._inject_cookie_string(cookie)
                    self.assertEqual({c.name for c in client._cookie_jar}, {'reddit_session', 'extra_cookie'})
                client._opener = Mock()
                client._opener.open.side_effect = urllib.error.HTTPError('https://www.reddit.com/test.json', 403, 'Forbidden', {}, None)
                with self.assertRaises(RedditError) as failure:
                    client._get_json('https://www.reddit.com/test.json')
                text = str(failure.exception)
                self.assertIn(label, text)
                self.assertNotIn('PRIVATE', text)
                self.assertNotIn('anti-bot', text)
                self.assertEqual(classify('Reddit API error: ' + text), 'forbidden')

    def test_xianyu_registration_and_direct_config_update_share_required_fields(self):
        complete = {key: 'test-value' for key in REQUIRED_COOKIE_FIELDS}
        for missing in REQUIRED_COOKIE_FIELDS:
            cookie = '; '.join(f'{k}={v}' for k, v in complete.items() if k != missing)
            with patch('webmirage.platforms.xianyu.tools.cfg.get_config', return_value={'xianyu_cookie': cookie}):
                self.assertFalse(XianyuTools().is_available())
            with patch('webmirage.platforms.system.tools.cfg.save_config') as save:
                result = SystemTools()._set_cookie({'key': 'xianyu_cookie', 'value': cookie})
                self.assertIn(missing, result)
                self.assertTrue(result.startswith('Error:'))
                save.assert_not_called()
