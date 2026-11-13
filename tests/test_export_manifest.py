# SPDX-License-Identifier: AGPL-3.0-only
# -*- coding: utf-8 -*-
"""Tests for the per-resource export manifest (images + videos).

These tests use locally built HTML and mocked HTTP responses only: no network
access, no WeChat credentials, no real export directory.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import wx_article_saver as wxas

ARTICLE_URL = "https://mp.weixin.qq.com/s/demo-article"

ARTICLE_HTML = """<!doctype html>
<html><head><meta charset="utf-8">
<meta property="og:title" content="清单测试文章">
</head><body>
<div id="js_content">
  <h1>正文标题</h1>
  <p>这是一段足够长的正文，用来满足正文识别的最小长度要求。</p>
  <img data-src="https://mmbiz.qpic.cn/mmbiz_jpg/demo/640" src="https://mmbiz.qpic.cn/mmbiz_jpg/demo/640">
  <img data-src="https://evil.example.com/tracker.jpg" src="https://evil.example.com/tracker.jpg">
  <img data-src="https://img.mmbiz.qpic.cn/boom.jpg" src="https://img.mmbiz.qpic.cn/boom.jpg">
  <video data-video-url="https://mpvideo.qpic.cn/encrypted.m3u8"></video>
</div>
</body></html>
"""


def _release_tempdir(tmp):
    """Let Windows release handles before removing the temp export tree."""
    import gc

    gc.collect()
    for _ in range(3):
        try:
            tmp.cleanup()
            return
        except PermissionError:
            import time

            time.sleep(0.05)


def fake_image_response(content=b"\x89PNG\r\n\x1a\n" + b"0" * 600, status=200):
    resp = Mock()
    resp.status_code = status
    resp.content = content
    resp.headers = {"Content-Type": "image/png"}
    return resp


def fake_hls_response(text, status=200):
    resp = Mock()
    resp.status_code = status
    resp.text = text
    resp.headers = {"Content-Type": "application/vnd.apple.mpegurl"}
    return resp


def fake_direct_video_response(payload=b"\x00\x00\x00\x18ftypmp42" + b"1" * 5000, status=200):
    resp = Mock()
    resp.status_code = status
    resp.headers = {"Content-Type": "video/mp4"}
    resp.url = "https://cdn.example.com/direct.mp4"
    resp.iter_content = lambda chunk_size=1024: iter([payload])
    resp.close = Mock()
    return resp


ENCRYPTED_HLS = """#EXTM3U
#EXT-X-KEY:METHOD=AES-128,URI="https://keys.example.com/k1"
#EXTINF:4.0,
https://cdn.example.com/seg0.ts
"""


class ExportManifestTests(unittest.TestCase):
    """Each required scenario end-to-end through save_article."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._root_patch = patch.object(wxas, "EXPORT_ROOT", self.root / "exports")
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.addCleanup(_release_tempdir, self.tmp)

    def export(self, captured_media=None):
        return wxas.save_article(ARTICLE_URL, ARTICLE_HTML, captured_media or [])

    def read_meta(self, folder):
        return json.loads((folder / "meta.json").read_text(encoding="utf-8"))

    def test_image_saved_whitelist_skipped_throw_failed_and_encrypted_hls_skipped(self):
        def fake_get(url, **kwargs):
            if "img.mmbiz.qpic.cn" in url:
                raise wxas.requests.ConnectionError("simulated connection reset")
            if "mmbiz.qpic.cn" in url:
                return fake_image_response()
            if "encrypted.m3u8" in url:
                return fake_hls_response(ENCRYPTED_HLS)
            raise AssertionError(f"unexpected URL fetched: {url}")

        with patch.object(wxas.requests, "get", side_effect=fake_get):
            folder, title, resources = self.export()

        self.assertEqual(title, "清单测试文章")
        meta = self.read_meta(folder)

        # Directory structure is preserved.
        for name in (
            "article.md",
            "article.html",
            "article.txt",
            "raw_wechat_response.html",
            "meta.json",
        ):
            self.assertTrue((folder / name).is_file(), name)
        self.assertFalse((folder / "videos").exists())

        manifest = meta["resources"]
        self.assertEqual(len(manifest["images"]), 3)
        self.assertEqual(len(manifest["videos"]), 1)
        for row in manifest["images"] + manifest["videos"]:
            self.assertIn(row["result"], ("saved", "skipped", "failed"))
            self.assertIn("reason", row)
            self.assertTrue(row["reason"])
            if row["result"] == "saved":
                self.assertTrue(row["local_path"].startswith(("images/", "videos/")))

        # 1) Normally saved image.
        saved = next(
            r for r in manifest["images"]
            if r["url"] == "https://mmbiz.qpic.cn/mmbiz_jpg/demo/640"
        )
        self.assertEqual([p.name for p in (folder / "images").iterdir()],
                         [Path(saved["local_path"]).name])
        self.assertEqual(saved["result"], "saved")
        self.assertEqual(saved["reason"], "ok")
        local = saved["local_path"]
        self.assertTrue(local.startswith("images/"))
        self.assertTrue((folder / local).is_file())
        self.assertGreater((folder / local).stat().st_size, 500)

        # 2) Off-whitelist domain is skipped, not failed.
        skipped = next(
            r for r in manifest["images"]
            if r["url"] == "https://evil.example.com/tracker.jpg"
        )
        self.assertEqual(skipped["result"], "skipped")
        self.assertEqual(skipped["reason"], "domain_not_allowed")
        self.assertNotIn("local_path", skipped)

        # 3) Download exception is recorded as failed.
        failed = next(
            r for r in manifest["images"]
            if r["url"] == "https://img.mmbiz.qpic.cn/boom.jpg"
        )
        self.assertEqual(failed["result"], "failed")
        self.assertEqual(failed["reason"], "download_error")

        # 4) Encrypted HLS is skipped (link preserved, no decrypt attempt).
        hls = manifest["videos"][0]
        self.assertEqual(hls["url"], "https://mpvideo.qpic.cn/encrypted.m3u8")
        self.assertEqual(hls["result"], "skipped")
        self.assertEqual(hls["reason"], "encrypted_hls")

        # Counts agree with the manifest rows.
        counts = manifest["counts"]
        self.assertEqual(counts["images"], {"saved": 1, "skipped": 1, "failed": 1})
        self.assertEqual(counts["videos"], {"saved": 0, "skipped": 1, "failed": 0})
        self.assertEqual(counts["total"], {"saved": 1, "skipped": 2, "failed": 1})
        self.assertEqual(counts["total"]["saved"], counts["saved"])
        for kind in ("images", "videos"):
            for result in ("saved", "skipped", "failed"):
                rows = [r for r in manifest[kind] if r["result"] == result]
                self.assertEqual(len(rows), counts[kind][result])

        # save_article's third return value is the same manifest.
        self.assertEqual(resources["counts"], counts)

    def test_all_media_failing_still_exports_with_zero_saved(self):
        def fake_get(url, **kwargs):
            if "mmbiz.qpic.cn" in url:
                raise wxas.requests.Timeout("simulated timeout")
            if "encrypted.m3u8" in url:
                raise wxas.requests.ConnectionError("simulated hls failure")
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(wxas.requests, "get", side_effect=fake_get):
            folder, title, resources = self.export()

        meta = self.read_meta(folder)
        counts = meta["resources"]["counts"]

        self.assertGreater(len(meta["resources"]["images"]), 0)
        self.assertEqual(counts["total"]["saved"], 0)
        self.assertEqual(
            counts["total"]["failed"],
            len(meta["resources"]["images"]) + len(meta["resources"]["videos"])
            - counts["total"]["skipped"],
        )
        # The article body itself is still exported.
        self.assertTrue((folder / "article.md").is_file())
        self.assertTrue((folder / "article.txt").is_file())
        self.assertFalse((folder / "images").exists())
        self.assertFalse((folder / "videos").exists())

        timeout_row = next(
            r for r in meta["resources"]["images"]
            if r["url"] == "https://mmbiz.qpic.cn/mmbiz_jpg/demo/640"
        )
        self.assertEqual(timeout_row["result"], "failed")
        self.assertEqual(timeout_row["reason"], "request_timeout")

    def test_manifest_never_persists_credentials(self):
        secret = "super-secret-pass-ticket"

        def fake_get(url, **kwargs):
            if "mmbiz.qpic.cn" in url:
                return fake_image_response()
            if "cdn.example.com" in url:
                return fake_hls_response(ENCRYPTED_HLS)
            raise AssertionError(f"unexpected URL: {url}")

        captured = [{
            "url": f"https://mpvideo.qpic.cn/play.m3u8?pass_ticket={secret}&Authorization=Bearer+{secret}",
            "headers": {
                "Cookie": f"pass_ticket={secret}",
                "Authorization": f"Bearer {secret}",
                "Referer": ARTICLE_URL,
            },
        }]

        with patch.object(wxas.requests, "get", side_effect=fake_get):
            folder, title, resources = self.export(captured_media=captured)

        raw = (folder / "meta.json").read_text(encoding="utf-8")
        self.assertNotIn(secret, raw)
        self.assertNotIn("Bearer", raw)
        for row in resources["images"] + resources["videos"]:
            self.assertNotIn("headers", row)
            self.assertNotIn("Cookie", json.dumps(row))
            self.assertNotIn("Bearer", json.dumps(row))
        hls_rows = [r for r in resources["videos"] if "play.m3u8" in r["url"]]
        self.assertTrue(hls_rows)
        self.assertIn("REDACTED", hls_rows[0]["url"])

    def test_video_downloaded_to_videos_dir(self):
        captured = [{
            "url": "https://cdn.example.com/direct.mp4",
            "headers": {"Referer": ARTICLE_URL},
        }]

        def fake_get(url, **kwargs):
            if url.endswith("direct.mp4"):
                return fake_direct_video_response()
            if "encrypted.m3u8" in url:
                return fake_hls_response(ENCRYPTED_HLS)
            raise AssertionError(f"unexpected URL: {url}")

        with patch.object(wxas.requests, "get", side_effect=fake_get):
            folder, title, resources = self.export(captured_media=captured)

        video_rows = [r for r in resources["videos"] if r["url"].endswith("direct.mp4")]
        self.assertEqual(len(video_rows), 1)
        row = video_rows[0]
        self.assertEqual(row["result"], "saved")
        self.assertEqual(row["reason"], "ok")
        self.assertTrue(row["local_path"].startswith("videos/"))
        self.assertTrue((folder / row["local_path"]).is_file())
        self.assertTrue((folder / row["local_path"]).stat().st_size > 1024)
        meta = self.read_meta(folder)
        self.assertEqual(meta["resources"]["counts"]["videos"]["saved"], 1)

    def test_video_candidate_cap_marks_overflow_as_skipped(self):
        def fake_get(url, **kwargs):
            if "cdn.example.com" in url:
                return fake_hls_response(ENCRYPTED_HLS)
            raise AssertionError(f"unexpected URL: {url}")

        captured = [
            {"url": f"https://cdn.example.com/v{i}.m3u8", "headers": {}}
            for i in range(wxas.MAX_VIDEOS_PER_EXPORT + 2)
        ]

        with patch.object(wxas.requests, "get", side_effect=fake_get):
            folder, title, resources = self.export(captured_media=captured)

        # 14 captured + 1 embed, capped at 12 => 3 overflow rows.
        expected_overflow = len(captured) + 1 - wxas.MAX_VIDEOS_PER_EXPORT
        overflow = [
            r for r in resources["videos"] if r["reason"] == "candidate_limit_exceeded"
        ]
        self.assertEqual(len(overflow), expected_overflow)
        self.assertTrue(all(r["result"] == "skipped" for r in overflow))
        self.assertEqual(len(resources["videos"]), len(captured) + 1)
        self.assertEqual(
            resources["counts"]["videos"]["skipped"],
            wxas.MAX_VIDEOS_PER_EXPORT + expected_overflow,
        )


