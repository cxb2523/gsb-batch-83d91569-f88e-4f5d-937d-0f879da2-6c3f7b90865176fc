import asyncio
import json
from pathlib import Path

import httpx
import pytest

from jevfetch import cli, pipeline, scoring, tokens, web
from jevfetch.blocks import Block, render
from jevfetch.jev import JevError
from jevfetch.pipeline import Config, choose_blocks, fetch_relevant_async, select_relevant, select_relevant_async


def blocks_of(n: int, words: int = 200) -> list[Block]:
    return [Block(i, ["Doc"], f"block {i} " + "word " * words, "p") for i in range(n)]


class FakeJev:
    def __init__(self):
        self.input_tokens = self.cached_input_tokens = self.requests = 0
        self.models = {"jev-test"}


def fake_scores(monkeypatch, stage1: dict[int, float], stage2: dict[int, float]):
    async def fanout(jev, blocks, query, window_tokens):
        jev.requests += 1
        return {b.id: stage1[b.id] for b in blocks if b.id in stage1}

    async def rescore(jev, blocks, ids, query):
        jev.requests += len(ids)
        return {i: stage2[i] for i in ids}

    monkeypatch.setattr(scoring, "fanout", fanout)
    monkeypatch.setattr(scoring, "rescore", rescore)


def test_choose_keeps_title_and_passing_blocks_when_body_is_long_enough():
    keep = choose_blocks(blocks_of(5), {1: 0.9, 2: 0.5, 3: 0.1}, {1: 0.95, 2: 0.2}, Config(min_output_tokens=100))
    assert keep == {0, 1}


def test_choose_fills_to_min_tokens_by_stage2_then_stage1_score():
    keep = choose_blocks(
        blocks_of(6, words=50), {1: 0.9, 2: 0.5, 3: 0.2, 4: 0.25}, {1: 0.95, 2: 0.4}, Config(min_output_tokens=150)
    )
    assert keep == {0, 1, 2, 4}


def test_choose_keeps_a_near_miss_next_to_a_kept_block_under_the_same_heading():
    blocks = blocks_of(8, words=50)
    blocks[6] = Block(6, ["Other"], blocks[6].text, "p")
    stage2 = {2: 0.65, 3: 0.95, 4: 0.6, 5: 0.65, 6: 0.65, 7: 0.95}
    keep = choose_blocks(blocks, {i: 0.5 for i in range(1, 8)}, stage2, Config(min_output_tokens=0))
    # 2 and 4 sit before and after kept 3; 5 is next to a rescued block only; 6 is under another heading
    assert keep == {0, 2, 3, 4, 7}


def test_choose_rescues_neighbors_by_the_configured_threshold():
    stage1, stage2 = {1: 0.9, 2: 0.5}, {1: 0.95, 2: 0.65}
    assert choose_blocks(blocks_of(4), stage1, stage2, Config(min_output_tokens=0)) == {0, 1, 2}
    assert choose_blocks(blocks_of(4), stage1, stage2, Config(min_output_tokens=0, neighbor_threshold=0.7)) == {0, 1}


def test_choose_leaves_a_neighbor_below_the_neighbor_threshold():
    keep = choose_blocks(blocks_of(4), {1: 0.9, 2: 0.5}, {1: 0.95, 2: 0.55}, Config(min_output_tokens=0))
    assert keep == {0, 1}


def test_choose_does_not_rescue_across_paths_that_render_the_same():
    blocks = blocks_of(3)
    blocks[1] = Block(1, ["A", "B"], blocks[1].text, "p")
    blocks[2] = Block(2, ["A > B"], blocks[2].text, "p")
    keep = choose_blocks(blocks, {1: 0.9, 2: 0.5}, {1: 0.95, 2: 0.65}, Config(min_output_tokens=0))
    assert keep == {0, 1}


