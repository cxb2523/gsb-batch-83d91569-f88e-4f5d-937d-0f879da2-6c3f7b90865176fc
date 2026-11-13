#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_probe.py —— 模型批量探测链路回归（trae_probe.probe_models / probe_one）

约束：
  · 只用 tempfile 临时目录 + 假账号 + 假 trae_client 模块，**绝不打真实上游、
    不读真实凭证/真实 model_health.json**；
  · 覆盖：正常探测、缓存跳过、force 重探、过期重探、limit 只截断待办、
    无账号记 no_account、stop_event 停止、错误五分类、逐条落盘可重载。

跑法：python test_probe.py    （全 PASS 退出码 0）
"""
import json
import os
import sys
import tempfile
import threading
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

TMP = tempfile.mkdtemp(prefix="trae-probe-test-")
HEALTH = os.path.join(TMP, "usage", "model_health.json")

import trae_probe                      # noqa: E402
trae_probe.set_health_path(HEALTH)

FAILS = []
CHECKS = [0]


def check(name, cond, extra=""):
    CHECKS[0] += 1
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else "  << " + str(extra)))
    if not cond:
        FAILS.append(name)


class FakeAccount(object):
    def __init__(self, uid, realm="cn", enabled=True):
        self.uid = uid
        self.realm = realm
        self.enabled = enabled
        self.token = "x" * 8           # 假 token：仅长度语义


# ---------------------------------------------------------------------------
# 假 trae_client：probe_one 内部 `import trae_client`，这里抢先注入 sys.modules
# ---------------------------------------------------------------------------
CALLS = []
HANDLER = [None]                       # fn(account, realm, model) -> dict 或 raise

fake_client = types.ModuleType("trae_client")


def _chat_once(account, realm=None, model=None, messages=None, **kwargs):
    CALLS.append({"model": model, "realm": realm,
                  "account": getattr(account, "uid", "")})
    handler = HANDLER[0]
    if handler is not None:
        return handler(account, realm, model)
    return {"text": "OK",
            "usage": {"prompt_tokens": 3, "completion_tokens": 1}}


fake_client.chat_once = _chat_once
sys.modules["trae_client"] = fake_client


class UpstreamError(Exception):
    """模拟带上游错误码的异常（与 trae_client 的异常形态一致：有 .code）。"""

    def __init__(self, code, message="upstream error"):
        super(UpstreamError, self).__init__(message)
        self.code = code


def reset():
    """清空健康文件、模块缓存、调用记录，恢复默认假客户端行为。"""
    if os.path.exists(HEALTH):
        os.remove(HEALTH)
    trae_probe.set_health_path(HEALTH)   # 顺便清 _cache
    del CALLS[:]
    HANDLER[0] = None


def seed_health(rows):
    """直接往健康文件里写旧结果（模拟上一轮探测留下的缓存）。"""
    data = {"updated_at": time.time(), "models": {}}
    for row in rows:
        data["models"].setdefault(row["realm"], {})[row["model"]] = row
    trae_probe.save_health(data)


def ok_row(model, realm="cn", at=None):
    return {"model": model, "realm": realm, "ok": True, "status": "ok",
            "at": time.time() if at is None else at,
            "elapsed_ms": 12, "error": "", "reply": "OK",
            "prompt_tokens": 3, "completion_tokens": 1, "account": "0001"}


# ---------------------------------------------------------------------------
# 1. 正常探测：全部 ok、逐条落盘、进度回调齐全
# ---------------------------------------------------------------------------
def test_normal():
    reset()
    accounts = [FakeAccount("u0001", "cn")]
    models = [{"key": "m1", "realm": "cn"}, {"key": "m2", "realm": "cn"}]
    progress = []
    out = trae_probe.probe_models(
        accounts, models,
        on_progress=lambda d, t, k, row: progress.append((d, t, k)))
    summary = out["summary"]
    check("normal: summary ok=2 failed=0",
          summary["ok"] == 2 and summary["failed"] == 0, summary)
    check("normal: total=2 skipped=0",
          summary["total"] == 2 and summary["skipped"] == 0, summary)
    check("normal: 客户端被调 2 次", len(CALLS) == 2, CALLS)
    check("normal: 结果全部 ok",
          all(r.get("ok") and r.get("status") == "ok" for r in out["results"]),
          out["results"])
    check("normal: 进度回调到 2/2",
          progress and progress[-1][0] == 2 and progress[-1][1] == 2, progress)
    check("normal: 返回 model_health",
          out["model_health"]["models"]["cn"]["m2"]["ok"] is True)
    disk = trae_probe.load_health(force=True)
    check("normal: 磁盘可重载（模拟进程重启后读取）",
          disk["models"]["cn"]["m1"]["ok"] is True, disk)
    check("normal: 无残留 tmp 文件", not os.path.exists(HEALTH + ".tmp"))
    with open(HEALTH, encoding="utf-8") as handle:
        raw = json.load(handle)
    check("normal: 落盘文件是合法 JSON", isinstance(raw.get("models"), dict))


# ---------------------------------------------------------------------------
# 2. 缓存跳过：新鲜 ok 结果直接复用，不打上游，但计入进度
# ---------------------------------------------------------------------------
def test_cache_skip():
    reset()
    seed_health([ok_row("m1"), ok_row("m2")])
    accounts = [FakeAccount("u0001", "cn")]
    models = [{"key": "m1", "realm": "cn"}, {"key": "m2", "realm": "cn"}]
    progress = []
    out = trae_probe.probe_models(
        accounts, models,
        on_progress=lambda d, t, k, row: progress.append((d, t, k, row)))
    summary = out["summary"]
    check("cache: skipped=2 且不调用上游",
          summary["skipped"] == 2 and len(CALLS) == 0, (summary, CALLS))
    check("cache: 结果带 cached 标记",
          all(r.get("cached") for r in out["results"]), out["results"])
    check("cache: ok/failed 不计入缓存条目",
          summary["ok"] == 0 and summary["failed"] == 0, summary)
    check("cache: 缓存条目也计入进度",
          len(progress) == 2 and progress[-1][0] == 2 and progress[-1][1] == 2,
          progress)


# ---------------------------------------------------------------------------
# 3. force=True：忽略新鲜缓存，全部重探
# ---------------------------------------------------------------------------
def test_force():
    reset()
    seed_health([ok_row("m1"), ok_row("m2")])
    accounts = [FakeAccount("u0001", "cn")]
    models = [{"key": "m1", "realm": "cn"}, {"key": "m2", "realm": "cn"}]
    out = trae_probe.probe_models(accounts, models, force=True)
    summary = out["summary"]
    check("force: 全部重探（客户端调 2 次）", len(CALLS) == 2, CALLS)
    check("force: skipped=0 ok=2",
          summary["skipped"] == 0 and summary["ok"] == 2, summary)


# ---------------------------------------------------------------------------
# 4. 过期缓存：超过 stale_seconds 的旧成功结果要重探
# ---------------------------------------------------------------------------
def test_stale_reprobe():
    reset()
    seed_health([ok_row("m1", at=time.time() - 90000)])   # > 24h
    accounts = [FakeAccount("u0001", "cn")]
    out = trae_probe.probe_models(accounts, [{"key": "m1", "realm": "cn"}])
    check("stale: 过期结果被重探", len(CALLS) == 1, CALLS)
    check("stale: skipped=0", out["summary"]["skipped"] == 0, out["summary"])
    # 自定义 stale_seconds 窗口内则仍算新鲜
    reset()
    seed_health([ok_row("m1", at=time.time() - 100)])
    out = trae_probe.probe_models(accounts, [{"key": "m1", "realm": "cn"}],
                                  stale_seconds=3600)
    check("stale: 窗口内复用", len(CALLS) == 0 and out["summary"]["skipped"] == 1,
          (CALLS, out["summary"]))


# ---------------------------------------------------------------------------
# 5. limit 只截断待办：前面命中缓存不能挤掉后面的探测名额
# ---------------------------------------------------------------------------
def test_limit_only_pending():
    reset()
    seed_health([ok_row("m1"), ok_row("m2")])             # 前两个命中缓存
    accounts = [FakeAccount("u0001", "cn")]
    models = [{"key": "m%d" % i, "realm": "cn"} for i in range(1, 6)]
    out = trae_probe.probe_models(accounts, models, limit=2)
    probed = [c["model"] for c in CALLS]
    check("limit: 缓存不占名额，探的是 m3/m4",
          probed == ["m3", "m4"], probed)
    summary = out["summary"]
    check("limit: total=缓存2+待办2",
          summary["total"] == 4 and summary["skipped"] == 2, summary)
    check("limit: m5 未被探测", "m5" not in probed, probed)
    keys = [r["model"] for r in out["results"]]
    check("limit: 结果含缓存条目与已探条目", keys == ["m1", "m2", "m3", "m4"], keys)


# ---------------------------------------------------------------------------
# 6. 无账号区域：记 no_account、计入失败、不中断整批
# ---------------------------------------------------------------------------
def test_no_account():
    reset()
    accounts = [FakeAccount("u0001", "cn"),
                FakeAccount("u0002", "intl", enabled=False)]   # intl 未启用
    models = [{"key": "mx", "realm": "intl"},
              {"key": "m1", "realm": "cn"}]
    out = trae_probe.probe_models(accounts, models)
    row = out["results"][0]
    check("no_account: 状态为 no_account 且不 ok",
          row["status"] == "no_account" and row["ok"] is False, row)
    summary = out["summary"]
    check("no_account: 计入失败", summary["failed"] == 1, summary)
    check("no_account: 整批未中断，后续 cn 模型正常探测",
          summary["ok"] == 1 and len(CALLS) == 1, (summary, CALLS))
    disk = trae_probe.load_health(force=True)
    check("no_account: 落盘保留 no_account 记录",
          disk["models"]["intl"]["mx"]["status"] == "no_account", disk)
    # accounts 为 None 也不能抛异常
    reset()
    out = trae_probe.probe_models(None, [{"key": "m", "realm": "cn"}])
    check("no_account: accounts=None 不抛异常",
          out["results"][0]["status"] == "no_account", out["results"])


# ---------------------------------------------------------------------------
# 7. stop_event：置位后停止后续探测，已完成条目保留在结果与文件中
# ---------------------------------------------------------------------------
def test_stop_event():
    reset()
    accounts = [FakeAccount("u0001", "cn")]
    models = [{"key": "m%d" % i, "realm": "cn"} for i in range(1, 4)]
    event = threading.Event()

    def progress(done, total, key, row):
        event.set()                  # 第一个探测完成后立即要求停止

    out = trae_probe.probe_models(accounts, models,
                                  on_progress=progress, stop_event=event)
    check("stop: 只探了 1 个", len(CALLS) == 1, CALLS)
    check("stop: 结果只保留已完成条目", len(out["results"]) == 1, out["results"])
    check("stop: 已完成条目 ok", out["results"][0]["ok"] is True, out["results"])
    disk = trae_probe.load_health(force=True)
    bucket = disk["models"].get("cn") or {}
    check("stop: 落盘只有已完成条目",
          sorted(bucket.keys()) == ["m1"], bucket)
    # 一开始就置位：一个都不探，但不抛异常
    reset()
    event2 = threading.Event()
    event2.set()
    out = trae_probe.probe_models(accounts, models, stop_event=event2)
    check("stop: 预置位时零探测且不抛异常",
          len(CALLS) == 0 and out["results"] == [], (CALLS, out["results"]))


# ---------------------------------------------------------------------------
# 8. 失败原因五分类：异常路径 + 上游 errors 列表路径
# ---------------------------------------------------------------------------
def test_error_classification():
    reset()
    account = FakeAccount("u0001", "cn")
    cases = [(4015, "risk_control"), (4019, "risk_control"),
             (4023, "unavailable"), (4003, "unavailable"),
             (401, "auth"), (403, "auth"),
             (429, "rate_limited"), (500, "error")]
    for code, expect in cases:
        def handler(a, r, m, _code=code):
            raise UpstreamError(_code)
        HANDLER[0] = handler
        row = trae_probe.probe_one(account, "m", "cn")
        check("classify: 异常 code=%s -> %s" % (code, expect),
              isinstance(row, dict) and row["status"] == expect
              and row["ok"] is False and row["error"],
              row)
    HANDLER[0] = None
    # 文本兜底：无 code 但消息含 risk control
    def handler_text(a, r, m):
        raise Exception("risk control triggered")
    HANDLER[0] = handler_text
    row = trae_probe.probe_one(account, "m", "cn")
    check("classify: 文本含 risk control -> risk_control",
          row["status"] == "risk_control", row)
    # 上游 200 但 body 里带 errors 列表
    for code, expect in [(4015, "risk_control"), (4023, "unavailable"),
                         (429, "rate_limited"), (500, "error")]:
        def handler_errs(a, r, m, _code=code):
            return {"text": "", "errors": [{"code": _code, "message": "boom"}]}
        HANDLER[0] = handler_errs
        row = trae_probe.probe_one(account, "m", "cn")
        check("classify: errors 列表 code=%s -> %s" % (code, expect),
              row["status"] == expect and row["ok"] is False, row)
    HANDLER[0] = None


# ---------------------------------------------------------------------------
# 9. probe_one 永不抛异常；批量中失败模型也逐条落盘
# ---------------------------------------------------------------------------
def test_never_raises_and_partial_persist():
    reset()
    account = FakeAccount("u0001", "cn")

    def handler_boom(a, r, m):
        raise RuntimeError("boom")
    HANDLER[0] = handler_boom
    try:
        row = trae_probe.probe_one(account, "m", "cn")
        raised = False
    except Exception:
        raised = True
        row = None
    check("robust: probe_one 不抛异常", not raised and isinstance(row, dict), row)
    check("robust: 未知异常归为 error",
          row and row["status"] == "error" and row["ok"] is False, row)
    # 批量：第一个失败、第二个成功，两条都要落盘
    reset()
    accounts = [FakeAccount("u0001", "cn")]

    def handler_mixed(a, r, m):
        if m == "bad":
            raise UpstreamError(4015, "risk control")
        return {"text": "OK", "usage": {}}
    HANDLER[0] = handler_mixed
    models = [{"key": "bad", "realm": "cn"}, {"key": "good", "realm": "cn"}]
    out = trae_probe.probe_models(accounts, models)
    summary = out["summary"]
    check("robust: 批量 ok=1 failed=1",
          summary["ok"] == 1 and summary["failed"] == 1, summary)
    disk = trae_probe.load_health(force=True)
    bucket = disk["models"]["cn"]
    check("robust: 失败与成功都落盘",
          bucket["bad"]["status"] == "risk_control"
          and bucket["good"]["ok"] is True, bucket)
    HANDLER[0] = None


def main():
    test_normal()
    test_cache_skip()
    test_force()
    test_stale_reprobe()
    test_limit_only_pending()
    test_no_account()
    test_stop_event()
    test_error_classification()
    test_never_raises_and_partial_persist()
    print("-" * 60)
    print("total %d checks, %d failed" % (CHECKS[0], len(FAILS)))
    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
