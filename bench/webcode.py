"""Compare jevfetch with Claude Code's WebFetch on Exa's WebCode items (github.com/exa-labs/benchmarks, MIT),
with search held fixed: both readers get the item's URL and question.

    uv run python bench/webcode.py convert --data DIR --preflight F --rawcheck F --out DIR
    uv run python bench/webcode.py tools OUT --items F [--ids A,B] [--sets highlights] [--thresholds 0.3,0.6]
    uv run python bench/webcode.py judge OUT --items F [--concurrency 4]
    uv run python bench/webcode.py summary OUT
    uv run python bench/webcode.py regrade AGENTS_OUT --items F [--concurrency 4]

`convert` keeps an item when its citation excerpt was found on the page, either in jevfetch's rendering
(preflight) or in the raw HTML (rawcheck). It writes the items, a question file and rubric for bench.agents, the
excluded items with their reason, and the excluded items whose page refused the fetch (blocked.json), which `tools`
can run to compare fetching alone. `tools` runs, per item and one after another, WebFetch through `claude -p` (one
call, plus continuation windows when the first is truncated) and jevfetch at each candidate threshold. `judge` asks
a Sonnet judge whether each returned text holds the expected answer: one vote per distinct text, then two more for
every text of an item on which the texts' verdicts differ. `regrade` grades the answers of a bench.agents run on
these items again, three votes each, asking whether the answer gives what the question asks: the rubric holds the
whole expected answer, and its judge also fails an answer that leaves out explanation the question did not ask for.
This is a manual, paid run outside CI."""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bench.compare_webfetch import header, webfetch_protocol
from bench.runner import PRICE_PER_MTOK
from jevfetch import tokens
from jevfetch.jev import Jev
from jevfetch.pipeline import Config, fetch_relevant_async

REPO = Path(__file__).resolve().parent.parent
WORD = re.compile(r"[A-Za-z0-9]+")
HEADER_LINE = re.compile(r"^# (jevfetch: |status: |error: |\d+/\d+ blocks, )")
WEBFETCH_FAILED = re.compile(r"returned HTTP [45]\d\d|failed to fetch|unable to fetch|could not (be )?fetch", re.I)
BLOCK_PAGE = re.compile(r"\b(403|429)\b|forbidden|access denied|just a moment|captcha|verify you are human", re.I)
JUDGE = """Below is a QUESTION, its REFERENCE ANSWER, and a TEXT that a page reader returned for the question.
Decide whether the TEXT itself contains the information needed to give the reference answer, in any wording.
Use only the TEXT. Do not use your own knowledge.
Reply with JSON only: {{"sufficient": true or false}}

QUESTION: {q}

REFERENCE ANSWER: {a}

TEXT:
{t}"""
# The expected answers often explain more than their question asks; an answer is not wrong for leaving that out.
ANSWER_JUDGE = """Below is a QUESTION, its REFERENCE ANSWER, and an ANSWER written by an assistant.
Decide whether the ANSWER answers the QUESTION correctly. The REFERENCE ANSWER is correct. It may explain more than
the QUESTION asks for; the ANSWER does not need that extra explanation. The ANSWER is wrong if it leaves out,
contradicts or misstates what the QUESTION asks for.
Reply with JSON only: {{"correct": true or false}}

QUESTION: {q}

REFERENCE ANSWER: {a}

ANSWER:
{t}"""
VOTES = 3


def norm(text: str) -> str:
    return " ".join(WORD.findall(text.lower()))


def has_excerpt(excerpt: str, text: str) -> bool:
    return norm(excerpt) in norm(text)


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def exclusion_reason(pre: dict, raw: dict | None) -> str:
    """Why an item was left out: the fetch result of the preflight, then of the raw re-fetch."""
    if pre["status"] != "ok":
        return f"jevfetch fetch failed: {pre.get('error', pre['status'])}"
    if raw and raw.get("raw_status") not in (None, 200):
        return f"excerpt not in jevfetch's rendering; raw fetch HTTP {raw['raw_status']}"
    return "excerpt neither in jevfetch's rendering nor in the raw HTML"


