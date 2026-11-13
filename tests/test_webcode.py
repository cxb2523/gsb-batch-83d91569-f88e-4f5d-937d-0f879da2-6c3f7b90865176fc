import json
from types import SimpleNamespace

import pytest

from bench import webcode
from bench.agents import __main__ as agents


def write_jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_excerpt_match_ignores_whitespace_and_markup():
    assert webcode.has_excerpt("If  maxsize is\nset to `None`,", "...if **maxsize** is set to None, the LRU...")
    assert not webcode.has_excerpt("maxsize is set to None", "maxsize is set to 128")


def test_webfetch_http_error_is_a_failed_fetch_even_when_the_call_was_valid():
    item = {"excerpt": "returned"}
    r = {
        "valid": True,
        "windows": 1,
        "truncated": False,
        "tokens": 30,
        "tool_seconds": 1,
        "wall_seconds": 5,
        "cost": 0.001,
        "command_cost": 0.02,
        "tool_models": [],
        "version": "x",
        "text": "The server returned HTTP 403 Forbidden.\n\nThe response body was not retrieved.",
    }
    row = webcode.webfetch_row(item, r)
    assert row["fetch_failed"] and not row["excerpt"]
    assert not webcode.webfetch_row(item, {**r, "text": "It returned the value 42."})["fetch_failed"]


def test_convert_keeps_items_with_the_excerpt_and_reports_the_rest(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    base = {"query": "q", "citation_excerpt": "ex", "expected_answer": "a"}
    write_jsonl(
        data / "highlights.jsonl", [{**base, "id": f"h{i}", "citation_url": f"https://e.com/{i}"} for i in range(4)]
    )
    write_jsonl(data / "rag.jsonl", [{**base, "id": "r0", "source_url": "https://e.com/r"}])
    write_jsonl(
        tmp_path / "pre.jsonl",
        [
            {"id": "h0", "status": "ok", "excerpt": True},
            {"id": "h1", "status": "ok", "excerpt": False},
            {"id": "h2", "status": "error", "error": "HTTPStatusError: 403 Forbidden"},
            {"id": "h3", "status": "ok", "excerpt": False},
            {"id": "r0", "status": "ok", "excerpt": True},
        ],
    )
    write_jsonl(
        tmp_path / "raw.jsonl",
        [
            {"id": "h1", "raw_status": 200, "raw_excerpt": True},
            {"id": "h2", "raw_status": 403, "raw_excerpt": False},
            {"id": "h3", "raw_status": 200, "raw_excerpt": False},
        ],
    )
    out = tmp_path / "suite"
    args = ["convert", "--data", str(data), "--preflight", str(tmp_path / "pre.jsonl")]
    webcode.main([*args, "--rawcheck", str(tmp_path / "raw.jsonl"), "--out", str(out), "--sets", "highlights"])
    assert [i["id"] for i in json.loads((out / "items.json").read_text())] == ["h0", "h1"]  # no rag item
    excluded = {e["id"]: e["reason"] for e in json.loads((out / "excluded.json").read_text())}
    assert set(excluded) == {"h2", "h3"} and "403" in excluded["h2"] and "raw HTML" in excluded["h3"]
    assert [i["id"] for i in json.loads((out / "blocked.json").read_text())] == ["h2"]
    assert json.loads((out / "rubric.json").read_text())["h0"] == {"f1": [["judge", "a"]]}


def reader(text, **kw):
    return {"text": text, "excerpt": False, "fetch_failed": False, **kw}


def test_identical_texts_are_judged_once():
    rows = [
        {
            "id": "x",
            "webfetch_single": reader("a"),
            "webfetch_cont": reader("a", same_as="webfetch_single"),
            "jevfetch_0.3": reader("# jevfetch: u\n# 3/9 blocks, 10 of 90 tokens\nb"),
            "jevfetch_0.6": reader("# jevfetch: u\n# 3/9 blocks, 10 of 90 tokens\nb"),
        }
    ]
    todo = webcode.pending_votes(rows, [])
    assert sorted((t[1], t[2], t[3]) for t in todo) == [("jevfetch_0.3", 0, "b"), ("webfetch_single", 0, "a")]


def vote(rid, tool, n, ok):
    return {"id": rid, "tool": tool, "vote": n, "sufficient": ok}


def test_disagreeing_first_votes_get_two_more_votes_each():
    rows = [
        {"id": "x", "webfetch_single": reader("a"), "jevfetch_0.6": reader("b")},
        {"id": "y", "webfetch_single": reader("c"), "jevfetch_0.6": reader("d")},
    ]
    cast = [
        vote("x", "webfetch_single", 0, False),
        vote("x", "jevfetch_0.6", 0, True),
        vote("y", "webfetch_single", 0, True),
        vote("y", "jevfetch_0.6", 0, True),
    ]
    todo = webcode.pending_votes(rows, cast)
    assert sorted((t[0], t[1], t[2]) for t in todo) == [
        ("x", "jevfetch_0.6", 1),
        ("x", "jevfetch_0.6", 2),
        ("x", "webfetch_single", 1),
        ("x", "webfetch_single", 2),
    ]


def test_verdict_waits_for_every_vote_then_takes_the_majority():
    rows = [{"id": "x", "webfetch_single": reader("a"), "webfetch_cont": reader("a"), "jevfetch_0.6": reader("b")}]
    cast = [vote("x", "webfetch_single", 0, False), vote("x", "jevfetch_0.6", 0, True)]
    assert set(webcode.verdicts(rows, cast).values()) == {None}  # the disagreement needs two more votes each
    cast += [
        vote("x", "webfetch_single", 1, True),
        vote("x", "webfetch_single", 2, True),
        vote("x", "jevfetch_0.6", 1, True),
        vote("x", "jevfetch_0.6", 2, False),
    ]
    assert webcode.verdicts(rows, cast) == {
        ("x", "webfetch_single"): True,
        ("x", "webfetch_cont"): True,
        ("x", "jevfetch_0.6"): True,
    }


def fake_readers(monkeypatch, calls):
    def webfetch(item, raw_dir):
        calls.append(("webfetch", item["id"]))
        r = reader("w")
        return {"webfetch_single": r, "webfetch_cont": {**r, "same_as": "webfetch_single"}}

    async def jevfetch_once(item, th):
        calls.append((f"jevfetch_{th}", item["id"]))
        return reader("j")

    monkeypatch.setattr(webcode, "webfetch", webfetch)
    monkeypatch.setattr(webcode, "jevfetch_once", jevfetch_once)


def tools_args(out, items, **kw):
    return SimpleNamespace(out=str(out), items=str(items), ids=None, sets=None, thresholds="0.3,0.6", parallel=1, **kw)


def test_tools_runs_every_reader_of_an_item_and_refuses_a_changed_configuration(tmp_path, monkeypatch):
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"id": "h0", "set": "highlights", "url": "u", "question": "q", "excerpt": "e"}]))
    calls = []
    fake_readers(monkeypatch, calls)
    out = tmp_path / "run"
    webcode.tools(tools_args(out, items))
    assert calls == [("webfetch", "h0"), ("jevfetch_0.3", "h0"), ("jevfetch_0.6", "h0")]
    webcode.tools(tools_args(out, items))  # same configuration: resumes, nothing left to run
    assert len(calls) == 3
    with pytest.raises(SystemExit):
        webcode.tools(SimpleNamespace(**{**vars(tools_args(out, items)), "thresholds": "0.3,0.9"}))


