"""统一的 G2 评论页采集模块。

三个示例脚本（g2_wait.py / g2_mobile.py / g2_debug.py）共用本模块，
逐页产出可核对的 :class:`PageOutcome`，把"成功 / 被拦截 / 等待超时 / 请求异常"
四种结局区分清楚，避免把失败页伪装成"空标题的成功页"。

设计要点
--------
* 传输层（:class:`Fetcher`）与采集逻辑分离：真实链路用
  :class:`ApiDirectFetcher` / :class:`ProxyFetcher`，测试可注入假 fetcher，
  因此本模块的测试完全不触网，不代表真实 G2 链路已跑通。
* 任一页抛异常都会被捕获并转成 ``REQUEST_ERROR`` 结局，不中断后续页。
* 凭据只从环境变量读取，缺失或仍是占位符时抛 :class:`CredentialError`，
  绝不静默用占位符发请求。
* 结局判定：
    - ``BLOCKED``：HTTP 403，或响应体 / 响应头命中 Cloudflare 拦截特征；
    - ``WAIT_TIMEOUT``：HTTP 200 且未被拦截，但指定等待元素在 DOM 中不存在；
    - ``REQUEST_ERROR``：请求本身抛异常，或 403 以外的非 2xx 状态；
    - ``SUCCESS``：200、未被拦截、（配置了等待元素时）等待元素命中。
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol, Sequence

import requests
from bs4 import BeautifulSoup


def ensure_utf8_output() -> None:
    """把标准输出/错误流重配置为 UTF-8。

    Windows 控制台可能默认 GBK 代码页，直接打印中文结局会花屏；
    在脚本入口调用一次即可。``-I`` 隔离模式下 PYTHONIOENCODING 被忽略，
    因此不能依赖环境变量。
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_URL = "https://api.brightdata.com/request"
PROXY_HOST = "brd.superproxy.io"
PROXY_PORT = 33335

#: 凭据环境变量名
ENV_API_TOKEN = "BRD_API_TOKEN"
ENV_CUSTOMER_ID = "BRD_CUSTOMER_ID"
ENV_ZONE_NAME = "BRD_ZONE_NAME"
ENV_ZONE_PASSWORD = "BRD_ZONE_PASSWORD"

#: 调试代理在响应头里返回的调试信息字段
DEBUG_HEADER = "x-brd-debug"

DEFAULT_TIMEOUT = 30

#: Cloudflare 拦截特征（小写匹配，命中响应体或响应头即判定被拦截）
CLOUDFLARE_MARKERS = (
    "cloudflare ray id:",
    "cf-ray",
    "attention required! | cloudflare",
    "sorry, you have been blocked",
    "please enable cookies and reload the page",
    "error 1015",  # rate limited
    "error 1020",  # access denied
    "error 1010",  # browser signature ban
    "challenge-platform",
    "/cdn-cgi/challenge-platform",
    "the owner of this website has banned your access",
)


class PageStatus(str, Enum):
    """单页采集结局。"""

    SUCCESS = "success"          # 200、未拦截、等待元素命中（或无需等待）
    BLOCKED = "blocked"          # 403 或命中 Cloudflare 拦截特征
    WAIT_TIMEOUT = "wait_timeout"  # 200 但指定等待元素不存在
    REQUEST_ERROR = "request_error"  # 请求异常或 403 以外的非 2xx 状态


