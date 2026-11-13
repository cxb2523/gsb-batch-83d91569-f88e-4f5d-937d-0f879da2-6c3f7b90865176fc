"""Reduce a document to the blocks relevant to a query.

1. A document of at most `passthrough_tokens` is returned whole.
2. Blocks whose stage-1 score reaches `candidate_threshold` are rescored in stage 2, and those reaching
   `keep_threshold` are kept. A block right before or after a kept one under the same heading is kept from
   `neighbor_threshold`, since a narrowly worded query tends to underrate the condition next to the answer.
3. The first block (title and front matter) is always kept.
4. If the kept body is shorter than `min_output_tokens`, blocks are added by stage-2 score, then by
   stage-1 score, until it is long enough."""

import asyncio
from dataclasses import asdict, dataclass
from typing import Literal

import httpx

from jevfetch import scoring, tokens
from jevfetch.blocks import PLAIN_TYPES, Block, merge_fragments, parse, render
from jevfetch.jev import Jev
from jevfetch.web import UnsupportedContent, fetch_page, fetch_rendered, save_file

Status = Literal["filtered", "passthrough", "no_match", "empty", "fetch_error"]


@dataclass(frozen=True)
class Config:
    candidate_threshold: float = 0.6
    keep_threshold: float = 0.8
    neighbor_threshold: float = 0.6
    passthrough_tokens: int = 2000
    min_output_tokens: int = 300
    window_tokens: int = 3000
    concurrency: int = 16
    model: str = "jev-latest"
    render_fallback: bool = True
    render_below_tokens: int = 200
    # Blocks read from notes (asides kept by blocks._clean) are scored apart from the page, which is passed through
    # or scored as it would be without them. Off: notes go out only with a page they fit with in passthrough_tokens.
    score_notes: bool = True


@dataclass
class Result:
    status: Status
    text: str
    url: str = ""
    doc_tokens: int = 0
    out_tokens: int = 0
    blocks_total: int = 0
    blocks_kept: int = 0
    rendered: bool = False
    jev_input_tokens: int = 0
    jev_cached_input_tokens: int = 0
    jev_requests: int = 0
    model: str = ""
    error: str = ""
    saved: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def choose_blocks(blocks: list[Block], stage1: dict[int, float], stage2: dict[int, float], cfg: Config) -> set[int]:
    keep = {i for i, v in stage2.items() if v >= cfg.keep_threshold}
    # Blocks read from notes are kept on their own scores only, so that the rest of the page is chosen, extended and
    # topped up as it would be without them. The page's blocks are numbered in page order before the notes
    # (blocks._number), so a page block's neighbours are the page blocks numbered one below and one above it.
    by_id = {b.id: b for b in blocks}
    keep |= {
        j
        for i in keep
        if not by_id[i].note
        for j in (i - 1, i + 1)
        if j in by_id
        and not by_id[j].note
        and by_id[j].path == by_id[i].path
        and stage2.get(j, 0) >= cfg.neighbor_threshold
    }
    first = next((b.id for b in blocks if not b.note), None)
    if first is not None:
        keep.add(first)
    ranked = sorted(stage2, key=stage2.get, reverse=True) + sorted(
        (i for i in stage1 if i not in stage2), key=stage1.get, reverse=True
    )
    ranked = [i for i in ranked if not by_id[i].note]
    body = sum(tokens.count(by_id[i].text) for i in keep if i != first and not by_id[i].note)
    for i in ranked:
        if body >= cfg.min_output_tokens:
            break
        if i not in keep:
            keep.add(i)
            body += tokens.count(by_id[i].text)
    return keep