class ExportResponseTests(unittest.TestCase):
    """The addon's response body must report manifest counts, not a bare success."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._root_patch = patch.object(wxas, "EXPORT_ROOT", self.root / "exports")
        self._root_patch.start()
        self.addCleanup(self._root_patch.stop)
        self.addCleanup(_release_tempdir, self.tmp)
        self._cache_patch = patch.dict(wxas.ARTICLE_CACHE, clear=True)
        self._cache_patch.start()
        self.addCleanup(self._cache_patch.stop)

    def _run_addon(self, fake_get):
        from types import SimpleNamespace

        token = "test-token"
        wxas.ARTICLE_CACHE[token] = {
            "url": ARTICLE_URL,
            "html": ARTICLE_HTML,
            "created": wxas.time.time(),
            "media": [],
        }

        class FakeRequest:
            method = "POST"
            pretty_host = "mp.weixin.qq.com"
            pretty_url = f"https://mp.weixin.qq.com{wxas.SAVE_PATH}?id={token}"
            headers = {}

            @staticmethod
            def get_text(strict=False):
                return ARTICLE_HTML

        flow = SimpleNamespace(request=FakeRequest(), response=None)
        fake_http = SimpleNamespace(
            Response=SimpleNamespace(
                make=lambda status, body, headers: SimpleNamespace(
                    status_code=status, body=body, headers=headers
                )
            )
        )
        with patch.object(wxas, "http", fake_http):
            with patch.object(wxas.requests, "get", side_effect=fake_get):
                wxas.WxArticleSaver().request(flow)
        return flow.response

    def test_all_media_failing_still_returns_success_with_zero_saved(self):
        def fake_get(url, **kwargs):
            raise wxas.requests.Timeout("simulated timeout")

        response = self._run_addon(fake_get)

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("已导出", body)
        self.assertIn("资源合计 已保存 0", body)
        self.assertIn("失败", body)

    def test_response_reports_saved_and_skipped_counts(self):
        def fake_get(url, **kwargs):
            if "img.mmbiz.qpic.cn" in url:
                raise wxas.requests.ConnectionError("simulated failure")
            if "mmbiz.qpic.cn" in url:
                return fake_image_response()
            if "encrypted.m3u8" in url:
                return fake_hls_response(ENCRYPTED_HLS)
            raise AssertionError(f"unexpected URL: {url}")

        response = self._run_addon(fake_get)

        self.assertEqual(response.status_code, 200)
        body = response.body.decode("utf-8")
        self.assertIn("图片 已保存 1、跳过 1、失败 1", body)
        self.assertIn("视频 已保存 0、跳过 1、失败 0", body)
        self.assertIn("资源合计 已保存 1、跳过 2、失败 1", body)


class ManifestHelperTests(unittest.TestCase):
    def test_count_results_ignores_unknown_results(self):
        entries = [
            {"result": "saved"}, {"result": "skipped"},
            {"result": "failed"}, {"result": "bogus"},
        ]
        self.assertEqual(
            wxas.count_results(entries),
            {"saved": 1, "skipped": 1, "failed": 1},
        )

    def test_format_export_summary_reports_all_three_counts(self):
        resources = wxas.build_resource_manifest(
            [{"result": "saved"}, {"result": "skipped"}, {"result": "failed"}],
            [{"result": "skipped"}],
        )
        summary = wxas.format_export_summary("标题", resources)
        self.assertIn("已导出：标题", summary)
        self.assertIn("图片 已保存 1、跳过 1、失败 1", summary)
        self.assertIn("视频 已保存 0、跳过 1、失败 0", summary)
        self.assertIn("资源合计 已保存 1、跳过 2、失败 1", summary)

    def test_summary_all_failed_is_zero_saved(self):
        resources = wxas.build_resource_manifest(
            [{"result": "failed"}, {"result": "failed"}], []
        )
        summary = wxas.format_export_summary("标题", resources)
        self.assertIn("资源合计 已保存 0、跳过 0、失败 2", summary)

    def test_sanitize_url_redacts_sensitive_query_params(self):
        url = "https://cdn.example.com/a.mp4?pass_ticket=abc&sig=def&x=1"
        safe = wxas.sanitize_url_for_manifest(url)
        self.assertNotIn("abc", safe)
        self.assertNotIn("def", safe)
        self.assertIn("x=1", safe)

    def test_sanitize_url_strips_userinfo(self):
        safe = wxas.sanitize_url_for_manifest("https://user:pw@cdn.example.com/a.mp4")
        self.assertNotIn("user", safe)
        self.assertNotIn("pw", safe)
        self.assertIn("cdn.example.com", safe)

    def test_button_markup_shows_export_summary(self):
        markup = wxas.button_markup("token-123")
        self.assertIn("wxas-video-hint", markup)
        self.assertIn("hint.textContent = msg", markup)
        self.assertIn("'text/plain;charset=UTF-8'", markup)

    def test_redacts_credentials_in_error_text(self):
        text = "failed: pass_ticket=abc123 Cookie: session=xyz"
        redacted = wxas.redact_credentials_text(text)
        self.assertNotIn("abc123", redacted)
        self.assertNotIn("xyz", redacted)
        self.assertIn("pass_ticket", redacted)


if __name__ == "__main__":
    unittest.main()
