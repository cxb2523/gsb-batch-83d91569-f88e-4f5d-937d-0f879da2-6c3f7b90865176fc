# -*- coding: utf-8 -*-
"""B站爬虫 —— 搜索王者荣耀攻略视频 + 评论区口碑。

用 curl_cffi 模拟真实 Chrome 指纹（对付基础反爬）。
B站搜索接口需要 WBI 签名，这里完整实现了签名算法（公开技术，无需登录）。
登录后（传 SESSDATA cookie）可拿到更全的评论。

每次按关键词搜索都会产出一份【可核对的结论】(report)，和原始视频数据一起
落盘到 data/raw/：
  - bilibili_videos.json        旧格式 {关键词: [视频, ...]}（分析代码照旧读取）
  - bilibili_search_report.json 每个关键词的状态 / 尝试次数 / 命中数 / 丢弃原因

状态四分类（不再把“被风控”混成“0 条”）：
  ok      成功有结果
  empty   成功但无结果（接口确实返回 0 条）
  blocked 重试耗尽仍被风控（v_voucher / 拦截码）
  error   请求异常（网络 / 非 JSON / 接口异常码）

依赖:  pip install curl_cffi
"""
import hashlib
import math
import re
import sys
import time
import urllib.parse
from functools import reduce
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from crawlers.base import save_raw

_SESSION = None
MAX_AGE_DAYS = 90          # 只保留近 90 天的视频，保证热度信号时效性

# ── 关键词搜索结论：状态 ────────────────────────────────────────────
STATUS_OK = "ok"                 # 成功有结果
STATUS_EMPTY = "empty"           # 成功但无结果
STATUS_BLOCKED = "blocked"       # 重试耗尽仍被风控
STATUS_ERROR = "error"           # 请求异常
STATUS_LABELS = {
    STATUS_OK: "成功有结果",
    STATUS_EMPTY: "成功但无结果",
    STATUS_BLOCKED: "重试耗尽仍被风控",
    STATUS_ERROR: "请求异常",
}
SUCCESS_STATUSES = (STATUS_OK, STATUS_EMPTY)
PROBLEM_STATUSES = (STATUS_BLOCKED, STATUS_ERROR)

# 单次尝试的结果标签（与“最终状态”区分：第 1 次被拦 ≠ 重试耗尽）
ATTEMPT_LABELS = {
    STATUS_OK: "拿到结果",
    STATUS_EMPTY: "返回空结果",
    STATUS_BLOCKED: "命中风控",
    STATUS_ERROR: "请求异常",
}

# ── 关键词搜索结论：视频丢弃原因 ─────────────────────────────────────
DROP_TOO_OLD = "发布时间过旧"
DROP_BAD_PUBDATE = "发布时间缺失或非法"
DROP_EMPTY_TITLE = "标题清洗后为空"
DROP_BAD_ROW = "视频条目格式异常"      # 兜底：接口返回了非对象条目

# B站风控/拦截相关返回码与文案线索
_RISK_CODES = {-352, -401, -403, -412, -509}
_RISK_HINTS = ("拦截", "风控", "频繁", "v_voucher", "voucher",
               "异常流量", "安全验证", "blocked", "risk")

_REPORT_NAME = "bilibili_search_report"
_LAST_REPORT = None      # 最近一次 crawl() 的结论（供 run.py / 排障直接打印）


def _session():
    """带真实 Chrome 指纹的持久 session，先访问首页拿 buvid3 cookie
    （B站搜索接口现在要求这个匿名 cookie，否则 403）。"""
    global _SESSION
    if _SESSION is not None:
        return _SESSION
    from curl_cffi import requests as creq          # 必需，纯 urllib 会被 403
    s = creq.Session(impersonate="chrome124")
    s.get("https://www.bilibili.com", timeout=15)   # 种下 buvid3 / b_nut
    # 补 buvid3/buvid4，绕过搜索接口的 v_voucher 风控软拦截（无需登录）
    try:
        spi = s.get("https://api.bilibili.com/x/frontend/finger/spi",
                    timeout=15).json().get("data", {})
        if spi.get("b_3"):
            s.cookies.set("buvid3", spi["b_3"], domain=".bilibili.com")
        if spi.get("b_4"):
            s.cookies.set("buvid4", spi["b_4"], domain=".bilibili.com")
    except Exception:                               # noqa: BLE001
        pass
    # 可选：有登录 cookie 时传入，能拿更全数据（见 README）
    import os
    if os.environ.get("BILI_SESSDATA"):
        s.cookies.set("SESSDATA", os.environ["BILI_SESSDATA"],
                      domain=".bilibili.com")
    _SESSION = s
    return s


