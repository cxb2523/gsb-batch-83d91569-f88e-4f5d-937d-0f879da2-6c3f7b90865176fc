"""用本地 HTML 样例 + 假响应演示四类逐页结局。

全程离线，不访问 G2、也不访问 Bright Data，仅展示采集模块如何判定：
    1. 正常页            -> 成功（h2/h3 标题计数 + 等待元素命中）
    2. 403 拦截页        -> 被拦截（Cloudflare 特征，标题为 0）
    3. 200 缺等待元素页  -> 等待超时（标题保留但不计入成功）
    4. 请求异常页        -> 请求异常（连接失败，不中断后续页）

运行：
    python -I tests/demo_fixtures.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

import requests  # noqa: E402

from g2_collector import (  # noqa: E402
    G2Collector,
    ensure_utf8_output,
    format_report,
)

ensure_utf8_output()

FIXTURES = REPO_ROOT / "tests" / "fixtures"
WAIT_SELECTOR = ".star-wrapper__desc"

URL_NORMAL = "https://www.g2.com/products/mongodb/reviews?page=normal"
URL_BLOCKED = "https://www.g2.com/products/mongodb/reviews?page=blocked"
URL_WAIT_MISSING = "https://www.g2.com/products/mongodb/reviews?page=wait-missing"
URL_REQUEST_ERROR = "https://www.g2.com/products/mongodb/reviews?page=conn-error"


class FakeResponse:
    def __init__(self, status_code: int, text: str, headers: Dict[str, str] | None = None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class ScriptedFetcher:
    """按固定脚本返回假响应 / 抛假异常，模拟一次完整的四页批次。"""

    def __init__(self) -> None:
        normal_html = (FIXTURES / "normal.html").read_text(encoding="utf-8")
        blocked_html = (FIXTURES / "blocked_403.html").read_text(encoding="utf-8")
        wait_missing_html = (FIXTURES / "wait_missing.html").read_text(encoding="utf-8")
        self._routing: Dict[str, Any] = {
            URL_NORMAL: FakeResponse(200, normal_html),
            URL_BLOCKED: FakeResponse(
                403,
                blocked_html,
                headers={"Server": "cloudflare", "CF-RAY": "8a7b6c5d4e3f2a1b"},
            ),
            URL_WAIT_MISSING: FakeResponse(200, wait_missing_html),
            URL_REQUEST_ERROR: requests.ConnectionError(
                "模拟：连接 brd.superproxy.io:33335 失败（隧道建立超时）"
            ),
        }

    def fetch(self, url: str) -> FakeResponse:
        result = self._routing[url]
        if isinstance(result, Exception):
            raise result
        return result


def main() -> int:
    urls = [URL_NORMAL, URL_BLOCKED, URL_WAIT_MISSING, URL_REQUEST_ERROR]
    collector = G2Collector(ScriptedFetcher(), wait_selector=WAIT_SELECTOR)
    outcomes = [collector.collect_page(url) for url in urls]

    print("本地样例演示（离线假响应，非真实 G2 链路）")
    print(f"等待元素: {WAIT_SELECTOR}")
    print()
    print(format_report(outcomes))
    print()

    # 逐页一句话核对表
    print("逐页核对表:")
    for index, outcome in enumerate(outcomes, start=1):
        wait_text = (
            "未配置"
            if outcome.wait_element_hit is None
            else ("命中" if outcome.wait_element_hit else "未命中")
        )
        print(
            f"  {index}. {outcome.status.value:13s} | "
            f"h2={outcome.h2_count} h3={outcome.h3_count} | "
            f"等待元素={wait_text} | 拦截={'是' if outcome.blocked else '否'} | "
            f"调试信息={'有' if outcome.debug_info_present else '无'} | {outcome.url}"
        )
    print()
    print("注意：以上均为本地假响应，仅验证判定逻辑，不代表真实 G2 链路已跑通。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
