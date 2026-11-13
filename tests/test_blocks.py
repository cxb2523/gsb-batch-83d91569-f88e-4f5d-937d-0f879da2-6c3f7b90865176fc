import inspect
import json
import sys
import time

import pytest

from jevfetch.blocks import merge_fragments, parse, plain, render

PAD = "<p>" + "filler text " * 60 + "</p>"  # long enough for <main> to be chosen as the content root


def page(body: str) -> str:
    return f"<html><body><header><nav>site menu</nav></header><main>{PAD}{body}</main></body></html>"


def texts(html: str) -> list[str]:
    return [b.text for b in parse(html)]


def test_a_small_section_with_a_content_id_is_not_taken_as_the_page():
    sections = "".join(f"<section><h2>{i}. Part {i}</h2>{PAD}</section>" for i in range(1, 21))
    html = f'<html><body>{sections}<section id="content"><h2>6.4. Content</h2>{PAD}</section></body></html>'
    paths = {b.path[0] for b in parse(html)}
    assert "1. Part 1" in paths and "6.4. Content" in paths


def test_leadin_merges_only_following_list_items():
    blocks = parse(
        page(
            "<p>The API has these limits:</p><ul><li>10 per second</li><li>100 per minute</li></ul>"
            "<p>An unrelated paragraph.</p>"
        )
    )
    group = [b for b in blocks if b.kind == "group"]
    assert [b.text for b in group] == ["The API has these limits:\n- 10 per second\n- 100 per minute"]
    assert "An unrelated paragraph." in [b.text for b in blocks]


def test_leadin_does_not_absorb_paragraphs_or_table_rows():
    t = texts(
        page(
            "<p>The API has these limits:</p><p>A long unrelated paragraph.</p>"
            "<table><tr><td>a</td><td>b</td></tr></table>"
        )
    )
    assert "The API has these limits:" in t
    assert "A long unrelated paragraph." in t
    assert "a | b" in t


def test_nested_li_keeps_leadin_inside_inline_tag():
    t = texts(page("<ul><li><strong>Only when enabled</strong>:<ul><li>alpha item one</li></ul></li></ul>"))
    assert any("Only when enabled" in x for x in t)
    assert any("alpha item one" in x for x in t)


def test_header_with_h1_keeps_title_as_heading_path():
    html = (
        "<html><body><main><header><h1>Hôtel Matignon</h1></header>"
        f"{PAD}<p>It is the residence of the Prime Minister.</p></main></body></html>"
    )
    blocks = parse(html)
    assert blocks[0].path == ["Hôtel Matignon"]


def test_header_keeps_only_h1_not_language_list():
    html = (
        "<html><body><main><header><h1>Harriet Lane</h1><ul><li>Deutsch</li><li>Français</li></ul></header>"
        f"{PAD}<p>She was the niece of James Buchanan.</p></main></body></html>"
    )
    blocks = parse(html)
    assert blocks[0].path == ["Harriet Lane"]
    assert not any(b.text in ("Deutsch", "Français") for b in blocks)


def test_site_header_without_h1_is_dropped():
    assert not any("site menu" in x for x in texts(page("<p>body text here.</p>")))


@pytest.mark.parametrize(
    "aside",
    [
        *(
            f'<aside class="box {c}"><p>The flag is off by default.</p></aside>'
            for c in ("note", "tip", "hint", "important", "warning", "caution", "danger", "admonition", "key-point")
        ),
        '<aside class="starlight-aside starlight-aside--caution"><p>The flag is off by default.</p></aside>',
        *(
            f'<aside role="{r}" class="flex rounded"><p>The flag is off by default.</p></aside>'
            for r in ("note", "doc-note", "doc-notice", "doc-tip")
        ),
        *(
            f"<aside><p>{label}: The flag is off by default.</p></aside>"
            for label in ("Note", "Important", "Warning", "Caution", "Tip", "Key Point", "Danger")
        ),
    ],
)
def test_notes_in_asides_are_kept(aside):
    assert any("The flag is off by default." in x for x in texts(page(f"<p>Intro text.</p>{aside}")))


