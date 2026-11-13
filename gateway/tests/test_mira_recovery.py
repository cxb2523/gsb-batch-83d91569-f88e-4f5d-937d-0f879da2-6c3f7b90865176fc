"""Simulate Mira replacement and outages without touching live application services."""
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))
import ensure_mira
from deploy_mira import BEGIN, render_route


class MiraRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.deploy_dir = directory / 'deploy'
        self.deploy_dir.mkdir()
        (self.deploy_dir / 'nginx.standalone.conf').write_text(BEGIN)
        public = directory / 'public/gateway'
        public.mkdir(parents=True)
        self.marker = public / '.mirage-managed'
        self.marker.touch()
        self.original = 'server {\n    location / {\n        try_files $uri /index.html;\n    }\n}\n'
        info = {'State': {'Running': True}, 'Config': {'Labels': {
            'com.docker.compose.project.working_dir': str(self.deploy_dir)}},
            'NetworkSettings': {'Networks': {'mira': {'Gateway': '172.22.0.1'}}}}
        self.stack.enter_context(patch.object(ensure_mira, 'frontend_info', return_value=info))
        self.stack.enter_context(patch.object(ensure_mira, 'expected_files', return_value={'/gateway/index.html': 'abc'}))
        self.docker = self.stack.enter_context(patch.object(ensure_mira, 'docker', return_value=SimpleNamespace(stdout=render_route(self.original, '172.22.0.1'))))
        self.hashes = self.stack.enter_context(patch.object(ensure_mira.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='abc  /gateway/index.html\n')))
        self.deploy = self.stack.enter_context(patch.object(ensure_mira, 'deploy'))
        self.check = self.stack.enter_context(patch.object(ensure_mira, 'check_route'))

    def test_replaced_container_restores_owned_page(self):
        self.docker.return_value.stdout = self.original
        self.hashes.return_value.returncode = 1
        ensure_mira.main()
        self.deploy.assert_called_once_with(repair_only=True)

    def test_missing_asset_alone_triggers_recovery(self):
        self.hashes.return_value.stdout = 'changed  /gateway/index.html\n'
        ensure_mira.main()
        self.deploy.assert_called_once_with(repair_only=True)

    def test_healthy_page_is_not_rewritten(self):
        ensure_mira.main()
        self.deploy.assert_not_called()
        self.check.assert_called_once()

    def test_api_outage_does_not_rewrite_working_page(self):
        self.check.side_effect = OSError('backend unavailable')
        with self.assertRaises(OSError):
            ensure_mira.main()
        self.deploy.assert_not_called()

    def test_unowned_page_is_not_automatically_installed(self):
        self.marker.unlink()
        with self.assertRaises(RuntimeError):
            ensure_mira.main()
        self.deploy.assert_not_called()
        self.docker.assert_not_called()


if __name__ == '__main__':
    unittest.main()