def test_tools_refuses_results_without_a_recorded_configuration(tmp_path, monkeypatch):
    items = tmp_path / "items.json"
    items.write_text(json.dumps([{"id": "h0", "set": "highlights", "url": "u", "question": "q", "excerpt": "e"}]))
    out = tmp_path / "old"
    out.mkdir()
    write_jsonl(out / "rows.jsonl", [{"id": "h0"}])
    fake_readers(monkeypatch, [])
    with pytest.raises(SystemExit):
        webcode.tools(tools_args(out, items))


def test_agent_bench_reads_another_question_file(tmp_path, monkeypatch):
    path = tmp_path / "q.json"
    path.write_text(json.dumps([{"id": "h0", "url": "https://e.com", "query": "q", "lang": "en", "gold": []}]))
    monkeypatch.setattr(agents, "QUESTIONS", path)
    assert [q["id"] for q in agents.questions(None)] == ["h0"]


def test_reader_only_arms_allow_nothing_but_the_reader_and_are_paired_in_the_report():
    assert agents.arm_tools("webfetch-only", with_url=True) == ("WebFetch", ["WebFetch"])
    assert agents.arm_tools("jevfetch-only", with_url=True) == ("Bash", ["Bash(jevfetch:*)"])
    assert agents.paired_arms(["webfetch-only", "jevfetch-only"]) == ("jevfetch-only", ["webfetch-only"])
    assert agents.paired_arms(["webfetch", "webfetch-haiku45", "jevfetch"]) == (
        "jevfetch",
        ["webfetch", "webfetch-haiku45"],
    )