@pytest.mark.parametrize(
    "aside",
    [
        '<aside class="sidebar"><p>Related posts about flags.</p></aside>',
        '<aside class="r-box promo"><p>Related posts about flags.</p></aside>',
        '<aside class="footnotes"><p>Related posts about flags.</p></aside>',
        "<aside><p>Important links: Related posts about flags.</p></aside>",
        '<nav><aside class="note"><p>Related posts about flags.</p></aside></nav>',
    ],
)
def test_sidebars_promotions_and_notes_in_navigation_are_dropped(aside):
    assert not any("Related posts" in x for x in texts(page(f"<p>Intro text.</p>{aside}")))


def test_a_kept_note_does_not_move_the_content_root():
    words = "word " * 90
    html = (
        f'<html><body><main><p>{words}</p><aside class="note"><p>Note: {"x " * 60}</p></aside></main>'
        f"<div><p>Outside the main element. {words * 3}</p></div></body></html>"
    )
    assert any(x.startswith("Outside the main element.") for x in texts(html))


def test_a_heading_inside_a_note_does_not_change_the_path_after_it():
    blocks = parse(
        page(
            "<h2>Install</h2><p>Run the installer first.</p>"
            '<aside class="note"><h4>Heads up</h4><p>Restart is needed.</p></aside><p>Then restart the service.</p>'
        )
    )
    paths = {b.text: b.path for b in blocks}
    assert paths["Restart is needed."] == ["Install", "Heads up"]
    assert paths["Then restart the service."] == ["Install"]


def test_a_note_between_a_leadin_and_its_list_follows_the_group():
    t = texts(
        page(
            "<p>If caching fails:</p>"
            '<aside class="note"><p>Diagnostics compare consecutive requests.</p></aside>'
            "<ul><li>Check the prefix</li><li>Check the lifetime</li></ul><p>Closing paragraph.</p>"
        )
    )
    group = "If caching fails:\n- Check the prefix\n- Check the lifetime"
    assert t[t.index(group) + 1 :] == ["Diagnostics compare consecutive requests.", "Closing paragraph."]


def test_a_leadin_inside_a_note_does_not_take_the_list_after_the_note():
    t = texts(page('<aside class="note"><p>Warning:</p></aside><ul><li>Normal step</li></ul>'))
    assert "Warning:" in t and "Normal step" in t


def test_a_note_moved_after_a_group_keeps_its_own_group():
    t = texts(
        page(
            "<p>If caching fails:</p>"
            '<aside class="note"><p>Common causes:</p><ul><li>Changed tools</li></ul></aside>'
            "<ul><li>Check the prefix</li></ul>"
        )
    )
    assert t[-2:] == ["If caching fails:\n- Check the prefix", "Common causes:\n- Changed tools"]


def test_parse_time_grows_linearly_with_the_number_of_notes():
    def seconds(n: int) -> float:
        html = page('<p>Step.</p><aside class="note"><p>Warning:</p></aside>' * n)
        best = float("inf")
        for _ in range(3):
            start = time.perf_counter()
            parse(html)
            best = min(best, time.perf_counter() - start)
        return best

    assert seconds(4000) < 6 * seconds(1000)  # 4 when linear, 16 when quadratic


def test_a_leadin_and_list_inside_one_note_are_grouped():
    t = texts(
        page('<aside class="note"><p>The multipliers are:</p><ul><li>1.25x write</li><li>0.1x read</li></ul></aside>')
    )
    assert "The multipliers are:\n- 1.25x write\n- 0.1x read" in t


def test_a_note_inside_a_table_cell_follows_its_row():
    t = texts(page('<table><tr><td>state</td><td>Optional.<aside class="note">Check it.</aside></td></tr></table>'))
    assert t[-2:] == ["state | Optional.", "Check it."]


