import re
import subprocess
from pathlib import Path

import httpx
import pytest

from jevfetch import web

PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"


def serve(monkeypatch, body: bytes, content_type: str | None, status: int = 200, final_url: str | None = None):
    headers = {"Content-Type": content_type} if content_type else {}

    def fake_get(url, **kwargs):
        return httpx.Response(status, content=body, headers=headers, request=httpx.Request("GET", final_url or url))

    monkeypatch.setattr(web.httpx, "get", fake_get)


def test_fetch_sends_identifying_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, headers, follow_redirects, timeout):
        seen.update(headers)
        return httpx.Response(200, text="<html></html>", request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "get", fake_get)
    assert web.fetch("https://example.com") == "<html></html>"
    assert "jevfetch/" in seen["User-Agent"]


def test_fetch_page_returns_the_final_url_and_the_media_type(monkeypatch):
    def fake_get(url, **kwargs):
        return httpx.Response(
            200,
            text="<html></html>",
            headers={"Content-Type": "Text/HTML; charset=utf-8"},
            request=httpx.Request("GET", "https://example.com/final"),
        )

    monkeypatch.setattr(web.httpx, "get", fake_get)
    assert web.fetch_page("https://example.com") == ("<html></html>", "https://example.com/final", "text/html")


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html; charset=utf-8",
        "Text/HTML; Charset=UTF-8",
        "text/html ; charset=utf-8",
        "application/xhtml+xml",
        "text/plain",
        "text/markdown",
        "text/x-markdown",
        None,
        "application/octet-stream",
        "binary/octet-stream",
    ],
)
def test_html_and_text_bodies_are_returned(monkeypatch, content_type):
    serve(monkeypatch, b"# Title\n\nSome text.", content_type)
    assert web.fetch("https://example.com") == "# Title\n\nSome text."


def test_repeated_content_type_header_uses_the_last_one(monkeypatch):
    def fake_get(url, **kwargs):
        headers = [("Content-Type", "application/json"), ("Content-Type", "text/html; charset=utf-8")]
        return httpx.Response(200, content=b"<p>ok</p>", headers=headers, request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "get", fake_get)
    assert web.fetch("https://example.com") == "<p>ok</p>"


def test_empty_unlabeled_body_is_returned_empty(monkeypatch):
    serve(monkeypatch, b"", None)
    assert web.fetch("https://example.com") == ""


def test_unlabeled_text_with_a_few_undecodable_bytes_is_returned(monkeypatch):
    serve(monkeypatch, b"<p>The caf\xe9 opened in 1990 and still serves the same menu.</p>", None)
    assert web.fetch("https://example.com").startswith("<p>The caf")


def test_pdf_signature_counts_only_at_the_start(monkeypatch):
    serve(monkeypatch, b"A PDF file starts with %PDF- and a version number.", "text/plain")
    assert web.fetch("https://example.com").startswith("A PDF file")


def test_error_status_is_reported_before_content_type(monkeypatch):
    serve(monkeypatch, b"{}", "application/json", status=404)
    with pytest.raises(httpx.HTTPStatusError):
        web.fetch("https://example.com")


def test_declared_html_is_not_sniffed_for_undecodable_bytes(monkeypatch):
    serve(monkeypatch, "<p>한국어 페이지</p>".encode("euc-kr"), "text/html")
    assert web.fetch("https://example.com").startswith("<p>")


@pytest.mark.parametrize(
    "content_type",
    [
        "application/json",
        "application/ld+json",
        "application/xml",
        "text/xml",
        "application/rss+xml",
        "application/atom+xml",
        "text/csv",
        "application/javascript",
        "application/yaml",
    ],
)
def test_text_like_content_types_are_returned(monkeypatch, content_type):
    serve(monkeypatch, b'{"version": "1.0"}', content_type)
    assert web.fetch("https://example.com") == '{"version": "1.0"}'


@pytest.mark.parametrize("content_type", ["application/pdf", "image/png", "image/svg+xml", "application/zip"])
def test_other_content_types_are_refused_by_name(monkeypatch, content_type):
    serve(monkeypatch, b"{}", content_type)
    with pytest.raises(web.UnsupportedContent, match=re.escape(content_type)):
        web.fetch("https://example.com")


@pytest.mark.parametrize("content_type", [None, "application/octet-stream", "text/plain"])
def test_pdf_is_recognized_by_its_signature(monkeypatch, content_type):
    serve(monkeypatch, PDF, content_type)
    with pytest.raises(web.UnsupportedContent, match="application/pdf"):
        web.fetch("https://example.com")


@pytest.mark.parametrize("content_type", [None, "application/octet-stream"])
@pytest.mark.parametrize(
    "body", [bytes(range(256)) * 8, b"IDX\x00\x00\x00\x10" * 200], ids=["invalid-utf8", "nul-heavy"]
)
def test_unlabeled_binary_is_refused(monkeypatch, content_type, body):
    serve(monkeypatch, body, content_type)
    with pytest.raises(web.UnsupportedContent, match="binary"):
        web.fetch("https://example.com")