class CredentialError(RuntimeError):
    """环境变量凭据缺失或仍是占位符。"""


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class Credentials:
    """Bright Data 凭据，只能通过 :meth:`from_env` 从环境变量构造。"""

    customer_id: str
    zone_name: str
    zone_password: Optional[str] = None
    api_token: Optional[str] = None

    @staticmethod
    def _clean(name: str, value: Optional[str]) -> str:
        if value is None or value.strip() == "":
            raise CredentialError(f"缺少环境变量 {name}，请先配置 Bright Data 凭据")
        cleaned = value.strip()
        # 拦截文档里的占位符，避免把占位符当真凭据发出去
        if cleaned.startswith("<") and cleaned.endswith(">"):
            raise CredentialError(f"环境变量 {name} 仍是占位符 {cleaned!r}，请填入真实值")
        if cleaned.upper().startswith("INSERT_YOUR_"):
            raise CredentialError(f"环境变量 {name} 仍是占位符 {cleaned!r}，请填入真实值")
        return cleaned

    @classmethod
    def from_env(
        cls,
        *,
        require_api_token: bool = False,
        require_zone_password: bool = False,
        environ: Optional[Dict[str, str]] = None,
    ) -> "Credentials":
        """从环境变量读取凭据。

        ``require_api_token`` 用于 API 直连模式；``require_zone_password``
        用于代理模式。缺失或为占位符时抛 :class:`CredentialError`。
        """
        env = environ if environ is not None else dict(os.environ)
        customer_id = cls._clean(ENV_CUSTOMER_ID, env.get(ENV_CUSTOMER_ID))
        zone_name = cls._clean(ENV_ZONE_NAME, env.get(ENV_ZONE_NAME))

        zone_password: Optional[str] = None
        if require_zone_password:
            zone_password = cls._clean(
                ENV_ZONE_PASSWORD, env.get(ENV_ZONE_PASSWORD)
            )

        api_token: Optional[str] = None
        if require_api_token:
            api_token = cls._clean(ENV_API_TOKEN, env.get(ENV_API_TOKEN))

        return cls(
            customer_id=customer_id,
            zone_name=zone_name,
            zone_password=zone_password,
            api_token=api_token,
        )


@dataclass
class PageOutcome:
    """单页可核对的采集结局。"""

    url: str
    status: PageStatus
    h2_headings: List[str] = field(default_factory=list)
    h3_headings: List[str] = field(default_factory=list)
    wait_selector: Optional[str] = None
    wait_element_hit: Optional[bool] = None  # None 表示本页未配置等待元素
    blocked: bool = False
    block_reason: Optional[str] = None
    http_status: Optional[int] = None
    debug_info_present: bool = False
    debug_info: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        """只有 SUCCESS 才算成功；等待超时不计入成功。"""
        return self.status is PageStatus.SUCCESS

    @property
    def h2_count(self) -> int:
        return len(self.h2_headings)

    @property
    def h3_count(self) -> int:
        return len(self.h3_headings)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "status": self.status.value,
            "http_status": self.http_status,
            "h2_count": self.h2_count,
            "h3_count": self.h3_count,
            "h2_headings": self.h2_headings,
            "h3_headings": self.h3_headings,
            "wait_selector": self.wait_selector,
            "wait_element_hit": self.wait_element_hit,
            "blocked": self.blocked,
            "block_reason": self.block_reason,
            "debug_info_present": self.debug_info_present,
            "error": self.error,
        }


@dataclass
class CollectionSummary:
    """整批采集的汇总，标题数只统计成功页，失败页绝不混入。"""

    total: int = 0
    success: int = 0
    blocked: int = 0
    wait_timeout: int = 0
    request_error: int = 0
    success_h2_total: int = 0
    success_h3_total: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "success": self.success,
            "blocked": self.blocked,
            "wait_timeout": self.wait_timeout,
            "request_error": self.request_error,
            "success_h2_total": self.success_h2_total,
            "success_h3_total": self.success_h3_total,
        }


# ---------------------------------------------------------------------------
# 传输层抽象
# ---------------------------------------------------------------------------


class Fetcher(Protocol):
    """传输层协议。真实实现与测试假实现都遵守同一接口。

    成功返回一个具备 ``status_code`` / ``text`` / ``headers`` 的对象；
    网络层问题直接抛 :class:`requests.RequestException`，由采集层兜底。
    """

    def fetch(self, url: str) -> Any:
        ...