def test_neighbours_are_page_blocks_next_to_each_other_on_the_page_not_notes():
    page = blocks_of(4, words=50)
    note = Block(4, ["Doc"], "Note: aside text.", "p", note=True)
    blocks = [page[0], page[1], note, page[2], page[3]]  # the note sits between page blocks 1 and 2
    stage2 = {1: 0.95, 2: 0.65, 3: 0.65, 4: 0.95}
    keep = choose_blocks(blocks, {i: 0.9 for i in range(5)}, stage2, Config(min_output_tokens=0))
    # 2 is rescued next to kept 1 across the note; the kept note (4) rescues nothing, not even page block 3
    assert keep == {0, 1, 2, 4}


def test_a_note_numbered_next_to_a_kept_page_block_is_not_rescued_as_its_neighbour():
    page = blocks_of(3, words=50)
    note = Block(3, ["Doc"], "Note: aside text.", "p", note=True)
    keep = choose_blocks([*page, note], {i: 0.9 for i in range(4)}, {2: 0.95, 3: 0.65}, Config(min_output_tokens=0))
    assert keep == {0, 2}


def test_notes_are_kept_on_their_own_scores_and_the_page_is_topped_up_as_without_them():
    page = blocks_of(6, words=50)
    stage1, stage2 = {1: 0.9, 2: 0.5, 3: 0.2, 4: 0.25}, {1: 0.95, 2: 0.4}
    without = choose_blocks(page, stage1, stage2, Config(min_output_tokens=150))
    notes = [Block(6, ["Doc"], "note " * 200, "p", note=True), Block(7, ["Doc"], "weak note " * 50, "p", note=True)]
    keep = choose_blocks(page + notes, {**stage1, 6: 0.9, 7: 0.99}, {**stage2, 6: 0.95}, Config(min_output_tokens=150))
    assert keep == without | {6}


def test_the_first_page_block_is_kept_when_a_note_comes_first():
    blocks = [Block(0, ["Doc"], "Note: first.", "p", note=True), *blocks_of(3)[1:]]
    assert choose_blocks(blocks, {}, {}, Config(min_output_tokens=0)) == {1}


def test_select_relevant_resolves_relative_links_with_base_url():
    res = select_relevant('<p><a href="/x">x</a></p>', "q", base_url="https://example.com/")
    assert "[x](https://example.com/x)" in res.text


async def test_select_relevant_async_takes_base_url_by_keyword_only():
    res = await select_relevant_async(
        '<p><a href="/x">x</a></p>', "q", Config(), FakeJev(), base_url="https://example.com/"
    )
    assert "[x](https://example.com/x)" in res.text
    with pytest.raises(TypeError):
        await select_relevant_async("<p>x</p>", "q", Config(), None, "https://example.com/")


