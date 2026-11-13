"""uv run python -m bench.agents run|judge|report RESULTS [--reps 2] [--concurrency 2] [--cases ID,...]

Agent-level comparison: Claude Code answers each of the 20 questions in bench/agents/questions.json twice, once
with WebFetch and once with jevfetch as its page reader, searching the web itself. The arms share the task prompt
and the tool set apart from the reader; the jevfetch arm gets skills/jevfetch/SKILL.md as its instructions, the
WebFetch arm bench/agents/webfetch.md. Answers are graded with the rubric in bench/agents/rubric.py; judge
elements go to a Sonnet judge that sees the answer with reader names redacted, three votes, majority. This is a
manual, paid run outside CI; see bench/README.md."""

import argparse
import asyncio
import hashlib
import json
import os
import random
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from bench.agents import analysis
from bench.agents.rubric import RUBRIC
from bench.runner import PRICE_PER_MTOK

ROOT = analysis.ROOT
REPO = ROOT.parent.parent
ORCHESTRATOR = "sonnet"
SMALL_MODEL: str | None = None
MAX_TURNS = 40
RUN_TIMEOUT_S = 900
VOTES = 3
PROMPT = (
    "다음 질문에 웹에서 확인한 사실로 답해줘. 수치와 적용 조건을 빠짐없이 적고, 근거로 쓴 출처 URL 을 함께 적어줘.\n\n"
    "질문: {q}"
)
PROMPT_WITH_URL = (
    "다음 질문에 이 페이지에서 확인한 사실로 답해줘. 수치와 적용 조건을 빠짐없이 적고, 근거로 쓴 출처 URL 을 함께 "
    "적어줘.\n\n페이지: {url}\n질문: {q}"
)
PROMPT_EN = (
    "Answer the following question with facts verified on the web. Include every number and every applicable "
    "condition, and give the source URLs you used.\n\nQuestion: {q}"
)
PROMPT_WITH_URL_EN = (
    "Answer the following question with facts verified on this page. Include every number and every applicable "
    "condition, and give the source URLs you used.\n\nPage: {url}\nQuestion: {q}"
)
JUDGE_PROMPT = """Below is an ANSWER written for a question, and a list of STATEMENTS.
For each statement, decide whether the ANSWER text itself states that content (in any language or wording).
Use only the ANSWER text. Do not use your own knowledge.
If the answer says it could not confirm something, it does not state it.
Reply with JSON only: {{"<statement id>": true or false, ...}}

QUESTION: {q}

STATEMENTS:
{s}

ANSWER:
{a}"""
ARMS = {
    "webfetch": {
        "tools": "WebSearch,WebFetch,Bash",
        "allowed": ["WebSearch", "WebFetch", "Bash(curl:*)", "Bash(grep:*)", "Bash(head:*)"],
        "instructions": ROOT / "webfetch.md",
    },
    "webfetch-haiku45": {  # the same arm with the reader model WebFetch used before Haiku 5.5
        "tools": "WebSearch,WebFetch,Bash",
        "allowed": ["WebSearch", "WebFetch", "Bash(curl:*)", "Bash(grep:*)", "Bash(head:*)"],
        "instructions": ROOT / "webfetch.md",
        "small_model": "claude-haiku-4-5-20251001",
    },
    "jevfetch": {
        "tools": "WebSearch,Bash",
        "allowed": ["WebSearch", "Bash(curl:*)", "Bash(grep:*)", "Bash(head:*)", "Bash(jevfetch:*)"],
        "instructions": REPO / "skills" / "jevfetch" / "SKILL.md",
    },
    # The same two arms with the reader as the only way to read a page: no curl, grep or head to fall back on.
    "webfetch-only": {
        "tools": "WebSearch,WebFetch",
        "allowed": ["WebSearch", "WebFetch"],
        "instructions": ROOT / "webfetch.md",
    },
    "jevfetch-only": {
        "tools": "WebSearch,Bash",
        "allowed": ["WebSearch", "Bash(jevfetch:*)"],
        "instructions": REPO / "skills" / "jevfetch" / "SKILL.md",
    },
}
DEFAULT_ARMS = ("webfetch", "jevfetch")


CONFIG_KEYS = (
    "instructions_sha1",
    "tools",
    "allowed",
    "lang",
    "with_url",
    "small_model",
    "model",
    "max_turns",
    "concurrency",
    "prompt",
    "seed",
)
ARM_ORDER = tuple(ARMS)  # report order; `main` trims ARMS to the arms being run


def config_mismatch(old: dict, expected: dict) -> list[str]:
    """Configuration keys on which a recorded run differs from what this invocation would run."""
    return [k for k in CONFIG_KEYS if old.get(k) != expected.get(k)]