class ApiDirectFetcher:
    """Web Unlocker API 直连（POST https://api.brightdata.com/request）。

    可携带 ``x-unblock-expect`` 头让 Unlocker 在服务端等待指定元素，
    采集层仍会在本地 DOM 上独立复核该元素是否真的存在。
    """

    def __init__(
        self,
        credentials: Credentials,
        *,
        wait_selector: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
    ) -> None:
        if not credentials.api_token:
            raise CredentialError(
                f"API 直连模式需要 {ENV_API_TOKEN}，请通过 Credentials.from_env("
                "require_api_token=True) 读取"
            )
        self._credentials = credentials
        self._wait_selector = wait_selector
        self._timeout = timeout
        self._session = session or requests.Session()

    def fetch(self, url: str) -> requests.Response:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._credentials.api_token}",
        }
        if self._wait_selector:
            headers["x-unblock-expect"] = json.dumps(
                {"element": self._wait_selector}
            )
        payload = {
            "zone": self._credentials.zone_name,
            "url": url,
            "format": "raw",
        }
        return self._session.post(
            API_URL, headers=headers, json=payload, timeout=self._timeout
        )


class ProxyFetcher:
    """原生代理访问（brd.superproxy.io:33335）。

    ``username_flags`` 为附加到代理用户名上的标志，例如 ``"ua-mobile"``
    或 ``"debug-full"``；调试模式下采集层会读取 ``x-brd-debug`` 响应头。
    """

    def __init__(
        self,
        credentials: Credentials,
        *,
        username_flags: Sequence[str] = (),
        timeout: int = DEFAULT_TIMEOUT,
        session: Optional[requests.Session] = None,
        verify: bool = False,
    ) -> None:
        if not credentials.zone_password:
            raise CredentialError(
                f"代理模式需要 {ENV_ZONE_PASSWORD}，请通过 Credentials.from_env("
                "require_zone_password=True) 读取"
            )
        suffix = "-" + "-".join(username_flags) if username_flags else ""
        username = (
            f"brd-customer-{credentials.customer_id}"
            f"-zone-{credentials.zone_name}{suffix}"
        )
        proxy_url = (
            f"http://{username}:{credentials.zone_password}"
            f"@{PROXY_HOST}:{PROXY_PORT}"
        )
        self._proxies = {"http": proxy_url, "https": proxy_url}
        self._timeout = timeout
        self._session = session or requests.Session()
        self._verify = verify

    def fetch(self, url: str) -> requests.Response:
        return self._session.get(
            url,
            proxies=self._proxies,
            timeout=self._timeout,
            verify=self._verify,
        )


# ---------------------------------------------------------------------------
# 判定辅助函数
# ---------------------------------------------------------------------------


def _header_get(headers: Any, name: str) -> Optional[str]:
    """大小写不敏感地取响应头，兼容 requests 响应与普通 dict。"""
    if headers is None:
        return None
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return value
        # requests 的 CaseInsensitiveDict 本身不区分大小写；
        # 普通 dict 需要手动兜底。
        if isinstance(headers, dict):
            lowered = name.lower()
            for key, val in headers.items():
                if key.lower() == lowered:
                    return val
    return None


def detect_cloudflare(status_code: int, text: str, headers: Any) -> Optional[str]:
    """命中 Cloudflare 拦截特征时返回原因字符串，否则返回 None。

    403 本身即视为拦截；此外响应体或任一响应头命中已知特征也算拦截，
    以覆盖"200 包着挑战页"这类情况。
    """
    if status_code == 403:
        return "HTTP 403"
    body = (text or "").lower()
    for marker in CLOUDFLARE_MARKERS:
        if marker in body:
            return f"响应体命中 Cloudflare 特征: {marker!r}"
    if headers is not None:
        cf_ray = _header_get(headers, "cf-ray")
        if cf_ray:
            return f"响应头 cf-ray={cf_ray!r}"
        # 注意：仅凭 server: cloudflare 不判定拦截——正常 CDN 响应也带该头，
        # 必须结合上面的挑战页特征或 cf-ray，避免误判。
    return None


