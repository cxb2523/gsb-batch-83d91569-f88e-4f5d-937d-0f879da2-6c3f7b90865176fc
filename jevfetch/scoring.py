"""Relevance scoring of blocks with Jev, in two stages. Jev sees the text without link targets.

Stage 1 asks one request per window of blocks, with one yes/no question per block. Stage 2 asks again
for each candidate block alone, with the neighbouring text as context. A block passes if it answers any
part of the query, because agents often pass keyword lists or several questions at once."""

import asyncio

from jevfetch import tokens
from jevfetch.blocks import Block, plain
from jevfetch.jev import Jev

QUESTION = (
    "`query` may contain several topics or sub-questions, possibly as a list of keywords. "
    "Does {passage} state information that answers at least one of them, such as a value, limit, "
    "date, deadline, rule, condition, exception, or behavior?"
)
CRITERIA = {
    "true": "`passage` states part of the answer to at least one topic or sub-question in `query`, "
    "or a condition, exception, price, or scope that qualifies such an answer.",
    "false": "`passage` is about something else, or only names a topic from `query` without stating anything about it.",
}
CONTEXT_NOTE = (
    "`context_before` and `context_after` are the neighbouring text on the page. They are shown only to "
    "resolve what `passage` refers to; judge the information in `passage` itself."
)
CONTEXT_CHARS = 400
WINDOW_ITEMS = 120
ITEM_OVERHEAD_TOKENS = 20  # the id and section fields that accompany each passage in a window


def _jev_text(b: Block) -> str:
    return b.text if b.kind == "pre" else plain(b.text)


def windows(blocks: list[Block], max_tokens: int) -> list[list[Block]]:
    """Blocks read from notes get windows of their own, so that the rest of the page is judged in the windows it
    would have without them."""
    out = []
    for group in ([b for b in blocks if not b.note], [b for b in blocks if b.note]):
        cur, n = [], 0
        for b in group:
            t = tokens.count(_jev_text(b)) + ITEM_OVERHEAD_TOKENS
            if cur and (n + t > max_tokens or len(cur) >= WINDOW_ITEMS):
                out.append(cur)
                cur, n = [], 0
            cur.append(b)
            n += t
        if cur:
            out.append(cur)
    return out


async def fanout(jev: Jev, blocks: list[Block], query: str, window_tokens: int = 3000) -> dict[int, float]:
    """Stage 1: probability that each block is relevant, judged within its window."""
    criteria = {k: v.replace("`passage`", "The passage") for k, v in CRITERIA.items()}

    async def one(win: list[Block]) -> dict[int, float]:
        questions = {
            f"p{b.id}": {
                "type": "noul",
                "criteria": criteria,
                "instructions": QUESTION.format(passage=f"passage `passages[{k}]` (id p{b.id})"),
            }
            for k, b in enumerate(win)
        }
        passages = [{"id": f"p{b.id}", "section": b.heading, "text": _jev_text(b)} for b in win]
        answers = await jev.ask({"query": query, "passages": passages}, questions)
        return {int(k[1:]): v["noul"] for k, v in answers.items()}

    scores: dict[int, float] = {}
    for part in await asyncio.gather(*(one(w) for w in windows(blocks, window_tokens))):
        scores.update(part)
    return scores


async def rescore(jev: Jev, blocks: list[Block], ids: list[int], query: str) -> dict[int, float]:
    """Stage 2: probability for each block in `ids`, judged alone with its neighbours as context. The neighbours of
    a block outside notes are the blocks outside notes next to it, as they would be without the notes."""
    page = [b for b in blocks if not b.note]
    pos = {b.id: (blocks, i) for i, b in enumerate(blocks)} | {b.id: (page, i) for i, b in enumerate(page)}
    instructions = QUESTION.format(passage="`passage`") + " " + CONTEXT_NOTE

    async def one(bid: int) -> tuple[int, float]:
        seq, i = pos[bid]
        b = seq[i]
        state = {
            "query": query,
            "section": b.heading,
            "passage": _jev_text(b),
            "context_before": _jev_text(seq[i - 1])[-CONTEXT_CHARS:] if i > 0 else "",
            "context_after": _jev_text(seq[i + 1])[:CONTEXT_CHARS] if i + 1 < len(seq) else "",
        }
        answers = await jev.ask(state, {"rel": {"type": "noul", "instructions": instructions, "criteria": CRITERIA}})
        return bid, answers["rel"]["noul"]

    return dict(await asyncio.gather(*(one(i) for i in ids)))