def test_a_note_inside_a_list_item_does_not_take_the_next_item():
    t = texts(page('<ul><li>First step<aside class="note">Warning:</aside></li><li>Normal step</li></ul>'))
    assert t[-3:] == ["First step", "Warning:", "Normal step"]


def test_a_list_inside_a_note_in_a_list_item_keeps_the_outer_group():
    t = texts(
        page(
            '<p>Steps:</p><ul><li>First step<aside class="note"><p>Also:</p><ul><li>inner</li></ul></aside></li>'
            "<li>Second step</li></ul>"
        )
    )
    assert t[-2:] == ["Steps:\n- First step\n- Second step", "Also:\n- inner"]


def test_a_note_inside_a_list_item_of_another_note_is_lifted_too():
    t = texts(
        page('<aside class="note"><ul><li>Step<aside class="tip">Warning:</aside></li><li>Next</li></ul></aside>')
    )
    assert t[-3:] == ["Step", "Warning:", "Next"]


def test_a_content_like_element_inside_a_note_is_not_taken_as_the_root():
    html = (
        f'<html><body><aside class="note"><div id="content">{"note words " * 80}</div></aside>'
        f"<div><p>Body paragraph. {'body words ' * 80}</p></div></body></html>"
    )
    assert any(x.startswith("Body paragraph.") for x in texts(html))


def test_inline_text_around_a_note_with_a_paragraph_stays_one_paragraph():
    t = texts('<html><body><div>Abc<span><aside class="note"><p>Note: twice.</p></aside></span>def</div></body></html>')
    assert t == ["Abcdef", "Note: twice."]


def test_a_nested_note_does_not_break_the_group_of_its_outer_note():
    t = texts(
        page(
            '<aside class="note"><p>Steps:</p><aside class="tip"><p>Back up first.</p></aside>'
            "<ul><li>Run setup</li></ul></aside>"
        )
    )
    assert t[-2:] == ["Steps:\n- Run setup", "Back up first."]


def test_a_note_outside_the_content_root_is_dropped():
    html = (
        f'<html><body><aside class="note"><p>Note: outside.</p></aside><main>{PAD}<p>Inside.</p></main></body></html>'
    )
    assert "Note: outside." not in texts(html)


def test_a_note_between_span_paragraphs_stays_between_them():
    t = texts(
        page(
            '<div><span data-as="p">Before text.</span><aside class="note">Note: middle.</aside>'
            '<span data-as="p">After text.</span></div>'
        )
    )
    assert t[-3:] == ["Before text.", "Note: middle.", "After text."]


def test_text_on_both_sides_of_a_note_stays_one_paragraph():
    t = texts('<html><body><div>A<aside class="note">Restart first.</aside>BC</div></body></html>')
    assert t == ["ABC", "Restart first."]


def test_a_note_in_a_nested_definition_keeps_the_inner_term():
    blocks = parse(
        page(
            "<dl><dt>outer</dt><dd><dl><dt>inner</dt>"
            '<dd>Inner text.<aside class="note">Note: inner note.</aside></dd></dl></dd></dl><p>After the list.</p>'
        )
    )
    paths = {b.text: b.path for b in blocks}
    assert paths["Note: inner note."] == ["outer", "inner"]
    assert paths["After the list."] == []


def test_a_note_in_a_quote_keeps_the_heading_before_it():
    blocks = parse(
        page(
            '<h2>First</h2><blockquote>Quoted text.<aside class="note">Note: quoted.</aside></blockquote>'
            "<h2>Second</h2><p>Second text.</p>"
        )
    )
    assert {b.text: b.path for b in blocks}["Note: quoted."] == ["First"]


def test_inline_text_around_a_note_stays_one_paragraph():
    t = texts(page('<div>Run it <span>now<aside class="note">Note: twice.</aside></span> and wait.</div>'))
    assert t[-2:] == ["Run it now and wait.", "Note: twice."]


