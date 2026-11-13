"""Compare jevfetch with Claude Code's built-in WebFetch on the bench cases, live, outside CI.

    uv run python bench/compare_webfetch.py [--runs 1] [--cases ID,...] [--parallel 3] [--no-continuation]

Both tools read the live URL. WebFetch is the real tool, driven through `claude -p` with everything but the
tool disabled; its result text, duration and model usage are read from the stream-json trace, and the trace
is kept under bench/reports/raw/. The comparison is observational: WebFetch fetches its own copy of the page,
so input equivalence is not proven. See bench/README.md."""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench import matching, runner
from jevfetch import tokens
from jevfetch.blocks import merge_fragments, parse, render
from jevfetch.cli import NOTES
from jevfetch.jev import Jev
from jevfetch.pipeline import Config, select_relevant_async
from jevfetch.web import fetch

ROOT = Path(__file__).parent
ORCHESTRATOR = "sonnet"
WINDOW = 100_000
MAX_WINDOWS = 5
NOTE = re.compile(r"\[WebFetch note: .*?offset: (\d+)\.\]", re.S)
CLAUDE_FLAGS = [
    "-p",
    "--model",
    ORCHESTRATOR,
    "--tools",
    "WebFetch",
    "--allowedTools",
    "WebFetch",
    "--max-turns",
    "2",
    "--setting-sources",
    "project",
    "--strict-mcp-config",
    "--disable-slash-commands",
    "--output-format",
    "stream-json",
    "--verbose",
]


def header(text: str, res) -> str:
    """The lines the jevfetch CLI prints before the text; they count as delivered context."""
    return (
        f"# jevfetch: {res.url}\n# status: {res.status} ({NOTES[res.status]})\n"
        f"# {res.blocks_kept}/{res.blocks_total} blocks, "
        f"{res.out_tokens} of {res.doc_tokens} tokens\n{text}"
    )


async def run_jevfetch(case: dict, html: str, model: str) -> dict:
    blocks = merge_fragments(parse(html))
    jev = Jev(model=model, use_cache=False)
    t0 = time.perf_counter()
    try:
        res = await select_relevant_async(blocks, case["question"], Config(model=model), jev)
    finally:
        await jev.aclose()
    seconds = time.perf_counter() - t0
    res.url = case["url"]
    kept = matching.output_blocks(res.text, blocks)
    delivered = header(res.text, res)
    return {
        "status": res.status,
        "facts": [matching.fact_in_blocks(f, kept) for f in case["facts"]],
        "keys": [matching.key_group_in_text(g, res.text) for g in case["keys"]],
        "tokens": tokens.count(delivered),
        "cost": jev.input_tokens * runner.PRICE_PER_MTOK / 1e6,
        "tool_seconds": round(seconds, 2),
        "jev_input_tokens": jev.input_tokens,
        "requests": jev.requests,
        "text": delivered,
    }


def claude_webfetch(case: dict, offset: int, raw_path: Path) -> dict:
    prompt = (
        f"Call the WebFetch tool exactly once with url {case['url']!r} and prompt {case['question']!r}"
        + (f" and offset {offset}" if offset else "")
        + ". Then reply with the tool's result text verbatim and nothing else. Do not call any tool a second time."
    )
    env = {**os.environ, "CLAUDE_CODE_WEBFETCH_CACHE_TTL_MS": "0"}
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(["claude", *CLAUDE_FLAGS, prompt], capture_output=True, text=True, env=env, timeout=300)
        stdout, stderr, returncode = proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired as e:
        stdout = e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        stderr = e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")
        returncode = None
    wall = time.perf_counter() - t0
    raw_path.write_text(stdout + stderr)
    calls, results, usage, tool_meta, version = [], [], {}, {}, None
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            version = ev.get("claude_code_version") or ev.get("version")
        if ev.get("type") == "assistant":
            calls += [c for c in ev["message"].get("content", []) if c.get("type") == "tool_use"]
        if ev.get("type") == "user":
            for c in ev["message"].get("content", []):
                if isinstance(c, dict) and c.get("type") == "tool_result":
                    content = c.get("content")
                    if isinstance(content, list):
                        content = "\n".join(x.get("text", "") for x in content if isinstance(x, dict))
                    results.append(content or "")
            if isinstance(ev.get("tool_use_result"), dict):
                tool_meta = ev["tool_use_result"]
        if ev.get("type") == "result":
            usage = ev.get("modelUsage") or {}
    valid = (
        len(calls) == 1
        and calls[0].get("name") == "WebFetch"
        and calls[0]["input"].get("url") == case["url"]
        and calls[0]["input"].get("prompt") == case["question"]
        and int(calls[0]["input"].get("offset") or 0) == offset
        and len(results) == 1
        and returncode == 0
    )
    orchestrator = {m for m in usage if ORCHESTRATOR in m}
    tool_models = [m for m in usage if m not in orchestrator]
    cost = sum(usage[m]["costUSD"] for m in tool_models) if tool_models and orchestrator else None
    return {
        "valid": valid,
        "text": results[0] if results else "",
        "calls": calls,
        "tool_models": tool_models,
        "cost": cost,
        "command_cost": sum(u.get("costUSD", 0) for u in usage.values()),
        "tool_seconds": (tool_meta.get("durationMs") or 0) / 1000,
        "wall_seconds": round(wall, 1),
        "bytes": tool_meta.get("bytes"),
        "version": version,
        "returncode": returncode,
    }


