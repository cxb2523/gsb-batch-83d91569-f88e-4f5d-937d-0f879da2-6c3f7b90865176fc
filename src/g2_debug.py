"""G2 评论采集 —— 调试代理通道（用户名附加 -debug-full）。

出口差异（本脚本独有）：
* 走原生代理 brd.superproxy.io:33335；
* 代理用户名附加 ``-debug-full``，启用详细调试信息；
* 读取并展示 ``x-brd-debug`` 响应头（结局对象中以
  ``debug_info_present`` / ``debug_info`` 体现）；
* 主输出 <h2> 标题；
* 不配置等待元素。

凭据从环境变量读取（缺失即报错，不使用占位符）：
    BRD_CUSTOMER_ID、BRD_ZONE_NAME、BRD_ZONE_PASSWORD

用法：
    python g2_debug.py [URL ...]
    不传 URL 时默认采集 https://www.g2.com/products/mongodb/reviews
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

# 允许直接 `python src/g2_debug.py` 运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests  # noqa: E402
from requests.packages.urllib3.exceptions import InsecureRequestWarning  # noqa: E402

from g2_collector import (  # noqa: E402
    CredentialError,
    Credentials,
    G2Collector,
    ProxyFetcher,
    ensure_utf8_output,
    format_page_outcome,
    format_summary,
    summarize,
)

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

DEFAULT_URLS = ["https://www.g2.com/products/mongodb/reviews"]


def main(urls: List[str]) -> int:
    ensure_utf8_output()
    try:
        credentials = Credentials.from_env(require_zone_password=True)
        fetcher = ProxyFetcher(credentials, username_flags=["debug-full"])
    except CredentialError as exc:
        print(f"凭据错误: {exc}", file=sys.stderr)
        return 2

    collector = G2Collector(fetcher)  # 调试通道不配置等待元素
    outcomes = collector.collect_all(urls)

    print("采集通道: 原生代理（-debug-full 调试模式）")
    for outcome in outcomes:
        print(format_page_outcome(outcome))
        if outcome.debug_info_present:
            print("  x-brd-debug 原文:")
            print(f"    {outcome.debug_info}")
    print()
    print(format_summary(outcomes))

    return 0 if summarize(outcomes).success == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or list(DEFAULT_URLS)))