def convert(args) -> None:
    data = Path(args.data)
    pre = {r["id"]: r for r in load(Path(args.preflight))}
    raw = {r["id"]: r for r in load(Path(args.rawcheck))}
    found = {i for i, r in pre.items() if r["status"] == "ok" and r["excerpt"]}
    found |= {i for i, r in raw.items() if r.get("raw_excerpt")}
    items, excluded, blocked = [], [], []
    for name in args.sets.split(","):
        for it in load(data / f"{name}.jsonl"):
            item = {
                "id": it["id"],
                "set": name,
                "url": it.get("citation_url") or it.get("source_url"),
                "question": it["query"],
                "excerpt": it["citation_excerpt"],
                "expected_answer": it["expected_answer"],
            }
            if it["id"] in found:
                items.append(item)
                continue
            reason = exclusion_reason(pre[it["id"]], raw.get(it["id"]))
            excluded.append({"id": it["id"], "set": name, "url": item["url"], "reason": reason})
            if re.search(r"\b(403|429)\b", reason):
                blocked.append(item)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1))
    (out / "excluded.json").write_text(json.dumps(excluded, ensure_ascii=False, indent=1))
    (out / "blocked.json").write_text(json.dumps(blocked, ensure_ascii=False, indent=1))
    questions = [{"id": i["id"], "url": i["url"], "query": i["question"], "lang": "en", "gold": []} for i in items]
    (out / "questions.json").write_text(json.dumps(questions, ensure_ascii=False, indent=1))
    rubric = {i["id"]: {"f1": [["judge", i["expected_answer"]]]} for i in items}
    (out / "rubric.json").write_text(json.dumps(rubric, ensure_ascii=False, indent=1))
    by_set = ", ".join(f"{s} {sum(i['set'] == s for i in items)}" for s in ("highlights", "rag"))
    print(f"{len(items)} items ({by_set}), {len(excluded)} excluded, {len(blocked)} of them blocked")


async def jevfetch_once(item: dict, threshold: float) -> dict:
    jev = Jev(use_cache=False)
    t0 = time.perf_counter()
    try:
        res = await fetch_relevant_async(item["url"], item["question"], Config(candidate_threshold=threshold), jev)
    finally:
        await jev.aclose()
    seconds = time.perf_counter() - t0
    failed = res.status == "fetch_error" or (res.doc_tokens < 500 and bool(BLOCK_PAGE.search(res.text)))
    text = header(res.text, res) if res.status != "fetch_error" else f"# jevfetch: {item['url']}\n# error: {res.error}"
    return {
        "status": res.status,
        "error": res.error,
        "fetch_failed": failed,
        "text": text,
        "tokens": tokens.count(text),
        "excerpt": not failed and has_excerpt(item["excerpt"], res.text),
        "seconds": round(seconds, 2),
        "jev_input_tokens": jev.input_tokens,
        "requests": jev.requests,
        "cost": jev.input_tokens * PRICE_PER_MTOK / 1e6,
        "model": res.model,
    }


def webfetch_row(item: dict, r: dict) -> dict:
    failed = not r["valid"] or bool(WEBFETCH_FAILED.search(r["text"][:400]))
    return {
        "valid": r["valid"],
        "fetch_failed": failed,
        "windows": r["windows"],
        "truncated": r["truncated"],
        "text": r["text"],
        "tokens": r["tokens"],
        "excerpt": not failed and has_excerpt(item["excerpt"], r["text"]),
        "seconds": r["tool_seconds"],
        "wall_seconds": r["wall_seconds"],
        "cost": r["cost"],
        "command_cost": r["command_cost"],
        "tool_models": r["tool_models"],
        "version": r["version"],
    }


def webfetch(item: dict, raw_dir: Path) -> dict:
    case = {"id": item["id"], "url": item["url"], "question": item["question"], "facts": [], "keys": []}
    single = webfetch_protocol(case, continuation=False, raw_dir=raw_dir, run=0)
    out = {"webfetch_single": webfetch_row(item, single)}
    if single["truncated"] and single["valid"]:
        out["webfetch_cont"] = webfetch_row(item, webfetch_protocol(case, continuation=True, raw_dir=raw_dir, run=0))
    else:  # one window was the whole page: the continuation protocol would return the same text
        out["webfetch_cont"] = {**out["webfetch_single"], "same_as": "webfetch_single"}
    return out