async def test_short_document_passes_through_without_jev(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async(blocks_of(3, words=10), "q", Config(), FakeJev())
    assert res.status == "passthrough" and res.jev_requests == 0 and res.blocks_kept == 3


async def test_text_input_is_parsed(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async("# Title\n\nshort text", "q", Config(), FakeJev())
    assert res.status == "passthrough" and res.text == "## Title\nshort text"


async def test_long_document_is_filtered_and_usage_counted(monkeypatch):
    fake_scores(monkeypatch, {i: (0.9 if i == 7 else 0.0) for i in range(20)}, {7: 0.99})
    res = await select_relevant_async(blocks_of(20), "q", Config(min_output_tokens=0), FakeJev())
    assert res.status == "filtered"
    assert res.blocks_kept == 2 and "block 7 " in res.text and "block 0 " in res.text
    windows = len(scoring.windows(blocks_of(20), Config().window_tokens))
    assert res.jev_requests == windows + 1 and res.model == "jev-test"


async def test_stage2_starts_while_a_slower_window_is_still_scored(monkeypatch):
    blocks = blocks_of(20)
    assert len(scoring.windows(blocks, Config().window_tokens)) > 1
    rescored = asyncio.Event()

    async def fanout(jev, win, query, window_tokens):
        if win[0].id == 0:
            await rescored.wait()  # the first window answers only after another window reached stage 2
        return {b.id: 0.9 for b in win}

    async def rescore(jev, blocks, ids, query):
        rescored.set()
        return {i: 0.99 for i in ids}

    monkeypatch.setattr(scoring, "fanout", fanout)
    monkeypatch.setattr(scoring, "rescore", rescore)
    res = await asyncio.wait_for(select_relevant_async(blocks, "q", Config(), FakeJev()), 1)
    assert res.status == "filtered"


async def test_default_candidate_threshold_sends_six_tenths_and_above_to_stage2(monkeypatch):
    sent: list[int] = []

    async def fanout(jev, win, query, window_tokens):
        return {b.id: {3: 0.59, 5: 0.6}.get(b.id, 0.0) for b in win}

    async def rescore(jev, blocks, ids, query):
        sent.extend(ids)
        return {i: 0.9 for i in ids}

    monkeypatch.setattr(scoring, "fanout", fanout)
    monkeypatch.setattr(scoring, "rescore", rescore)
    await select_relevant_async(blocks_of(20), "q", Config(), FakeJev())
    assert sent == [5]


async def test_score_ties_are_broken_by_page_order_not_arrival_order(monkeypatch):
    blocks = blocks_of(20)
    last = scoring.windows(blocks, Config().window_tokens)[-1][0].id
    answered = asyncio.Event()

    async def fanout(jev, win, query, window_tokens):
        if win[0].id == last:
            answered.set()
        else:
            await answered.wait()  # the last window arrives first
        return {b.id: 0.2 for b in win}

    monkeypatch.setattr(scoring, "fanout", fanout)
    res = await asyncio.wait_for(select_relevant_async(blocks, "q", Config(min_output_tokens=300), FakeJev()), 1)
    assert "block 1 " in res.text and "block 2 " in res.text and f"block {last} " not in res.text


async def test_no_block_passing_keep_threshold_reports_no_match(monkeypatch):
    fake_scores(monkeypatch, {i: 0.4 for i in range(20)}, {i: 0.5 for i in range(20)})
    res = await select_relevant_async(blocks_of(20), "q", Config(), FakeJev())
    assert res.status == "no_match" and res.out_tokens >= Config().min_output_tokens


async def test_empty_document():
    res = await select_relevant_async([], "q", Config(), FakeJev())
    assert res.status == "empty" and res.text == ""


async def test_fetch_error_is_reported_not_raised(monkeypatch):
    def fail(url):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(pipeline, "fetch_page", fail)
    res = await fetch_relevant_async("https://example.com", "q", Config(), FakeJev())
    assert res.status == "fetch_error" and "ConnectError" in res.error and res.saved == ""


PDF_BODY = b"%PDF-1.4\n" + b"stream x\x9c\xed\x01 endstream\n" * 2000


def serve(monkeypatch, body: bytes, content_type: str):
    def fake_get(url, **kwargs):
        headers = {"Content-Type": content_type}
        return httpx.Response(200, content=body, headers=headers, request=httpx.Request("GET", url))

    monkeypatch.setattr(web.httpx, "get", fake_get)


async def test_pdf_is_a_fetch_error_naming_its_type_without_jev(monkeypatch, tmp_path):
    fake_scores(monkeypatch, {}, {})
    serve(monkeypatch, PDF_BODY, "application/pdf")
    monkeypatch.setattr(pipeline, "fetch_rendered", lambda url: None)
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path))
    jev = FakeJev()
    res = await fetch_relevant_async("https://example.com/a.pdf", "q", Config(), jev)
    assert res.status == "fetch_error" and "application/pdf" in res.error
    assert jev.requests == 0 and res.text == ""


async def test_a_refused_file_is_saved_for_another_reader(monkeypatch, tmp_path):
    serve(monkeypatch, PDF_BODY, "application/pdf")
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path))
    res = await fetch_relevant_async("https://example.com/a.pdf", "q", Config(), FakeJev())
    saved = Path(res.saved)
    assert saved.parent == tmp_path and saved.suffix == ".pdf" and saved.read_bytes() == PDF_BODY
    assert [p.name for p in tmp_path.iterdir()] == [saved.name]