def paired_arms(arms: list[str]) -> tuple[str | None, list[str]]:
    """The jevfetch arm ("jevfetch" or "jevfetch-only") and the WebFetch arms it is compared with."""
    subject = next((a for a in arms if a.startswith("jevfetch")), None)
    return subject, [a for a in arms if a.startswith("webfetch")] if subject else []


def arms_present(rows: list[dict]) -> list[str]:
    known = [a for a in ARM_ORDER if any(r["arm"] == a for r in rows)]
    return known + sorted({r["arm"] for r in rows} - set(ARM_ORDER))


def concurrency_note(rows: list[dict]) -> str:
    seen = {r.get("concurrency") for r in rows}
    if None in seen:
        return "concurrency not recorded for some runs, so durations may not be single-session latency"
    if seen == {1}:
        return "runs were executed one at a time (concurrency 1)"
    levels = ", ".join(str(c) for c in sorted(seen))
    return f"runs were executed with concurrency {levels}, so this is not single-session latency"


def paired_stats(rows: list[dict], ref: str, arm: str, seed: int) -> dict | None:
    """jevfetch-style paired ratios of `arm` against `ref`, clustered by question; None without a common question."""
    cost, secs, facts = {}, {}, {}
    for q in sorted({r["case"] for r in rows}):
        a = [r for r in rows if r["arm"] == ref and r["case"] == q and r["finished"] and r["cost_with_jev"] is not None]
        b = [r for r in rows if r["arm"] == arm and r["case"] == q and r["finished"] and r["cost_with_jev"] is not None]
        if a and b:
            cost[q] = ([r["cost_with_jev"] for r in a], [r["cost_with_jev"] for r in b])
            secs[q] = ([r["seconds"] for r in a], [r["seconds"] for r in b])
        ag = [r["grade"]["right"] for r in rows if r["arm"] == ref and r["case"] == q and r["grade"]]
        bg = [r["grade"]["right"] for r in rows if r["arm"] == arm and r["case"] == q and r["grade"]]
        if ag and bg:
            facts[q] = (ag, bg)
    if not cost:
        return None
    return {
        "questions": len(cost),
        "cost": analysis.paired_ratio_ci(cost, seed=seed),
        "time": analysis.paired_ratio_ci(secs, seed=seed),
        "facts": analysis.paired_diff_ci(facts, seed=seed) if facts else None,
    }


def arm_env(arm: str, small_model: str | None) -> dict:
    """The arm's own small model wins over the command-line override; neither leaves the default."""
    env = {}
    model = ARMS[arm].get("small_model") or small_model
    if model:
        env["ANTHROPIC_SMALL_FAST_MODEL"] = model  # the model WebFetch (and Claude Code's background calls) use
    return env


def arm_tools(arm: str, with_url: bool) -> tuple[str, list[str]]:
    """Tool list and allow rules; with a URL given, the agent gets no WebSearch."""
    a = ARMS[arm]
    if not with_url:
        return a["tools"], a["allowed"]
    tools = ",".join(x for x in a["tools"].split(",") if x != "WebSearch")
    return tools, [x for x in a["allowed"] if x != "WebSearch"]


def build_command(case: dict, arm: str, with_url: bool, lang: str = "ko") -> list[str]:
    query = case.get(f"query_{lang}") or case["query"]
    templates = {
        ("ko", False): PROMPT,
        ("ko", True): PROMPT_WITH_URL,
        ("en", False): PROMPT_EN,
        ("en", True): PROMPT_WITH_URL_EN,
    }
    prompt = templates[(lang, with_url)].format(url=case["url"], q=query)
    tools, allowed = arm_tools(arm, with_url)
    cmd = ["claude", "-p", prompt, "--safe-mode", "--model", ORCHESTRATOR]
    cmd += ["--tools", tools, "--allowedTools", *allowed, "--append-system-prompt", instructions(arm)]
    cmd += ["--no-session-persistence", "--output-format", "stream-json", "--verbose", "--max-turns", str(MAX_TURNS)]
    return cmd


def instructions(arm: str) -> str:
    text = Path(ARMS[arm]["instructions"]).read_text()
    return text.split("---", 2)[2].strip() if text.startswith("---") else text.strip()