def test_definition_list_wrapped_in_div():
    blocks = parse(page("<dl><div><dt>timeout</dt><dd>Seconds to wait before giving up.</dd></div></dl>"))
    dd = [b for b in blocks if b.text == "Seconds to wait before giving up."]
    assert dd and dd[0].path[-1] == "timeout"


def test_code_block_keeps_whitespace():
    code = "def f():\n    return 1\n\nprint(f())"
    blocks = parse(page(f"<pre>{code}</pre>"))
    assert any(b.kind == "pre" and b.text == code for b in blocks)


def test_plain_text_uses_markdown_headings():
    blocks = parse("# Title\n\nFirst paragraph.\n\n## Section\n\nSecond paragraph.")
    assert [(b.path, b.text) for b in blocks] == [
        (["Title"], "First paragraph."),
        (["Title", "Section"], "Second paragraph."),
    ]


PRICES = (
    "<table><thead><tr><th>GPU</th><th>Listed</th><th>Effective</th></tr></thead>"
    "<tbody><tr><td>A100</td><td>$0.50</td><td>$0.65</td></tr></tbody></table>"
)


def test_a_table_header_row_is_marked_and_rows_know_their_table():
    blocks = merge_fragments(parse(page(PRICES + PRICES.replace("GPU", "Card"))))
    rows = [b for b in blocks if b.kind == "row"]
    assert [b.head for b in rows] == [True, False, True, False]
    assert rows[0].table == rows[1].table != rows[2].table == rows[3].table
    assert all(b.table == 0 for b in blocks if b.kind != "row")


def test_a_first_row_of_th_cells_is_a_header_and_a_first_row_of_td_cells_is_not():
    th = "<table><tr><th>GPU</th><th>Price</th></tr><tr><td>A100</td><td>$1</td></tr></table>"
    assert [b.head for b in parse(page(th)) if b.kind == "row"] == [True, False]
    assert [b.head for b in parse(page(th.replace("th>", "td>"))) if b.kind == "row"] == [False, False]


def test_a_table_row_that_leads_a_list_and_a_long_header_row_keep_their_table():
    long_th = "<th>" + "Effective hourly price after downtime. " * 150 + "</th>"
    html = (
        f"<table><tr><th>Step</th>{long_th}</tr><tr><td>1</td><td>Run these:</td></tr></table><ul><li>a b c</li></ul>"
    )
    blocks = merge_fragments(parse(page(html)))
    head = [b for b in blocks if b.head]
    group = next(b for b in blocks if b.text.startswith("1 | Run these:"))
    assert len(head) > 1 and group.kind == "group" and {b.table for b in head} == {group.table} != {0}


def test_merge_fragments_joins_short_steps_but_not_rows():
    blocks = merge_fragments(parse("1. request (by March 31)\n\n2. review\n\nA longer paragraph " + "x " * 80))
    assert blocks[0].text == "1. request (by March 31)\n2. review"


def test_render_prints_heading_only_when_path_changes():
    blocks = parse("# A\n\none\n\ntwo\n\n# B\n\nthree")
    assert render(blocks) == "## A\none\ntwo\n## B\nthree"
    assert render(blocks, {0, 2}) == "## A\none\n## B\nthree"


def test_inline_elements_are_joined_as_written():
    t = texts(page("<p>If <em>maxsize</em> is set to <code>None</code>, the cache can grow.</p>"))
    assert "If maxsize is set to None, the cache can grow." in t


def test_sphinx_signature_and_permalink_symbol():
    html = page(
        '<dl><dt><em class="property">@</em><span class="sig-prename">functools.</span>'
        '<span class="sig-name">lru_cache</span><span class="sig-paren">(</span><em>maxsize</em>'
        '<span class="sig-paren">)</span><a class="headerlink" href="#x">¶</a></dt>'
        "<dd><p>Decorator to wrap a function.</p></dd></dl>"
    )
    dd = [b for b in parse(html) if b.text == "Decorator to wrap a function."]
    assert dd and dd[0].path[-1] == "@functools.lru_cache(maxsize)"


