"""Replay mode removes TYPESAFE_API_KEY from the process so that a request without a recording raises JevError
inside the client instead of reaching the network."""

import hashlib
import os

from bs4 import BeautifulSoup

from bench import matching
from jevfetch import tokens
from jevfetch.blocks import merge_fragments, parse, render
from jevfetch.jev import Jev, JevError
from jevfetch.pipeline import Config, select_relevant_async

PRICE_PER_MTOK = 0.042  # USD per million Jev input tokens


def _short_sha1(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def fact_id(fact: str | list[str]) -> str:
    return _short_sha1("\n".join(matching.fact_spans(fact)))


def key_id(group: list) -> str:
    return _short_sha1("|".join(matching.alias_text(a) for a in group))


def raw_text(doc: str) -> str:
    if doc.lstrip().startswith("<") or "<html" in doc[:3000].lower():
        soup = BeautifulSoup(doc, "lxml")
        for t in soup.select("sup.reference"):  # Wikipedia citation markers sit inside sentences
            t.decompose()
        return soup.get_text(" ")
    return doc


def preflight(case: dict, doc: str) -> list[str]:
    raw = raw_text(doc)
    problems = []
    for fact in case.get("facts", []):
        spans = matching.fact_spans(fact)
        if not spans or not all(s.strip() for s in spans):
            problems.append(f"empty fact: {fact!r}")
            continue
        for span in spans:
            if not matching.in_raw_text(span, raw):
                problems.append(f"fact not on page: {span[:80]!r}")
    for group in case.get("keys", []):
        if not any(matching.in_raw_text(matching.alias_text(a), raw) for a in group):
            problems.append(f"no alias on page: {group!r}")
    return problems


def fact_position(fact: str | list[str], raw: str) -> float | None:
    squashed = matching.squash(raw)
    i = squashed.find(matching.squash(matching.fact_spans(fact)[0]))
    return round(i / max(1, len(squashed)), 3) if i >= 0 else None


async def run_case_async(case: dict, doc: str, record: bool, cfg: Config | None = None) -> dict:
    cfg = cfg or Config()
    if not record:
        os.environ.pop("TYPESAFE_API_KEY", None)
    blocks = merge_fragments(parse(doc))
    full_blocks = [b.text for b in blocks]
    raw = raw_text(doc)
    facts, keys = case.get("facts", []), case.get("keys", [])
    out = {
        "id": case["id"],
        "question": case["question"],
        "snapshot_sha256": hashlib.sha256(doc.encode()).hexdigest(),
        "expected_status": case.get("status", "filtered"),
        "answerable": case.get("answerable", True),
        "extraction": {fact_id(f): matching.fact_in_blocks(f, full_blocks) for f in facts},
        "fact_positions": {fact_id(f): fact_position(f, raw) for f in facts},
        "doc_tokens": tokens.count(render(blocks)),
        "blocks_total": len(blocks),
        "missing_recording": False,
    }
    jev = Jev(concurrency=cfg.concurrency, model=cfg.model)
    try:
        res = await select_relevant_async(blocks, case["question"], cfg, jev)
    except JevError as e:
        if record:
            raise
        out.update(status=None, missing_recording=True, error=str(e))
        return out
    finally:
        out["jev_keys"] = sorted(jev.keys)
        await jev.aclose()
    kept = matching.output_blocks(res.text, blocks)
    out.update(
        status=res.status,
        facts={fact_id(f): matching.fact_in_blocks(f, kept) for f in facts},
        keys={key_id(g): matching.key_group_in_text(g, res.text) for g in keys},
        out_tokens=res.out_tokens,
        blocks_kept=res.blocks_kept,
        workload=res.jev_input_tokens + res.jev_cached_input_tokens,
        live_tokens=res.jev_input_tokens,
        requests=res.jev_requests,
        model=res.model,
        span_density=_span_density(facts, kept, res.out_tokens),
        text=res.text,
    )
    return out


def _span_density(facts: list, kept: list[str], out_tokens: int) -> float | None:
    if not facts or not out_tokens:
        return None
    n = sum(tokens.count(" ".join(matching.fact_spans(f))) for f in facts if matching.fact_in_blocks(f, kept))
    return round(n / out_tokens, 3)
