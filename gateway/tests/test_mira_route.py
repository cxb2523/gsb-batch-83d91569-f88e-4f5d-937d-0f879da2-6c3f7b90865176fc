"""Application route checks; no containers or host configuration are changed."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from deploy_mira import check_session, render_route
from ensure_mira import files_match
from serve_mira import bridge_address


class MiraRouteTests(unittest.TestCase):
    def setUp(self):
        self.original = """server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    location = /health { return 200 'ok'; }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
"""

    def test_preserves_mira_root_health_and_existing_listener(self):
        result = render_route(self.original, "172.22.0.1")
        self.assertIn("    listen 80;", result)
        self.assertEqual(result.count("listen "), 1)
        self.assertIn("location = /health { return 200 'ok'; }", result)
        self.assertIn("try_files $uri $uri/ /index.html;", result)
        self.assertIn("location ^~ /gateway/", result)
        self.assertIn("proxy_pass http://172.22.0.1:8091/api/;", result)
        self.assertIn("try_files $uri $uri/ /gateway/index.html;", result)
        self.assertIn("absolute_redirect off;", result)

    def test_repeat_deploy_replaces_only_managed_block(self):
        first = render_route(self.original, "172.22.0.1")
        second = render_route(first, "172.23.0.1")
        self.assertEqual(second.count("location ^~ /gateway/ {"), 1)
        self.assertEqual(second.count("location ^~ /gateway/api/ {"), 1)
        self.assertNotIn("172.22.0.1", second)
        self.assertIn("172.23.0.1", second)

    def test_refuses_unknown_nginx_layout(self):
        with self.assertRaises(ValueError):
            render_route("server { listen 80; }", "172.22.0.1")

    def test_html_spa_fallback_is_not_a_healthy_session(self):
        with self.assertRaises(ValueError):
            check_session(b'<html>Mira</html>', 'text/html')
        for body in (b'{}', b'[]', b'{"authenticated":"false","configured":true}'):
            with self.assertRaises(ValueError):
                check_session(body, 'application/json')
        check_session(b'{"authenticated":false,"configured":true}', 'application/json; charset=utf-8')

    def test_asset_check_detects_missing_and_changed_files(self):
        expected = {'/gateway/index.html': 'abc', '/gateway/assets/app.js': 'def'}
        self.assertTrue(files_match('abc  /gateway/index.html\ndef  /gateway/assets/app.js\n', expected))
        self.assertFalse(files_match('abc  /gateway/index.html\n', expected))
        self.assertFalse(files_match('abc  /gateway/index.html\nold  /gateway/assets/app.js\n', expected))
        self.assertFalse(files_match('', {}))

    def test_backend_only_binds_a_known_private_bridge(self):
        for address in ["0.0.0.0", "127.0.0.1", "8.8.8.8"]:
            info = {"NetworkSettings": {"Networks": {"mira": {"Gateway": address}}}}
            with self.assertRaises(RuntimeError):
                bridge_address(info)
        info = {"NetworkSettings": {"Networks": {"mira": {"Gateway": "172.22.0.1"}}}}
        self.assertEqual(bridge_address(info), "172.22.0.1")


if __name__ == "__main__":
    unittest.main()
