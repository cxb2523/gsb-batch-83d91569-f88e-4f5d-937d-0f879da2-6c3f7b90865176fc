"""G2 评论采集 —— API 直连通道（带 x-unblock-expect 等待元素）。

出口差异（本脚本独有）：
* 走 Web Unlocker API 直连（POST https://api.brightdata.com/request）；
* 请求头携带 ``x-unblock-expect``，让 Unlocker 在服务端等待
  ``.star-wrapper__desc`` 元素，本地再独立复核一次；
* 主输出 <h2> 标题。

凭据从环境变量读取（缺失即报错，不使用占位符）：
    BRD_API_TOKEN、BRD_CUSTOMER_ID、BRD_ZONE_NAME

用法：
    python g2_wait.py [URL ...]
    不传 URL 时默认采集 https://www.g2.com/products/mongodb/reviews
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

# 允许直接 `python src/g2_wait.py` 运行
sys.path.insert(0, str(Path(__file__).resolve().parent))

from g2_collector import (  # noqa: E402
    ApiDirectFetcher,
    CredentialError,
    Credentials,
    G2Collector,
    ensure_utf8_output,
    format_report,
    summarize,
)

WAIT_SELECTOR = ".star-wrapper__desc"
DEFAULT_URLS = ["https://www.g2.com/products/mongodb/reviews"]


def main(urls: List[str]) -> int:
    ensure_utf8_output()
    try:
        credentials = Credentials.from_env(require_api_token=True)
        fetcher = ApiDirectFetcher(credentials, wait_selector=WAIT_SELECTOR)
    except CredentialError as exc:
        print(f"凭据错误: {exc}", file=sys.stderr)
        return 2

    collector = G2Collector(fetcher, wait_selector=WAIT_SELECTOR)
    outcomes = collector.collect_all(urls)

    print(f"采集通道: API 直连（x-unblock-expect 等待 {WAIT_SELECTOR}）")
    print(format_report(outcomes))

    # 任一页非成功即返回非零退出码，便于自动化核对
    return 0 if summarize(outcomes).success == len(outcomes) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:] or list(DEFAULT_URLS)))
