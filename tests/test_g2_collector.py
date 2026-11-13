"""g2_collector 的离线单元测试。

所有传输层均为假实现（FakeFetcher / FakeResponse），测试全程不触网，
只验证结局判定逻辑，不代表真实 G2 链路已跑通。

运行（隔离模式，避免从当前目录误加载第三方模块）：
    python -I -m unittest -v tests.test_g2_collector
或：
    python -I tests/test_g2_collector.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

# 以脚本方式运行（python -I tests/test_g2_collector.py）时补好 src 路径
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import requests  # noqa: E402

from g2_collector import (  # noqa: E402
    ApiDirectFetcher,
    CLOUDFLARE_MARKERS,
    CredentialError,
    Credentials,
    G2Collector,
    PageStatus,
    ProxyFetcher,
    detect_cloudflare,
    format_report,
    summarize,
)

FIXTURES = REPO_ROOT / "tests" / "fixtures"
WAIT_SELECTOR = ".star-wrapper__desc"


class FakeResponse:
    """模拟 requests.Response 的最小实现。"""

    def __init__(
        self,
        status_code: int,
        text: str = "",
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = dict(headers or {})


class FakeFetcher:
    """按 URL 映射假响应；映射到异常则抛出，模拟请求异常页。"""

    def __init__(self, routing: Dict[str, Any]) -> None:
        self._routing = routing
        self.calls: List[str] = []

    def fetch(self, url: str) -> FakeResponse:
        self.calls.append(url)
        result = self._routing[url]
        if isinstance(result, Exception):
            raise result
        return result


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# 四个样例页的 URL（均为假地址，仅用于路由）
URL_NORMAL = "https://example.test/g2/normal"
URL_BLOCKED = "https://example.test/g2/blocked"
URL_WAIT_MISSING = "https://example.test/g2/wait-missing"
URL_REQUEST_ERROR = "https://example.test/g2/request-error"


def build_routing() -> Dict[str, Any]:
    return {
        URL_NORMAL: FakeResponse(200, _read_fixture("normal.html")),
        URL_BLOCKED: FakeResponse(
            403,
            _read_fixture("blocked_403.html"),
            headers={"Server": "cloudflare", "CF-RAY": "8a7b6c5d4e3f2a1b"},
        ),
        URL_WAIT_MISSING: FakeResponse(
            200, _read_fixture("wait_missing.html")
        ),
        URL_REQUEST_ERROR: requests.ConnectionError(
            "模拟连接失败：代理隧道建立失败"
        ),
    }


class PageOutcomeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fetcher = FakeFetcher(build_routing())
        # 配置等待选择器，覆盖等待命中 / 等待超时两种路径
        self.collector = G2Collector(self.fetcher, wait_selector=WAIT_SELECTOR)

    def test_normal_page_is_success_with_headings_and_wait_hit(self) -> None:
        outcome = self.collector.collect_page(URL_NORMAL)
        self.assertEqual(outcome.status, PageStatus.SUCCESS)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.http_status, 200)
        self.assertEqual(outcome.h2_count, 3)
        self.assertEqual(outcome.h3_count, 2)
        self.assertEqual(
            outcome.h2_headings,
            [
                "What is Mongodb?",
                "What do you like best about Mongodb?",
                "What do you dislike about Mongodb?",
            ],
        )
        self.assertEqual(outcome.wait_selector, WAIT_SELECTOR)
        self.assertTrue(outcome.wait_element_hit)
        self.assertFalse(outcome.blocked)
        self.assertIsNone(outcome.error)

    def test_blocked_403_page_is_blocked_and_has_no_titles(self) -> None:
        outcome = self.collector.collect_page(URL_BLOCKED)
        self.assertEqual(outcome.status, PageStatus.BLOCKED)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.blocked)
        self.assertEqual(outcome.block_reason, "HTTP 403")
        self.assertEqual(outcome.http_status, 403)
        # 被拦截页不得产出任何标题
        self.assertEqual(outcome.h2_headings, [])
        self.assertEqual(outcome.h3_headings, [])
        self.assertEqual(outcome.h2_count, 0)
        self.assertFalse(outcome.wait_element_hit)

    def test_cloudflare_body_marker_blocks_even_on_200(self) -> None:
        # 200 但响应体是 Cloudflare 挑战页：仍应判定被拦截
        challenge_body = (
            "<html><body><h1>Attention Required! | Cloudflare</h1>"
            "<script src='/cdn-cgi/challenge-platform/h/g/orchestrate/v1'></script>"
            "</body></html>"
        )
        fetcher = FakeFetcher(
            {"https://example.test/challenge": FakeResponse(200, challenge_body)}
        )
        outcome = G2Collector(fetcher).collect_page(
            "https://example.test/challenge"
        )
        self.assertEqual(outcome.status, PageStatus.BLOCKED)
        self.assertTrue(outcome.blocked)
        self.assertIn("Cloudflare", outcome.block_reason)

    def test_wait_missing_page_is_wait_timeout_but_keeps_titles(self) -> None:
        outcome = self.collector.collect_page(URL_WAIT_MISSING)
        self.assertEqual(outcome.status, PageStatus.WAIT_TIMEOUT)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.http_status, 200)
        self.assertFalse(outcome.wait_element_hit)
        # 标题如实保留以便排查，但本页不计入成功
        self.assertEqual(outcome.h2_count, 2)
        self.assertEqual(outcome.h3_count, 1)
        self.assertIn(WAIT_SELECTOR, outcome.error)

    def test_request_exception_page_is_request_error_and_continues(self) -> None:
        outcome = self.collector.collect_page(URL_REQUEST_ERROR)
        self.assertEqual(outcome.status, PageStatus.REQUEST_ERROR)
        self.assertFalse(outcome.ok)
        self.assertIsNone(outcome.http_status)
        self.assertIn("ConnectionError", outcome.error)
        self.assertEqual(outcome.h2_headings, [])

    def test_one_failure_does_not_stop_later_pages(self) -> None:
        urls = [
            URL_BLOCKED,        # 被拦截
            URL_REQUEST_ERROR,  # 请求异常
            URL_WAIT_MISSING,   # 等待超时
            URL_NORMAL,         # 成功
        ]
        outcomes = self.collector.collect_all(urls)

        # 四页全部返回结局，顺序与输入一致
        self.assertEqual([o.url for o in outcomes], urls)
        self.assertEqual(
            [o.status for o in outcomes],
            [
                PageStatus.BLOCKED,
                PageStatus.REQUEST_ERROR,
                PageStatus.WAIT_TIMEOUT,
                PageStatus.SUCCESS,
            ],
        )
        # 每页都确实发起了请求（没有因前页失败而跳过）
        self.assertEqual(self.fetcher.calls, urls)

        summary = summarize(outcomes)
        self.assertEqual(summary.total, 4)
        self.assertEqual(summary.success, 1)
        self.assertEqual(summary.blocked, 1)
        self.assertEqual(summary.wait_timeout, 1)
        self.assertEqual(summary.request_error, 1)
        # 只有成功页的标题计入汇总
        self.assertEqual(summary.success_h2_total, 3)
        self.assertEqual(summary.success_h3_total, 2)

    def test_debug_header_is_captured(self) -> None:
        debug_text = "upstream=200; tunnel=brd; challenge_solved=true"
        fetcher = FakeFetcher(
            {
                URL_NORMAL: FakeResponse(
                    200,
                    _read_fixture("normal.html"),
                    headers={"x-brd-debug": debug_text},
                )
            }
        )
        outcome = G2Collector(fetcher, wait_selector=WAIT_SELECTOR).collect_page(
            URL_NORMAL
        )
        self.assertEqual(outcome.status, PageStatus.SUCCESS)
        self.assertTrue(outcome.debug_info_present)
        self.assertEqual(outcome.debug_info, debug_text)

    def test_no_wait_selector_means_wait_hit_is_none(self) -> None:
        fetcher = FakeFetcher(
            {URL_NORMAL: FakeResponse(200, _read_fixture("normal.html"))}
        )
        outcome = G2Collector(fetcher).collect_page(URL_NORMAL)
        self.assertEqual(outcome.status, PageStatus.SUCCESS)
        self.assertIsNone(outcome.wait_selector)
        self.assertIsNone(outcome.wait_element_hit)

    def test_unexpected_500_is_request_error(self) -> None:
        fetcher = FakeFetcher(
            {"https://example.test/500": FakeResponse(500, "gateway error")}
        )
        outcome = G2Collector(fetcher).collect_page("https://example.test/500")
        self.assertEqual(outcome.status, PageStatus.REQUEST_ERROR)
        self.assertEqual(outcome.http_status, 500)
        self.assertEqual(outcome.h2_headings, [])

    def test_report_is_rendered_for_every_page(self) -> None:
        outcomes = self.collector.collect_all(
            [URL_NORMAL, URL_BLOCKED, URL_WAIT_MISSING, URL_REQUEST_ERROR]
        )
        report = format_report(outcomes)
        for url in (URL_NORMAL, URL_BLOCKED, URL_WAIT_MISSING, URL_REQUEST_ERROR):
            self.assertIn(url, report)
        for label in ("成功", "被拦截", "等待超时", "请求异常"):
            self.assertIn(label, report)


class CloudflareDetectionTests(unittest.TestCase):
    def test_403_always_blocked(self) -> None:
        self.assertEqual(detect_cloudflare(403, "anything", {}), "HTTP 403")

    def test_markers_are_non_empty(self) -> None:
        self.assertTrue(all(marker == marker.lower() for marker in CLOUDFLARE_MARKERS))
        self.assertGreater(len(CLOUDFLARE_MARKERS), 3)

    def test_normal_body_not_flagged(self) -> None:
        body = _read_fixture("normal.html")
        self.assertIsNone(detect_cloudflare(200, body, {}))


class CredentialTests(unittest.TestCase):
    def test_missing_env_raises(self) -> None:
        with self.assertRaises(CredentialError):
            Credentials.from_env(
                require_api_token=True,
                environ={"BRD_CUSTOMER_ID": "cust123", "BRD_ZONE_NAME": "zone1"},
            )
        with self.assertRaises(CredentialError):
            Credentials.from_env(
                require_zone_password=True,
                environ={"BRD_CUSTOMER_ID": "cust123"},
            )

    def test_placeholder_values_rejected(self) -> None:
        with self.assertRaises(CredentialError):
            Credentials.from_env(
                require_api_token=True,
                environ={
                    "BRD_CUSTOMER_ID": "<customer_id>",
                    "BRD_ZONE_NAME": "zone1",
                    "BRD_API_TOKEN": "tok",
                },
            )
        with self.assertRaises(CredentialError):
            Credentials.from_env(
                require_api_token=True,
                environ={
                    "BRD_CUSTOMER_ID": "cust123",
                    "BRD_ZONE_NAME": "zone1",
                    "BRD_API_TOKEN": "INSERT_YOUR_API_TOKEN",
                },
            )

    def test_valid_env_loaded_and_optional_fields_absent(self) -> None:
        creds = Credentials.from_env(
            environ={
                "BRD_CUSTOMER_ID": "cust123",
                "BRD_ZONE_NAME": "zone1",
            }
        )
        self.assertEqual(creds.customer_id, "cust123")
        self.assertEqual(creds.zone_name, "zone1")
        self.assertIsNone(creds.api_token)
        self.assertIsNone(creds.zone_password)

        full = Credentials.from_env(
            require_api_token=True,
            require_zone_password=True,
            environ={
                "BRD_CUSTOMER_ID": "cust123",
                "BRD_ZONE_NAME": "zone1",
                "BRD_API_TOKEN": "tok_abc",
                "BRD_ZONE_PASSWORD": "pw_xyz",
            },
        )
        self.assertEqual(full.api_token, "tok_abc")
        self.assertEqual(full.zone_password, "pw_xyz")


class TransportConstructionTests(unittest.TestCase):
    """校验三个通道各自的出口差异在构造层成立（不发起真实请求）。"""

    def test_api_fetcher_requires_token_and_sends_expect_header(self) -> None:
        creds = Credentials(
            customer_id="cust123", zone_name="zone1", api_token="tok_abc"
        )
        captured: Dict[str, Any] = {}

        class _Session:
            def post(self, url, headers, json, timeout):  # noqa: A002
                captured.update(
                    url=url, headers=headers, json=json, timeout=timeout
                )
                return FakeResponse(200, _read_fixture("normal.html"))

        fetcher = ApiDirectFetcher(
            creds, wait_selector=WAIT_SELECTOR, session=_Session()
        )
        response = fetcher.fetch(URL_NORMAL)
        self.assertEqual(response.status_code, 200)
        self.assertIn("x-unblock-expect", captured["headers"])
        self.assertIn(WAIT_SELECTOR, captured["headers"]["x-unblock-expect"])
        self.assertEqual(
            captured["headers"]["Authorization"], "Bearer tok_abc"
        )
        self.assertEqual(captured["json"]["zone"], "zone1")
        self.assertEqual(captured["json"]["url"], URL_NORMAL)
        self.assertEqual(captured["json"]["format"], "raw")

    def test_api_fetcher_without_token_raises(self) -> None:
        creds = Credentials(customer_id="cust123", zone_name="zone1")
        with self.assertRaises(CredentialError):
            ApiDirectFetcher(creds)

    def test_proxy_username_flags(self) -> None:
        creds = Credentials(
            customer_id="cust123",
            zone_name="zone1",
            zone_password="pw_xyz",
        )
        captured: Dict[str, Any] = {}

        class _Session:
            def get(self, url, proxies, timeout, verify):
                captured.update(
                    url=url, proxies=proxies, timeout=timeout, verify=verify
                )
                return FakeResponse(
                    200,
                    _read_fixture("normal.html"),
                    headers={"x-brd-debug": "dbg=1"},
                )

        mobile = ProxyFetcher(
            creds, username_flags=["ua-mobile"], session=_Session()
        )
        mobile.fetch(URL_NORMAL)
        self.assertIn(
            "brd-customer-cust123-zone-zone1-ua-mobile:",
            captured["proxies"]["https"],
        )

        debug = ProxyFetcher(
            creds, username_flags=["debug-full"], session=_Session()
        )
        debug.fetch(URL_NORMAL)
        self.assertIn(
            "brd-customer-cust123-zone-zone1-debug-full:",
            captured["proxies"]["https"],
        )

    def test_proxy_fetcher_without_password_raises(self) -> None:
        creds = Credentials(customer_id="cust123", zone_name="zone1")
        with self.assertRaises(CredentialError):
            ProxyFetcher(creds, username_flags=["ua-mobile"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
