import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
from app import create_app
from fastapi.testclient import TestClient
from platform_worker import credentials, validate_credential_updates
from webmirage.platforms.xianyu.credentials import REQUIRED_COOKIE_FIELDS, RequiredCredentialError


class XianyuRequiredTests(unittest.TestCase):
    values = {'_m_h5_tk': 'test-token_9999999999999', '_m_h5_tk_enc': 'test-enc', 'cookie2': 'test-session==', 'unb': '1'}

    def test_each_required_field_is_enforced_for_values_and_full_import(self):
        validate_credential_updates('xianyu', self.values)
        for field in REQUIRED_COOKIE_FIELDS:
            for full in (False, True):
                with self.subTest(field=field, full=full):
                    values = {k: v for k, v in self.values.items() if k != field}
                    updates = {'xianyu_cookie': '; '.join(f'{k}={v}' for k, v in values.items())} if full else values
                    with self.assertRaisesRegex(RequiredCredentialError, field):
                        validate_credential_updates('xianyu', updates)
                    meta = credentials({'xianyu_cookie': '; '.join(f'{k}={v}' for k, v in values.items())}, 'xianyu')
                    self.assertFalse(meta['configured'])
                    self.assertEqual(meta['missing'], [field])
        validate_credential_updates('xianyu', {'xianyu_cookie': '; '.join(f'{k}={v}' for k, v in self.values.items())})

    def test_empty_or_similar_names_do_not_satisfy_required_fields(self):
        for extra in ('_m_h5_tk_enc=; cookie2=', 'not_m_h5_tk_enc=enc; my_cookie2=session'):
            meta = credentials({'xianyu_cookie': '_m_h5_tk=token; unb=1; ' + extra}, 'xianyu')
            self.assertEqual(meta['missing'], ['_m_h5_tk_enc', 'cookie2'])

    def test_api_names_missing_fields_without_writing_or_echoing_values(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {'GATEWAY_PLATFORM_BRIDGE': '0'}):
            app = create_app(admin_password='test-password', controller_secret='test-controller', history_path=Path(td) / 'history.sqlite3')
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/login', json={'password': 'test-password'}).status_code, 200)
                response = client.post('/api/platforms/credentials', headers={'X-Gateway-Request': '1'},
                                       json={'platform': 'xianyu', 'updates': {'_m_h5_tk': 'PRIVATE-INPUT', 'unb': '1'}})
                self.assertEqual(response.status_code, 400)
                self.assertIn('_m_h5_tk_enc', response.json()['detail'])
                self.assertIn('cookie2', response.json()['detail'])
                self.assertNotIn('PRIVATE-INPUT', response.text)
