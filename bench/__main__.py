"""uv run python -m bench [--record] [--update-baseline] [--cases ID,...]

Runs every case in bench/cases.json through jevfetch's selection and compares the result with
bench/baseline.json. See bench/README.md for the modes and the gate rules."""

import argparse
import asyncio
import dataclasses
import gzip
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

from bench import compare, runner
from jevfetch.jev import Jev
from jevfetch.pipeline import Config

ROOT = Path(__file__).parent


def load_cases(ids: set[str] | None) -> list[dict]:
    cases = json.loads((ROOT / "cases.json").read_text())
    return [c for c in cases if not ids or c["id"] in ids]


def load_page(name: str) -> str:
    path = ROOT / "pages" / name
    gz = path.with_suffix(path.suffix + ".gz")
    if not path.exists() and gz.exists():
        return gzip.decompress(gz.read_bytes()).decode("utf-8")
    return path.read_text(encoding="utf-8")


async def resolve_model(baseline: dict | None, record: bool) -> str:
    """Recordings are keyed by the model name, so this returns a pinned name, never the jev-latest alias."""
    if baseline:
        return baseline["model"]["resolved"]
    for path in sorted((ROOT / "jev").glob("*.json")):
        name = json.loads(path.read_text()).get("model")
        if name:
            return name
    if not record:
        sys.exit("no baseline and no recordings in bench/jev; run `uv run python -m bench --record` first")
    jev = Jev(model=Config.model, use_cache=False)
    try:
        await jev.ask({"text": "ping"}, {"q": {"type": "noul", "instructions": "`text` is the word ping"}})
    finally:
        await jev.aclose()
    (name,) = jev.models
    return name


def parse_overrides(items: list[str], ap: argparse.ArgumentParser) -> dict:
    fields = {f.name: f for f in dataclasses.fields(Config)}
    out = {}
    for item in items:
        name, _, value = item.partition("=")
        if name not in fields:
            ap.error(f"--set: unknown Config field {name!r}")
        default = fields[name].default
        if isinstance(default, bool):
            if value.lower() in ("true", "1", "yes"):
                out[name] = True
            elif value.lower() in ("false", "0", "no"):
                out[name] = False
            else:
                ap.error(f"--set {name}: expected true/false, got {value!r}")
        else:
            out[name] = type(default)(value)
    return out


async def run_all(cases: list[dict], record: bool, cfg: Config) -> dict:
    results, missing = {}, []
    for case in cases:
        doc = load_page(case["page"])
        problems = runner.preflight(case, doc)
        if problems:
            sys.exit(f"case error in {case['id']}: " + "; ".join(problems))
        t0 = time.perf_counter()
        res = await runner.run_case_async(case, doc, record=record, cfg=cfg)
        res["seconds"] = round(time.perf_counter() - t0, 2)
        res["page"] = case["page"]
        if res["missing_recording"]:
            missing.append(case["id"])
        results[case["id"]] = res
    return {"cases": results, "missing_recordings": missing}


def summarize(results: dict) -> dict:
    cases = [c for c in results.values() if not c["missing_recording"]]
    pos = [c for c in cases if c["answerable"]]
    facts = [v for c in pos for v in c["facts"].values()]
    keys = [v for c in pos for v in c["keys"].values()]
    extraction = [v for c in pos for v in c["extraction"].values()]
    with_facts = [c for c in pos if c["facts"]]
    per_case = [sum(c["facts"].values()) / len(c["facts"]) for c in with_facts]
    by_page: dict[str, list[float]] = {}
    for c, retention in zip(with_facts, per_case, strict=True):
        by_page.setdefault(c["page"], []).append(retention)
    workload = sum(c["workload"] for c in cases)
    return {
        "cases": len(cases),
        "facts_total": len(facts),
        "facts_passed": sum(facts),
        "keys_total": len(keys),
        "keys_passed": sum(keys),
        "extraction_passed": sum(extraction),
        "retention_pooled": round(sum(facts) / len(facts), 3) if facts else None,
        "retention_case_mean": round(statistics.mean(per_case), 3) if per_case else None,
        "retention_page_macro": round(statistics.mean(statistics.mean(v) for v in by_page.values()), 3)
        if by_page
        else None,
        "status_ok": sum(c["status"] == c["expected_status"] for c in cases),
        "out_tokens": sum(c["out_tokens"] for c in cases),
        "doc_tokens": sum(c["doc_tokens"] for c in cases),
        "workload": workload,
        "live_tokens": sum(c["live_tokens"] for c in cases),
        "requests": sum(c["requests"] for c in cases),
        "cost_usd": round(workload * runner.PRICE_PER_MTOK / 1e6, 4),
        "seconds": round(sum(c["seconds"] for c in cases), 1),
    }


def position_bucket(frac: float | None) -> str:
    if frac is None:
        return "?"
    if frac < 1 / 3:
        return "start"
    if frac < 2 / 3:
        return "middle"
    return "end"