def jevfetch_revision() -> dict:
    """The checkout's HEAD, and whether jevfetch/ or skills/ differ from it: the agent runs this checkout's
    `.venv/bin/jevfetch` and reads its SKILL.md."""
    git = ["git", "-C", str(REPO)]
    rev = subprocess.run([*git, "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    status = subprocess.run([*git, "status", "--porcelain", "--", "jevfetch", "skills"], capture_output=True, text=True)
    return {"revision": rev.stdout.strip(), "revision_dirty": bool(status.stdout.strip())}


QUESTIONS = ROOT / "questions.json"  # --questions replaces it, and --rubric replaces RUBRIC, for another suite


def questions(ids: set[str] | None) -> list[dict]:
    qs = json.loads(QUESTIONS.read_text())
    return [q for q in qs if not ids or q["id"] in ids]


def run_name(case: str, arm: str, rep: int) -> str:
    return f"{case}__{arm}__{rep}"


async def run_one(
    results: Path,
    sem: asyncio.Semaphore,
    case: dict,
    arm: str,
    rep: int,
    with_url: bool,
    lang: str,
    concurrency: int,
    seed: int,
) -> None:
    name = run_name(case["id"], arm, rep)
    out = results / "agents" / f"{name}.jsonl"
    meta_path = results / "agents" / f"{name}.meta.json"
    cmd = build_command(case, arm, with_url, lang)
    tools, allowed = arm_tools(arm, with_url)
    config = {
        "instructions": str(ARMS[arm]["instructions"]),
        "instructions_sha1": hashlib.sha1(instructions(arm).encode()).hexdigest()[:10],
        "prompt": cmd[2],
        "tools": tools,
        "allowed": allowed,
        "model": ORCHESTRATOR,
        "max_turns": MAX_TURNS,
        "with_url": with_url,
        "lang": lang,
        "small_model": arm_env(arm, SMALL_MODEL).get("ANTHROPIC_SMALL_FAST_MODEL"),
        "concurrency": concurrency,
        "seed": seed,
    }
    if out.exists() and analysis.run_metrics(out.read_text().splitlines(), ORCHESTRATOR)["finished"]:
        old = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        if diff := config_mismatch(old, config):
            sys.exit(f"{name} exists with a different configuration ({', '.join(diff)}); use a fresh results directory")
        return
    workdir = results / "work" / name
    workdir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "JEVFETCH_CACHE_DIR": str(results / "jev" / name),
        "PATH": f"{REPO / '.venv' / 'bin'}:{os.environ.get('PATH', '')}",  # the jevfetch under test
        **arm_env(arm, SMALL_MODEL),
    }
    for attempt in range(2):  # one retry for API errors only; every attempt's trace is kept
        async with sem:
            t0 = time.perf_counter()
            with out.open("w") as f:
                p = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=workdir,
                    stdout=f,
                    stderr=asyncio.subprocess.DEVNULL,
                    stdin=asyncio.subprocess.DEVNULL,
                    env=env,
                )
                try:
                    await asyncio.wait_for(p.wait(), timeout=RUN_TIMEOUT_S)
                    timed_out = False
                except TimeoutError:
                    p.kill()
                    await p.wait()
                    timed_out = True
        wall = round(time.perf_counter() - t0, 1)
        meta_path.write_text(
            json.dumps(
                {
                    "attempt": attempt,
                    "wall_seconds": wall,
                    "timed_out": timed_out,
                    "returncode": p.returncode,
                    **config,
                    **jevfetch_revision(),
                },
                ensure_ascii=False,
            )
        )
        m = analysis.run_metrics(out.read_text().splitlines(), ORCHESTRATOR)
        if m["finished"] or timed_out or attempt == 1:
            break  # the last attempt stays as the run's trace even when it did not finish
        out.rename(results / "agents" / f"{name}.attempt{attempt}.failed.jsonl")
    print(name, "ok" if m["finished"] else "timed out" if timed_out else "no result", f"{wall}s", flush=True)


async def run(
    results: Path, reps: int, concurrency: int, ids: set[str] | None, seed: int, with_url: bool, lang: str
) -> None:
    (results / "agents").mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    rng = random.Random(seed)
    jobs = []
    for rep in range(reps):
        for case in questions(ids):
            arms = list(ARMS)
            rng.shuffle(arms)  # arm order is random within each (question, rep) block
            jobs.append([(case, arm, rep) for arm in arms])
    rng.shuffle(jobs)  # block order is random too, so no arm runs systematically earlier in the session
    jobs = [j for block in jobs for j in block]
    schedule = results / "schedule.json"
    earlier = json.loads(schedule.read_text()) if schedule.exists() else []
    schedule.write_text(json.dumps(earlier + [[c["id"], a, r] for c, a, r in jobs]))
    tasks = [asyncio.create_task(run_one(results, sem, c, a, r, with_url, lang, concurrency, seed)) for c, a, r in jobs]
    await asyncio.gather(*tasks)


def traces(results: Path) -> list[Path]:
    return sorted(p for p in (results / "agents").glob("*__*__*.jsonl") if ".attempt" not in p.name)