def run_config(args, items: list[dict]) -> dict:
    """What a results directory was produced with; a rerun into it must match. The code is hashed from the files
    themselves, so uncommitted and untracked changes count."""
    code = hashlib.sha1()
    for path in sorted(
        [*(REPO / "jevfetch").glob("*.py"), REPO / "bench" / "webcode.py", REPO / "bench" / "compare_webfetch.py"]
    ):
        code.update(path.read_bytes())
    return {
        "thresholds": args.thresholds,
        "items_sha1": hashlib.sha1(json.dumps(items, sort_keys=True).encode()).hexdigest()[:12],
        "code_sha1": code.hexdigest()[:12],
    }


def tools(args) -> None:
    out = Path(args.out)
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    items = json.loads(Path(args.items).read_text())
    if args.sets:
        items = [i for i in items if i["set"] in args.sets.split(",")]
    if args.ids:
        items = [i for i in items if i["id"] in args.ids.split(",")]
    config = run_config(args, items)
    cfg_path = out / "config.json"
    old = json.loads(cfg_path.read_text()) if cfg_path.exists() else None
    if old is None and load(out / "rows.jsonl"):
        sys.exit(f"{out} holds results without a recorded configuration; use a fresh directory")
    if old is not None and old != config:
        diff = ", ".join(k for k in config if old.get(k) != config[k])
        sys.exit(f"{out} was produced with a different configuration ({diff}); use a fresh directory")
    cfg_path.write_text(json.dumps(config, indent=1))
    done = {r["id"] for r in load(out / "rows.jsonl")}
    thresholds = [float(x) for x in args.thresholds.split(",")]

    def one(item):  # the readers of one item run back to back, so they fetch the page at nearly the same time
        row = {"id": item["id"], "set": item["set"], "url": item["url"], "started": dt.datetime.now().isoformat()}
        row.update(webfetch(item, raw_dir))
        for th in thresholds:
            row[f"jevfetch_{th}"] = asyncio.run(jevfetch_once(item, th))
        return row

    with ThreadPoolExecutor(max_workers=args.parallel) as pool, (out / "rows.jsonl").open("a") as f:
        for row in pool.map(one, [i for i in items if i["id"] not in done]):
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(row["id"], {k: v["excerpt"] for k, v in readers(row).items()}, flush=True)


def readers(row: dict) -> dict:
    return {k: v for k, v in row.items() if isinstance(v, dict)}


def distinct_texts(row: dict) -> tuple[dict[str, str], dict[str, str]]:
    """The texts to judge for one item, keyed by the first reader that returned each (jevfetch's header lines
    removed), and every reader's key into them: readers that returned the same text share one verdict."""
    texts: dict[str, str] = {}
    owner: dict[str, str] = {}
    for k, v in readers(row).items():
        body = "\n".join(ln for ln in v["text"].splitlines() if not HEADER_LINE.match(ln))
        owner[k] = next((j for j, t in texts.items() if t == body), k)
        texts.setdefault(owner[k], body)
    return texts, owner


def votes_needed(rid: str, texts: dict[str, str], first: dict[tuple[str, str], bool]) -> int:
    """One vote per text, or three for every text of an item whose texts got different first votes."""
    if all((rid, k) in first for k in texts) and len({first[(rid, k)] for k in texts}) > 1:
        return VOTES
    return 1


def first_votes(cast: list[dict]) -> dict[tuple[str, str], bool]:
    return {(c["id"], c["tool"]): c["sufficient"] for c in cast if c["vote"] == 0 and c["sufficient"] is not None}


def pending_votes(rows: list[dict], cast: list[dict]) -> list[tuple[str, str, int, str]]:
    """(item, reader, vote number, text) still to judge."""
    have = {(c["id"], c["tool"], c["vote"]) for c in cast if c["sufficient"] is not None}
    first = first_votes(cast)
    todo = []
    for row in rows:
        texts, _ = distinct_texts(row)
        n = votes_needed(row["id"], texts, first)
        todo += [
            (row["id"], k, v, body) for k, body in texts.items() for v in range(n) if (row["id"], k, v) not in have
        ]
    return todo


