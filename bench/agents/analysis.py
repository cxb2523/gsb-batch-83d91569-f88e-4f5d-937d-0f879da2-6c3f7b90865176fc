"""Scoring and trace analysis for the agent-level comparison (see bench/agents/__main__.py)."""

import json
import random
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).parent
TOOL_NAMES = re.compile(r"jevfetch|WebFetch|web_fetch|curl", re.I)
JEVFETCH_CALL = re.compile(r"(?<![\w/.-])jevfetch\s")
CURL_CALL = re.compile(r"(?<![\w/.-])curl\s")
# Claude Code's refusal text for a Bash command (or a part of a pipeline) that no allow rule covers.
DENIED = re.compile(
    r"\brequires? approval\b|^This Bash command|^Claude requested permission"
    r"|A variable in this command can't be checked before it runs",
    re.I | re.M,
)
JEVFETCH_HEADER = re.compile(r"^# \d+/\d+ blocks, \d+ of (\d+) tokens", re.M)
SIZE_BUCKETS = (("small", 5_000), ("medium", 20_000))  # extracted page tokens; above the last bound is "large"


def size_bucket(page_tokens: int | None) -> str:
    if page_tokens is None:
        return "?"
    for name, bound in SIZE_BUCKETS:
        if page_tokens < bound:
            return name
    return "large"


def elements(facts: dict):
    """(element id, element, required) for every element of every fact; a trailing False marks an optional one."""
    for fid, els in facts.items():
        for i, el in enumerate(els):
            optional = len(el) > (3 if el[0] == "near" else 2) and el[-1] is False
            yield f"{fid}#{i}", el, not optional


def near(text: str, patterns: list[str], window: int) -> bool:
    pos = [[m.start() for m in re.finditer(p, text, re.I)] for p in patterns]
    if not all(pos):
        return False
    return any(all(any(abs(q - p0) <= window for q in ps) for ps in pos[1:]) for p0 in pos[0])


def score(text: str, facts: dict, verdicts: dict[str, bool]) -> tuple[int, int]:
    """(facts right, facts scored): a fact is right only when every required element holds."""
    right: dict[str, bool] = {}
    for eid, el, required in elements(facts):
        if not required:
            continue
        if el[0] == "judge":
            hit = bool(verdicts.get(eid, False))
        elif el[0] == "re":
            hit = re.search(el[1], text, re.I) is not None
        else:
            hit = near(text, el[1], el[2])
        fid = eid.split("#")[0]
        right[fid] = right.get(fid, True) and hit
    return sum(right.values()), len(right)


def redact(text: str) -> str:
    """The judge must not see which reader produced the answer."""
    return TOOL_NAMES.sub("[tool]", text)


def _events(lines: list[str]):
    for line in lines:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(ev, dict):
            yield ev