def extract_headings(soup: BeautifulSoup) -> Dict[str, List[str]]:
    """提取 h2 / h3 文本，保持文档顺序。"""
    return {
        "h2": [h.get_text(strip=True) for h in soup.find_all("h2")],
        "h3": [h.get_text(strip=True) for h in soup.find_all("h3")],
    }


def summarize(outcomes: Sequence[PageOutcome]) -> CollectionSummary:
    """汇总一批结局；标题计数只累加成功页。"""
    summary = CollectionSummary(total=len(outcomes))
    for outcome in outcomes:
        if outcome.status is PageStatus.SUCCESS:
            summary.success += 1
            summary.success_h2_total += outcome.h2_count
            summary.success_h3_total += outcome.h3_count
        elif outcome.status is PageStatus.BLOCKED:
            summary.blocked += 1
        elif outcome.status is PageStatus.WAIT_TIMEOUT:
            summary.wait_timeout += 1
        else:
            summary.request_error += 1
    return summary


# ---------------------------------------------------------------------------
# 采集器
# ---------------------------------------------------------------------------


class G2Collector:
    """逐页采集并产出 :class:`PageOutcome`。

    Parameters
    ----------
    fetcher:
        传输层实现（API 直连 / 代理 / 测试假实现）。
    wait_selector:
        可选 CSS 选择器。配置后，200 响应里找不到该元素即判 ``WAIT_TIMEOUT``。
    parser:
        BeautifulSoup 解析器，默认 ``lxml``。
    """

    def __init__(
        self,
        fetcher: Fetcher,
        *,
        wait_selector: Optional[str] = None,
        parser: str = "lxml",
    ) -> None:
        self._fetcher = fetcher
        self._wait_selector = wait_selector
        self._parser = parser

    def collect_page(self, url: str) -> PageOutcome:
        """采集单页，任何异常都收敛为结局对象，不向上抛。"""
        try:
            response = self._fetcher.fetch(url)
        except requests.RequestException as exc:
            return PageOutcome(
                url=url,
                status=PageStatus.REQUEST_ERROR,
                wait_selector=self._wait_selector,
                # 请求未成功，无法判断元素是否存在；有配置选择器时记为未命中
                wait_element_hit=False if self._wait_selector else None,
                error=f"请求异常: {type(exc).__name__}: {exc}",
            )

        status_code = getattr(response, "status_code", None)
        text = getattr(response, "text", "") or ""
        headers = getattr(response, "headers", None)
        debug_info = _header_get(headers, DEBUG_HEADER)

        # 1) 拦截判定（403 或 Cloudflare 特征）
        block_reason = detect_cloudflare(status_code, text, headers)
        if block_reason is not None:
            return PageOutcome(
                url=url,
                status=PageStatus.BLOCKED,
                http_status=status_code,
                wait_selector=self._wait_selector,
                wait_element_hit=False if self._wait_selector else None,
                blocked=True,
                block_reason=block_reason,
                debug_info_present=bool(debug_info),
                debug_info=debug_info,
            )

        # 2) 非 2xx（且不是 403）按请求异常处置，不解析、不计标题
        if not isinstance(status_code, int) or not (200 <= status_code < 300):
            return PageOutcome(
                url=url,
                status=PageStatus.REQUEST_ERROR,
                http_status=status_code,
                wait_selector=self._wait_selector,
                wait_element_hit=False if self._wait_selector else None,
                error=f"未预期的 HTTP 状态码: {status_code}",
                debug_info_present=bool(debug_info),
                debug_info=debug_info,
            )

        # 3) 200：解析 DOM，提取标题，复核等待元素
        soup = BeautifulSoup(text, self._parser)
        headings = extract_headings(soup)

        wait_hit: Optional[bool] = None
        if self._wait_selector:
            wait_hit = soup.select_one(self._wait_selector) is not None
            if not wait_hit:
                # 等待超时：标题如实记录以便排查，但本页不计入成功
                return PageOutcome(
                    url=url,
                    status=PageStatus.WAIT_TIMEOUT,
                    http_status=status_code,
                    h2_headings=headings["h2"],
                    h3_headings=headings["h3"],
                    wait_selector=self._wait_selector,
                    wait_element_hit=False,
                    debug_info_present=bool(debug_info),
                    debug_info=debug_info,
                    error=f"等待元素 {self._wait_selector!r} 在 200 响应中不存在",
                )

        return PageOutcome(
            url=url,
            status=PageStatus.SUCCESS,
            http_status=status_code,
            h2_headings=headings["h2"],
            h3_headings=headings["h3"],
            wait_selector=self._wait_selector,
            wait_element_hit=wait_hit,
            debug_info_present=bool(debug_info),
            debug_info=debug_info,
        )

    def collect_all(self, urls: Sequence[str]) -> List[PageOutcome]:
        """逐页采集；任一页失败都不中断后续页。"""
        outcomes: List[PageOutcome] = []
        for url in urls:
            outcomes.append(self.collect_page(url))
        return outcomes


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