def test_chrome_from_environment(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"
    chrome.write_text("")
    monkeypatch.setenv("JEVFETCH_CHROME", str(chrome))
    assert web.find_chrome() == str(chrome)


def test_rendering_without_chrome_or_after_timeout_returns_none(monkeypatch):
    monkeypatch.setattr(web, "find_chrome", lambda: None)
    assert web.fetch_rendered("https://example.com") is None

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("chrome", 1)

    monkeypatch.setattr(web, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(web.subprocess, "run", timeout)
    assert web.fetch_rendered("https://example.com") is None


# The fetch result object (fetch_page_result), exercised on stub responses only.


@pytest.fixture
def files_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path))
    return tmp_path


def test_a_text_page_is_a_successful_result_with_the_final_url_and_type(monkeypatch):
    serve(
        monkeypatch,
        b"<html><body><p>The policy took effect on 1 January.</p></body></html>",
        "Text/HTML; charset=utf-8",
        final_url="https://example.com/moved/",
    )
    res = web.fetch_page_result("https://example.com/start")
    assert res.ok and res.success and res.error_kind == "" and res.error == ""
    assert res.url == res.final_url == "https://example.com/moved/"
    assert res.media_type == "text/html" and res.kind == "text/html"
    assert res.text.startswith("<html>") and res.saved == ""
    assert res.to_dict() == {
        "url": "https://example.com/moved/",
        "media_type": "text/html",
        "kind": "text/html",
        "ok": True,
        "error_kind": "",
        "error": "",
        "status_code": 200,
        "text": res.text,
        "saved": "",
        "render_status": "",
        "render_error": "",
    }


def test_a_pdf_signature_wins_over_a_declared_text_type(monkeypatch, files_dir):
    serve(monkeypatch, PDF, "text/plain")
    res = web.fetch_page_result("https://example.com/download")
    assert not res.ok and res.error_kind == "unsupported_content" and res.kind == "application/pdf"
    assert res.text == "" and "application/pdf" in res.error
    saved = Path(res.saved)
    assert saved.exists() and saved.parent == files_dir and saved.suffix == ".pdf"
    assert saved.read_bytes() == PDF


def test_an_unlabeled_binary_body_is_a_saved_file(monkeypatch, files_dir):
    serve(monkeypatch, b"IDX\x00\x00\x00\x10" * 200, None)
    res = web.fetch_page_result("https://example.com/blob")
    assert not res.ok and res.error_kind == "unsupported_content" and "binary" in res.error
    saved = Path(res.saved)
    assert saved.exists() and saved.parent == files_dir and saved.suffix == ".bin"
    assert saved.read_bytes() == b"IDX\x00\x00\x00\x10" * 200


def test_a_declared_binary_type_is_a_saved_file_with_its_extension(monkeypatch, files_dir):
    serve(monkeypatch, b"PK\x03\x04" + b"\x00" * 100, "application/zip")
    res = web.fetch_page_result("https://example.com/a.zip")
    assert res.error_kind == "unsupported_content" and res.kind == "application/zip"
    assert Path(res.saved).suffix == ".zip" and Path(res.saved).parent == files_dir


def test_a_404_is_an_http_error_before_any_content_type_decision(monkeypatch, files_dir):
    serve(monkeypatch, b'{"error": "gone"}', "application/json", status=404)
    res = web.fetch_page_result("https://example.com/missing")
    assert not res.ok and res.error_kind == "http_error" and res.status_code == 404
    assert res.media_type == "application/json" and res.text == "" and res.saved == ""
    assert "404" in res.error and not list(files_dir.iterdir())


def test_a_network_error_keeps_the_requested_url(monkeypatch):
    def fail(url, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(web.httpx, "get", fail)
    res = web.fetch_page_result("https://example.com/start")
    assert not res.ok and res.error_kind == "network_error" and res.url == "https://example.com/start"
    assert "ConnectError" in res.error and res.saved == "" and res.status_code == 0


def test_an_empty_body_is_an_empty_content_result(monkeypatch):
    serve(monkeypatch, b"", "text/html")
    res = web.fetch_page_result("https://example.com/blank")
    assert not res.ok and res.error_kind == "empty_content" and res.media_type == "text/html"
    assert res.text == "" and res.saved == "" and "empty" in res.error


def test_a_file_that_cannot_be_saved_is_unsupported_without_a_path(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(blocker))
    serve(monkeypatch, PDF, "application/pdf")
    res = web.fetch_page_result("https://example.com/a.pdf")
    assert res.error_kind == "unsupported_content" and res.saved == "" and "could not save" in res.error


def test_rendering_without_chrome_is_a_failed_render_not_a_success(monkeypatch):
    monkeypatch.setattr(web, "find_chrome", lambda: None)
    res = web.fetch_rendered_result("https://example.com")
    assert not res.ok and res.dom == "" and "Chrome" in res.error


def test_rendering_after_timeout_is_a_failed_render_not_a_success(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("chrome", 60)

    monkeypatch.setattr(web, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(web.subprocess, "run", timeout)
    res = web.fetch_rendered_result("https://example.com")
    assert not res.ok and res.dom == "" and "timed out" in res.error


def test_a_rendered_page_is_a_successful_render(monkeypatch):
    monkeypatch.setattr(web, "find_chrome", lambda: "/bin/chrome")
    monkeypatch.setattr(
        web.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="<html><body><p>ready</p></body></html>", stderr=""),
    )
    res = web.fetch_rendered_result("https://example.com")
    assert res.ok and res.error == "" and res.dom.startswith("<html>")
    assert web.fetch_rendered("https://example.com") == res.dom
