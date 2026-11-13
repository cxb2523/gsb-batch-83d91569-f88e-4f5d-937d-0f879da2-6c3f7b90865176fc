"""
Webpack / Vue / React H5 全站前端工程深度递归抓取器 (Project Dumper)

在原有“只有成功数量”的基础上，本模块为每个被处理的资源（主入口 HTML 除外）
生成一条可逐项核对的结论，记录：

* 原始引用 (raw_reference)
* 解析后的完整 URL (resolved_url)
* 本地保存的相对路径 (local_path)
* 结果状态 (status): success / skipped / failed / duplicate
* 失败或跳过的原因 (reason)

调用方仍可按原方式使用 ``ProjectDumper(output_dir=...).dump(target_url)``（返回 bool），
随后通过 ``dumper.last_report`` / ``dumper.report`` 或 ``dumper.dump_with_report(url)``
拿到结构化的逐资源清单与汇总计数。
"""

import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..utils.logger import log_info, log_warn, log_error, log_step
from ..utils.path_helper import sanitize_url_to_path
from ..sandbox.user_agents import get_wechat_ua

# 逐资源结果状态（稳定的机器可读取值）
STATUS_SUCCESS = "success"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_DUPLICATE = "duplicate"

RESOURCE_STATUSES = (STATUS_SUCCESS, STATUS_SKIPPED, STATUS_FAILED, STATUS_DUPLICATE)


@dataclass
class ResourceResult:
    """单个资源（非主入口 HTML）的抓取结论。"""

    raw_reference: str
    resolved_url: str
    local_path: str
    status: str
    reason: str = ""
    size_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "raw_reference": self.raw_reference,
            "resolved_url": self.resolved_url,
            "local_path": self.local_path,
            "status": self.status,
            "reason": self.reason,
            "size_bytes": self.size_bytes,
        }


@dataclass
class DumpReport:
    """一次 dump 的完整结果，可直接序列化为 JSON 供程序读取。"""

    target_url: str
    success: bool = False
    entry_html_saved: bool = False
    error: Optional[str] = None
    output_dir: Optional[str] = None
    resources: List[ResourceResult] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        """汇总计数；每次都由 resources 实时计算，保证与清单条目严格一致。"""
        counts = {status: 0 for status in RESOURCE_STATUSES}
        for item in self.resources:
            counts[item.status] = counts.get(item.status, 0) + 1
        return counts

    @property
    def total(self) -> int:
        return len(self.resources)

    def to_dict(self) -> Dict[str, object]:
        return {
            "target_url": self.target_url,
            "success": self.success,
            "entry_html_saved": self.entry_html_saved,
            "error": self.error,
            "output_dir": self.output_dir,
            "counts": self.counts,
            "resources": [item.to_dict() for item in self.resources],
        }


