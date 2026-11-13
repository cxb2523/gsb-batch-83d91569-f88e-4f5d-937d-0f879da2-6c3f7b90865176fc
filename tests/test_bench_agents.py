import json

from bench.agents import analysis, rubric


def test_near_requires_every_pattern_within_the_window():
    assert analysis.near("the limit is 6 hours for GitHub-hosted runners", [r"GitHub[- ]?hosted", r"6\s*hours?"], 200)
    assert not analysis.near(
        "GitHub-hosted runners. " + "x " * 300 + "6 hours", [r"GitHub[- ]?hosted", r"6\s*hours?"], 50
    )
    assert not analysis.near("6 hours only", [r"GitHub[- ]?hosted", r"6\s*hours?"], 200)


def test_fact_is_right_only_when_every_required_element_holds():
    facts = {
        "f1": [("re", r"TimeoutExpired"), ("judge", "The exception is raised after the child terminated.")],
        "f2": [("re", r"never"), ("re", r"optional-thing", False)],
    }
    text = "TimeoutExpired is raised; it never happens otherwise."
    assert analysis.score(text, facts, {"f1#1": True}) == (2, 2)
    assert analysis.score(text, facts, {"f1#1": False}) == (1, 2)
    assert analysis.score("nothing", facts, {"f1#1": True}) == (0, 2)


def test_rubric_covers_every_question_and_judge_elements_are_sentences():
    questions = json.loads((analysis.ROOT / "questions.json").read_text())
    assert set(rubric.RUBRIC) == {q["id"] for q in questions}
    for facts in rubric.RUBRIC.values():
        for _eid, el, _required in analysis.elements(facts):
            assert el[0] in ("re", "near", "judge")
            if el[0] == "judge":
                assert el[1].endswith(".")


def test_redaction_hides_which_reader_wrote_the_answer():
    text = "I used jevfetch and WebFetch, then curl; see web_fetch output."
    assert analysis.redact(text) == "I used [tool] and [tool], then [tool]; see [tool] output."


def trace(*events: dict) -> list[str]:
    return [json.dumps(e) for e in events]


def assistant(*items: dict) -> dict:
    return {"type": "assistant", "message": {"content": list(items)}}


def bash(command: str) -> dict:
    return {"type": "tool_use", "name": "Bash", "input": {"command": command}}


def test_run_metrics_count_reader_invocations_anywhere_in_a_bash_command():
    lines = trace(
        {"type": "system", "subtype": "init", "claude_code_version": "2.1.294"},
        assistant(bash("jevfetch https://a 'q1' & jevfetch https://b 'q2'; wait")),
        assistant({"type": "tool_use", "name": "WebFetch", "input": {"url": "https://c", "prompt": "p"}}),
        assistant(bash("cd /tmp && curl -sL https://d | head")),
        {
            "type": "result",
            "subtype": "success",
            "result": "answer",
            "total_cost_usd": 0.05,
            "duration_ms": 12000,
            "num_turns": 3,
            "usage": {"input_tokens": 10, "cache_creation_input_tokens": 20, "cache_read_input_tokens": 30},
            "modelUsage": {
                "claude-sonnet-5-5": {"costUSD": 0.04, "outputTokens": 700},
                "claude-haiku-5-5": {"costUSD": 0.01, "outputTokens": 50},
            },
        },
    )
    m = analysis.run_metrics(lines, orchestrator="sonnet")
    assert m["finished"] and m["answer"] == "answer"
    assert m["jevfetch_calls"] == 2 and m["webfetch_calls"] == 1 and m["curl_calls"] == 1
    assert m["cost"] == 0.05 and m["reader_model_cost"] == 0.01 and m["main_input_tokens"] == 60
    assert m["main_model_cost"] == 0.04 and m["main_output_tokens"] == 700
    assert m["seconds"] == 12.0 and m["turns"] == 3 and m["claude_version"] == "2.1.294"


def test_run_without_a_result_event_is_unfinished_and_max_turns_counts_as_no_answer():
    assert analysis.run_metrics(trace(assistant(bash("ls"))), orchestrator="sonnet")["finished"] is False
    m = analysis.run_metrics(
        trace(
            {"type": "result", "subtype": "error_max_turns", "is_error": True, "total_cost_usd": 0.2, "duration_ms": 1}
        ),
        orchestrator="sonnet",
    )
    assert m["finished"] is True and m["answer"] == ""
    api = trace({"type": "result", "subtype": "error", "is_error": True, "api_error_status": 529})
    assert analysis.run_metrics(api, orchestrator="sonnet")["finished"] is False


def test_jev_cost_sums_fresh_requests_recorded_in_the_run_cache(tmp_path):
    d = tmp_path / "jev"
    d.mkdir()
    (d / "a.json").write_text(json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 1000}, "answers": {}}))
    (d / "b.json").write_text(json.dumps({"model": "jev-1.13.0", "usage": {"input_tokens": 500}, "answers": {}}))
    assert analysis.jev_usage(tmp_path) == {"input_tokens": 1500, "requests": 2, "models": ["jev-1.13.0"]}
    assert analysis.jev_usage(tmp_path / "missing") == {"input_tokens": 0, "requests": 0, "models": []}