def _get_json(url):
    return _session().get(url, timeout=15).json()


def _reset_session():
    global _SESSION
    _SESSION = None


# WBI 混淆置换表（B站前端固定常量）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def _get_mixin_key(orig):
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, "")[:32]


def _get_wbi_keys(fetcher=None):
    """从 nav 接口取 img_key / sub_key（无需登录即可拿到）。"""
    data = (fetcher or _get_json)("https://api.bilibili.com/x/web-interface/nav")
    wbi = data["data"]["wbi_img"]
    img = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    return img, sub


def _sign(params, fetcher=None):
    img, sub = _get_wbi_keys(fetcher)
    mixin = _get_mixin_key(img + sub)
    params = dict(params, wts=int(time.time()))
    query = urllib.parse.urlencode(sorted(params.items()))
    params["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return params


def _search_url(keyword, page, fetcher=None):
    params = _sign({
        "search_type": "video",
        "keyword": keyword,
        "page": page,
        "order": "totalrank",
    }, fetcher)
    return ("https://api.bilibili.com/x/web-interface/wbi/search/type?"
            + urllib.parse.urlencode(params))


def _classify_response(payload):
    """把一次搜索响应归为 (状态, 视频行列表, 说明)。

    关键：把“风控软拦截”和“接口确实返回空”分开。
      - data 里只有 v_voucher / data 为空 / 拦截码 -> blocked
      - result 明确是空列表 或 numResults=0       -> empty
      - 其它结构问题（网络已在调用侧捕获）          -> error
    """
    if not isinstance(payload, dict):
        return STATUS_ERROR, None, "响应不是 JSON 对象"

    code = payload.get("code", 0)
    msg = str(payload.get("message") or "")
    if code not in (0, "0", None):
        risk = (any(h in msg for h in _RISK_HINTS)
                or any(h in msg.lower() for h in ("voucher", "blocked", "risk")))
        try:
            risk = risk or int(code) in _RISK_CODES
        except (TypeError, ValueError):
            pass
        status = STATUS_BLOCKED if risk else STATUS_ERROR
        return status, None, f"接口返回 code={code} message={msg!r}"

    data = payload.get("data")
    if not isinstance(data, dict):
        # 搜索接口软拦截时常见 data 为空/缺失，无结果时会带 numResults=0
        return STATUS_BLOCKED, None, "data 字段为空或缺失（疑似风控软拦截）"
    if data.get("v_voucher"):
        return STATUS_BLOCKED, None, "data 含 v_voucher（风控软拦截）"

    result = data.get("result")
    if result is None:
        num = data.get("numResults")
        try:
            num = int(num)
        except (TypeError, ValueError):
            num = None
        if num == 0:
            return STATUS_EMPTY, [], "接口返回 0 条结果"
        if num and num > 0:
            return STATUS_ERROR, None, "numResults>0 但 result 缺失（响应字段缺失）"
        return STATUS_BLOCKED, None, "result 缺失且无结果计数（疑似风控软拦截）"
    if not isinstance(result, list):
        return STATUS_ERROR, None, (
            f"result 字段类型异常: {type(result).__name__}")

    # 原始命中条数 = 接口 result 里的条目数（含字段缺失/非字典项）
    if not result:
        return STATUS_EMPTY, [], "接口返回空结果列表"
    return STATUS_OK, result, ""


def _strip(s):
    """清洗搜索标题：去掉 B站高亮标签和多余空白。"""
    text = re.sub(r"<[^>]+>", "", s or "")
    return re.sub(r"\s+", " ", text).strip()


def _pubdate_ts(pub, now=None):
    """把 pubdate 转成时间戳；缺失 / 非数字 / 非正 / 未来时间都算非法。"""
    if isinstance(pub, bool) or pub is None:
        return None
    try:
        ts = float(pub)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ts) or ts <= 0:
        return None
    now = time.time() if now is None else now
    if ts > now + 86400:                         # 未来时间视为非法
        return None
    return ts


