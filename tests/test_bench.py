import argparse

import httpx
import pytest

import bench.__main__ as bench_main
from bench import compare, matching, runner
from jevfetch.blocks import Block, render
from jevfetch.jev import Jev, JevError


def test_emphasis_markers_wrapping_a_token_are_stripped_but_inner_underscores_stay():
    assert matching.strip_emphasis("set `maxsize` to _None_ or *True*") == "set maxsize to None or True"
    assert matching.strip_emphasis("max_size and __init__") == "max_size and __init__"


def test_link_markup_is_unwrapped_to_its_text():
    assert matching.strip_emphasis("returns a [named tuple](../glossary.html#term-named-tuple) showing") == (
        "returns a named tuple showing"
    )
    assert matching.strip_emphasis("see [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259) and [x](y)") == (
        "see RFC 8259 and x"
    )
    assert matching.strip_emphasis("a[1] (note)") == "a[1] (note)"
    assert matching.key_in_text("shell injection", "avoid [shell injection](https://x/y) vulnerabilities")


def test_fact_matches_across_whitespace_and_emphasis_but_keeps_punctuation_and_case():
    blocks = ["If _maxsize_ is set to `None`,  the LRU feature is\ndisabled."]
    assert matching.fact_in_blocks("If maxsize is set to None, the LRU feature is disabled.", blocks)
    assert not matching.fact_in_blocks("If maxsize is set to None the LRU feature is disabled.", blocks)
    assert not matching.fact_in_blocks("if maxsize is set to none, the lru feature is disabled.", blocks)


def test_ordered_spans_must_all_appear_in_order_inside_one_block():
    spans = ["Standard", "3,000 messages per second"]
    assert matching.fact_in_blocks(spans, ["Standard | 3,000 messages per second | 256 KB"])
    assert not matching.fact_in_blocks(spans, ["3,000 messages per second | Standard"])
    assert not matching.fact_in_blocks(spans, ["Standard", "3,000 messages per second"])


def test_heading_lines_are_dropped_before_fact_matching():
    text = "## Limits > Throughput\nStandard | 3,000 messages per second\n## Retention\nkept 4 days"
    blocks = matching.output_blocks(text)
    assert blocks == ["Standard | 3,000 messages per second", "kept 4 days"]


def test_output_blocks_keeps_a_block_whose_body_has_a_heading_like_line():
    blocks = [
        Block(id=0, path=["A"], text="alpha\n## body comment\nomega", kind="p"),
        Block(id=1, path=["A"], text="beta", kind="p"),
        Block(id=2, path=["B"], text="gamma", kind="p"),
    ]
    assert matching.output_blocks(render(blocks), blocks) == [b.text for b in blocks]
    assert matching.output_blocks(render(blocks, keep={1, 2}), blocks) == ["beta", "gamma"]
    assert matching.output_blocks(render(blocks, keep={0, 2}), blocks) == [blocks[0].text, "gamma"]


def test_squad_normalize_lowercases_and_drops_punctuation_and_articles():
    assert matching.squad_normalize("The cache's  size: 256 KB!") == "caches size 256 kb"


def test_key_matches_as_contiguous_token_sequence_not_substring():
    assert matching.key_in_text("grow without bound", "the cache can grow without bound.")
    assert not matching.key_in_text("10", "limit is 100 items")
    assert matching.key_in_text("10", "limit is 10 items")


def test_key_alias_group_passes_when_any_alias_matches():
    assert matching.key_group_in_text(["256 KB", "256KB"], "maximum size is 256KB")
    assert not matching.key_group_in_text(["256 KB", "256KB"], "maximum size is 256 kilobytes")


def test_exact_key_keeps_punctuation():
    assert not matching.key_group_in_text([{"text": "-1", "exact": True}], "returns 1 on success")
    assert matching.key_group_in_text([{"text": "-1", "exact": True}], "returns -1 on failure")
    assert matching.key_group_in_text(["-1"], "returns 1 on success")  # non-exact keys lose the sign


def test_preflight_checks_existence_ignoring_all_whitespace():
    raw = "The maximum\n   message size is 256 KB."
    assert matching.in_raw_text("maximum message size is 256 KB", raw)
    assert matching.in_raw_text("size is256KB", raw)
    assert not matching.in_raw_text("size is 512 KB", raw)


def case(**over):
    base = {
        "id": "c1",
        "snapshot_sha256": "abc",
        "question": "q?",
        "expected_status": "filtered",
        "status": "filtered",
        "facts": {"f1": True, "f2": True},
        "keys": {"k1": True},
        "extraction": {"f1": True, "f2": True},
        "out_tokens": 100,
        "workload": 1000,
    }
    base.update(over)
    return base


def baseline(*cases, model="jev-1.13.0"):
    return {"schema": 1, "model": {"requested": model, "resolved": model}, "cases": {c["id"]: c for c in cases}}


def run(*cases, model="jev-1.13.0", missing=()):
    return {
        "model": {"requested": model, "resolved": model},
        "cases": {c["id"]: c for c in cases},
        "missing_recordings": list(missing),
    }


def failures(base, cur, update_baseline=False):
    return [f.rule for f in compare.compare(base, cur, update_baseline=update_baseline)]


def test_identical_runs_produce_no_failures():
    assert failures(baseline(case()), run(case())) == []


def test_lost_fact_fails():
    assert "lost_fact" in failures(baseline(case()), run(case(facts={"f1": True, "f2": False})))