def test_paired_bootstrap_interval_contains_the_point_estimate_and_is_clustered_by_question():
    per_question = {"q1": ([1.0, 1.2], [0.5, 0.6]), "q2": ([2.0, 2.2], [1.0, 1.1]), "q3": ([1.0, 1.0], [0.5, 0.5])}
    est, lo, hi = analysis.paired_ratio_ci(per_question, samples=500, seed=1)
    assert abs(est - 0.5) < 0.02 and lo <= est <= hi
    est_d, lo_d, hi_d = analysis.paired_diff_ci({"q1": ([3, 3], [2, 3]), "q2": ([2, 2], [2, 2])}, samples=500, seed=1)
    assert lo_d <= est_d <= hi_d and abs(est_d - (-0.25)) < 1e-9


def test_run_metrics_count_denied_bash_commands_and_distinguish_them_from_page_text():
    denied = {
        "type": "user",
        "message": {
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": "This Bash command contains multiple operations. "
                    "The following part requires approval: grep -o x",
                }
            ]
        },
    }
    page = {
        "type": "user",
        "message": {
            "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "the page says permission denied"}]
        },
    }
    lines = trace(
        assistant({"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "curl x | grep -o x"}}),
        denied,
        assistant({"type": "tool_use", "id": "t2", "name": "Bash", "input": {"command": "curl y"}}),
        page,
        {"type": "result", "subtype": "success", "result": "a", "total_cost_usd": 0.01, "duration_ms": 1},
    )
    m = analysis.run_metrics(lines, orchestrator="sonnet")
    assert m["denied_calls"] == 1 and m["curl_calls"] == 2


def test_mean_seconds_is_reported_next_to_the_median():
    lines = trace({"type": "result", "subtype": "success", "result": "a", "total_cost_usd": 0.01, "duration_ms": 4000})
    assert analysis.run_metrics(lines, orchestrator="sonnet")["seconds"] == 4.0


def test_with_url_mode_gives_the_page_and_removes_web_search():
    from bench.agents.__main__ import build_command

    case = {"id": "q", "url": "https://example.com/doc", "query": "질문?", "query_ko": "질문?", "query_en": "Question?"}
    cmd = build_command(case, "webfetch", with_url=True)
    prompt = cmd[2]
    assert "https://example.com/doc" in prompt and "질문?" in prompt and "답해줘" in prompt
    en = build_command(case, "webfetch", with_url=True, lang="en")[2]
    assert "Question?" in en and "질문?" not in en and "Answer" in en
    assert cmd[cmd.index("--tools") + 1] == "WebFetch,Bash"
    assert "WebSearch" not in cmd[cmd.index("--allowedTools") : cmd.index("--append-system-prompt")]
    cmd = build_command(case, "jevfetch", with_url=True)
    assert cmd[cmd.index("--tools") + 1] == "Bash"
    cmd = build_command(case, "jevfetch", with_url=False)
    assert cmd[cmd.index("--tools") + 1] == "WebSearch,Bash" and "https://example.com/doc" not in cmd[2]


def test_page_tokens_are_read_from_the_jevfetch_header_and_bucketed_by_size():
    lines = trace(
        assistant({"type": "tool_use", "id": "b1", "name": "Bash", "input": {"command": "jevfetch u q"}}),
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "b1",
                        "content": "# jevfetch: u\n# status: filtered (x)\n# 17/155 blocks, 4504 of 13262 tokens\ntext",
                    }
                ]
            },
        },
        {"type": "result", "subtype": "success", "result": "a", "total_cost_usd": 0.01, "duration_ms": 1},
    )
    assert analysis.run_metrics(lines, orchestrator="sonnet")["page_tokens"] == 13262
    assert analysis.size_bucket(13262) == "medium" and analysis.size_bucket(2000) == "small"
    assert analysis.size_bucket(33000) == "large" and analysis.size_bucket(None) == "?"


def test_compare_pairs_two_result_sets_by_question(tmp_path):
    from bench.agents.__main__ import compare_sets

    def runs(arm, cost, secs, right):
        return [
            {
                "case": q,
                "arm": arm,
                "rep": r,
                "finished": True,
                "cost_with_jev": cost,
                "seconds": secs,
                "grade": {"right": right, "total": 2},
                "lang": "ko",
                "bucket": "small",
            }
            for q in ("q1", "q2", "q3")
            for r in (0, 1)
        ]

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "runs.json").write_text(json.dumps(runs("webfetch", 0.04, 20.0, 2)))
    (b / "runs.json").write_text(json.dumps(runs("jevfetch", 0.03, 10.0, 1)))
    out = compare_sets([(a, "webfetch"), (b, "jevfetch")], seed=1)
    assert out["questions"] == 3 and out["facts"] == [(12, 12), (6, 12)]
    assert abs(out["cost_ratio"][1][0] - 0.75) < 1e-9 and abs(out["time_ratio"][1][0] - 0.5) < 1e-9
    assert out["cost_ratio"][0][0] == 1.0  # the first set is the reference


