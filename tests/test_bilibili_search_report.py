# -*- coding: utf-8 -*-
"""B站采集链路 · 离线验收测试。

用本地自造响应替代真实网络，不发起任何外部请求：
  1) 关键词A：第一次被风控拦截，第二次返回“过期视频 + 缺发布时间 + 标题清洗为空
     + 正常视频”的混合响应；
  2) 关键词B：始终被风控拦截（重试耗尽）；
  3) 关键词C：返回空结果。

检查：
  - 三个关键词状态各不相同（ok / blocked / empty），尝试次数正确；
  - 各条丢弃视频的丢弃原因正确；
  - 结论与原始数据一起落盘，原始数据仍是旧格式；
  - 单个关键词失败不影响其余关键词，全流程仍能生成指南。
"""
import json
import time
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _nav_payload():
    # 真实 nav 的 wbi key 是 32 位哈希文件名，置换表按 64 位取 mixin key
    return {"code": 0, "data": {"wbi_img": {
        "img_url": "https://i0.hdslb.com/bfs/wbi/"
                   "7cd0849423c23e5b3a9f2d8c1e6b4a70.png",
        "sub_url": "https://i0.hdslb.com/bfs/wbi/"
                   "1b8b0f3c5e1d2c4a9f7e6d5c4b3a2918.png",
    }}}