class ProjectDumper:
    def __init__(self, output_dir: str = "output_project", platform_ua: str = "ios",
                 timeout: float = 10):
        self.output_dir = Path(output_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        self.headers = {
            "User-Agent": get_wechat_ua(platform_ua),
            "Referer": "https://mp.weixin.qq.com/",
            "Accept": "*/*"
        }
        # 兼容旧属性：本次运行中已请求/已登记的完整 URL
        self.downloaded: set = set()
        # 本次运行的逐资源报告（dump 之前为 None）
        self.last_report: Optional[DumpReport] = None
        self._seen: set = set()
        self._path_map: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # 公共调用入口
    # ------------------------------------------------------------------
    @property
    def report(self) -> Optional[DumpReport]:
        """最近一次 dump 的报告（与 last_report 等价）。"""
        return self.last_report

    def get_last_report(self) -> Optional[DumpReport]:
        return self.last_report

    def dump(self, target_url: str) -> bool:
        """保持原有调用方式：返回本次抓取是否成功（主入口 HTML 是否取到）。"""
        return self.dump_with_report(target_url).success

    def dump_with_report(self, target_url: str) -> DumpReport:
        """执行抓取并返回包含逐资源清单的 DumpReport。"""
        report = DumpReport(target_url=target_url, output_dir=str(self.output_dir))
        self.last_report = report
        self._seen = set()
        self._path_map = {}
        self.downloaded = set()

        log_info(f"开始全站递归抓取: [bold cyan]{target_url}[/bold cyan]")
        log_step(f"本地存储根路径: {self.output_dir}")

        # 1. 主入口 HTML 失败时立即返回失败，不产生任何成功结论
        try:
            html = self._download(target_url)
        except Exception as e:
            reason = self._format_error(e)
            msg = f"无法访问目标 URL: {reason}"
            log_error(msg)
            report.error = msg
            report.success = False
            return report

        index_file = self.output_dir / "index.html"
        try:
            with open(index_file, "w", encoding="utf-8") as f:
                f.write(html.decode("utf-8", errors="ignore"))
        except OSError as e:
            reason = self._format_error(e)
            msg = f"主入口 HTML 保存失败: {reason}"
            log_error(msg)
            report.error = msg
            report.success = False
            return report

        report.entry_html_saved = True
        log_info(f"主入口 HTML 已保存: index.html ({len(html)} 字节)")

        # 2. 资源发现（队列元素为 (原始引用, 解析基准 URL)）
        queue = deque()
        for raw_ref in self._extract_html_refs(html.decode("utf-8", errors="ignore")):
            queue.append((raw_ref, target_url))

        log_step(f"解析到 {len(queue)} 个初始静态资源引用，开始异步深入解包...")

        # 3. 顺序处理队列；单个资源失败不会中断整次抓取
        while queue:
            raw_ref, base_url = queue.popleft()
            full_url, skip_reason = self._resolve_reference(raw_ref, base_url)

            if skip_reason is not None:
                report.resources.append(ResourceResult(
                    raw_reference=raw_ref,
                    resolved_url=full_url,
                    local_path="",
                    status=STATUS_SKIPPED,
                    reason=skip_reason,
                ))
                continue

            if full_url in self._seen:
                # 同一完整 URL 只真正下载一次，后续引用仅记录为重复
                local_path = self._path_map.get(full_url) or self._local_rel_path(full_url)
                report.resources.append(ResourceResult(
                    raw_reference=raw_ref,
                    resolved_url=full_url,
                    local_path=local_path,
                    status=STATUS_DUPLICATE,
                    reason="重复引用：同一 URL 已处理过，未重复下载",
                ))
                continue

            self._seen.add(full_url)
            self.downloaded.add(full_url)
            domain, rel_path = sanitize_url_to_path(full_url)
            local_path = f"{domain}/{rel_path.as_posix()}"
            save_file = self.output_dir / domain / rel_path

            try:
                data = self._download(full_url)
                save_file.parent.mkdir(parents=True, exist_ok=True)
                with open(save_file, "wb") as f:
                    f.write(data)
            except Exception as e:
                reason = self._format_error(e)
                log_warn(f"资源下载失败: {full_url} — {reason}")
                report.resources.append(ResourceResult(
                    raw_reference=raw_ref,
                    resolved_url=full_url,
                    local_path=local_path,
                    status=STATUS_FAILED,
                    reason=reason,
                ))
                continue

            log_info(f"已提取: {domain}/{rel_path} ({len(data)} 字节)")
            report.resources.append(ResourceResult(
                raw_reference=raw_ref,
                resolved_url=full_url,
                local_path=local_path,
                status=STATUS_SUCCESS,
                size_bytes=len(data),
            ))
            self._path_map[full_url] = local_path

            # 深度嗅探子资源（JS 分包 / sourceMappingURL / CSS url(...)）
            try:
                children = self._discover_children(local_path, data, full_url, target_url)
            except Exception as e:  # 解析失败不影响已保存资源与队列中剩余资源
                log_warn(f"解析资源内的子引用失败: {full_url} — {self._format_error(e)}")
                children = []
            for child_ref, child_base in children:
                queue.append((child_ref, child_base))

        # 4. 汇总日志：计数与清单严格一致
        counts = report.counts
        report.success = True
        log_info(
            "全站前端工程抓取完成！资源成功 [bold green]{success}[/bold green] 个，"
            "重复 {duplicate} 个，跳过 {skipped} 个，失败 {failed} 个"
            "（另有主入口 HTML: index.html）。".format(**counts)
        )
        if counts[STATUS_FAILED]:
            log_warn(f"共计 {counts[STATUS_FAILED]} 个资源下载失败，失败 URL 与原因见上方日志。")
        return report

    # ------------------------------------------------------------------
    # 资源发现
    # ------------------------------------------------------------------
    @staticmethod
    def _extract_html_refs(html: str) -> List[str]:
        """提取 HTML 中 script/link 的 src 与 href（保留出现顺序与重复引用）。"""
        refs: List[str] = []
        for match in re.finditer(
            r'<(?:script|link)\b[^>]*?\b(?:src|href)\s*=\s*(?:["\']([^"\'>\s]+)["\']|([^"\'>\s]+))',
            html, re.IGNORECASE
        ):
            ref = match.group(1) or match.group(2)
            if ref:
                refs.append(ref)
        return refs

    def _discover_children(self, local_path: str, data: bytes,
                           full_url: str, page_url: str) -> List[Tuple[str, str]]:
        """根据已下载资源的类型解析出子资源引用。

        返回 (原始引用, 解析基准 URL) 列表，基准 URL 沿用原有规则：
        JS 分包候选与目标页面地址拼接，sourceMappingURL 与 CSS url(...)
        与引用它们的资源自身地址拼接。
        """
        lower_path = local_path.lower()
        if lower_path.endswith(".js"):
            return self._discover_js_children(data.decode("utf-8", errors="ignore"), full_url, page_url)
        if lower_path.endswith(".css"):
            return self._discover_css_children(data.decode("utf-8", errors="ignore"), full_url)
        return []

    @staticmethod
    def _discover_js_children(text: str, js_url: str, page_url: str) -> List[Tuple[str, str]]:
        children: List[Tuple[str, str]] = []

        # 1. 常规 JS 路径（保留字面量中的重复引用）
        literal_chunks: List[str] = []
        literal_chunks += re.findall(r'["\'](js/[a-zA-Z0-9_\-\.]+\.js)["\']', text)
        literal_chunks += re.findall(r'["\'](chunk-[a-zA-Z0-9_\-\.]+\.js)["\']', text)

        # 2. 嗅探 Webpack 动态 Chunk 加载器 (如 {"name":"name"}[e] + ".<releaseDate>.js")
        suffix_matches = set(re.findall(r'\[e\]\|\|e\)\s*\+\s*["\']([^\'"]+\.js)["\']', text))
        dict_matches = re.findall(r'\"([a-zA-Z0-9_\-\~]+)\"\s*:\s*\"([a-zA-Z0-9_\-\~]+)\"', text)

        generated: List[str] = []
        if suffix_matches and dict_matches:
            for sfx in suffix_matches:
                for _, v in dict_matches:
                    generated.append(f"js/{v}{sfx}")

        # 3. 嗅探 Webpack require.e("chunk-name") 动态调用链
        e_matches = re.findall(r'\.e\((["\'])([^"\']+)\1\)', text)
        if e_matches and suffix_matches:
            for sfx in suffix_matches:
                for _, cname in e_matches:
                    generated.append(f"js/{cname}{sfx}")

        # 4. 嗅探深层派生分包 chunk-xxxxxx
        raw_chunk_ids = re.findall(r'(chunk-[a-zA-Z0-9_]+)', text)
        if raw_chunk_ids and suffix_matches:
            for sfx in suffix_matches:
                for rc in set(raw_chunk_ids):
                    generated.append(f"js/{rc}{sfx}")

        # 字面量引用全部保留（重复引用交由统一的 URL 去重逻辑记为 duplicate）；
        # 组合推导出的候选只保留一次，避免同一推断被重复展开。
        for chunk in literal_chunks:
            children.append((chunk, page_url))
        for chunk in dict.fromkeys(generated):
            children.append((chunk, page_url))

        # 5. sourceMappingURL（相对 JS 文件所在地址解析）
        for raw_map in re.findall(r'sourceMappingURL\s*=\s*["\']?([^"\'\s*]+)', text):
            if raw_map:
                children.append((raw_map, js_url))

        return children

    @staticmethod
    def _discover_css_children(text: str, css_url: str) -> List[Tuple[str, str]]:
        children: List[Tuple[str, str]] = []
        for asset in re.findall(r'url\s*\(\s*["\']?([^"\'\)\s]+)["\']?\s*\)', text):
            children.append((asset, css_url))
        return children

    # ------------------------------------------------------------------
    # URL 解析 / 下载 / 错误描述
    # ------------------------------------------------------------------
    def _resolve_reference(self, raw_ref: str, base_url: str) -> Tuple[str, Optional[str]]:
        """把原始引用解析为可下载的完整 URL。

        返回 (full_url, skip_reason)。skip_reason 不为 None 时表示该引用无需下载，
        full_url 保留原始引用以便核对。
        """
        ref = (raw_ref or "").strip()
        if not ref:
            return ref, "空引用"

        if ref.startswith("#"):
            return ref, "页面内锚点引用，不是可下载资源"
        if ref in (".", "./"):
            return ref, "指向页面自身/目录，不是可下载资源"

        if ref.startswith("//"):
            return self._strip_fragment("https:" + ref), None

        scheme = urllib.parse.urlsplit(ref).scheme.lower()
        if scheme in ("http", "https"):
            return self._strip_fragment(ref), None
        if scheme:
            # data:/blob:/javascript:/mailto: 等非 HTTP 资源不下载
            return ref, f"不支持的协议 {scheme}:，未下载"

        return self._strip_fragment(urllib.parse.urljoin(base_url, ref)), None

    @staticmethod
    def _strip_fragment(url: str) -> str:
        return urllib.parse.urldefrag(url)[0]

    def _local_rel_path(self, full_url: str) -> str:
        domain, rel_path = sanitize_url_to_path(full_url)
        return f"{domain}/{rel_path.as_posix()}"

    def _download(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers=self.headers)
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=self.timeout, context=ctx) as resp:
            return resp.read()

    @staticmethod
    def _format_error(exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return f"HTTP {exc.code} {exc.reason}"
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower():
                return f"请求超时: {reason}"
            return f"网络错误: {reason}"
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return f"请求超时: {exc}"
        if isinstance(exc, OSError):
            return f"本地保存失败: {exc}"
        return f"{type(exc).__name__}: {exc}"
