"""Regression: standalone startup must not depend on Mira or its base path."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import serve


class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.static = self.root / 'gateway/frontend/dist'
        self.static.mkdir(parents=True)
        self.index = self.static / 'index.html'
        self.index.write_text('<script src="/assets/app.js"></script>')
        data = self.root / 'mihomo/data'
        data.mkdir(parents=True)
        (data / 'API_SECRET').write_text('test-private-secret')
        self.root_patch = patch.object(serve, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        env = patch.dict(os.environ, {}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def test_start_without_mira_or_docker_and_override_old_cookie_path(self):
        with patch('subprocess.run', side_effect=AssertionError('Must not inspect Mira')):
            os.environ['GATEWAY_COOKIE_PATH'] = '/gateway/'
            self.assertEqual(serve.configure(), ('127.0.0.1', 8091))
            self.assertEqual(os.environ['GATEWAY_COOKIE_PATH'], '/')
            self.assertEqual(os.environ['GATEWAY_STATIC_DIR'], str(self.static))
            os.environ['GATEWAY_HOST'] = '192.168.188.3'
            self.assertEqual(serve.configure(), ('192.168.188.3', 8091))

    def test_old_mira_bundle_is_rejected_instead_of_serving_blank_page(self):
        self.index.write_text('<script src="/gateway/assets/app.js"></script>')
        with self.assertRaisesRegex(RuntimeError, 'VITE_APP_BASE=/'):
            serve.configure()

    def test_wildcard_and_public_listeners_are_rejected(self):
        for host in ['0.0.0.0', '::', '8.8.8.8']:
            with self.subTest(host=host):
                os.environ['GATEWAY_HOST'] = host
                with self.assertRaises(ValueError):
                    serve.configure()