def _drop_row(v, cleaned_title, pubdate, reason):
    if not isinstance(v, dict):
        v = {}
    return {
        "bvid": v.get("bvid"),
        "title": cleaned_title,
        "raw_title": v.get("title"),
        "pubdate": pubdate,
        "reason": reason,
    }


def _empty_report(keyword, retries, status, detail="", attempt_log=None):
    return {
        "keyword": keyword,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "attempts": len(attempt_log or []),
        "max_attempts": retries,
        "raw_hits": 0,
        "kept": 0,
        "discarded_count": 0,
        "discarded": [],
        "attempt_log": list(attempt_log or []),
        "detail": detail,
    }


def search_keyword(keyword, page=1, retries=3, *, fetcher=None,
                   sleep=None, now=None):
    """搜索单个关键词，返回 (保留的视频列表, 可核对结论)。

    重试语义与旧实现一致：命中风控就重置 session 并退避再试，达到 retries
    上限后停止；请求异常不重试、直接记一次 error。任何失败都收敛成结论返回、
    不向外抛异常（除 crawl 里兜底的意外 bug），因此单个关键词不会中断其它关键词。

    fetcher / sleep / now 是给离线验收用的注入点：传一个假的 fetcher 就能
    用本地假响应替代真实网络，不碰 B站。
    """
    now = time.time() if now is None else now
    retries = max(1, int(retries))
    sleep = time.sleep if sleep is None else sleep

    status, rows, detail = STATUS_ERROR, None, ""
    attempt_log = []
    attempts = 0

    for attempt in range(retries):
        attempts += 1
        try:
            payload = (fetcher or _get_json)(_search_url(keyword, page, fetcher))
        except Exception as e:                       # noqa: BLE001 网络/JSON异常
            status, rows = STATUS_ERROR, None
            detail = f"{type(e).__name__}: {e}"
        else:
            status, rows, detail = _classify_response(payload)

        attempt_log.append({
            "attempt": attempts,
            "outcome": status,
            "outcome_label": ATTEMPT_LABELS[status],
            "detail": detail,
        })
        if status in SUCCESS_STATUSES:
            break
        if status != STATUS_BLOCKED:                 # 请求异常不再重试
            break
        # 命中风控：换新 session（重拿 buvid）+ 退避后再试（保持旧语义）
        _reset_session()
        if attempt < retries - 1:
            try:
                sleep(2 * (attempt + 1))
            except Exception:                        # noqa: BLE001
                pass

    # ── 时效过滤 + 丢弃原因 ─────────────────────────────────────────
    rows = rows or []
    cutoff = now - MAX_AGE_DAYS * 86400
    kept, dropped = [], []
    for v in rows:
        if not isinstance(v, dict):
            dropped.append(_drop_row(v, "", None, DROP_BAD_ROW))
            continue
        cleaned_title = _strip(v.get("title"))
        pub = v.get("pubdate")
        ts = _pubdate_ts(pub, now)
        if ts is None:
            dropped.append(_drop_row(v, cleaned_title, pub, DROP_BAD_PUBDATE))
            continue
        if ts < cutoff:
            dropped.append(_drop_row(v, cleaned_title, pub, DROP_TOO_OLD))
            continue
        if not cleaned_title:
            dropped.append(_drop_row(v, cleaned_title, pub, DROP_EMPTY_TITLE))
            continue
        kept.append({
            "title": cleaned_title,
            "author": v.get("author"),
            "play": v.get("play"),
            "like": v.get("like"),
            "bvid": v.get("bvid"),
            "pubdate": v.get("pubdate"),
        })

    report = {
        "keyword": keyword,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "attempts": attempts,
        "max_attempts": retries,
        "raw_hits": len(rows),
        "kept": len(kept),
        "discarded_count": len(dropped),
        "discarded": dropped,
        "attempt_log": attempt_log,
        "detail": detail,
    }
    return kept, report