async def ask_judge(sem: asyncio.Semaphore, prompt: str) -> tuple[dict | None, float]:
    cmd = ["claude", "-p", prompt, "--safe-mode", "--model", ORCHESTRATOR, "--tools", "", "--no-session-persistence"]
    cmd += ["--output-format", "json"]
    cost = 0.0
    for _ in range(3):
        async with sem:
            p = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                stdin=asyncio.subprocess.DEVNULL,
            )
            out, _ = await p.communicate()
        try:
            res = json.loads(out.decode().strip().splitlines()[-1])
            cost += res.get("total_cost_usd") or 0
            text = res["result"]
            return json.loads(text[text.find("{") : text.rfind("}") + 1]), cost
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            continue
    return None, cost


async def judge(results: Path, concurrency: int, seed: int) -> None:
    qs = {q["id"]: q for q in questions(None)}
    (results / "grade").mkdir(exist_ok=True)
    sem = asyncio.Semaphore(concurrency)
    todo = []
    for trace in traces(results):
        case = trace.stem.split("__")[0]
        statements = [(eid, el[1]) for eid, el, _ in analysis.elements(RUBRIC[case]) if el[0] == "judge"]
        m = analysis.run_metrics(trace.read_text().splitlines(), ORCHESTRATOR)
        if not statements or not m["finished"]:
            continue
        for vote in range(VOTES):
            if not (results / "grade" / f"{trace.stem}.{vote}.json").exists():
                todo.append((trace.stem, case, statements, analysis.redact(m["answer"]), vote))
    random.Random(seed).shuffle(todo)  # grading order must not reveal the arm

    async def one(stem, case, statements, answer, vote):
        s = "\n".join(f"- {eid}: {text}" for eid, text in statements)
        meta_path = results / "agents" / f"{stem}.meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        lang = meta.get("lang") or qs[case].get("lang", "ko")
        query = qs[case].get(f"query_{lang}") or qs[case]["query"]
        verdicts, cost = await ask_judge(sem, JUDGE_PROMPT.format(q=query, s=s, a=answer))
        if verdicts is not None and set(verdicts) >= {eid for eid, _ in statements}:
            (results / "grade" / f"{stem}.{vote}.json").write_text(json.dumps({"verdicts": verdicts, "cost": cost}))
            print(stem, vote, "graded", flush=True)
        else:
            print(stem, vote, "NO VERDICT", flush=True)

    await asyncio.gather(*(one(*t) for t in todo))


def grade(results: Path, trace: Path) -> dict | None:
    """Facts right for one run, or None while a judge vote is missing."""
    case = trace.stem.split("__")[0]
    m = analysis.run_metrics(trace.read_text().splitlines(), ORCHESTRATOR)
    judged = [eid for eid, el, _ in analysis.elements(RUBRIC[case]) if el[0] == "judge"]
    votes = []
    for v in range(VOTES if judged and m["finished"] else 0):
        f = results / "grade" / f"{trace.stem}.{v}.json"
        if not f.exists():
            return None
        votes.append(json.loads(f.read_text())["verdicts"])
    verdicts = {eid: sum(bool(v[eid]) for v in votes) * 2 > len(votes) for eid in judged}
    split = [eid for eid in judged if votes and len({bool(v[eid]) for v in votes}) > 1]
    right, total = analysis.score(m["answer"], RUBRIC[case], verdicts) if m["finished"] else (0, len(RUBRIC[case]))
    return {
        "right": right,
        "total": total,
        "split": split,
        "judge_cost": sum(
            json.loads((results / "grade" / f"{trace.stem}.{v}.json").read_text())["cost"] for v in range(len(votes))
        ),
    }


LANG: dict[str, str] = {}
PAGE_TOKENS: dict[str, int] = {}