def test_superscripts_stay_separate_and_hidden_text_is_dropped():
    t = texts(
        page(
            "<p>He won the set 7–6<sup>4</sup> in a tiebreak.</p>"
            '<table><tr><td><span style="display:none">Jacobs, Daniel</span>Daniel Jacobs</td><td>DE</td></tr></table>'
        )
    )
    assert "He won the set 7–6 4 in a tiebreak." in t
    assert "Daniel Jacobs | DE" in t


def test_block_boundaries_still_separate_words():
    t = texts(page("<ul><li><div>first</div><div>second</div></li></ul><p>one<br>two</p>"))
    assert "first second" in t and "one two" in t


def test_paragraphs_in_spans_become_separate_blocks():
    # Mintlify renders each paragraph as <span data-as="p">, with only a newline between them.
    html = page(
        '<h2>Behavior</h2><span data-as="p">First paragraph is long enough.</span>\n'
        '<span data-as="p">Second paragraph, also long enough.</span>\n<ul><li>alpha item one</li></ul>'
    )
    blocks = [b for b in parse(html) if b.path == ["Behavior"]]
    assert [b.text for b in blocks] == [
        "First paragraph is long enough.",
        "Second paragraph, also long enough.",
        "alpha item one",
    ]


def test_bare_text_in_a_container_is_kept_in_order():
    t = texts(page("<div>Loose text before the paragraph.<p>A paragraph.</p>Loose text after it.</div>"))
    assert t[-3:] == ["Loose text before the paragraph.", "A paragraph.", "Loose text after it."]


def test_inline_fragments_around_bare_text_stay_one_paragraph():
    t = texts(page("<div>This is <em>very</em> <strong>important</strong> text.</div>"))
    assert "This is very important text." in t


def test_links_keep_their_targets_resolved_against_the_page_url():
    t = [
        b.text
        for b in parse(page('<p>See the <a href="/docs/x.html">guide</a> for details.</p>'), "https://example.com/a/b")
    ]
    assert "See the [guide](https://example.com/docs/x.html) for details." in t


def test_links_without_a_page_url_keep_the_href_as_written():
    t = texts(page('<ul><li><a href="other.html">Other page</a></li></ul>'))
    assert "[Other page](other.html)" in t


def test_fragment_links_and_heading_links_stay_plain():
    blocks = parse(page('<h2><a href="#sec">Section</a></h2><p><a href="#top">top</a> of the text here.</p>'))
    assert blocks[-1].path == ["Section"] and blocks[-1].text == "top of the text here."


def test_plain_strips_link_targets():
    assert plain("See the [guide](https://example.com/g) and [a](b) now.") == "See the guide and a now."


def test_short_linked_items_merge_by_their_visible_length():
    href = "https://example.com/a/very/long/path/that/pushes/the/linked/length/of/each/item/past/the/limit"
    items = "".join(f'<li><a href="{href}/{i}">item {i}</a></li>' for i in range(3))
    blocks = merge_fragments(parse(page(f"<ul>{items}</ul>")))
    assert any(b.kind == "frag" and b.text.count("](") == 3 for b in blocks)


def test_small_json_is_one_block():
    blocks = parse('{"name": "httpx", "version": "0.28.1"}')
    assert [(b.path, b.text) for b in blocks] == [([], '{"name": "httpx", "version": "0.28.1"}')]