def search_videos(keyword, page=1, retries=3, *, fetcher=None,
                  sleep=None, now=None):
    """兼容旧接口：只返回通过时效过滤的视频列表。

    需要状态 / 尝试次数 / 丢弃原因时用 search_keyword()。
    """
    kept, _report = search_keyword(keyword, page=page, retries=retries,
                                   fetcher=fetcher, sleep=sleep, now=now)
    return kept


# 无空格关键词更容易过风控（带空格更易触发 v_voucher）
DEFAULT_KEYWORDS = ("王者荣耀最强阵容", "王者荣耀英雄梯度", "王者荣耀上分英雄",
                    "王者荣耀T0英雄", "王者荣耀版本答案")


def _build_report(reports):
    counts = {s: 0 for s in STATUS_LABELS}
    raw_hits = kept = discarded = 0
    for r in reports:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
        raw_hits += r["raw_hits"]
        kept += r["kept"]
        discarded += r["discarded_count"]
    return {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "max_age_days": MAX_AGE_DAYS,
        "status_labels": STATUS_LABELS,
        "attempt_labels": ATTEMPT_LABELS,
        "summary": {
            "keywords": len(reports),
            "ok": counts.get(STATUS_OK, 0),
            "empty": counts.get(STATUS_EMPTY, 0),
            "blocked": counts.get(STATUS_BLOCKED, 0),
            "error": counts.get(STATUS_ERROR, 0),
            "raw_hits": raw_hits,
            "kept": kept,
            "discarded": discarded,
        },
        "keywords": reports,
        "by_keyword": {r["keyword"]: r for r in reports},
        "problem_keywords": [r["keyword"] for r in reports
                             if r["status"] in PROBLEM_STATUSES],
    }


def crawl(keywords=DEFAULT_KEYWORDS, *, fetcher=None, sleep=None,
          pace=3):
    """逐个关键词采集，保存“原始数据 + 可核对结论”，返回旧格式数据。

    单个关键词被风控 / 请求异常只影响它自己的结论，不中断循环，也不影响
    官方英雄装备采集和后续分析出稿。
    """
    global _LAST_REPORT
    sleep = time.sleep if sleep is None else sleep
    if fetcher is None:
        # 保持旧行为：没装 curl_cffi 时由调用方（run.py）明确提示“跳过”
        try:
            __import__("curl_cffi")          # 仅做可用性检查
        except ImportError as e:
            raise ImportError(
                "未安装 curl_cffi（pip install curl_cffi），B站采集跳过") from e
    results, reports = {}, []
    for kw in keywords:
        try:
            videos, report = search_keyword(kw, fetcher=fetcher, sleep=sleep)
        except Exception as e:                       # noqa: BLE001 兜底：意外 bug
            videos = []
            report = _empty_report(kw, retries=3, status=STATUS_ERROR,
                                   detail=f"{type(e).__name__}: {e}")
        results[kw] = videos
        reports.append(report)
        print(f"[B站] '{kw}' -> {report['status_label']}｜"
              f"尝试 {report['attempts']} 次｜原始 {report['raw_hits']}｜"
              f"保留 {report['kept']}｜丢弃 {report['discarded_count']}")
        _reset_session()          # 每个关键词换新 session，降低风控
        if pace:
            try:
                sleep(pace)
            except Exception:                    # noqa: BLE001
                pass

    # 原始视频仍按旧格式保存，旧分析代码可直接读取
    save_raw("bilibili_videos", results)
    # 结论与原始数据同目录落盘，便于核对 / 排障
    report = _build_report(reports)
    save_raw(_REPORT_NAME, report)
    _LAST_REPORT = report
    return results


def last_report():
    """最近一次 crawl() 的结论（按关键词状态的汇总）。"""
    return _LAST_REPORT


if __name__ == "__main__":
    crawl()