def collect(results: Path) -> list[dict]:
    LANG.update({q["id"]: q.get("lang", "ko") for q in questions(None)})
    PAGE_TOKENS.update({q["id"]: q["page_tokens"] for q in questions(None) if q.get("page_tokens")})
    rows = []
    for trace in traces(results):  # page size comes from the jevfetch arm's header and is shared by the question
        m = analysis.run_metrics(trace.read_text().splitlines(), ORCHESTRATOR)
        if m["page_tokens"]:
            case = trace.stem.split("__")[0]
            PAGE_TOKENS[case] = max(PAGE_TOKENS.get(case, 0), m["page_tokens"])
    for trace in traces(results):
        case, arm, rep = trace.stem.split("__")
        m = analysis.run_metrics(trace.read_text().splitlines(), ORCHESTRATOR)
        meta_path = results / "agents" / f"{trace.stem}.meta.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        jev = analysis.jev_usage(results / "jev" / trace.stem)
        g = grade(results, trace)
        failed = list((results / "agents").glob(f"{trace.stem}.attempt*.failed.jsonl"))
        failed_cost = sum(analysis.run_metrics(f.read_text().splitlines(), ORCHESTRATOR)["cost"] or 0 for f in failed)
        rows.append(
            {
                "case": case,
                "arm": arm,
                "rep": int(rep),
                **m,
                "answer": m["answer"],
                "votes": [
                    json.loads(f.read_text())["verdicts"]
                    for f in sorted((results / "grade").glob(f"{trace.stem}.*.json"))
                ]
                if (results / "grade").is_dir()
                else [],
                "answer_sha1": hashlib.sha1(m["answer"].encode()).hexdigest()[:12],
                "jev_input_tokens": jev["input_tokens"],
                "jev_requests": jev["requests"],
                "jev_models": jev["models"],
                "jev_cost": jev["input_tokens"] * PRICE_PER_MTOK / 1e6,
                "cost_with_jev": (m["cost"] + jev["input_tokens"] * PRICE_PER_MTOK / 1e6)
                if m["cost"] is not None
                else None,
                "timed_out": meta.get("timed_out", False),
                "wall_seconds": meta.get("wall_seconds"),
                "failed_attempts": len(failed),
                "failed_attempt_cost": failed_cost,
                "instructions_sha1": meta.get("instructions_sha1"),
                "revision": meta.get("revision"),
                "revision_dirty": meta.get("revision_dirty", False),
                "with_url": meta.get("with_url", False),
                "small_model": meta.get("small_model"),
                "concurrency": meta.get("concurrency"),
                "seed": meta.get("seed"),
                "lang": meta.get("lang") or LANG.get(case, "ko"),
                "bucket": analysis.size_bucket(PAGE_TOKENS.get(case)),
                "allowed": meta.get("allowed"),
                "grade": g,
            }
        )
    return rows


def fmt(x, digits=4):
    return "-" if x is None else f"{x:.{digits}f}"