def webfetch_protocol(case: dict, continuation: bool, raw_dir: Path, run: int) -> dict:
    tag = "cont" if continuation else "single"
    offset, windows, invalid = 0, 0, 0
    cost, cmd_cost, tool_s, wall_s = 0.0, 0.0, 0.0, 0.0
    cost_known = True
    texts: list[str] = []
    models: set[str] = set()
    version = None
    while True:
        windows += 1
        r = claude_webfetch(case, offset, raw_dir / f"{case['id']}-r{run}-{tag}-w{windows}.jsonl")
        version = version or r["version"]
        models |= set(r["tool_models"])
        texts.append(r["text"])
        invalid += not r["valid"]
        cost_known &= r["cost"] is not None
        cost += r["cost"] or 0
        cmd_cost += r["command_cost"]
        tool_s += r["tool_seconds"]
        wall_s += r["wall_seconds"]
        m = NOTE.search(r["text"])
        if not continuation or not m or windows >= MAX_WINDOWS or not r["valid"]:
            break
        offset = int(m.group(1))
    text = "\n".join(texts)
    ok = invalid == 0
    return {
        "windows": windows,
        "truncated": bool(NOTE.search(texts[-1])),
        "valid": ok,
        "facts": [ok and matching.fact_in_blocks(f, [text]) for f in case["facts"]],
        "keys": [ok and matching.key_group_in_text(g, text) for g in case["keys"]],
        "tokens": tokens.count(text),
        "cost": cost if cost_known else None,
        "command_cost": cmd_cost,
        "tool_seconds": round(tool_s, 2),
        "wall_seconds": round(wall_s, 1),
        "tool_models": sorted(models),
        "version": version,
        "text": text,
    }


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return round(statistics.mean(vals), 4) if vals else None