def ask(prompt: str, key: str = "sufficient") -> tuple[bool | None, float]:
    cmd = ["claude", "-p", prompt, "--safe-mode", "--model", "sonnet", "--tools", "", "--no-session-persistence"]
    cmd += ["--output-format", "json"]
    cost = 0.0
    for _ in range(3):
        p = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        try:
            res = json.loads(p.stdout.strip().splitlines()[-1])
            cost += res.get("total_cost_usd") or 0
            text = res["result"]
            value = json.loads(text[text.find("{") : text.rfind("}") + 1])[key]
            if isinstance(value, bool):  # "false" as a string or null is no verdict; ask again
                return value, cost
        except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
            continue
    return None, cost


def judge(args) -> None:
    out = Path(args.out)
    items = {i["id"]: i for i in json.loads(Path(args.items).read_text())}
    rows = load(out / "rows.jsonl")
    path = out / "judge.jsonl"

    def one(t):
        rid, tool, vote, text = t
        it = items[rid]
        ok, cost = ask(JUDGE.format(q=it["question"], a=it["expected_answer"], t=text))
        return {"id": rid, "tool": tool, "vote": vote, "sufficient": ok, "cost": cost}

    for _ in range(2):  # first votes, then the extra votes their disagreements call for
        todo = pending_votes(rows, load(path))
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool, path.open("a") as f:
            for r in pool.map(one, todo):
                f.write(json.dumps(r) + "\n")
                f.flush()
                print(r["id"], r["tool"], r["vote"], r["sufficient"], flush=True)


def verdicts(rows: list[dict], cast: list[dict]) -> dict[tuple[str, str], bool | None]:
    """Majority verdict per (item, reader), or None until every vote the item needs is in."""
    votes: dict[tuple[str, str], dict[int, bool]] = {}
    for c in cast:
        if c["sufficient"] is not None:
            votes.setdefault((c["id"], c["tool"]), {})[c["vote"]] = c["sufficient"]
    first = first_votes(cast)
    out = {}
    for row in rows:
        texts, owner = distinct_texts(row)
        n = votes_needed(row["id"], texts, first)
        for k in readers(row):
            got = [v for i, v in votes.get((row["id"], owner[k]), {}).items() if i < n]
            out[(row["id"], k)] = sum(got) * 2 > n if len(got) == n else None
    return out


def final_answer(path: Path) -> str:
    """The final answer of a bench.agents run, from its stream-json trace."""
    results = [e for e in load(path) if e.get("type") == "result"]
    return results[-1].get("result", "") if results else ""


def regrade(args) -> None:
    out = Path(args.out)
    items = {i["id"]: i for i in json.loads(Path(args.items).read_text())}
    prompts = {}  # (question, arm, rep) -> the judge prompt for that answer
    for path in sorted((out / "agents").glob("*__*__*.jsonl")):
        qid, arm, rep = path.name[: -len(".jsonl")].split("__")
        if qid in items and ".attempt" not in rep:  # a retried run keeps its failed attempts' traces beside it
            it = items[qid]
            text = final_answer(path)
            prompts[(qid, arm, int(rep))] = ANSWER_JUDGE.format(q=it["question"], a=it["expected_answer"], t=text)
    # A vote counts only for the prompt it was cast on, so a changed answer, item or prompt is judged again.
    sha = {k: hashlib.sha1(p.encode()).hexdigest()[:12] for k, p in prompts.items()}
    path = out / "regrade.jsonl"

    def current(c: dict) -> bool:
        return c["correct"] is not None and sha.get((c["id"], c["arm"], c["rep"])) == c.get("input")

    have = {(c["id"], c["arm"], c["rep"], c["vote"]) for c in load(path) if current(c)}
    todo = [(k, v) for k in prompts for v in range(VOTES) if (*k, v) not in have]

    def one(job):
        (qid, arm, rep), vote = job
        ok, cost = ask(prompts[(qid, arm, rep)], key="correct")
        return {
            "id": qid,
            "arm": arm,
            "rep": rep,
            "vote": vote,
            "input": sha[(qid, arm, rep)],
            "correct": ok,
            "cost": cost,
        }

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool, path.open("a") as f:
        for r in pool.map(one, todo):  # the prompt carries the answer, not which arm wrote it
            f.write(json.dumps(r) + "\n")
            f.flush()
    cast = load(path)
    votes: dict[tuple, list[bool]] = {}
    for c in cast:
        if current(c):
            votes.setdefault((c["id"], c["arm"], c["rep"]), []).append(c["correct"])
    for arm in sorted({a for _, a, _ in prompts}):
        keys = [k for k in prompts if k[1] == arm]
        done = [k for k in keys if len(votes.get(k, [])) >= VOTES]
        right = [k for k in done if sum(votes[k]) * 2 > len(votes[k])]
        split = [k[0] for k in done if len(set(votes[k])) > 1]
        print(
            f"{arm}: correct {len(right)}/{len(done)} ({len(keys) - len(done)} awaiting votes); wrong "
            f"{sorted(k[0] for k in done if k not in right)}; split votes {split}"
        )
    print(f"regrade votes {len(cast)}, cost ${sum(c['cost'] for c in cast):.3f}")