def test_large_json_splits_into_records_with_key_paths():
    url = "https://files.example/" + "x" * 300
    files = [{"filename": f"httpx-0.1.{i}.whl", "sha256": "f" * 64, "url": url} for i in range(3)]
    doc = json.dumps({"info": {"name": "httpx", "version": "0.28.1"}, "releases": {"0.1": files, "0.2": files}})
    assert len(doc) > 1500
    blocks = parse(doc)
    assert any(b.path == [] and b.text == '{"info": {"name": "httpx", "version": "0.28.1"}}' for b in blocks)
    versions = [b for b in blocks if "httpx-0.1.0.whl" in b.text]
    assert [(b.path, b.text[:8]) for b in versions] == [(["releases"], '{"0.1": '), (["releases"], '{"0.2": ')]
    assert all(len(b.text) <= 1500 for b in blocks)


def test_long_json_string_value_is_its_own_block():
    doc = json.dumps({"info": {"description": "# httpx\n\nA client. " * 150, "version": "1.0"}})
    blocks = parse(doc)
    description = [b for b in blocks if b.path == ["info", "description"]]
    assert description and description[0].text.startswith("# httpx")
    assert any('"version": "1.0"' in b.text and b.path == ["info"] for b in blocks)


def test_invalid_json_is_plain_text():
    blocks = parse('{"name": not json')
    assert [b.text for b in blocks] == ['{"name": not json']


def test_small_xml_is_one_block():
    blocks = parse('<?xml version="1.0"?><note><to>Ann</to><body>Call me.</body></note>')
    assert [(b.path, b.text) for b in blocks] == [([], "<note><to>Ann</to><body>Call me.</body></note>")]


def test_large_xml_splits_into_elements_with_tag_paths():
    items = "".join(
        f"<item><title>Story {i}</title><description>{'words ' * 150}</description></item>" for i in range(3)
    )
    blocks = parse(f'<?xml version="1.0"?>\n<rss><channel><title>News</title>{items}</channel></rss>')
    stories = [b for b in blocks if "<title>Story" in b.text]
    assert len(stories) == 3 and all(b.path == ["rss", "channel"] and b.text.startswith("<item>") for b in stories)
    assert any(b.path == ["rss", "channel"] and "<title>News</title>" in b.text for b in blocks)


def test_markdown_starting_with_an_html_tag_is_plain_text():
    blocks = parse('<h1 align="center">Project</h1>\n\nSome intro text here.\n\n## Install\n\nRun pip install.')
    assert [b.path for b in blocks] == [[], [], ["Install"]]


def test_markdown_with_a_centered_logo_keeps_its_headings():
    blocks = parse('<p align="center"><img src="logo.png"></p>\n\n# Title\n\nBody text paragraph.\n')
    assert any(b.path == ["Title"] and b.text == "Body text paragraph." for b in blocks)


def test_xml_without_a_declaration_is_parsed_as_xml():
    blocks = parse('<rss version="2.0"><channel><title>News</title></channel></rss>')
    assert len(blocks) == 1 and blocks[0].text.startswith("<rss")


def test_link_target_with_parentheses_is_encoded_and_stripped_whole():
    html = page('<p>See <a href="/wiki/Python_(programming_language)">Python</a> for details.</p>')
    t = [b.text for b in parse(html, "https://en.wikipedia.org/wiki/Main")]
    linked = "See [Python](https://en.wikipedia.org/wiki/Python_%28programming_language%29) for details."
    assert linked in t and plain(linked) == "See Python for details."


def test_link_target_with_a_space_is_encoded_and_stripped():
    html = page('<p>See <a href="/a b.html">the page</a> for details.</p>')
    t = [b.text for b in parse(html, "https://example.com/")]
    assert t[-1] == "See [the page](https://example.com/a%20b.html) for details."
    assert plain(t[-1]) == "See the page for details."


def test_base_href_resolves_relative_links():
    html = (
        '<html><head><base href="https://cdn.example.org/docs/"></head><body><main>'
        f'{PAD}<p>See the <a href="guide.html">guide</a> now.</p></main></body></html>'
    )
    t = [b.text for b in parse(html, "https://example.com/a/b")]
    assert "See the [guide](https://cdn.example.org/docs/guide.html) now." in t


