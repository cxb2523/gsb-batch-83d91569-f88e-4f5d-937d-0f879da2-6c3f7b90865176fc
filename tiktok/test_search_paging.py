"""Offline tests for the search paging contract — no network, no exits.

The upstream is faked at `search.api`, i.e. exactly the seam every search
endpoint calls through, so the assertions cover the server-side loop, the
per-page exit country and the stop reasons, plus the HTTP mapping through
routes.py (a local WSGI call, no server process).

    python -m pytest tiktok/test_search_paging.py -q
"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bottle  # noqa: E402
import pytest  # noqa: E402

import routes  # noqa: E402,F401  (mounts the routes on bottle's default app)
from scraper_errors import UpstreamError  # noqa: E402
from schema_fields import load_query  # noqa: E402
from tiktok import schemas, search  # noqa: E402

US_ID = "20261005135356D987AA8C89367BE6C0E1"


def video_row(name):
    return {"id": name, "author": {"uniqueId": "nasa", "id": "1"}}


def user_row(name):
    return {"user_info": {"unique_id": name, "id": "1"}}


class FakeUpstream:
    """Answers one page per call, by offset. `pages` maps offset ->
    (payload, country) or an exception to raise."""

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def __call__(self, path, params, *, countries, boot=False, used=None, **kwargs):
        self.calls.append({"path": path, "params": dict(params), "countries": countries})
        offset = int(params.get("offset", params.get("cursor", 0)) or 0)
        answer = self.pages[offset]
        if isinstance(answer, Exception):
            raise answer
        payload, country = answer
        if used is not None:
            used["country"] = country
        return payload


def install(monkeypatch, upstream):
    monkeypatch.setattr(search, "api", upstream)
    return upstream


def video_page(has_more, cursor, rows, logid=US_ID):
    return {"status_code": 0, "has_more": has_more, "cursor": cursor,
            "item_list": [video_row(row) for row in rows], "log_pb": {"impr_id": logid}}


# ---- endpoint-level contract -------------------------------------------------------------

def test_two_pages_then_has_more_false(monkeypatch):
    answers = {0: (video_page(1, 20, ["a1", "a2"]), "us"),
               20: (video_page(0, None, ["b1"]), "us")}
    upstream = install(monkeypatch, FakeUpstream(answers))
    result = search.search_videos("nasa", country="gb")
    assert result["video_count"] == 3 and [v["id"] for v in result["videos"]] == ["a1", "a2", "b1"]
    assert result["pages"] == [
        {"page": 1, "count": 2, "country": "US", "next_cursor": f"20.{US_ID}"},
        {"page": 2, "count": 1, "country": "US", "next_cursor": None},
    ]
    assert result["stop"] == {"reason": "done", "message": "upstream reported has_more false",
                              "last_page": 2}
    assert result["next_cursor"] is None and result["has_more"] is False
    # the caller's country is asked first, the US exit falls back
    assert upstream.calls[0]["countries"] == ("gb", "us")
    # page 2 carries the first page's search id, exactly as the cursor encoded it
    assert upstream.calls[1]["params"]["offset"] == 20
    assert upstream.calls[1]["params"]["search_id"] == US_ID


def test_first_page_stalls_when_has_more_but_no_cursor(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(1, None, ["a1"]), "us")}))
    result = search.search_videos("nasa")
    assert result["video_count"] == 1
    assert len(result["pages"]) == 1
    assert result["pages"][0]["next_cursor"] is None
    assert result["stop"]["reason"] == "cursor_stalled"
    assert result["stop"]["last_page"] == 1
    assert result["stop"]["message"]
    assert result["has_more"] is False and result["next_cursor"] is None


def test_stall_when_next_cursor_repeats_the_page(monkeypatch):
    answers = {0: (video_page(1, 0, ["a1"]), "us")}
    install(monkeypatch, FakeUpstream(answers))
    result = search.search_videos("nasa")
    assert result["stop"]["reason"] == "cursor_stalled"
    assert len(result["pages"]) == 1


def test_second_page_upstream_error_keeps_first_page(monkeypatch):
    answers = {0: (video_page(1, 20, ["a1", "a2"]), "us"),
               20: UpstreamError("HTTP 502 on /api/search/item/full/")}
    install(monkeypatch, FakeUpstream(answers))
    result = search.search_videos("nasa")
    assert result["video_count"] == 2 and [v["id"] for v in result["videos"]] == ["a1", "a2"]
    assert len(result["pages"]) == 1
    assert result["stop"]["reason"] == "upstream_error"
    assert result["stop"]["last_page"] == 1
    assert "HTTP 502" in result["stop"]["message"]


def test_users_search_pages_stay_on_the_eu_exit_and_skip_empty_country(monkeypatch):
    first = {"status_code": 0, "has_more": 1, "cursor": 10,
             "user_list": [user_row("nasa")], "rid": "RID"}
    second = {"status_code": 0, "has_more": 0, "user_list": [user_row("esa")]}
    upstream = install(monkeypatch, FakeUpstream({0: (first, "de"), 10: (second, "de")}))
    result = search.search_users("nasa")
    assert [user["username"] for user in result["users"]] == ["nasa", "esa"]
    assert [page["country"] for page in result["pages"]] == ["DE", "DE"]
    assert [page["next_cursor"] for page in result["pages"]] == ["10.RID", None]
    assert result["stop"]["reason"] == "done"
    assert all(call["countries"] == ("de",) for call in upstream.calls)


def test_max_pages_caps_collection_and_keeps_the_cursor(monkeypatch):
    answers = {0: (video_page(1, 20, ["a1"]), "us"),
               20: (video_page(1, 40, ["b1"]), "us"),
               40: (video_page(0, None, ["c1"]), "us")}
    install(monkeypatch, FakeUpstream(answers))
    result = search.search_videos("nasa", max_pages=2)
    assert result["video_count"] == 2 and [page["page"] for page in result["pages"]] == [1, 2]
    assert result["stop"]["reason"] == "done" and result["stop"]["last_page"] == 2
    assert result["next_cursor"] == f"40.{US_ID}" and result["has_more"] is True


def test_top_pages_merge_videos_and_users(monkeypatch):
    def top_page(has_more, cursor):
        return {"status_code": 0, "has_more": has_more, "cursor": cursor, "log_pb": {"impr_id": US_ID},
                "data": [{"type": 1, "item": {"id": "v1", "author": {"uniqueId": "nasa"}}},
                         {"type": 4, "user_list": [user_row("esa")]}]}

    install(monkeypatch, FakeUpstream({0: (top_page(1, 12), "de"), 12: (top_page(0, None), "de")}))
    result = search.search_top("nasa")
    assert result["video_count"] == 2 and result["user_count"] == 2
    assert [page["count"] for page in result["pages"]] == [2, 2]
    assert result["stop"]["reason"] == "done"


def test_empty_dataset_still_reports_done(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(0, None, []), "us")}))
    result = search.search_videos("nothing")
    assert result["video_count"] == 0 and result["pages"][0]["count"] == 0
    assert result["stop"]["reason"] == "done"


def test_max_pages_out_of_range_is_rejected_by_the_schema():
    for bad in ("0", "11", "-1", "abc"):
        data, error = load_query(schemas.VideoSearchSchema, {"query": "x", "max_pages": bad})
        assert data is None and error["error"].startswith("Invalid parameters")
    for schema in (schemas.UserSearchSchema, schemas.SearchSchema):
        for bad in ("0", "11"):
            assert load_query(schema, {"query": "x", "max_pages": bad})[1] is not None
    data, error = load_query(schemas.VideoSearchSchema, {"query": "x", "max_pages": "10"})
    assert error is None and data["max_pages"] == 10
    assert load_query(schemas.VideoSearchSchema, {"query": "x"})[0]["max_pages"] == 3


# ---- HTTP mapping ------------------------------------------------------------------------

def wsgi_get(path, query_string):
    """Call routes' bottle app directly (no server) -> (status, JSON body)."""
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = int(status.split()[0])

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query_string,
        "SERVER_NAME": "localhost",
        "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.version": (1, 0),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": io.StringIO(),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    body = b"".join(bottle.default_app()(environ, start_response))
    return captured["status"], json.loads(body.decode("utf-8"))


