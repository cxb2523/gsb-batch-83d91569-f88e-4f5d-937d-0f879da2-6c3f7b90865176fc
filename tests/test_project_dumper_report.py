#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_project_dumper_report.py: ProjectDumper 逐资源归档结论回归测试

使用本地 ThreadingHTTPServer 构造受控站点，覆盖：
- HTML 中 script/link 的 src 与 href 资源发现
- 相对路径 / ./ 相对路径 / 协议相对路径 //host/... / 绝对 URL 解析
- 重复引用只下载一次并记为 duplicate
- JS 分包 chunk、sourceMappingURL 与 CSS url(...) 子资源发现
- data: 等不可下载引用记为 skipped
- 单个资源 404 / 超时时继续处理剩余队列并记为 failed
- 主入口 HTML 请求失败时返回 False 且无资源清单
- 汇总计数与逐资源清单严格一致
"""

import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from wechat_h5_devtools.extractor.project_dumper import (  # noqa: E402
    ProjectDumper,
    STATUS_SUCCESS,
    STATUS_SKIPPED,
    STATUS_FAILED,
    STATUS_DUPLICATE,
)

INDEX_TEMPLATE = """<!doctype html><html><head>
<link rel="stylesheet" href="/static/css/app.css">
<link rel="stylesheet" href="//127.0.0.1:{port}/static/css/app.css">
<script src="static/js/app.js"></script>
<script src="./static/js/app.js#frag"></script>
<script src="/static/js/missing.js"></script>
<script src="/static/js/slow.js"></script>
<script>var inline = "static/js/inline-only.js";</script>
</head><body>hi</body></html>
"""

APP_JS = """
var a = "js/vendor-a.js";
var a2 = 'js/vendor-a.js';
var b = "chunk-7788.js";
//# sourceMappingURL=app.js.map
"""

APP_CSS = """
@font-face { src: url("../fonts/a.woff2"); }
body { background: url('/static/img/bg.png'); }
body:after { content: url("data:image/png;base64,AAA"); }
"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.hits.append(self.path)
        path = self.path.split("?")[0]
        port = self.server.server_port
        routes = {
            "/article": (200, INDEX_TEMPLATE.format(port=port).encode("utf-8"), "text/html"),
            "/static/css/app.css": (200, APP_CSS.encode("utf-8"), "text/css"),
            "/static/js/app.js": (200, APP_JS.encode("utf-8"), "application/javascript"),
            "/static/js/app.js.map": (200, b'{"version":3}', "application/json"),
            "/js/vendor-a.js": (200, b"vendor", "application/javascript"),
            "/static/fonts/a.woff2": (200, b"font", "font/woff2"),
            "/static/img/bg.png": (200, b"png", "image/png"),
        }
        if path == "/static/js/slow.js":
            time.sleep(3)
            self.send_response(200)
            self.send_header("Content-Length", "4")
            self.end_headers()
            self.wfile.write(b"slow")
            return
        if path in routes:
            status, body, ctype = routes[path]
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()


def _start_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits = []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_dump_resource_report(tmp_path):
    srv = _start_server()
    try:
        port = srv.server_port
        dumper = ProjectDumper(output_dir=str(tmp_path / "site"), timeout=1)
        assert dumper.dump(f"http://127.0.0.1:{port}/article") is True

        report = dumper.get_last_report()
        doc = report.to_dict()
        resources = doc["resources"]
        counts = doc["counts"]

        # 汇总计数与清单条目严格一致
        assert sum(counts.values()) == len(resources)
        assert set(counts) == {STATUS_SUCCESS, STATUS_SKIPPED, STATUS_FAILED, STATUS_DUPLICATE}
        for item in resources:
            assert set(item) == {"raw_reference", "resolved_url", "local_path",
                                 "status", "reason", "size_bytes"}

        by_raw = {}
        for item in resources:
            by_raw.setdefault(item["raw_reference"], []).append(item)

        # 相对路径、./ 与绝对 URL 都能解析到同一完整 URL，且只真正下载一次
        app_js = by_raw["static/js/app.js"][0]
        assert app_js["status"] == STATUS_SUCCESS
        assert app_js["resolved_url"] == f"http://127.0.0.1:{port}/static/js/app.js"
        duplicate = by_raw["./static/js/app.js#frag"][0]
        assert duplicate["status"] == STATUS_DUPLICATE
        assert duplicate["resolved_url"] == app_js["resolved_url"]
        assert srv.hits.count("/static/js/app.js") == 1
        assert srv.hits.count("/static/css/app.css") == 1

        # 404 与超时都记为 failed，携带 URL 与原因，且不中断后续队列
        missing = by_raw["/static/js/missing.js"][0]
        assert missing["status"] == STATUS_FAILED and "404" in missing["reason"]
        slow = by_raw["/static/js/slow.js"][0]
        assert slow["status"] == STATUS_FAILED and "超时" in slow["reason"]

        # data: 引用记为 skipped 并说明原因
        data_ref = by_raw['data:image/png;base64,AAA'][0]
        assert data_ref["status"] == STATUS_SKIPPED and data_ref["reason"]

        # JS 分包与 sourceMappingURL 子资源
        assert by_raw["chunk-7788.js"][0]["resolved_url"].endswith("/chunk-7788.js")
        assert by_raw["app.js.map"][0]["status"] == STATUS_SUCCESS
        assert by_raw["app.js.map"][0]["resolved_url"].endswith("/static/js/app.js.map")

        # CSS url(...) 子资源（相对路径按 CSS 自身地址解析）
        assert by_raw["../fonts/a.woff2"][0]["status"] == STATUS_SUCCESS
        assert by_raw["../fonts/a.woff2"][0]["resolved_url"].endswith("/static/fonts/a.woff2")

        # 成功资源确实落盘，路径与清单一致
        for item in resources:
            if item["status"] == STATUS_SUCCESS:
                assert (tmp_path / "site" / item["local_path"]).is_file()
        assert (tmp_path / "site" / "index.html").is_file()

        # 报告可序列化为 JSON
        json.dumps(doc, ensure_ascii=False)

        # 主入口失败：返回 False，且不产生资源清单或成功结论
        fail_dumper = ProjectDumper(output_dir=str(tmp_path / "fail"), timeout=1)
        fail_report = fail_dumper.dump_with_report(f"http://127.0.0.1:{port}/nope")
        assert fail_report.success is False
        assert fail_report.entry_html_saved is False
        assert fail_report.resources == []
        assert "404" in fail_report.error
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_dump_resource_report(Path(tmp))
    print("test_project_dumper_report: PASS")