@pytest.mark.parametrize("tag", ["div", "p"])
def test_list_leadin_wrapped_in_a_block_tag_is_printed_once(tag):
    t = texts(page(f"<ul><li><{tag}>Lead text here</{tag}><ul><li>sub item one</li></ul></li></ul>"))
    assert t.count("Lead text here") == 1 and "sub item one" in t


def test_inline_tags_separated_by_whitespace_are_one_paragraph():
    assert "Important message" in texts(page("<div><strong>Important</strong> <span>message</span></div>"))


def test_short_inline_pieces_are_not_dropped():
    assert "A: Yes" in texts(page("<div><b>A:</b> <span>Yes</span></div>"))


def test_deeply_nested_json_does_not_crash():
    parse("[" * 100000 + "]" * 100000)


def test_oversized_xml_element_keeps_its_attributes():
    entries = "".join(f"<entry><title>Story {i}</title><summary>{'words ' * 150}</summary></entry>" for i in range(3))
    blocks = parse(f'<?xml version="1.0"?><feed xml:lang="en">{entries}</feed>')
    assert any(b.path == ["feed"] and b.text == '<feed xml:lang="en">' for b in blocks)


def test_json_groups_count_key_length_and_separators():
    doc = json.dumps({"k" * 2000: 1, **{f"key{i}": "v" * 100 for i in range(30)}})
    assert all(len(b.text) <= 1500 for b in parse(doc))


def test_script_and_data_links_stay_plain():
    t = texts(page('<p><a href="JavaScript:void(0)">menu</a> and <a href="data:text/html,x">inline</a> text.</p>'))
    assert "menu and inline text." in t


def test_json_nested_deeper_than_the_recursion_limit_falls_back_to_text(monkeypatch):
    doc = ('["' + "x" * 1600 + '", ') * 100 + "[]" + "]" * 100  # every level is over MAX_DATA_CHARS, so each descends
    limit = sys.getrecursionlimit()
    low = len(inspect.stack(0)) + 60
    real_loads = json.loads

    def loads_with_room(text):  # the C parser accepts depths that a per-level descent does not fit
        sys.setrecursionlimit(limit)
        try:
            return real_loads(text)
        finally:
            sys.setrecursionlimit(low)

    monkeypatch.setattr(json, "loads", loads_with_room)
    sys.setrecursionlimit(low)
    try:
        blocks = parse(doc)
    finally:
        sys.setrecursionlimit(limit)
    assert "".join(b.text for b in blocks) == doc


def test_xml_nested_deeper_than_the_recursion_limit_falls_back_to_text():
    doc = ("<a>" + "x" * 1600) * 100 + "</a>" * 100  # every element is over MAX_DATA_CHARS, so each level descends
    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(len(inspect.stack(0)) + 60)
    try:
        blocks = parse(doc)
    finally:
        sys.setrecursionlimit(limit)
    assert "".join(b.text for b in blocks) == doc


def test_a_document_whose_root_is_an_html_element_is_parsed_as_html():
    doc = (
        '<pre>Request for Comments: 8259   Obsoletes: <a href="./rfc7159">7159</a>\n\n'
        '   <span class="h1">Title</span>\n   Abstract text.\n</pre>'
    )
    blocks = parse(doc)
    text = " ".join(b.text for b in blocks)
    assert "<a href" not in text and "<span" not in text
    assert "7159" in text and "Abstract text." in text


# Trips both HTML sniffs: it opens and closes with a <p>, and its code fence holds an HTML response.
README_WITH_HTML_SAMPLE = (
    '<p align="center"><img src="logo.png"></p>\n\n# Client\n\nFetch a page.\n\n'
    "```pycon\n>>> r.text\n'<!doctype html>\\n<html>\\n<head>...'\n```\n\n"
    '## Install\n\nRun pip install.\n\n<p align="center">BSD licensed.</p>\n'
)