_STATUS_LABELS = {
    PageStatus.SUCCESS: "成功",
    PageStatus.BLOCKED: "被拦截",
    PageStatus.WAIT_TIMEOUT: "等待超时",
    PageStatus.REQUEST_ERROR: "请求异常",
}


def format_page_outcome(outcome: PageOutcome) -> str:
    """把单页结局渲染成可核对的多行文本。"""
    lines = [
        f"URL: {outcome.url}",
        f"  状态: {_STATUS_LABELS[outcome.status]} ({outcome.status.value})"
        + (f" [HTTP {outcome.http_status}]" if outcome.http_status is not None else ""),
        f"  h2 标题数: {outcome.h2_count}，h3 标题数: {outcome.h3_count}",
    ]
    if outcome.wait_selector:
        hit_text = {
            True: "命中",
            False: "未命中",
            None: "未配置",
        }[outcome.wait_element_hit]
        lines.append(
            f"  等待元素 {outcome.wait_selector!r}: {hit_text}"
        )
    else:
        lines.append("  等待元素: 本通道未配置")
    lines.append(f"  是否触发拦截: {'是' if outcome.blocked else '否'}"
                 + (f"（{outcome.block_reason}）" if outcome.block_reason else ""))
    lines.append(f"  调试信息(x-brd-debug): {'有' if outcome.debug_info_present else '无'}")
    if outcome.error:
        lines.append(f"  处置说明: {outcome.error}")
    if outcome.h2_headings:
        lines.append("  h2 标题:")
        lines.extend(f"    - {title}" for title in outcome.h2_headings)
    if outcome.h3_headings:
        lines.append("  h3 标题:")
        lines.extend(f"    - {title}" for title in outcome.h3_headings)
    return "\n".join(lines)


def format_summary(outcomes: Sequence[PageOutcome]) -> str:
    """渲染整批汇总。"""
    summary = summarize(outcomes)
    lines = [
        "=" * 60,
        "汇总（标题数仅统计成功页，失败页不计入）",
        f"  总页数: {summary.total}",
        f"  成功: {summary.success}",
        f"  被拦截: {summary.blocked}",
        f"  等待超时: {summary.wait_timeout}",
        f"  请求异常: {summary.request_error}",
        f"  成功页 h2 标题总数: {summary.success_h2_total}",
        f"  成功页 h3 标题总数: {summary.success_h3_total}",
        "=" * 60,
    ]
    return "\n".join(lines)


def format_report(outcomes: Sequence[PageOutcome]) -> str:
    """逐页结局 + 汇总的完整文本报告。"""
    pages = "\n\n".join(format_page_outcome(o) for o in outcomes)
    return f"{pages}\n\n{format_summary(outcomes)}"