def run_metrics(lines: list[str], orchestrator: str) -> dict:
    """What one `claude -p` stream-json trace says about the run.

    finished: a result event without an API error. Reaching the turn limit counts as finished with an empty
    answer; an API error (usage limit, overload) does not, so the run can be retried."""
    m = {
        "finished": False,
        "answer": "",
        "subtype": None,
        "cost": None,
        "reader_model_cost": 0.0,
        "main_model_cost": 0.0,
        "main_output_tokens": 0,
        "seconds": None,
        "turns": None,
        "main_input_tokens": None,
        "jevfetch_calls": 0,
        "webfetch_calls": 0,
        "curl_calls": 0,
        "denied_calls": 0,
        "page_tokens": None,
        "claude_version": None,
        "models": [],
    }
    bash_ids: set[str] = set()
    for ev in _events(lines):
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            m["claude_version"] = ev.get("claude_code_version") or ev.get("version")
        elif kind == "user":
            for item in ev.get("message", {}).get("content", []):
                if not isinstance(item, dict) or item.get("type") != "tool_result":
                    continue
                content = item.get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else "".join(x.get("text", "") for x in content or [] if isinstance(x, dict))
                )
                if item.get("tool_use_id") in bash_ids and DENIED.search(text):
                    m["denied_calls"] += 1
                if item.get("tool_use_id") in bash_ids and (h := JEVFETCH_HEADER.search(text)):
                    m["page_tokens"] = max(m["page_tokens"] or 0, int(h.group(1)))
        elif kind == "assistant":
            for item in ev.get("message", {}).get("content", []):
                if not isinstance(item, dict) or item.get("type") != "tool_use":
                    continue
                if item.get("name") == "Bash":
                    bash_ids.add(item.get("id"))
                if item.get("name") == "WebFetch":
                    m["webfetch_calls"] += 1
                elif item.get("name") == "Bash":
                    command = item.get("input", {}).get("command", "")
                    m["jevfetch_calls"] += len(JEVFETCH_CALL.findall(command))
                    m["curl_calls"] += len(CURL_CALL.findall(command))
        elif kind == "result":
            if ev.get("api_error_status") or (ev.get("is_error") and ev.get("subtype") != "error_max_turns"):
                m["finished"] = False
                continue
            usage = ev.get("usage") or {}
            model_usage = ev.get("modelUsage") or {}
            m.update(
                finished=True,
                subtype=ev.get("subtype"),
                answer="" if ev.get("subtype") == "error_max_turns" else (ev.get("result") or ""),
                cost=ev.get("total_cost_usd"),
                seconds=(ev.get("duration_ms") or 0) / 1000,
                turns=ev.get("num_turns"),
                main_input_tokens=sum(
                    usage.get(k) or 0
                    for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
                ),
                reader_model_cost=sum(
                    u.get("costUSD", 0) for name, u in model_usage.items() if orchestrator not in name
                ),
                main_model_cost=sum(u.get("costUSD", 0) for name, u in model_usage.items() if orchestrator in name),
                main_output_tokens=sum(
                    u.get("outputTokens", 0) for name, u in model_usage.items() if orchestrator in name
                ),
                models=sorted(model_usage),
            )
    return m


def jev_usage(cache_dir: Path) -> dict:
    """Fresh Jev requests recorded in a run's own cache directory: one file per request actually sent."""
    files = sorted((cache_dir / "jev").glob("*.json")) if (cache_dir / "jev").is_dir() else []
    tokens, models = 0, set()
    for f in files:
        data = json.loads(f.read_text())
        tokens += data.get("usage", {}).get("input_tokens", 0)
        if data.get("model"):
            models.add(data["model"])
    return {"input_tokens": tokens, "requests": len(files), "models": sorted(models)}


def _bootstrap(per_question: dict, stat, samples: int, seed: int) -> tuple[float, float, float]:
    """Resample questions (the cluster), keeping each question's paired runs together."""
    ids = sorted(per_question)
    est = stat([per_question[q] for q in ids])
    rng = random.Random(seed)
    draws = []
    for _ in range(samples):
        pick = [per_question[rng.choice(ids)] for _ in ids]
        try:
            draws.append(stat(pick))
        except ZeroDivisionError:
            continue
    draws.sort()
    lo, hi = draws[int(0.025 * len(draws))], draws[min(len(draws) - 1, int(0.975 * len(draws)))]
    return est, lo, hi


def paired_ratio_ci(per_question: dict, samples: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """mean(treatment) / mean(control) over questions, with a 95% bootstrap interval clustered by question.

    per_question: id -> (control values, treatment values) for that question's runs."""

    def stat(rows):
        control = statistics.mean(statistics.mean(c) for c, _ in rows)
        treatment = statistics.mean(statistics.mean(t) for _, t in rows)
        return treatment / control

    return _bootstrap(per_question, stat, samples, seed)


def paired_diff_ci(per_question: dict, samples: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """mean over questions of (mean treatment - mean control), with a 95% bootstrap interval clustered by question."""

    def stat(rows):
        return statistics.mean(statistics.mean(t) - statistics.mean(c) for c, t in rows)

    return _bootstrap(per_question, stat, samples, seed)