async def test_a_pdf_served_as_octet_stream_is_saved_as_pdf(monkeypatch, tmp_path):
    serve(monkeypatch, PDF_BODY, "application/octet-stream")
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path))
    res = await fetch_relevant_async("https://example.com/download?id=7", "q", Config(), FakeJev())
    assert Path(res.saved).suffix == ".pdf"


async def test_unknown_binary_is_saved_as_bin(monkeypatch, tmp_path):
    serve(monkeypatch, bytes(range(256)) * 8, "application/octet-stream")
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path))
    res = await fetch_relevant_async("https://example.com/blob", "q", Config(), FakeJev())
    assert Path(res.saved).suffix == ".bin"


async def test_a_file_that_cannot_be_saved_is_still_a_fetch_error(monkeypatch, tmp_path):
    serve(monkeypatch, PDF_BODY, "application/pdf")
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(blocker))
    res = await fetch_relevant_async("https://example.com/a.pdf", "q", Config(), FakeJev())
    assert res.status == "fetch_error" and "application/pdf" in res.error and res.saved == ""


async def test_nearly_empty_page_is_rendered_with_a_browser(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    monkeypatch.setattr(
        pipeline, "fetch_page", lambda url: ("<html><body><div id='app'></div></body></html>", url, "text/html")
    )
    monkeypatch.setattr(
        pipeline, "fetch_rendered", lambda url: "<html><body><p>" + "rendered text " * 40 + "</p></body></html>"
    )
    res = await fetch_relevant_async("https://example.com", "q", Config(), FakeJev())
    assert res.rendered and "rendered text" in res.text


async def test_markdown_served_as_plain_text_keeps_its_headings_and_is_not_rendered(monkeypatch):
    doc = "# Client\n\n```pycon\n>>> r.text\n'<!doctype html>\\n<html>'\n```\n\n## Install\n\nRun pip install.\n"
    monkeypatch.setattr(pipeline, "fetch_page", lambda url: (doc, url, "text/plain"))
    rendered = []
    monkeypatch.setattr(pipeline, "fetch_rendered", rendered.append)
    res = await fetch_relevant_async("https://example.com/README.md", "q", Config(), FakeJev())
    assert "## Client > Install" in res.text and not rendered


def run_cli(monkeypatch, capsys, res=None, error=None, args=("https://example.com", "what?")):
    def fake(url, q, cfg):
        if error:
            raise error
        return res

    monkeypatch.setattr(cli, "fetch_relevant", fake)
    code = cli.main(list(args))
    return code, capsys.readouterr()


def test_cli_prints_status_and_text(monkeypatch, capsys):
    res = pipeline.Result(
        "filtered",
        "## Doc\nanswer",
        url="https://example.com",
        doc_tokens=5000,
        out_tokens=10,
        blocks_total=40,
        blocks_kept=2,
    )
    code, out = run_cli(monkeypatch, capsys, res)
    assert code == 0
    assert "# status: filtered" in out.out and "2/40 blocks, 10 of 5000 tokens" in out.out
    assert out.out.endswith("answer\n")


def test_cli_json_output(monkeypatch, capsys):
    res = pipeline.Result("passthrough", "text", url="https://example.com")
    code, out = run_cli(monkeypatch, capsys, res, args=("https://example.com", "q", "--json"))
    assert code == 0 and json.loads(out.out)["status"] == "passthrough"


def test_cli_reports_a_pdf_as_fetch_error_naming_its_type(monkeypatch, capsys, tmp_path):
    serve(monkeypatch, PDF_BODY, "application/pdf")
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("JEVFETCH_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)  # a Jev call would exit 2 instead of reaching the network
    code = cli.main(["https://example.com/a.pdf", "what?", "--no-render"])
    out = capsys.readouterr().out
    assert code == 1
    assert "# status: fetch_error" in out and "# error: UnsupportedContent: application/pdf" in out
    saved = [line.removeprefix("# saved: ") for line in out.splitlines() if line.startswith("# saved: ")]
    assert len(saved) == 1 and Path(saved[0]).read_bytes() == PDF_BODY


def test_cli_exit_codes(monkeypatch, capsys):
    code, out = run_cli(monkeypatch, capsys, error=JevError("402: billing"))
    assert code == 2 and "402" in out.err
    code, _ = run_cli(monkeypatch, capsys, pipeline.Result("fetch_error", "", error="ConnectError: down"))
    assert code == 1


class CapturingJev(FakeJev):
    def __init__(self):
        super().__init__()
        self.states = []

    async def ask(self, state, questions):
        self.states.append(state)
        return {k: {"noul": 0.0} for k in questions}


async def test_stage1_sends_passages_without_link_targets():
    jev = CapturingJev()
    await scoring.fanout(jev, [Block(0, ["Doc"], "See the [guide](https://example.com/g) now.", "p")], "q")
    assert jev.states[0]["passages"][0]["text"] == "See the guide now."


async def test_stage2_sends_passage_and_context_without_link_targets():
    jev = CapturingJev()
    blocks = [Block(0, ["Doc"], "Before [a](x).", "p"), Block(1, ["Doc"], "The [guide](y) says so.", "p")]
    await scoring.rescore(jev, blocks, [1], "q")
    assert jev.states[0]["passage"] == "The guide says so." and jev.states[0]["context_before"] == "Before a."


async def test_fetched_pages_resolve_relative_links_against_their_url(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    html = '<html><body><p>Read the <a href="/docs/">docs</a>.</p></body></html>'
    monkeypatch.setattr(pipeline, "fetch_page", lambda url: (html, url, "text/html"))
    monkeypatch.setattr(pipeline, "fetch_rendered", lambda url: None)
    res = await fetch_relevant_async("https://example.com/start", "q", Config(), FakeJev())
    assert "[docs](https://example.com/docs/)" in res.text


async def test_stage1_sends_code_blocks_as_written():
    jev = CapturingJev()
    await scoring.fanout(jev, [Block(0, ["Doc"], "handlers[key](event)", "pre")], "q")
    assert jev.states[0]["passages"][0]["text"] == "handlers[key](event)"


async def test_links_resolve_against_the_final_url_after_redirects(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    html = '<html><body><p>Read the <a href="docs/">docs</a>.</p></body></html>'
    monkeypatch.setattr(pipeline, "fetch_page", lambda url: (html, "https://example.com/v2/start", "text/html"))
    monkeypatch.setattr(pipeline, "fetch_rendered", lambda url: None)
    res = await fetch_relevant_async("https://example.com/start", "q", Config(), FakeJev())
    assert "[docs](https://example.com/v2/docs/)" in res.text


def test_windows_measure_blocks_without_link_targets():
    href = "https://example.com/" + "x" * 3000
    linked = [Block(i, ["Doc"], f"[item {i}]({href})", "p") for i in range(6)]
    visible = [Block(i, ["Doc"], f"item {i}", "p") for i in range(6)]

    def ids(ws):
        return [[b.id for b in w] for w in ws]

    assert ids(scoring.windows(linked, 200)) == ids(scoring.windows(visible, 200))


def test_notes_get_windows_of_their_own_and_leave_the_page_windows_as_they_were():
    page = [Block(i, ["Doc"], f"page paragraph {i} " * 20, "p") for i in range(8)]
    with_notes = [*page[:3], Block(8, ["Doc"], "note text " * 20, "p", note=True), *page[3:]]

    def ids(ws):
        return [[b.id for b in w] for w in ws]

    assert ids(scoring.windows(with_notes, 300)) == [*ids(scoring.windows(page, 300)), [8]]


async def test_stage2_context_of_a_page_block_skips_notes_and_a_note_sees_its_neighbours():
    jev = CapturingJev()
    blocks = [
        Block(0, ["Doc"], "Before.", "p"),
        Block(1, ["Doc"], "Note: aside.", "p", note=True),
        Block(2, ["Doc"], "After.", "p"),
    ]
    await scoring.rescore(jev, blocks, [0, 2, 1], "q")
    by_passage = {s["passage"]: s for s in jev.states}
    assert by_passage["After."]["context_before"] == "Before."
    assert by_passage["Before."]["context_after"] == "After."
    assert by_passage["Note: aside."]["context_before"] == "Before."
    assert by_passage["Note: aside."]["context_after"] == "After."


def note_blocks(n: int, words: int) -> list[Block]:
    return [Block(100 + i, ["Doc"], f"Note: {i} " + "caveat " * words, "p", note=True) for i in range(n)]


async def test_notes_go_out_with_a_page_short_enough_to_pass_through(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async(blocks_of(2, words=10) + note_blocks(1, 10), "q", Config(), FakeJev())
    assert res.status == "passthrough" and "Note: 0" in res.text


async def test_without_score_notes_a_short_page_that_notes_would_push_over_the_limit_passes_through_alone(
    monkeypatch,
):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async(
        blocks_of(2, words=10) + note_blocks(1, 3000), "q", Config(score_notes=False), FakeJev()
    )
    assert res.status == "passthrough" and "Note: 0" not in res.text and "block 1" in res.text


async def test_a_nearly_empty_page_with_a_long_note_is_still_rendered(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    note = "<aside class='note'><p>" + "Note: caveat " * 200 + "</p></aside>"
    monkeypatch.setattr(
        pipeline, "fetch_page", lambda url: (f"<html><body><p>Loading...</p>{note}</body></html>", url, "text/html")
    )
    monkeypatch.setattr(
        pipeline, "fetch_rendered", lambda url: "<html><body><p>" + "rendered text " * 40 + "</p></body></html>"
    )
    res = await fetch_relevant_async("https://example.com", "q", Config(), FakeJev())
    assert res.rendered and "rendered text" in res.text


async def test_a_short_document_of_only_notes_passes_through(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async(note_blocks(1, 10), "q", Config(), FakeJev())
    assert res.status == "passthrough" and "Note: 0" in res.text


async def test_with_score_notes_an_answer_only_in_a_note_reaches_the_output(monkeypatch):
    page = blocks_of(20)
    note = note_blocks(1, 10)[0]
    note.id = 20
    fake_scores(monkeypatch, {20: 0.9}, {20: 0.95})
    res = await select_relevant_async(page + [note], "q", Config(score_notes=True), FakeJev())
    assert res.status == "filtered" and "Note: 0" in res.text


async def test_a_long_page_is_scored_with_its_notes_unless_turned_off(monkeypatch):
    seen = []

    async def fanout(jev, blocks, query, window_tokens=3000):
        seen.extend(b.text for b in blocks)
        return {b.id: 0.0 for b in blocks}

    monkeypatch.setattr(scoring, "fanout", fanout)
    page = blocks_of(20)
    await select_relevant_async(page + note_blocks(2, 10), "q", Config(), FakeJev())
    assert any(t.startswith("Note:") for t in seen)
    seen.clear()
    await select_relevant_async(page + note_blocks(2, 10), "q", Config(score_notes=False), FakeJev())
    assert seen == [b.text for b in page]


async def test_a_short_page_goes_out_whole_and_only_its_notes_are_scored_when_they_do_not_fit(monkeypatch):
    seen = []

    async def fanout(jev, blocks, query, window_tokens=3000):
        jev.requests += 1
        seen.extend(b.note for b in blocks)
        return {b.id: 0.9 for b in blocks}

    async def rescore(jev, blocks, ids, query):
        jev.requests += len(ids)
        text = {b.id: b.text for b in blocks}
        return {i: 0.95 if text[i].startswith("Note: 0 ") else 0.1 for i in ids}

    monkeypatch.setattr(scoring, "fanout", fanout)
    monkeypatch.setattr(scoring, "rescore", rescore)
    notes = note_blocks(5, 500)  # each fits in one block; together they do not fit with the page
    res = await select_relevant_async(blocks_of(2, words=10) + notes, "q", Config(), FakeJev())
    assert res.status == "passthrough" and seen and all(seen)
    assert "block 0" in res.text and "block 1" in res.text and "Note: 0" in res.text and "Note: 1" not in res.text


def price_table(first: int, note: bool = False, words: int = 0) -> list[Block]:
    return [
        Block(first, ["Doc"], "GPU | Listed | Effective", "row", note=note, table=1, head=True),
        Block(first + 1, ["Doc"], "A100 | $0.50 | $0.65" + " word" * words, "row", note=note, table=1),
        Block(first + 2, ["Doc"], "H100 | $0.90 | $1.15", "row", note=note, table=1),
        Block(first + 3, ["Doc"], "plain | row", "row", note=note, table=2),  # a table without a header row
    ]


async def test_a_kept_table_row_goes_out_with_its_tables_header_row(monkeypatch):
    fake_scores(monkeypatch, {21: 0.9, 23: 0.9}, {21: 0.99, 23: 0.99})
    res = await select_relevant_async(blocks_of(20) + price_table(20), "q", Config(min_output_tokens=0), FakeJev())
    assert "GPU | Listed | Effective\nA100 | $0.50 | $0.65\nplain | row" in res.text
    assert "H100" not in res.text and res.blocks_kept == 4  # the first block, two rows, and the header row
    assert res.jev_requests == len(scoring.windows(blocks_of(20) + price_table(20), Config().window_tokens)) + 2


async def test_a_table_none_of_whose_rows_is_kept_leaves_its_header_row_out(monkeypatch):
    other = [
        Block(24, ["Doc"], "Region | Latency", "row", table=3, head=True),
        Block(25, ["Doc"], "us-east | 20 ms", "row", table=3),
    ]
    fake_scores(monkeypatch, {21: 0.9}, {21: 0.99})
    res = await select_relevant_async(
        blocks_of(20) + price_table(20) + other, "q", Config(min_output_tokens=0), FakeJev()
    )
    assert "GPU | Listed | Effective\nA100" in res.text and "Region | Latency" not in res.text


async def test_a_note_table_row_kept_beside_a_whole_page_goes_out_with_its_header_row(monkeypatch):
    async def fanout(jev, blocks, query, window_tokens=3000):
        jev.requests += 1
        return {b.id: 0.9 for b in blocks}

    async def rescore(jev, blocks, ids, query):
        jev.requests += len(ids)
        text = {b.id: b.text for b in blocks}
        return {i: 0.95 if text[i].startswith("A100") else 0.1 for i in ids}

    monkeypatch.setattr(scoring, "fanout", fanout)
    monkeypatch.setattr(scoring, "rescore", rescore)
    res = await select_relevant_async(
        blocks_of(2, words=10) + price_table(2, note=True, words=2500), "q", Config(), FakeJev()
    )
    assert res.status == "passthrough" and "block 1" in res.text
    assert "GPU | Listed | Effective\nA100" in res.text and "H100" not in res.text


async def test_a_document_of_notes_too_long_to_pass_through_is_scored(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    res = await select_relevant_async(note_blocks(2, 1500), "q", Config(), FakeJev())
    assert res.status == "no_match" and res.jev_requests > 0


def test_cli_scores_notes_unless_no_notes_is_given(monkeypatch, capsys):
    seen = []

    def fake(url, q, cfg):
        seen.append(cfg.score_notes)
        return pipeline.Result("passthrough", "text", url=url)

    monkeypatch.setattr(cli, "fetch_relevant", fake)
    cli.main(["https://example.com", "q"])
    cli.main(["https://example.com", "q", "--no-notes"])
    assert seen == [True, False]


async def test_doc_tokens_count_the_page_and_its_notes_as_rendered_together(monkeypatch):
    fake_scores(monkeypatch, {}, {})
    page = [Block(i, [f"Section {i}"], f"block {i} " + "word " * 200, "p") for i in range(10)]
    notes = [Block(10 + i, [f"Section {i}"], f"Note: {i} " + "caveat " * 50, "p", note=True) for i in range(10)]
    mixed = [b for pair in zip(page, notes, strict=True) for b in pair]
    res = await select_relevant_async(mixed, "q", Config(), FakeJev())
    assert res.doc_tokens == tokens.count(render(mixed))