def _keyword_of(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.path.endswith("/web-interface/nav"):
        return None
    return urllib.parse.parse_qs(parsed.query).get("keyword", [""])[0]


def _blocked_payload(keyword):
    # 软拦截：HTTP 200 + code 0，但 data 里只有 v_voucher
    return {"code": 0, "message": "0",
            "data": {"v_voucher": "v_voucher_" + keyword}}


def _blocked_code_payload(keyword):
    # 硬拦截：业务错误码 + 拦截文案
    return {"code": -352, "message": "请求被拦截", "data": None}


def _now():
    return int(time.time())


def _mixed_payload(keyword):
    """第二次请求：混合 4 类视频（正常 / 过旧 / 缺发布时间 / 标题清洗后为空）。"""
    return {"code": 0, "data": {
        "numResults": 5, "result": [
            # 正常：可保留
            {"bvid": "BV1ok", "title": "<em>王者荣耀</em> S44 最强阵容",
             "author": "UP-ok", "play": 120000, "like": 8000,
             "pubdate": _now() - 3 * 86400},
            # 发布时间过旧
            {"bvid": "BV1old", "title": "王者荣耀 老版本阵容",
             "author": "UP-old", "play": 900, "like": 10,
             "pubdate": _now() - 200 * 86400},
            # 发布时间缺失
            {"bvid": "BV1nopub", "title": "王者荣耀 无发布时间",
             "author": "UP-nopub", "play": 500, "like": 5},
            # 发布时间非法
            {"bvid": "BV1badpub", "title": "王者荣耀 非法发布时间",
             "author": "UP-bad", "play": 100, "like": 1, "pubdate": "abc"},
            # 标题清洗后为空
            {"bvid": "BV1emptytitle", "title": "<em></em>",
             "author": "UP-empty", "play": 50, "like": 0,
             "pubdate": _now() - 1 * 86400},
        ]}}


def _empty_payload(keyword):
    return {"code": 0, "data": {"numResults": 0, "result": [], "page": 1}}


def _ok_payload(keyword):
    return {"code": 0, "data": {"numResults": 1, "result": [
        {"bvid": "BV1" + keyword, "title": keyword + " 版本答案",
         "author": "UP-ok", "play": 100000, "like": 3000,
         "pubdate": _now() - 2 * 86400}]}}


class _ScriptedFetcher:
    """按关键词排队返回预设响应；每个关键词第 N 次调用取第 N 个响应。"""

    def __init__(self, scripts):
        self.scripts = scripts          # {keyword: [payload_or_exc, ...]}
        self.calls = {}
        self.urls = []

    def __call__(self, url):
        keyword = _keyword_of(url)
        if keyword is None:                       # nav：假 WBI 密钥
            return _nav_payload()
        self.urls.append((keyword, time.time()))
        n = self.calls.get(keyword, 0)
        self.calls[keyword] = n + 1
        seq = self.scripts[keyword]
        step = seq[min(n, len(seq) - 1)]
        if isinstance(step, Exception):
            raise step
        return step(keyword) if callable(step) else step


@pytest.fixture()
def raw_dir(tmp_path, monkeypatch):
    """把 crawlers.base.save_raw 的输出目录指到临时目录，避免污染仓库。"""
    import crawlers.base as base
    d = tmp_path / "raw"
    d.mkdir()
    monkeypatch.setattr(base, "DATA_RAW", d)
    return d


@pytest.fixture()
def no_sleep(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda *_: None)


def test_search_keyword_blocked_then_filtered(no_sleep):
    """关键词A：首次被拦 -> 重试成功，并按原因丢弃不合格视频。"""
    from crawlers import bilibili

    kw = "关键词A"
    fetcher = _ScriptedFetcher({kw: [_blocked_payload, _mixed_payload]})
    kept, report = bilibili.search_keyword(kw, retries=3, fetcher=fetcher)

    assert report["status"] == bilibili.STATUS_OK
    assert report["status_label"] == "成功有结果"
    assert report["attempts"] == 2                  # 首次被拦 + 第二次成功
    assert report["raw_hits"] == 5
    assert report["kept"] == 1
    assert report["discarded_count"] == 4

    reasons = {d["bvid"]: d["reason"] for d in report["discarded"]}
    assert reasons["BV1old"] == bilibili.DROP_TOO_OLD
    assert reasons["BV1nopub"] == bilibili.DROP_BAD_PUBDATE
    assert reasons["BV1badpub"] == bilibili.DROP_BAD_PUBDATE
    assert reasons["BV1emptytitle"] == bilibili.DROP_EMPTY_TITLE
    assert [v["bvid"] for v in kept] == ["BV1ok"]
    # 每次尝试都有记录，便于核对是“被拦”还是“真没数据”
    assert [a["outcome"] for a in report["attempt_log"]] == [
        bilibili.STATUS_BLOCKED, bilibili.STATUS_OK]


def test_search_keyword_always_blocked(no_sleep):
    """关键词B：始终被风控 -> retries 耗尽后 blocked，且抛出的是结论不是异常。"""
    from crawlers import bilibili

    kw = "关键词B"
    fetcher = _ScriptedFetcher({kw: [_blocked_code_payload]})
    kept, report = bilibili.search_keyword(kw, retries=3, fetcher=fetcher)

    assert kept == []
    assert report["status"] == bilibili.STATUS_BLOCKED
    assert report["status_label"] == "重试耗尽仍被风控"
    assert report["attempts"] == 3
    assert report["max_attempts"] == 3
    assert report["raw_hits"] == 0
    assert len(report["attempt_log"]) == 3
    assert fetcher.calls[kw] == 3                  # 正好重试到上限


def test_search_keyword_empty_vs_blocked(no_sleep):
    """空结果必须判为 empty，不能和被拦混为一谈。"""
    from crawlers import bilibili

    kw = "关键词C"
    fetcher = _ScriptedFetcher({kw: [_empty_payload]})
    kept, report = bilibili.search_keyword(kw, retries=3, fetcher=fetcher)

    assert kept == []
    assert report["status"] == bilibili.STATUS_EMPTY
    assert report["status_label"] == "成功但无结果"
    assert report["attempts"] == 1
    assert report["raw_hits"] == 0
    assert fetcher.calls[kw] == 1


def test_search_keyword_request_error(no_sleep):
    """请求异常（网络/非 JSON）判为 error，一次即止（重试只针对风控）。"""
    from crawlers import bilibili

    kw = "关键词D"
    fetcher = _ScriptedFetcher({kw: [ConnectionError("boom")]})
    kept, report = bilibili.search_keyword(kw, retries=2, fetcher=fetcher)

    assert kept == []
    assert report["status"] == bilibili.STATUS_ERROR
    assert report["status_label"] == "请求异常"
    assert report["attempts"] == 1
    assert fetcher.calls[kw] == 1


def test_crawl_writes_report_and_legacy_raw(raw_dir, no_sleep):
    """crawl 落盘：原始数据保持旧格式，结论单独一份且三者状态各不相同。"""
    from crawlers import bilibili

    keywords = ("关键词A", "关键词B", "关键词C")
    fetcher = _ScriptedFetcher({
        "关键词A": [_blocked_payload, _mixed_payload],
        "关键词B": [_blocked_payload],
        "关键词C": [_empty_payload],
    })
    results = bilibili.crawl(keywords, fetcher=fetcher, pace=0)

    # 旧格式：{关键词: [ {title, author, play, like, bvid, pubdate}, ... ]}
    raw_path = raw_dir / "bilibili_videos.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    assert list(raw) == list(keywords)
    assert list(raw["关键词A"][0]) == ["title", "author", "play",
                                      "like", "bvid", "pubdate"]
    assert raw["关键词B"] == [] and raw["关键词C"] == []
    assert results == raw

    # 结论落盘
    report_path = raw_dir / "bilibili_search_report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    by_kw = report["by_keyword"]

    assert by_kw["关键词A"]["status"] == bilibili.STATUS_OK
    assert by_kw["关键词B"]["status"] == bilibili.STATUS_BLOCKED
    assert by_kw["关键词C"]["status"] == bilibili.STATUS_EMPTY
    statuses = {by_kw[kw]["status"] for kw in keywords}
    # 三者各不相同：有结果 / 重试耗尽被风控 / 成功但无结果
    assert statuses == {bilibili.STATUS_OK, bilibili.STATUS_EMPTY,
                        bilibili.STATUS_BLOCKED}
    assert len(statuses) == 3

    assert by_kw["关键词A"]["attempts"] == 2
    assert by_kw["关键词A"]["raw_hits"] == 5
    assert by_kw["关键词A"]["kept"] == 1
    assert by_kw["关键词B"]["attempts"] == 3
    assert by_kw["关键词C"]["attempts"] == 1
    assert report["summary"]["blocked"] == 1
    assert report["summary"]["empty"] == 1
    assert report["summary"]["ok"] == 1
    assert set(report["problem_keywords"]) == {"关键词B"}
    assert report["generated_at"]
    # 每条结论都带验收要求的字段
    for kw in keywords:
        for field in ("keyword", "status", "attempts", "raw_hits",
                      "kept", "discarded", "discarded_count"):
            assert field in by_kw[kw]


def test_full_pipeline_survives_blocked_keyword(monkeypatch, no_sleep, tmp_path):
    """全流程：B站关键词被拦/异常时，官方采集与出稿照常完成。"""
    import run as runner
    import analysis.equipment as analysis_equipment
    import analysis.hero_strength as analysis_hero_strength
    import analysis.generate_guide as analysis_generate_guide
    import crawlers.base as base
    from crawlers import bilibili, official_pvp

    # 全流程输出都落到临时目录，不污染仓库 data/raw 与 guide/
    raw_dir = tmp_path / "raw"
    proc_dir = tmp_path / "processed"
    guide_dir = tmp_path / "guide"
    for d in (raw_dir, proc_dir, guide_dir):
        d.mkdir()
    monkeypatch.setattr(base, "DATA_RAW", raw_dir)
    for mod in (analysis_hero_strength, analysis_equipment):
        monkeypatch.setattr(mod, "DATA_RAW", raw_dir)
        monkeypatch.setattr(mod, "DATA_PROCESSED", proc_dir)
    monkeypatch.setattr(analysis_generate_guide, "DATA_PROCESSED", proc_dir)
    monkeypatch.setattr(analysis_generate_guide, "GUIDE_DIR", guide_dir)

    # 官方 herolist 的真实字段名：cname / roles("1|2" 编码) / skin_name
    heroes = [
        {"ename": 101, "cname": "扁鹊", "id_name": "bianque", "title": "",
         "roles": "4|6", "skin_name": "a|b|c"},
        {"ename": 102, "cname": "镜", "id_name": "jing", "title": "",
         "roles": "3", "skin_name": "a|b|c|d"},
        {"ename": 103, "cname": "公孙离", "id_name": "gongsunli", "title": "",
         "roles": "5", "skin_name": "a|b|c|d|e"},
        {"ename": 104, "cname": "张飞", "id_name": "zhangfei", "title": "",
         "roles": "1|6", "skin_name": "a|b|c|d"},
        {"ename": 105, "cname": "花木兰", "id_name": "huamulan", "title": "",
         "roles": "2", "skin_name": "a|b|c|d|e|f"},
        {"ename": 106, "cname": "东皇太一", "id_name": "donghuangtaiyi",
         "title": "", "roles": "6|5", "skin_name": "a|b|c"},
    ]
    items = [
        {"item_id": i, "item_name": name, "item_type": 1,
         "price": 2000, "total_price": 3000, "des1": "desc",
         "des2": "passive"}
        for i, name in enumerate(
            ("无尽战刃", "影刃", "末世", "闪电匕首", "强者破军", "仁者破晓"), 1)
    ]

    def fake_fetch_json(url, **kw):
        return heroes if url == official_pvp.HERO_URL else items

    monkeypatch.setattr(official_pvp, "fetch_json", fake_fetch_json)

    keywords = bilibili.DEFAULT_KEYWORDS
    scripts = {}
    for i, kw in enumerate(keywords):
        if i == 0:
            scripts[kw] = [_blocked_payload, _mixed_payload]     # 先拦后成
        elif i == 1:
            scripts[kw] = [_blocked_code_payload]                # 始终被拦
        elif i == 2:
            scripts[kw] = [_empty_payload]                       # 空结果
        elif i == 3:
            scripts[kw] = [_ok_payload]
        else:
            scripts[kw] = [_ok_payload]
    monkeypatch.setattr(bilibili, "_get_json",
                        _ScriptedFetcher(scripts))

    runner.step_crawl()
    report = bilibili.last_report()
    assert report["summary"]["blocked"] >= 1              # 确有被拦关键词
    assert report["by_keyword"][keywords[1]]["status"] == bilibili.STATUS_BLOCKED

    # 官方数据照样落盘；B站结论也在
    assert (raw_dir / "heroes.json").exists()
    assert (raw_dir / "items.json").exists()
    assert (raw_dir / "bilibili_search_report.json").exists()

    path = runner.step_analyze()
    text = Path(path).read_text(encoding="utf-8")
    assert "英雄强度榜" in text and "装备梯度" in text and "阵容搭配" in text
    assert "扁鹊" in text