def table(results: dict, baseline: dict | None) -> str:
    rows = [
        "| case | status | facts | keys | extract | out/doc tok | workload | pos | s |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for cid, c in results.items():
        if c["missing_recording"]:
            rows.append(f"| {cid} | missing recording | | | | | | | |")
            continue
        b = baseline["cases"].get(cid) if baseline else None
        delta = f" ({c['out_tokens'] - b['out_tokens']:+d})" if b and "out_tokens" in b else ""
        mark = "" if c["status"] == c["expected_status"] else " **!=**"
        pos = ",".join(sorted({position_bucket(p) for p in c["fact_positions"].values()})) or "-"
        label = f"{cid} (new)" if baseline and cid not in baseline["cases"] else cid
        rows.append(
            f"| {label} | {c['status']}{mark} | {sum(c['facts'].values())}/{len(c['facts'])} | "
            f"{sum(c['keys'].values())}/{len(c['keys'])} | {sum(c['extraction'].values())}/{len(c['extraction'])} | "
            f"{c['out_tokens']}/{c['doc_tokens']}{delta} | {c['workload']} | {pos} | {c['seconds']} |"
        )
    return "\n".join(rows)


def prune_recordings(directory: Path, keep: set[str]) -> list[str]:
    """Delete `<key>.json` files in `directory` whose key is not in `keep`; returns the deleted names."""
    removed = sorted(p.name for p in directory.glob("*.json") if p.stem not in keep)
    for name in removed:
        (directory / name).unlink()
    return removed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bench", description=__doc__)
    ap.add_argument("--record", action="store_true", help="call Jev for requests without a recording")
    ap.add_argument("--update-baseline", action="store_true", help="write bench/baseline.json after the run")
    ap.add_argument("--cases", help="comma-separated case ids (default: all)")
    ap.add_argument("--summary", help="also append the markdown table to this file (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE", help="override a Config field")
    ap.add_argument("--prune", action="store_true", help="delete recordings in bench/jev that this run did not use")
    args = ap.parse_args(argv)
    if args.update_baseline and args.cases:
        ap.error("--update-baseline rewrites the whole baseline; drop --cases")
    if args.prune and (args.cases or args.set):
        ap.error("--prune needs the full run with the default Config")
    ids = set(args.cases.split(",")) if args.cases else None
    cases = load_cases(ids)
    if ids and (unknown := ids - {c["id"] for c in cases}):
        ap.error("unknown case id(s): " + ", ".join(sorted(unknown)))
    overrides = parse_overrides(args.set, ap)

    os.environ["JEVFETCH_CACHE_DIR"] = str(ROOT)  # recordings live in bench/jev
    baseline_path = ROOT / "baseline.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.exists() else None
    model = asyncio.run(resolve_model(baseline, args.record))
    cfg = Config(**{"model": model, **overrides})
    run = asyncio.run(run_all(cases, record=args.record, cfg=cfg))
    resolved = sorted({c["model"] for c in run["cases"].values() if c.get("model")})
    run["model"] = {"requested": model, "resolved": ",".join(resolved) or model}
    run["summary"] = summarize(run["cases"])

    out = [table(run["cases"], baseline), "", "summary: " + json.dumps(run["summary"])]
    if run["missing_recordings"]:
        out.append(
            f"\n{len(run['missing_recordings'])} case(s) have Jev requests without a recording: "
            + ", ".join(run["missing_recordings"])
            + "\nrun `uv run python -m bench --record` locally with TYPESAFE_API_KEY set and commit bench/jev"
        )
    reference = baseline or {"model": run["model"], "cases": {}}
    if args.cases:
        reference = {**reference, "cases": {k: v for k, v in reference["cases"].items() if k in run["cases"]}}
    failures = compare.compare(reference, run, update_baseline=args.update_baseline)
    blocking = [f for f in failures if f.blocking]
    if baseline is None and not args.update_baseline:
        blocking.append(compare.Failure("baseline", "*", "no baseline.json; run with --update-baseline"))
        failures.append(blocking[-1])
    if failures:
        out.append("\ngate:")
        out += [f"  {'FAIL' if f.blocking else 'note'} {f}" for f in failures]
    out.append("\nFAIL" if blocking else "\nPASS")
    if args.prune and not run["missing_recordings"]:
        used = {k for c in run["cases"].values() for k in c.get("jev_keys", [])}
        removed = prune_recordings(ROOT / "jev", used)
        out.append(f"\npruned {len(removed)} unused recording(s)")
    text = "\n".join(out)
    print(text)
    if args.summary:
        with open(args.summary, "a") as f:
            f.write(text + "\n")

    if args.update_baseline and not blocking and not args.cases:
        for c in run["cases"].values():  # drop what changes between identical runs
            c.pop("text", None)
            c.pop("seconds", None)
            c.pop("jev_keys", None)
        run["summary"].pop("seconds", None)
        baseline_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "model": run["model"],
                    "config": dict(vars(cfg)),
                    "cases_sha256": hashlib.sha256((ROOT / "cases.json").read_bytes()).hexdigest(),
                    "summary": run["summary"],
                    "cases": run["cases"],
                },
                indent=1,
                ensure_ascii=False,
            )
            + "\n"
        )
        print(f"wrote {baseline_path}")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