async def select_relevant_async(
    doc: str | list[Block],
    query: str,
    cfg: Config | None = None,
    jev: Jev | None = None,
    *,
    base_url: str = "",
) -> Result:
    """The blocks of `doc` (text, HTML, or already parsed blocks) that are relevant to `query`.

    `base_url` resolves relative links in a string document, via `parse`;
    it is ignored for already parsed blocks."""
    cfg = cfg or Config()
    blocks = parse(doc, base_url) if isinstance(doc, str) else doc
    page = [b for b in blocks if not b.note]
    full = render(page)
    doc_tokens = tokens.count(full)
    if not blocks:
        return Result("empty", "", doc_tokens=doc_tokens)
    fits = doc_tokens <= cfg.passthrough_tokens  # decided on the page alone, as without notes
    if fits and len(page) < len(blocks) and tokens.count(with_notes := render(blocks)) <= cfg.passthrough_tokens:
        page, full = blocks, with_notes
        doc_tokens = tokens.count(full)
    if fits and page and (len(page) == len(blocks) or not cfg.score_notes):
        return Result(
            "passthrough",
            full,
            doc_tokens=doc_tokens,
            out_tokens=doc_tokens,
            blocks_total=len(page),
            blocks_kept=len(page),
        )
    if not page and not cfg.score_notes:  # notes alone, too long to pass through
        return Result("empty", "", doc_tokens=doc_tokens)
    # From here on, with score_notes, a page short enough to pass through goes out whole and only its notes are
    # scored; a longer page is scored, its notes apart from it.
    whole = fits and bool(page)
    if cfg.score_notes and len(page) < len(blocks):
        doc_tokens = tokens.count(render(blocks))  # headings repeat around the notes, so not page plus notes
    blocks = merge_fragments(blocks if cfg.score_notes else page)
    own = jev is None
    jev = jev or Jev(concurrency=cfg.concurrency, model=cfg.model)
    try:
        before = (jev.input_tokens, jev.cached_input_tokens, jev.requests)

        # A window's candidates go to stage 2 as soon as that window is scored, not after the slowest window.
        async def window(win: list[Block]) -> tuple[dict[int, float], dict[int, float]]:
            scores = await scoring.fanout(jev, win, query, cfg.window_tokens)
            candidates = [i for i, v in scores.items() if v >= cfg.candidate_threshold]
            return scores, await scoring.rescore(jev, blocks, candidates, query) if candidates else {}

        # Merged in page order, not arrival order: choose_blocks breaks score ties by dict order.
        stage1: dict[int, float] = {}
        stage2: dict[int, float] = {}
        windows = [w for w in scoring.windows(blocks, cfg.window_tokens) if not whole or all(b.note for b in w)]
        for scores, rescored in await asyncio.gather(*(window(w) for w in windows)):
            stage1.update(scores)
            stage2.update(rescored)
        usage = (jev.input_tokens - before[0], jev.cached_input_tokens - before[1], jev.requests - before[2])
        model = ",".join(sorted(jev.models))
    finally:
        if own:
            await jev.aclose()
    keep = choose_blocks(blocks, stage1, stage2, cfg)
    if whole:
        keep |= {b.id for b in blocks if not b.note}
    # A kept table row goes out with its table's header row, which names the column of each value.
    tables = {b.table for b in blocks if b.id in keep and b.table}
    keep |= {b.id for b in blocks if b.head and b.table in tables}
    text = render(blocks, keep)
    status = (
        "passthrough" if whole else "filtered" if any(v >= cfg.keep_threshold for v in stage2.values()) else "no_match"
    )
    return Result(
        status,
        text,
        doc_tokens=doc_tokens,
        out_tokens=tokens.count(text),
        blocks_total=len(blocks),
        blocks_kept=len(keep),
        jev_input_tokens=usage[0],
        jev_cached_input_tokens=usage[1],
        jev_requests=usage[2],
        model=model,
    )


async def fetch_relevant_async(url: str, query: str, cfg: Config | None = None, jev: Jev | None = None) -> Result:
    """Fetch `url` and keep the blocks relevant to `query`, re-rendering the page if its static HTML is nearly empty."""
    cfg = cfg or Config()
    try:
        html, final_url, media_type = await asyncio.to_thread(fetch_page, url)
    except UnsupportedContent as e:
        error = f"{type(e).__name__}: {e}"
        try:
            saved = await asyncio.to_thread(save_file, url, e.kind, e.content)
        except OSError as save_error:
            return Result("fetch_error", "", url=url, error=f"{error}; could not save it: {save_error}")
        return Result("fetch_error", "", url=url, error=error, saved=saved)
    except httpx.HTTPError as e:
        return Result("fetch_error", "", url=url, error=f"{type(e).__name__}: {e}")
    blocks, rendered = parse(html, final_url, media_type), False

    def size(bs: list[Block]) -> int:  # the page without its notes, as rendering was decided without them
        return tokens.count(render([b for b in bs if not b.note]))

    # A browser shows a plain-text type as source, so rendering adds nothing and turns the text into HTML.
    if cfg.render_fallback and media_type not in PLAIN_TYPES and size(blocks) < cfg.render_below_tokens:
        dom = await asyncio.to_thread(fetch_rendered, url)
        if dom:
            again = parse(dom, final_url)
            if size(again) > size(blocks):
                blocks, rendered = again, True
    res = await select_relevant_async(blocks, query, cfg, jev)
    res.url, res.rendered = url, rendered
    return res


def select_relevant(doc: str | list[Block], query: str, cfg: Config | None = None, *, base_url: str = "") -> Result:
    return asyncio.run(select_relevant_async(doc, query, cfg, base_url=base_url))


def fetch_relevant(url: str, query: str, cfg: Config | None = None) -> Result:
    return asyncio.run(fetch_relevant_async(url, query, cfg))