@pytest.mark.parametrize("media_type", ["text/plain; charset=utf-8", "text/markdown"])
def test_markdown_declared_as_text_keeps_its_headings(media_type):
    paths = {tuple(b.path) for b in parse(README_WITH_HTML_SAMPLE, media_type=media_type)}
    assert {("Client",), ("Client", "Install")} <= paths


@pytest.mark.parametrize("prefix", ["", "﻿", "<!-- mode: Text -->\n  "])
def test_html_file_declared_as_plain_text_is_parsed_as_html(prefix):
    doc = f"{prefix}<!DOCTYPE html><html><body><h2>A</h2><p>Body text here.</p></body></html>"
    assert any(b.path == ["A"] and b.text == "Body text here." for b in parse(doc, media_type="text/plain"))


def test_many_leading_comments_are_checked_quickly():
    doc = "<!--a-->" * 375 + "\n\n# Title\n\nUse a <div> here.\n"
    start = time.perf_counter()
    blocks = parse(doc, media_type="text/plain")
    assert time.perf_counter() - start < 1 and any(b.path == ["Title"] for b in blocks)


def test_json_declared_as_plain_text_is_still_split_by_key():
    doc = json.dumps({"info": {"description": "word " * 400, "version": "1.0"}})
    assert any(b.path == ["info", "description"] for b in parse(doc, media_type="text/plain"))


def test_short_fragments_of_a_note_and_of_the_page_are_not_merged():
    blocks = merge_fragments(parse(page('<p>Short page line.</p><aside class="note"><p>Note: short.</p></aside>')))
    assert [(b.text, b.note) for b in blocks][-2:] == [("Short page line.", False), ("Note: short.", True)]


def test_a_note_before_inline_text_after_a_line_break_stays_before_it():
    t = texts(page('<p>Before text.</p>\n<aside class="note">Note: first.</aside><span>After text.</span>'))
    assert t[-3:] == ["Before text.", "Note: first.", "After text."]


def test_a_long_note_split_into_pieces_stays_a_note():
    sentence = "This sentence belongs to a long note. "
    blocks = parse(page(f'<aside class="note"><p>{sentence * 200}</p></aside>'))
    pieces = [b for b in blocks if b.text.startswith("This sentence")]
    assert len(pieces) > 1 and all(b.note for b in pieces)


def test_short_paragraphs_of_one_note_merge_into_a_note_fragment():
    blocks = merge_fragments(parse(page('<p>Intro text.</p><aside class="note"><p>Note: one.</p><p>Two.</p></aside>')))
    assert [(b.text, b.kind, b.note) for b in blocks][-1] == ("Note: one.\nTwo.", "frag", True)


def test_page_fragments_on_both_sides_of_a_note_merge_as_without_it():
    with_note = merge_fragments(
        parse(page('<p>Step one.</p><aside class="note"><p>Note: careful.</p></aside><p>Step two.</p>'))
    )
    without = merge_fragments(parse(page("<p>Step one.</p><p>Step two.</p>")))
    assert [b.text for b in with_note if not b.note] == [b.text for b in without]
    assert [b.text for b in with_note if b.note] == ["Note: careful."]


def test_a_note_with_one_sentence_too_long_for_a_block_stays_a_note_when_cut():
    blocks = parse(page(f'<aside class="note"><p>Note: {"x" * 9000}</p></aside>'))
    pieces = [b for b in blocks if "xxxx" in b.text]
    assert len(pieces) > 2 and all(b.note for b in pieces)


def test_page_blocks_keep_the_ids_they_have_without_notes_and_notes_come_after():
    body = "<p>One paragraph here.</p>{}<p>Two paragraph here.</p>"
    with_note = merge_fragments(parse(page(body.format('<aside class="note"><p>Note: x.</p></aside>'))))
    without = merge_fragments(parse(page(body.format(""))))
    assert [(b.id, b.text) for b in with_note if not b.note] == [(b.id, b.text) for b in without]
    assert [b.id for b in with_note if b.note] == [len(without)]