def test_regrade_votes_three_times_per_answer_without_the_arm_and_resumes(tmp_path, monkeypatch, capsys):
    items = [{"id": "q1", "question": "Which flag?", "expected_answer": "The X flag, because of a regression."}]
    (tmp_path / "items.json").write_text(json.dumps(items))
    runs = tmp_path / "run" / "agents"
    runs.mkdir(parents=True)
    for arm, answer in (("webfetch-only", "The Y flag."), ("jevfetch-only", "The X flag.")):
        write_jsonl(runs / f"q1__{arm}__0.jsonl", [{"type": "assistant"}, {"type": "result", "result": answer}])
    prompts = []

    def ask(prompt, key="sufficient"):
        prompts.append(prompt)
        return key == "correct" and "The X flag." in prompt.split("ANSWER:")[-1], 0.01

    monkeypatch.setattr(webcode, "ask", ask)
    args = SimpleNamespace(out=str(tmp_path / "run"), items=str(tmp_path / "items.json"), concurrency=2)
    webcode.regrade(args)
    out = capsys.readouterr().out
    assert len(prompts) == 6 and not any("webfetch" in p or "jevfetch" in p for p in prompts)
    assert "jevfetch-only: correct 1/1" in out and "webfetch-only: correct 0/1" in out
    webcode.regrade(args)
    assert len(prompts) == 6  # every vote is in, so nothing is asked again


def test_regrade_asks_again_when_an_answer_changes(tmp_path, monkeypatch, capsys):
    items = [{"id": "q1", "question": "Which flag?", "expected_answer": "The X flag."}]
    (tmp_path / "items.json").write_text(json.dumps(items))
    runs = tmp_path / "run" / "agents"
    runs.mkdir(parents=True)
    trace = runs / "q1__jevfetch-only__0.jsonl"
    write_jsonl(trace, [{"type": "result", "result": "The X flag."}])
    asked = []

    def ask(prompt, key="sufficient"):
        asked.append(prompt)
        return "The X flag." in prompt.split("ANSWER:")[-1], 0.0

    monkeypatch.setattr(webcode, "ask", ask)
    args = SimpleNamespace(out=str(tmp_path / "run"), items=str(tmp_path / "items.json"), concurrency=1)
    webcode.regrade(args)
    write_jsonl(trace, [{"type": "result", "result": "The Y flag."}])
    webcode.regrade(args)
    assert len(asked) == 6 and "jevfetch-only: correct 0/1" in capsys.readouterr().out.splitlines()[-2]


def test_regrade_skips_the_traces_of_failed_attempts(tmp_path, monkeypatch, capsys):
    items = [{"id": "q1", "question": "Which flag?", "expected_answer": "The X flag."}]
    (tmp_path / "items.json").write_text(json.dumps(items))
    runs = tmp_path / "run" / "agents"
    runs.mkdir(parents=True)
    write_jsonl(runs / "q1__jevfetch-only__0.jsonl", [{"type": "result", "result": "The X flag."}])
    write_jsonl(runs / "q1__jevfetch-only__0.attempt0.failed.jsonl", [{"type": "result", "result": "limit reached"}])
    asked = []

    def ask(prompt, key="sufficient"):
        asked.append(prompt)
        return True, 0.0

    monkeypatch.setattr(webcode, "ask", ask)
    webcode.regrade(SimpleNamespace(out=str(tmp_path / "run"), items=str(tmp_path / "items.json"), concurrency=1))
    assert len(asked) == 3 and not any("limit reached" in p for p in asked)
    assert "jevfetch-only: correct 1/1" in capsys.readouterr().out


def test_ask_takes_only_a_true_or_false_verdict(monkeypatch):
    replies = iter(['{"correct": "false"}', '{"correct": null}', '{"correct": false}'])

    def run(cmd, **kw):
        return SimpleNamespace(stdout=json.dumps({"result": next(replies), "total_cost_usd": 0.01}))

    monkeypatch.setattr(webcode.subprocess, "run", run)
    assert webcode.ask("prompt", key="correct") == (False, pytest.approx(0.03))


def test_summary_times_the_items_every_reader_fetched_apart_from_all_items(tmp_path, capsys):
    def reader(failed, seconds):
        return {
            "fetch_failed": failed,
            "excerpt": not failed,
            "text": "t",
            "tokens": 10,
            "seconds": seconds,
            "cost": 0.0,
        }

    rows = [
        {"id": "a", "set": "highlights", "web": reader(False, 2.0), "jev": reader(False, 1.0)},
        {"id": "b", "set": "highlights", "web": reader(True, 5.0), "jev": reader(False, 3.0)},
    ]
    write_jsonl(tmp_path / "rows.jsonl", rows)
    write_jsonl(tmp_path / "judge.jsonl", [])
    webcode.summary(SimpleNamespace(out=str(tmp_path)))
    out = capsys.readouterr().out
    assert "seconds 1.0; over all 2 items: tokens 20, seconds 4.0" in out
    assert "seconds 2.0; over all 2 items: tokens 20, seconds 7.0" in out