def test_an_arm_can_pin_its_own_small_model_and_the_env_carries_it():
    from bench.agents.__main__ import ARMS, arm_env

    assert ARMS["webfetch-haiku45"]["small_model"] == "claude-haiku-4-5-20251001"
    assert ARMS["webfetch-haiku45"]["tools"] == ARMS["webfetch"]["tools"]
    assert arm_env("webfetch-haiku45", None)["ANTHROPIC_SMALL_FAST_MODEL"] == "claude-haiku-4-5-20251001"
    assert "ANTHROPIC_SMALL_FAST_MODEL" not in arm_env("webfetch", None)
    assert arm_env("webfetch", "claude-haiku-4-5-20251001")["ANTHROPIC_SMALL_FAST_MODEL"] == "claude-haiku-4-5-20251001"


def test_denied_commands_are_counted_for_plural_and_singular_refusals():
    denied = "This Bash command contains multiple operations. The following parts require approval: mkdir -p x"
    assert analysis.DENIED.search(denied)
    assert analysis.DENIED.search(
        "This Bash command contains multiple operations. The following part requires approval: sed"
    )
    assert not analysis.DENIED.search("the docs page lists repository permissions and approval workflows")
    assert analysis.DENIED.search("A variable in this command can't be checked before it runs.")


def test_resume_refuses_a_finished_run_made_with_another_configuration():
    from bench.agents.__main__ import config_mismatch

    expected = {
        "instructions_sha1": "abc",
        "tools": "Bash",
        "allowed": ["Bash(curl:*)"],
        "lang": "ko",
        "with_url": True,
        "small_model": None,
        "model": "sonnet",
        "max_turns": 40,
    }
    assert config_mismatch({**expected}, expected) == []
    assert config_mismatch({**expected, "lang": "en"}, expected) == ["lang"]
    assert config_mismatch({**expected, "concurrency": 2}, {**expected, "concurrency": 1}) == ["concurrency"]
    assert config_mismatch({**expected, "prompt": "a", "seed": 1}, {**expected, "prompt": "b", "seed": 2}) == [
        "prompt",
        "seed",
    ]
    assert config_mismatch({**expected, "instructions_sha1": "zzz", "small_model": "h45"}, expected) == [
        "instructions_sha1",
        "small_model",
    ]


def _rows(arm, cost, secs, right, concurrency=1):
    return [
        {
            "case": q,
            "arm": arm,
            "rep": r,
            "finished": True,
            "cost_with_jev": cost,
            "seconds": secs,
            "grade": {"right": right, "total": 2},
            "lang": "ko",
            "bucket": "small",
            "concurrency": concurrency,
        }
        for q in ("q1", "q2", "q3")
        for r in (0, 1)
    ]


def test_report_covers_every_arm_present_and_pairs_jevfetch_with_each_reference():
    from bench.agents.__main__ import arms_present, paired_stats

    rows = (
        _rows("jevfetch", 0.03, 10.0, 1) + _rows("webfetch-haiku45", 0.06, 20.0, 2) + _rows("webfetch", 0.04, 20.0, 2)
    )
    assert arms_present(rows) == ["webfetch", "webfetch-haiku45", "jevfetch"]
    s = paired_stats(rows, "webfetch-haiku45", "jevfetch", seed=1)
    assert s["questions"] == 3
    assert abs(s["cost"][0] - 0.5) < 1e-9 and abs(s["time"][0] - 0.5) < 1e-9 and abs(s["facts"][0] + 1.0) < 1e-9
    assert paired_stats(_rows("jevfetch", 0.03, 10.0, 1), "webfetch", "jevfetch", seed=1) is None


def test_time_note_states_the_recorded_concurrency():
    from bench.agents.__main__ import concurrency_note

    assert "concurrency 1" in concurrency_note(_rows("jevfetch", 0.03, 10.0, 1))
    assert "not single-session" not in concurrency_note(_rows("jevfetch", 0.03, 10.0, 1))
    assert "not single-session latency" in concurrency_note(_rows("jevfetch", 0.03, 10.0, 1, concurrency=2))
    assert "not recorded" in concurrency_note(_rows("jevfetch", 0.03, 10.0, 1, concurrency=None))


def test_jevfetch_revision_names_the_checkout():
    from bench.agents.__main__ import jevfetch_revision

    rev = jevfetch_revision()
    assert set(rev) == {"revision", "revision_dirty"}
    assert len(rev["revision"]) >= 7 and int(rev["revision"], 16) >= 0
    assert isinstance(rev["revision_dirty"], bool)