def report(results: Path, seed: int) -> str:
    rows = collect(results)
    if not rows:
        sys.exit("no runs in " + str(results))
    ungraded = [r for r in rows if r["finished"] and r["grade"] is None]
    arms = arms_present(rows)
    by_arm = {a: [r for r in rows if r["arm"] == a] for a in arms}
    recorded = sorted({r["revision"] for r in rows if r.get("revision")})
    if recorded:
        git_rev, dirty = ", ".join(recorded), any(r["revision_dirty"] for r in rows)
    else:  # runs made before the revision was recorded per run
        head = jevfetch_revision()
        git_rev, dirty = f"{head['revision']} (checkout HEAD when the report was generated)", head["revision_dirty"]
    claude_version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    models = sorted({m for r in rows for m in r["models"]})
    jev_models = sorted({m for r in rows for m in r["jev_models"]})
    versions_seen = sorted({r["claude_version"] for r in rows if r["claude_version"]})

    def mean(a, key):
        vals = [r[key] for r in by_arm[a] if r.get(key) is not None]
        return statistics.mean(vals) if vals else None

    def median(a, key):
        vals = [r[key] for r in by_arm[a] if r.get(key) is not None]
        return statistics.median(vals) if vals else None

    def facts(a):
        gs = [r["grade"] for r in by_arm[a] if r["grade"] is not None]
        return sum(g["right"] for g in gs), sum(g["total"] for g in gs)

    lines = [
        f"# Agent-level comparison, {datetime.now().strftime('%Y-%m-%d')}",
        "",
        f"- Claude Code `claude --version`: {claude_version}; versions seen in traces: "
        f"{', '.join(versions_seen) or 'n/a'}; orchestrator model: {ORCHESTRATOR}; "
        f"models billed: {', '.join(models) or 'n/a'}; Jev models: {', '.join(jev_models) or 'n/a'}",
        f"- jevfetch revision {git_rev}{' (uncommitted changes in jevfetch/ or skills/)' if dirty else ''}; "
        "instruction sha1 recorded at run time: "
        + ", ".join(f"{a} {sorted({r['instructions_sha1'] for r in by_arm[a]})}" for a in arms)
        + "; allowed tools: "
        + "; ".join(f"{a} {sorted({' '.join(r['allowed'] or []) for r in by_arm[a]})}" for a in arms),
        "- mode: "
        + ", ".join(sorted({"URL given, no WebSearch" if r.get("with_url") else "no URL, WebSearch" for r in rows}))
        + "; question language: "
        + ", ".join(sorted({r["lang"] for r in rows}))
        + "; small model override: "
        + ", ".join(sorted({str(r.get("small_model")) for r in rows})),
        f"- questions: {len({r['case'] for r in rows})}; runs per arm: "
        + ", ".join(f"{a} {len(by_arm[a])}" for a in arms)
        + "; schedule seed "
        + ", ".join(sorted({str(r.get("seed")) for r in rows}))
        + f"; bootstrap seed {seed}; arm order randomized within each (question, repetition) block, block order random",
        "- failures: "
        + ", ".join(
            f"{a}: {sum(not r['finished'] for r in by_arm[a])} unfinished, "
            f"{sum(r['timed_out'] for r in by_arm[a])} timed out, "
            f"{sum(r['subtype'] == 'error_max_turns' for r in by_arm[a])} hit the turn limit, "
            f"{sum(r['failed_attempts'] for r in by_arm[a])} retried API errors "
            f"(${sum(r['failed_attempt_cost'] for r in by_arm[a]):.4f} spent on failed attempts, not in the means), "
            f"{sum(r['denied_calls'] > 0 for r in by_arm[a])} runs with a Bash command refused "
            "(allow rules or variable check)"
            for a in arms
        ),
        f"- ungraded finished runs: {len(ungraded)}" if ungraded else "- all finished runs graded",
        "- Cost: `total_cost_usd` of the `claude -p` run (main model plus WebFetch's reader model) plus, for jevfetch, "
        "the Jev input tokens actually sent during the run (one recording per request in the run's own cache) "
        f"at ${PRICE_PER_MTOK}/Mtok. Time: the run's `duration_ms`. Unfinished runs count as zero facts and are "
        "excluded from cost and time means. 'Of which Haiku' is every non-orchestrator model billed in the run: "
        "WebFetch's reader and Claude Code's own background calls, which occur in both arms.",
        "",
        "## Summary",
        "",
        "| arm | rubric facts matched / checked | runs finished | mean cost per question (USD) | of which main model "
        "| of which Haiku | of which Jev | median seconds | mean seconds | mean turns | main-agent input tokens "
        "| main-agent output tokens | reader calls per run | curl calls (runs) | runs with a refused command |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in arms:
        right, total = facts(a)
        fin = [r for r in by_arm[a] if r["finished"]]
        reader_calls = statistics.mean(r["jevfetch_calls"] + r["webfetch_calls"] for r in fin) if fin else None
        lines.append(
            f"| {a} | {right}/{total} | {len(fin)}/{len(by_arm[a])} | {fmt(mean(a, 'cost_with_jev'))} | "
            f"{fmt(mean(a, 'main_model_cost'))} | {fmt(mean(a, 'reader_model_cost'))} | {fmt(mean(a, 'jev_cost'))} | "
            f"{fmt(median(a, 'seconds'), 1)} | {fmt(mean(a, 'seconds'), 1)} | {fmt(mean(a, 'turns'), 2)} | "
            f"{fmt(mean(a, 'main_input_tokens'), 0)} | {fmt(mean(a, 'main_output_tokens'), 0)} | "
            f"{fmt(reader_calls, 2)} | "
            f"{sum(r['curl_calls'] for r in fin)} ({sum(r['curl_calls'] > 0 for r in fin)}) | "
            f"{sum(r['denied_calls'] > 0 for r in fin)} |"
        )
    subject, refs = paired_arms(arms)
    lines += [
        "",
        "## Paired comparison (jevfetch relative to each WebFetch arm, 95% bootstrap interval clustered by question)",
        "",
    ]
    for ref in refs:
        st = paired_stats(rows, ref, subject, seed)
        if st is None:
            continue
        est, lo, hi = st["cost"]
        lines.append(
            f"- vs {ref}, cost ratio: {est:.2f} (interval {lo:.2f} to {hi:.2f}), i.e. {abs(100 * (1 - est)):.0f}% "
            f"{'lower' if est < 1 else 'higher'}; {st['questions']} questions"
        )
        est, lo, hi = st["time"]
        lines.append(
            f"- vs {ref}, mean-time ratio: {est:.2f} (interval {lo:.2f} to {hi:.2f}); {concurrency_note(rows)}"
        )
        if st["facts"]:
            est, lo, hi = st["facts"]
            lines.append(f"- vs {ref}, facts right per run, difference: {est:+.2f} (interval {lo:+.2f} to {hi:+.2f})")
    if not refs:
        lines.append("- none (needs the jevfetch arm and at least one WebFetch arm)")
    lines += ["", "## By page size (extracted tokens: small < 5,000, medium < 20,000, large) and language", ""]
    lines += [
        "| bucket | lang | questions | arm | facts | mean cost | main model | Haiku | Jev | median s | mean turns "
        "| main input tok | main output tok | reader calls/run | curl calls (runs) | cost ratio (interval) "
        "| mean-time ratio (interval) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    groups = sorted({(r["bucket"], r["lang"]) for r in rows})
    for bucket, lang in groups:
        sub = [r for r in rows if r["bucket"] == bucket and r["lang"] == lang and r["finished"]]
        qids = sorted({r["case"] for r in sub})
        ratios = ("", "")
        if len(qids) >= 3 and refs:
            cost_cells, time_cells = [], []
            for ref in refs:
                st = paired_stats(sub, ref, subject, seed)
                if st is None or st["questions"] < len(qids):
                    continue
                tag = f" vs {ref}" if len(refs) > 1 else ""
                e, lo, hi = st["cost"]
                cost_cells.append(f"{e:.2f} ({lo:.2f} to {hi:.2f}){tag}")
                e, lo, hi = st["time"]
                time_cells.append(f"{e:.2f} ({lo:.2f} to {hi:.2f}){tag}")
            ratios = ("; ".join(cost_cells), "; ".join(time_cells))
        for a in arms:
            rs = [r for r in sub if r["arm"] == a]
            if not rs:
                continue
            gs = [r["grade"] for r in rs if r["grade"]]
            facts_cell = f"{sum(g['right'] for g in gs)}/{sum(g['total'] for g in gs)}"
            lines.append(
                f"| {bucket} | {lang} | {len(qids)} | {a} | {facts_cell} | "
                f"{fmt(statistics.mean(r['cost_with_jev'] for r in rs))} | "
                f"{fmt(statistics.mean(r['main_model_cost'] for r in rs))} | "
                f"{fmt(statistics.mean(r['reader_model_cost'] for r in rs))} | "
                f"{fmt(statistics.mean(r['jev_cost'] for r in rs))} | "
                f"{fmt(statistics.median(r['seconds'] for r in rs), 1)} | "
                f"{fmt(statistics.mean(r['turns'] for r in rs), 2)} | "
                f"{fmt(statistics.mean(r['main_input_tokens'] for r in rs), 0)} | "
                f"{fmt(statistics.mean(r['main_output_tokens'] for r in rs), 0)} | "
                f"{fmt(statistics.mean(r['jevfetch_calls'] + r['webfetch_calls'] for r in rs), 2)} | "
                f"{sum(r['curl_calls'] for r in rs)} ({sum(r['curl_calls'] > 0 for r in rs)}) | "
                f"{ratios[0] if a == subject else ''} | {ratios[1] if a == subject else ''} |"
            )
    splits = [(r["case"], r["arm"], r["rep"], r["grade"]["split"]) for r in rows if r["grade"] and r["grade"]["split"]]
    judged_runs = sum(
        1 for r in rows if r["grade"] and any(el[0] == "judge" for _, el, _ in analysis.elements(RUBRIC[r["case"]]))
    )
    lines += [
        "",
        f"## Judge votes that were not unanimous ({len(splits)} of {judged_runs} judged runs; "
        "review by hand before publishing)",
        "",
    ]
    lines += [f"- {c} {a} rep {rep}: {', '.join(s)}" for c, a, rep, s in splits] or ["- none"]
    lines += [
        "",
        "## Per run",
        "",
        "| question | size | lang | arm | rep | finished | facts | cost | Jev | seconds | turns | main input tok "
        "| jevfetch calls | WebFetch calls | curl calls | denied | answer sha1 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r["case"], r["rep"], r["arm"])):
        g = r["grade"]
        finished = "yes" if r["finished"] else ("timeout" if r["timed_out"] else "no")
        facts_cell = f"{g['right']}/{g['total']}" if g else "-"
        turns = r["turns"] if r["turns"] is not None else "-"
        main_in = r["main_input_tokens"] if r["main_input_tokens"] is not None else "-"
        lines.append(
            f"| {r['case']} | {r['bucket']} | {r['lang']} | {r['arm']} | {r['rep']} | {finished} | {facts_cell} | "
            f"{fmt(r['cost_with_jev'])} | "
            f"{fmt(r['jev_cost'])} | {fmt(r['seconds'], 1)} | {turns} | {main_in} | "
            f"{r['jevfetch_calls']} | {r['webfetch_calls']} | {r['curl_calls']} | {r['denied_calls']} | "
            f"{r['answer_sha1']} |"
        )
    text = "\n".join(lines) + "\n"
    (results / "report.md").write_text(text)
    (results / "runs.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    return text


def compare_sets(sets: list[tuple[Path, str]], seed: int = 0) -> dict:
    """Pair the finished runs of several (results dir, arm) sets by question; the first set is the reference."""
    loaded = []
    for d, arm in sets:
        rows = [r for r in json.loads((d / "runs.json").read_text()) if r["arm"] == arm and r["finished"]]
        loaded.append({q: [r for r in rows if r["case"] == q] for q in sorted({r["case"] for r in rows})})
    common = sorted(set.intersection(*(set(s) for s in loaded)))
    ref = loaded[0]
    out = {"questions": len(common), "facts": [], "cost": [], "median_seconds": [], "cost_ratio": [], "time_ratio": []}
    for s in loaded:
        rs = [r for q in common for r in s[q]]
        out["facts"].append((sum(r["grade"]["right"] for r in rs), sum(r["grade"]["total"] for r in rs)))
        out["cost"].append(statistics.mean(r["cost_with_jev"] for r in rs))
        out["median_seconds"].append(statistics.median(r["seconds"] for r in rs))
        pc = {q: ([r["cost_with_jev"] for r in ref[q]], [r["cost_with_jev"] for r in s[q]]) for q in common}
        pt = {q: ([r["seconds"] for r in ref[q]], [r["seconds"] for r in s[q]]) for q in common}
        out["cost_ratio"].append(analysis.paired_ratio_ci(pc, seed=seed))
        out["time_ratio"].append(analysis.paired_ratio_ci(pt, seed=seed))
    return out


def compare_text(sets: list[tuple[Path, str]], seed: int) -> str:
    o = compare_sets(sets, seed)
    lines = [
        f"{o['questions']} common questions; ratios are against the first set, paired by question",
        "| set | facts | mean cost | median s | cost ratio (interval) | mean-time ratio (interval) |",
        "|---|---|---|---|---|---|",
    ]
    for i, (d, arm) in enumerate(sets):
        c, t = o["cost_ratio"][i], o["time_ratio"][i]
        lines.append(
            f"| {d.name}:{arm} | {o['facts'][i][0]}/{o['facts'][i][1]} | {o['cost'][i]:.4f} | "
            f"{o['median_seconds'][i]:.1f} | "
            f"{c[0]:.2f} ({c[1]:.2f} to {c[2]:.2f}) | {t[0]:.2f} ({t[1]:.2f} to {t[2]:.2f}) |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench.agents", description=__doc__)
    ap.add_argument("command", choices=["run", "judge", "report", "compare"])
    ap.add_argument(
        "results",
        type=str,
        nargs="+",
        help="results directory; for compare, two or more DIR:arm pairs (first is the reference)",
    )
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--cases", help="comma-separated question ids")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--arms", help="comma-separated subset of arms to run (default: both)")
    ap.add_argument("--webfetch-instructions", type=Path, help="replace the WebFetch arm's instruction file")
    ap.add_argument("--with-url", action="store_true", help="give the agent the page URL and no WebSearch")
    ap.add_argument("--lang", choices=["ko", "en"], default="ko", help="language of the task prompt and question")
    ap.add_argument("--small-model", help="ANTHROPIC_SMALL_FAST_MODEL for the runs, e.g. claude-haiku-4-5-20251001")
    ap.add_argument("--questions", type=Path, help="question file to use instead of bench/agents/questions.json")
    ap.add_argument("--rubric", type=Path, help="JSON rubric {question id: {fact id: [element, ...]}} for --questions")
    args = ap.parse_args(argv)
    global SMALL_MODEL, QUESTIONS
    SMALL_MODEL = args.small_model
    if bool(args.questions) != bool(args.rubric):
        ap.error("--questions and --rubric go together")
    if args.questions:
        QUESTIONS = args.questions.resolve()
        RUBRIC.clear()
        RUBRIC.update(json.loads(args.rubric.read_text()))
    if args.command == "compare":
        sets = []
        for item in args.results:
            d, _, arm = item.partition(":")
            if not arm:
                ap.error("compare takes DIR:arm items")
            sets.append((Path(d).resolve(), arm))
        print(compare_text(sets, args.seed))
        return 0
    if len(args.results) != 1:
        ap.error("one results directory")
    if args.webfetch_instructions:
        ARMS["webfetch"]["instructions"] = args.webfetch_instructions.resolve()
    wanted = args.arms.split(",") if args.arms else list(DEFAULT_ARMS)
    if unknown := set(wanted) - set(ARMS):
        ap.error("unknown arm(s): " + ", ".join(sorted(unknown)))
    for arm in list(ARMS):
        if arm not in wanted:
            del ARMS[arm]
    results = Path(args.results[0]).resolve()
    ids = set(args.cases.split(",")) if args.cases else None
    if ids and (unknown := ids - {q["id"] for q in questions(None)}):
        ap.error("unknown question id(s): " + ", ".join(sorted(unknown)))
    if args.command == "run":
        asyncio.run(run(results, args.reps, args.concurrency, ids, args.seed, args.with_url, args.lang))
    elif args.command == "judge":
        asyncio.run(judge(results, args.concurrency, args.seed))
    else:
        print(report(results, args.seed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