def test_fact_that_failed_in_baseline_may_still_fail():
    assert failures(baseline(case(facts={"f1": True, "f2": False})), run(case(facts={"f1": True, "f2": False}))) == []


def test_lost_key_fails():
    assert "lost_key" in failures(baseline(case()), run(case(keys={"k1": False})))


def test_status_mismatch_fails():
    assert "status" in failures(baseline(case()), run(case(status="no_match")))


def test_status_is_checked_for_a_case_missing_from_the_baseline():
    assert "status" in failures(baseline(case(id="a")), run(case(id="a"), case(id="new", status="no_match")))


def test_extraction_drop_fails():
    assert "extraction" in failures(baseline(case()), run(case(extraction={"f1": True, "f2": False})))


def test_aggregate_overrun_counts_only_common_cases():
    base = baseline(case(id="a", out_tokens=900), case(id="b", out_tokens=100))
    ok = run(case(id="a", out_tokens=1000), case(id="b", out_tokens=100), case(id="new", out_tokens=5000))
    assert "aggregate_out_tokens" not in failures(base, ok)
    bad = run(case(id="a", out_tokens=1101), case(id="b", out_tokens=100))
    assert "aggregate_out_tokens" in failures(base, bad)


def test_aggregate_workload_overrun_fails():
    base = baseline(case(id="a", workload=1000), case(id="b", workload=1000))
    assert "aggregate_workload" in failures(base, run(case(id="a", workload=1300), case(id="b", workload=1000)))


def test_single_case_overrun_fails_even_when_aggregate_is_fine():
    base = baseline(case(id="a", out_tokens=900), case(id="b", out_tokens=100))
    cur = run(case(id="a", out_tokens=700), case(id="b", out_tokens=300))
    assert "case_out_tokens" in failures(base, cur)
    assert "aggregate_out_tokens" not in failures(base, cur)


def test_missing_case_fails_and_new_case_is_only_noted():
    assert "missing_case" in failures(baseline(case(id="a"), case(id="b")), run(case(id="a")))
    assert failures(baseline(case(id="a")), run(case(id="a"), case(id="new"))) == []


def test_removed_fact_fails():
    assert "removed_fact" in failures(baseline(case()), run(case(facts={"f1": True})))


def test_identity_change_fails_unless_updating_baseline():
    for change in ({"question": "other?"}, {"snapshot_sha256": "zzz"}):
        assert "identity" in failures(baseline(case()), run(case(**change)))
        assert "identity" not in failures(baseline(case()), run(case(**change)), update_baseline=True)


def test_model_mismatch_fails_even_when_updating_baseline():
    assert "model" in failures(baseline(case()), run(case(), model="jev-2.0.0"))
    assert "model" in failures(baseline(case()), run(case(), model="jev-2.0.0"), update_baseline=True)


def test_missing_recordings_fail_even_when_updating_baseline():
    assert "missing_recording" in failures(baseline(case()), run(case(), missing=["deadbeef"]))
    assert "missing_recording" in failures(baseline(case()), run(case(), missing=["deadbeef"]), update_baseline=True)


def test_regressions_are_reported_but_allowed_when_updating_baseline():
    found = compare.compare(baseline(case()), run(case(facts={"f1": False, "f2": True})), update_baseline=True)
    assert [f.rule for f in found] == ["lost_fact"]
    assert all(not f.blocking for f in found)


async def test_replay_mode_reports_missing_recording_instead_of_calling_the_api(monkeypatch, tmp_path):
    async def boom(*a, **k):
        raise AssertionError("network call attempted in replay mode")

    monkeypatch.setattr(httpx.AsyncClient, "post", boom)
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy")
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(tmp_path))
    doc = "# T\n\n" + "\n\n".join(f"paragraph {i} " + "word " * 150 for i in range(20))
    res = await runner.run_case_async({"id": "x", "question": "q?"}, doc, record=False)
    assert res["missing_recording"] is True
    assert res["status"] is None


async def test_record_mode_raises_on_api_failure_instead_of_reporting_a_missing_recording(monkeypatch, tmp_path):
    async def unauthorized(self, body):
        raise JevError("401: unauthorized")

    monkeypatch.setattr(Jev, "_post", unauthorized)
    monkeypatch.setenv("TYPESAFE_API_KEY", "dummy")
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(tmp_path))
    doc = "# T\n\n" + "\n\n".join(f"paragraph {i} " + "word " * 150 for i in range(20))
    with pytest.raises(JevError):
        await runner.run_case_async({"id": "x", "question": "q?"}, doc, record=True)


def test_unknown_case_id_is_a_usage_error():
    with pytest.raises(SystemExit):
        bench_main.main(["--cases", "nope"])


def test_set_parses_booleans_and_passes_model_through():
    ap = argparse.ArgumentParser()
    assert bench_main.parse_overrides(["render_fallback=false"], ap) == {"render_fallback": False}
    assert bench_main.parse_overrides(["render_fallback=1", "model=x"], ap) == {"render_fallback": True, "model": "x"}
    with pytest.raises(SystemExit):
        bench_main.parse_overrides(["render_fallback=maybe"], ap)
    with pytest.raises(SystemExit):
        bench_main.parse_overrides(["nope=1"], ap)


def test_prune_removes_recordings_the_run_did_not_use(tmp_path):
    from bench.__main__ import prune_recordings

    for name in ("keep1", "keep2", "stale"):
        (tmp_path / f"{name}.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("x")
    assert prune_recordings(tmp_path, {"keep1", "keep2"}) == ["stale.json"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["keep1.json", "keep2.json", "notes.txt"]