def test_http_cursor_stalled_is_200(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(1, None, ["a1"]), "us")}))
    status, body = wsgi_get("/search/videos", "query=nasa")
    assert status == 200
    assert len(body["pages"]) == 1 and body["stop"]["reason"] == "cursor_stalled"


def test_http_upstream_error_is_200_with_kept_data(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(1, 20, ["a1"]), "us"),
                                       20: UpstreamError("upstream exhausted retries")}))
    status, body = wsgi_get("/search/videos", "query=nasa")
    assert status == 200
    assert body["video_count"] == 1 and body["stop"]["reason"] == "upstream_error"


def test_http_bad_cursor_is_400(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(0, None, ["a1"]), "us")}))
    for cursor in ("notacursor", "20.short"):
        status, body = wsgi_get("/search/videos", f"query=nasa&cursor={cursor}")
        assert status == 400
        assert body["stop"]["reason"] == "bad_cursor" and body["pages"] == []


def test_http_bad_cursor_from_the_endpoint_is_400():
    """main.py calls the endpoint functions directly, bypassing the schema."""
    with pytest.raises(search.BadCursorExhausted) as caught:
        search.search_videos("nasa", cursor="notacursor")
    assert caught.value.body["stop"]["reason"] == "bad_cursor"
    assert "Invalid cursor" in caught.value.body["error"]


def test_http_max_pages_out_of_range_is_400(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(0, None, ["a1"]), "us")}))
    for bad in ("0", "11"):
        status, body = wsgi_get("/search/videos", f"query=nasa&max_pages={bad}")
        assert status == 400 and "max_pages" in body["error"]
    status, body = wsgi_get("/search/users", "query=nasa&max_pages=11")
    assert status == 400 and "max_pages" in body["error"]


def test_http_two_pages_then_done(monkeypatch):
    install(monkeypatch, FakeUpstream({0: (video_page(1, 20, ["a1"]), "us"),
                                       20: (video_page(0, None, ["b1"]), "us")}))
    status, body = wsgi_get("/search/videos", "query=nasa")
    assert status == 200 and body["stop"]["reason"] == "done"
    assert [page["next_cursor"] for page in body["pages"]] == [f"20.{US_ID}", None]