def summary(args) -> None:
    out = Path(args.out)
    rows = load(out / "rows.jsonl")
    cast = load(out / "judge.jsonl")
    final = verdicts(rows, cast)
    names = list(readers(rows[0]))
    failed_any = {r["id"] for r in rows if any(v["fetch_failed"] for v in readers(r).values())}
    sets = sorted({r["set"] for r in rows})
    print(
        f"items {len(rows)}: "
        + ", ".join(f"{s} {sum(r['set'] == s for r in rows)}" for s in sets)
        + f"; a reader failed to fetch on {len(failed_any)} {sorted(failed_any)}"
    )
    for name in names:
        rs = [r[name] for r in rows]
        both = [r for r in rows if r["id"] not in failed_any]
        pending = sum(final[(r["id"], name)] is None for r in both)
        judged = [final[(r["id"], name)] for r in both if final[(r["id"], name)] is not None]
        spent = [x["command_cost"] if "command_cost" in x else x["cost"] for x in rs if "same_as" not in x]
        failed = sum(x["fetch_failed"] for x in rs)
        print(
            f"{name}: fetch failed {failed}; on the {len(both)} items every reader fetched: "
            f"excerpt {sum(r[name]['excerpt'] for r in both)}, sufficient {sum(judged)}/{len(judged)}"
            f" ({pending} awaiting votes), seconds {sum(r[name]['seconds'] or 0 for r in both):.1f}; "
            f"over all {len(rows)} items: "
            f"tokens {sum(x['tokens'] for x in rs)}, seconds {sum(x['seconds'] or 0 for x in rs):.1f}, "
            f"cost ${sum(c or 0 for c in spent):.3f}"
        )
    print(f"judge votes {len(cast)}, cost ${sum(c['cost'] for c in cast):.3f}")
    ths = sorted(n for n in names if n.startswith("jevfetch_"))
    if len(ths) == 2:
        a, b = ths
        lost = [r["id"] for r in rows if r[a]["excerpt"] and not r[b]["excerpt"]]
        won = [r["id"] for r in rows if r[b]["excerpt"] and not r[a]["excerpt"]]
        print(f"excerpt with {a} only: {len(lost)} {lost}; with {b} only: {len(won)} {won}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("convert")
    c.add_argument("--data", required=True)
    c.add_argument("--preflight", required=True)
    c.add_argument("--rawcheck", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--sets", default="highlights,rag", help="comma-separated: highlights, rag")
    t = sub.add_parser("tools")
    t.add_argument("out")
    t.add_argument("--items", required=True)
    t.add_argument("--ids")
    t.add_argument("--sets", help="comma-separated: highlights, rag")
    t.add_argument("--thresholds", default="0.3,0.6")
    t.add_argument("--parallel", type=int, default=3)
    j = sub.add_parser("judge")
    j.add_argument("out")
    j.add_argument("--items", required=True)
    j.add_argument("--concurrency", type=int, default=4)
    s = sub.add_parser("summary")
    s.add_argument("out")
    g = sub.add_parser("regrade")
    g.add_argument("out", help="a bench.agents run directory on these items")
    g.add_argument("--items", required=True)
    g.add_argument("--concurrency", type=int, default=4)
    args = ap.parse_args(argv)
    {"convert": convert, "tools": tools, "judge": judge, "summary": summary, "regrade": regrade}[args.command](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