def rate(flags: list[list[bool]]) -> float | None:
    flat = [x for f in flags for x in f]
    return round(sum(flat) / len(flat), 3) if flat else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--cases")
    ap.add_argument("--parallel", type=int, default=3, help="concurrent claude -p processes")
    ap.add_argument("--no-continuation", action="store_true")
    args = ap.parse_args(argv)

    baseline = json.loads((ROOT / "baseline.json").read_text())
    model = baseline["model"]["resolved"]
    cases = json.loads((ROOT / "cases.json").read_text())
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    today = dt.date.today().isoformat()
    raw_dir = ROOT / "reports" / "raw" / today
    raw_dir.mkdir(parents=True, exist_ok=True)

    pages, rows = {}, {}
    for case in cases:
        t0 = time.perf_counter()
        html = fetch(case["url"])
        fetch_seconds = round(time.perf_counter() - t0, 2)
        pages[case["id"]] = html
        live_sha = hashlib.sha256(html.encode()).hexdigest()
        snap_sha = baseline["cases"].get(case["id"], {}).get("snapshot_sha256")
        stale = runner.preflight(case, html)
        row = {
            "case": case["id"],
            "page": case["page"],
            "answerable": case.get("answerable", True),
            "hash_match": live_sha == snap_sha,
            "stale": bool(stale),
            "stale_detail": stale,
            "fetch_seconds": fetch_seconds,
            "whole_page_tokens": tokens.count(render(parse(html))),
            "jevfetch": [],
            "webfetch_single": [],
            "webfetch_continuation": [],
        }
        rows[case["id"]] = row
        if stale:
            continue
        for _ in range(args.runs):
            t0 = time.perf_counter()
            r = asyncio.run(run_jevfetch(case, html, model))
            r["wall_seconds"] = round(time.perf_counter() - t0, 1)
            r["seconds_with_fetch"] = round(row["fetch_seconds"] + r["tool_seconds"], 2)
            row["jevfetch"].append(r)
        print(
            f"jevfetch {case['id']}: {row['jevfetch'][-1]['status']} facts={row['jevfetch'][-1]['facts']}", flush=True
        )

    jobs = [(c, run) for c in cases if not rows[c["id"]]["stale"] for run in range(args.runs)]

    def do(job):
        case, run = job
        single = webfetch_protocol(case, continuation=False, raw_dir=raw_dir, run=run)
        if args.no_continuation:
            cont = None
        elif single["truncated"] and single["valid"]:
            cont = webfetch_protocol(case, continuation=True, raw_dir=raw_dir, run=run)
        else:
            cont = single  # not truncated: one window is the whole page; invalid: no continuation is attempted
        print(
            f"webfetch {case['id']} r{run}: single keys={single['keys']} valid={single['valid']}"
            + (f"; continuation windows={cont['windows']}" if cont else ""),
            flush=True,
        )
        return job, single, cont

    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for (case, _run), single, cont in pool.map(do, jobs):
            rows[case["id"]]["webfetch_single"].append(single)
            if cont:
                rows[case["id"]]["webfetch_continuation"].append(cont)

    git_rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    lock_sha = hashlib.sha256((ROOT.parent / "uv.lock").read_bytes()).hexdigest()[:16]
    claude_version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    tool_models = sorted(
        {
            m
            for r in rows.values()
            for p in ("webfetch_single", "webfetch_continuation")
            for x in r[p]
            for m in x["tool_models"]
        }
    )
    live = [r for r in rows.values() if not r["stale"]]
    pos = [r for r in live if r["answerable"]]
    live_pos_cases = [c for c in cases if c.get("answerable", True) and not rows[c["id"]]["stale"]]

    long_pages = [r for r in pos if any(x["truncated"] for x in r["webfetch_single"])]
    tools = [("WebFetch single call", "webfetch_single")]
    if not args.no_continuation:
        tools.append(("WebFetch continuation (max 5 windows)", "webfetch_continuation"))
    tools.append(("jevfetch", "jevfetch"))

    def col(name, rs, key):
        return [x[key] for r in rs for x in r[name]]

    def with_fetch(name):
        return "seconds_with_fetch" if name == "jevfetch" else "tool_seconds"

    def summary_row(label, name, rs):
        fact_rate = rate([x["facts"] for r in rs for x in r[name]])
        key_rate = rate([x["keys"] for r in rs for x in r[name]])
        invalid = sum(not x.get("valid", True) for r in rs for x in r[name])
        return (
            f"| {label} | {key_rate} | {fact_rate} | {mean(col(name, rs, 'tokens'))} | "
            f"{mean(col(name, rs, 'cost'))} | {mean(col(name, rs, 'tool_seconds'))} | "
            f"{mean(col(name, rs, with_fetch(name)))} | {invalid} |"
        )

    def page_macro_row(label, name, rs):
        by_page: dict[str, list[dict]] = {}
        for r in rs:
            by_page.setdefault(r["page"], []).append(r)
        key_means = [rate([x["keys"] for r in prs for x in r[name]]) for prs in by_page.values()]
        fact_means = [rate([x["facts"] for r in prs for x in r[name]]) for prs in by_page.values()]
        return f"| {label} (page macro) | {mean(key_means)} | {mean(fact_means)} | | | | | |"

    def totals_row(label, name, rs):
        costs = col(name, rs, "cost")
        cost = round(sum(costs), 4) if all(c is not None for c in costs) else None
        return f"| {label} (totals) | | | {sum(col(name, rs, 'tokens'))} | {cost} | | | |"

    def summary_table(rs):
        head = [
            "| tool | key coverage | facts quoted verbatim | delivered tokens | tool cost USD | tool seconds "
            "| tool seconds incl. fetch | invalid runs |",
            "|---|---|---|---|---|---|---|---|",
            f"| whole page (context-retention reference) | 1.0 | 1.0 | {mean(r['whole_page_tokens'] for r in rs)} "
            "| 0 | 0 | 0 | 0 |",
        ]
        body = [summary_row(label, name, rs) for label, name in tools]
        body += [page_macro_row(label, name, rs) for label, name in tools]
        body += [totals_row(label, name, rs) for label, name in tools]
        return head + body

    lines = [
        f"# WebFetch comparison, {today}",
        "",
        f"- Claude Code: {claude_version}; orchestrator model: {ORCHESTRATOR}; "
        f"WebFetch tool model(s) observed: {', '.join(tool_models) or 'n/a'}",
        f"- Jev model: {model} (cold, cache disabled); Jev price ${runner.PRICE_PER_MTOK}/Mtok input, output free",
        f"- jevfetch revision {git_rev}, uv.lock {lock_sha}",
        f"- runs per case: {args.runs}; cases: {len(cases)}; stale (gold no longer on live page, excluded): "
        f"{sum(r['stale'] for r in rows.values())}; "
        f"live page hash == snapshot: {sum(r['hash_match'] for r in live)}/{len(live)}",
        f"- denominators: facts {sum(len(c['facts']) for c in live_pos_cases)}, "
        f"keys {sum(len(c['keys']) for c in live_pos_cases)}, answerable cases {len(pos)}",
        "- Observational comparison: WebFetch fetches its own copy of the page; input equivalence is not proven. "
        "jevfetch tool seconds is fetch-free selection time and 'incl. fetch' adds jevfetch's own download; "
        "WebFetch latency is the tool's own durationMs, which includes its download. "
        "Command wall time and command cost (orchestrator included) are in the JSON next to this report.",
        "",
        "## Summary (answerable cases, mean over runs)",
        "",
        *summary_table(pos),
        "",
        f"## Long pages (single call truncated; {len(long_pages)} answerable cases, mean over runs)",
        "",
        *summary_table(long_pages),
        "",
        "## Per case (first run)",
        "",
        "| case | hash | whole page tok | WebFetch single: keys/facts/tok/windows "
        "| WebFetch cont.: keys/facts/tok/windows | jevfetch: status/keys/facts/tok |",
        "|---|---|---|---|---|---|",
    ]

    def cell(x, with_status=False):
        if not x:
            return "-"
        s = f"{sum(x['keys'])}/{len(x['keys'])} / {sum(x['facts'])}/{len(x['facts'])} / {x['tokens']}"
        if "windows" in x:
            s += f" / {x['windows']}{'+' if x['truncated'] else ''}"
        if with_status:
            s = f"{x['status']} / " + s
        return s + ("" if x.get("valid", True) else " (invalid)")

    for r in rows.values():
        if r["stale"]:
            lines.append(f"| {r['case']} | stale | | | | |")
            continue
        lines.append(
            f"| {r['case']} | {'=' if r['hash_match'] else '≠'} | {r['whole_page_tokens']} | "
            f"{cell(r['webfetch_single'][0] if r['webfetch_single'] else None)} | "
            f"{cell(r['webfetch_continuation'][0] if r['webfetch_continuation'] else None)} | "
            f"{cell(r['jevfetch'][0] if r['jevfetch'] else None, True)} |"
        )
    report = "\n".join(lines)
    out_md = ROOT / "reports" / f"webfetch-{today}.md"
    out_md.write_text(report + "\n")
    for r in rows.values():
        for name in ("jevfetch", "webfetch_single", "webfetch_continuation"):
            for x in r[name]:
                x["output_sha1"] = hashlib.sha1(x["text"].encode()).hexdigest()[:12]
    (ROOT / "reports" / f"webfetch-{today}.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    print(report)
    print(f"\nwrote {out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
