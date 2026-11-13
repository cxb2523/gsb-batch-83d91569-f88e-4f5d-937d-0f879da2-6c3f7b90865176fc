"""Split a document into blocks, the unit that jevfetch scores and returns.

A block is a paragraph, list item, table row, or code block, labelled with its heading path. A list
lead-in ending in a colon is merged with the list items that follow it, because the lead-in often
carries the condition that the items depend on."""

import bisect
import json
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup, CData, NavigableString, Tag

DROP = {"script", "style", "noscript", "nav", "footer", "aside", "form", "svg", "button", "iframe"}
# An <aside> is a sidebar, table of contents, or promotion on most sites, but documentation sites also write their
# notes and warnings as one. These names mark the notes, which are kept.
NOTE_CLASSES = {"note", "tip", "hint", "important", "warning", "caution", "danger", "admonition", "key-point"}
NOTE_ROLES = {"note", "doc-note", "doc-notice", "doc-tip"}
NOTE_LABEL = re.compile(r"(?:note|important|warning|caution|tip|key point|danger)\s*:", re.I)
HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
LEAF_BLOCKS = {"p", "li", "pre", "blockquote", "dt", "dd", "tr", "figcaption", "caption"}
CONTAINERS = {"table", "ul", "ol", "dl"}
# Wikipedia furniture, the permalink symbols (¶, #) that documentation generators append to headings, and
# elements a browser does not show (such as the hidden sort keys in Wikipedia tables).
NOISE = (
    "sup.reference, .mw-editsection, .navbox, .reflist, .references, .toc, #toc, .sidebar, "
    "a.headerlink, a.hash-link, a.anchor-link, "
    '[style*="display:none"], [style*="display: none"], [hidden], .sortkey'
)
BLOCK_LEVEL = set(
    "address article aside blockquote caption dd div dl dt figcaption figure footer form h1 h2 h3 h4 "
    "h5 h6 header hr li main nav ol p pre section table tbody td tfoot th thead tr ul".split()
)
# Types a browser shows as source. Markdown may hold raw HTML, so its content alone cannot tell it from a page.
PLAIN_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
MAX_BLOCK_CHARS = 4000  # keeps a single Jev request within the model's input limit
MAX_DATA_CHARS = 1500
# A content-like element holding less of the page's text than this is one section, not the content: the HTML
# of an RFC gives its section titled "Content" the id "content".
MIN_ROOT_SHARE = 0.1

Kind = Literal["p", "li", "pre", "row", "group", "frag"]


@dataclass
class Block:
    id: int
    path: list[str]
    text: str
    kind: Kind
    note: bool = False  # read from a note (an aside kept by _clean)
    table: int = 0  # for a table row, the id() of its <table>; 0 otherwise
    head: bool = False  # a table's header row: in <thead>, or a first row of <th> cells

    @property
    def heading(self) -> str:
        return " > ".join(self.path)


def parse(doc: str, base_url: str = "", media_type: str = "") -> list[Block]:
    """Blocks of an HTML page, a JSON or XML document, or plain text and markdown.

    Links in HTML are written as [text](href); `base_url` resolves relative hrefs. JSON is split by key and
    array item and XML by element, with the key or tag path in place of the heading path. The kind is read
    from the content; a `media_type` (Content-Type) in PLAIN_TYPES rules out HTML unless the document opens
    as one (an .html file on a raw file host)."""
    kind = _kind(doc)
    if kind == "html" and media_type.split(";")[0].strip().lower() in PLAIN_TYPES and not _is_page(doc):
        kind = "text"
    if kind == "html":
        return _parse_html(doc, base_url)
    try:
        if kind == "json":
            return _parse_json(doc)
        if kind == "xml":
            return _parse_xml(doc)
    except RecursionError:  # nested deeper than the interpreter allows: the parsers accept it, the splitters cannot
        pass
    return _parse_plain(doc)


def merge_fragments(blocks: list[Block], short: int = 100, cap: int = 800) -> list[Block]:
    """Merge consecutive short paragraphs or list items under the same heading (e.g. steps of a flow chart).

    Such fragments rarely say on their own what they are about. Table rows and code are never merged. Lengths
    are measured without link targets, so a list of short links still merges. The rest of the page is merged as if
    its notes were not there, and a note only within its run of note blocks."""

    def merge(seq: list[tuple[int, Block]]) -> list[tuple[int, Block]]:  # (position of the first block, merged)
        out: list[tuple[int, Block]] = []
        for k, b in seq:
            prev = out[-1][1] if out else None
            if (
                prev
                and b.kind in ("p", "li")
                and len(plain(b.text)) < short
                and prev.path == b.path
                and (prev.kind == "frag" or (prev.kind in ("p", "li") and len(plain(prev.text)) < short))
                and len(plain(prev.text)) + len(plain(b.text)) < cap
            ):
                out[-1] = (out[-1][0], Block(0, prev.path, prev.text + "\n" + b.text, "frag", b.note))
            else:
                out.append((k, Block(0, b.path, b.text, b.kind, b.note, b.table, b.head)))
        return out

    parts = merge([(k, b) for k, b in enumerate(blocks) if not b.note])
    run: list[tuple[int, Block]] = []
    for k, b in enumerate([*blocks, None]):
        if b is not None and b.note:
            run.append((k, b))
        elif run:
            parts += merge(run)
            run = []
    return _number(_split_long([b for _, b in sorted(parts, key=lambda kb: kb[0])]))


def render(blocks: list[Block], keep: set[int] | None = None) -> str:
    """Blocks in document order, with a "## heading path" line wherever the path changes.

    With `keep`, only blocks whose id is in it are rendered."""
    lines, last_path = [], None
    for b in blocks:
        if keep is not None and b.id not in keep:
            continue
        if b.path != last_path:
            if b.path:
                lines.append("## " + b.heading)
            last_path = b.path
        lines.append(b.text)
    return "\n".join(lines)


def _text(el: Tag, *, links: bool = False, base: str = "") -> str:
    """The element's text with inline elements joined as written, so that <span>f</span><span>(x)</span> reads
    "f(x)" (BeautifulSoup's get_text(" ") gives "f (x)"). Block boundaries, <br>, and super- and subscripts
    separate words."""
    out: list[str] = []

    def walk(node: Tag) -> None:
        for c in node.children:
            if type(c) in (NavigableString, CData):
                out.append(str(c))
            elif isinstance(c, Tag):
                target = _link_target(c, base) if links and c.name == "a" else ""
                if target and (inner := _text(c, links=True, base=base).strip()):
                    out.append(f"[{inner}]({target})")
                elif c.name == "br":
                    out.append("\n")
                elif c.name in BLOCK_LEVEL or c.name in ("sup", "sub"):  # 6<sup>4</sup> must not read as 64
                    out.append(" ")
                    walk(c)
                    out.append(" ")
                else:
                    walk(c)

    walk(el)
    return "".join(out)


def _link_target(a: Tag, base: str) -> str:
    href = (a.get("href") or "").strip()
    if not href or href.startswith("#") or href.lower().startswith(("javascript:", "vbscript:", "data:")):
        return ""
    url = urljoin(base, href) if base else href
    return re.sub(r"[()\s]", lambda m: quote(m.group()), url)


def plain(text: str) -> str:
    # _link_target percent-encodes "(", ")" and whitespace, so a generated target never contains them.
    return re.sub(r"\[([^\]]*)\]\([^)\s]*\)", r"\1", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _is_html(doc: str) -> bool:
    head = doc[:3000].lower()
    return any(t in head for t in ("<html", "<body", "<div", "<p>", "<!doctype"))


# A comment body never spans "-->", so a run of comments has one parse and a failed match does not backtrack.
_PAGE_START = re.compile(r"﻿?(?:\s*<!--(?:(?!-->).)*-->)*\s*(?:<!doctype html|<html)", re.I | re.S)


def _is_page(doc: str) -> bool:
    """Whether `doc` opens as an HTML document, as an .html file does and markdown does not."""
    return bool(_PAGE_START.match(doc[:3000]))


def _kind(doc: str) -> Literal["html", "json", "xml", "text"]:
    body = doc.lstrip()
    if body[:1] in ("{", "["):
        try:
            json.loads(body)
            return "json"
        except (ValueError, RecursionError):
            pass
    if body.startswith("<?xml") and "<html" not in doc[:3000].lower():
        return "xml"
    if _is_html(doc):
        return "html"
    root = re.match(r"<([A-Za-z_][\w.:-]*)[\s>/]", body)
    if root and body.rstrip().endswith(f"</{root.group(1)}>"):  # one element wraps the whole document
        return "html" if root.group(1).lower() in BLOCK_LEVEL else "xml"  # rfc-editor serves RFCs as one <pre>
    return "text"


def _root(soup: BeautifulSoup) -> Tag:
    body = soup.body or soup
    total = len(body.get_text(" ", strip=True))
    for sel in ("main", "article", "[role=main]", "#content", "#main-content", ".body"):
        el = soup.select_one(sel)
        n = len(el.get_text(" ", strip=True)) if el else 0
        if n > 500 and n >= MIN_ROOT_SHARE * total:
            return el
    return body


def _parse_plain(doc: str) -> list[Block]:
    path: list[tuple[int, str]] = []
    out: list[Block] = []
    for para in re.split(r"\n\s*\n", doc):
        para = para.strip()
        if not para:
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", para)
        if m and "\n" not in para:
            level = len(m.group(1))
            while path and path[-1][0] >= level:
                path.pop()
            path.append((level, m.group(2).strip()))
            continue
        out.append(Block(0, [h for _, h in path], para, "p"))
    return _number(_split_long(out))


def _parse_json(doc: str) -> list[Block]:
    """A node up to MAX_DATA_CHARS is one block. A longer object or array is split: its small members are
    grouped in document order, each large member becomes its own blocks under the key or index, and a long
    string is emitted as text."""
    out: list[Block] = []

    def dump(value) -> str:
        return json.dumps(value, ensure_ascii=False)

    def descend(node, path: list[str]) -> None:
        text = dump(node)
        if len(text) <= MAX_DATA_CHARS:
            out.append(Block(0, path, text, "p"))
            return
        if isinstance(node, dict):
            items, empty = list(node.items()), {}
        elif isinstance(node, list):
            items, empty = list(enumerate(node)), []
        else:
            out.append(Block(0, path, node if isinstance(node, str) else text, "p"))
            return
        group = empty.copy()

        def flush() -> None:
            nonlocal group
            if group:
                out.append(Block(0, path, dump(group), "p"))
            group = empty.copy()

        for key, value in items:
            piece = dump({key: value}) if isinstance(node, dict) else dump(value)
            if len(piece) > MAX_DATA_CHARS:
                flush()
                descend(value, path + [str(key)])
                continue
            candidate = {**group, key: value} if isinstance(group, dict) else [*group, value]
            if group and len(dump(candidate)) > MAX_DATA_CHARS:
                flush()
                candidate = {key: value} if isinstance(group, dict) else [value]
            group = candidate
        flush()

    descend(json.loads(doc), [])
    return _number(_split_long(out))


def _parse_xml(doc: str) -> list[Block]:
    """An element up to MAX_DATA_CHARS is one block of its own markup. A longer element is split: runs of
    same-named small children (with the text between them) are grouped, and each large child is split under
    its tag path."""
    out: list[Block] = []

    def emit(text: str, path: list[str]) -> None:
        text = _norm(text)
        if len(text) >= 3:
            out.append(Block(0, path, text, "p"))

    def descend(el: Tag, path: list[str]) -> None:
        text = str(el)
        if len(text) <= MAX_DATA_CHARS:
            emit(text, path)
            return
        path = path + [el.name]
        if el.attrs:
            emit(text[: text.index(">") + 1], path)
        group: list[str] = []
        name = None
        for c in el.children:
            if isinstance(c, Tag):
                piece = str(c)
                if (group and c.name != name) or sum(map(len, group)) + len(piece) > MAX_DATA_CHARS:
                    emit("".join(group), path)
                    group = []
                if len(piece) > MAX_DATA_CHARS:
                    descend(c, path)
                    continue
                name = c.name
            elif type(c) in (NavigableString, CData):
                piece = str(c)
            else:
                continue
            group.append(piece)
        emit("".join(group), path)

    for c in BeautifulSoup(doc, "xml").children:
        if isinstance(c, Tag):
            descend(c, [])
    return _number(_split_long(out))


def _is_note(aside: Tag) -> bool:
    for c in aside.get("class") or []:
        if c.lower().rpartition("--")[2] in NOTE_CLASSES:  # also a BEM modifier, as in starlight-aside--note
            return True
    return (aside.get("role") or "").lower() in NOTE_ROLES or bool(
        NOTE_LABEL.match(aside.get_text(" ", strip=True)[:40])
    )


def _clean(soup: BeautifulSoup) -> list[Tag]:
    """Drop what is not content. Returns the asides kept as notes, outermost only."""
    # Keep the page title but drop the rest of the header: Wikipedia puts the h1 and its language menu
    # in the same <header>.
    for t in soup.find_all("header"):
        h1 = t.find("h1")
        if h1:
            t.replace_with(h1.extract())
        else:
            t.decompose()
    notes = []
    for t in soup.find_all(DROP):
        if t.decomposed:  # inside an element dropped before it
            continue
        if t.name == "aside" and _is_note(t):
            notes.append(t)
        else:
            t.decompose()
    for t in soup.select(NOISE):
        t.decompose()
    kept = {id(t) for t in notes if not t.decomposed}
    return [t for t in notes if id(t) in kept and not any(id(p) in kept for p in t.parents)]


def _own_text(li: Tag, base: str) -> str:
    """Text of a list item without its nested lists, including text inside inline tags."""
    parts = []
    for c in li.children:
        if isinstance(c, NavigableString):
            parts.append(str(c))
        elif isinstance(c, Tag) and c.name not in CONTAINERS:
            parts.append(_text(c, links=True, base=base))
    return " ".join(parts)


def _definition_items(dl: Tag) -> list[Tag]:
    items = []
    for c in dl.children:
        if isinstance(c, Tag) and c.name in ("dt", "dd"):
            items.append(c)
        elif isinstance(c, Tag) and c.name == "div":  # HTML5 allows <div> around each dt/dd group
            items += [x for x in c.children if isinstance(x, Tag) and x.name in ("dt", "dd")]
    return items


def _parse_html(html: str, base: str = "") -> list[Block]:
    soup = BeautifulSoup(html, "lxml")
    if (tag := soup.find("base", href=True)) is not None:
        base = urljoin(base, tag["href"])
    notes = _clean(soup)
    # The page is read as if its notes had been dropped too, so that its content root and its blocks are what they
    # would be without them; each note is read on its own and its blocks follow the block before it in the page.
    order = {id(n): k for k, n in enumerate(soup.descendants)} if notes else {}
    ends = (
        {id(dl): max((order[id(d)] for d in dl.descendants), default=order[id(dl)]) for dl in soup.find_all("dl")}
        if notes
        else {}
    )
    holders = [{id(p) for p in n.parents} for n in notes]
    for n in notes:
        n.extract()
    root = _root(soup)
    notes = [n for n, held_by in zip(notes, holders, strict=True) if id(root) in held_by]
    return _number(_split_long(_merge_leadins(*_read(root, base, [], notes, order, ends))))


def _read(
    el: Tag, base: str, path0: list[tuple[int, str]], notes: list[Tag], order: dict[int, int], ends: dict[int, int]
) -> tuple[list[Block], set[int]]:
    """Blocks of `el` without its `notes` (asides inside it, in page order), each note's blocks (grouped within the
    note) put after the block that it sits in or follows. Also returns the indices of the blocks from notes."""
    for n in notes:
        n.extract()
    blocks, src, events = _walk(el, base, path0, order, ends)
    at_events = [at for at, _ in events]
    out: list[Block] = []
    from_notes: set[int] = set()
    k = 0
    for n in notes:
        at = order[id(n)]
        p = bisect.bisect_left(src, at)  # src is in page order
        out += blocks[k:p]
        k = max(k, p)
        e = bisect.bisect_left(at_events, at)
        inner = [a for a in n.find_all("aside") if a.find_parent("aside") is n]
        sub = _merge_leadins(*_read(n, base, events[e - 1][1] if e else path0, inner, order, ends))
        for b in sub:
            b.note = True
        from_notes.update(range(len(out), len(out) + len(sub)))
        out += sub
    out += blocks[k:]
    return out, from_notes


def _walk(
    root: Tag, base: str, path0: list[tuple[int, str]], order: dict[int, int], ends: dict[int, int]
) -> tuple[list[Block], list[int], list[tuple[int, list[tuple[int, str]]]]]:
    """Blocks of `root`. With `order` (page position of each node), also the position each block was read from
    and the positions where the heading path changed, with the path from there on."""
    path = list(path0)
    out: list[Block] = []
    src: list[int] = []
    events: list[tuple[int, list[tuple[int, str]]]] = []
    here = 0

    def emit(text: str, kind: Kind, table: int = 0, head: bool = False) -> None:
        text = text.strip("\n") if kind == "pre" else _norm(text)
        if len(text.strip()) >= 3:
            out.append(Block(0, [h for _, h in path], text, kind, table=table, head=head))
            if order:
                src.append(here)

    def moved(at: float) -> None:
        if order:
            events.append((at, path[:]))

    def flush(run: list[NavigableString | Tag]) -> None:
        """Mintlify writes each paragraph as <span data-as="p">, so such a span is a paragraph of its own; the
        rest of a run of inline content is one paragraph."""
        nonlocal here
        text = ""
        start = order.get(id(run[0]), 0) if run else 0  # where the text being gathered begins
        for n in run:
            if isinstance(n, Tag) and n.get("data-as") == "p":
                here = start
                emit(text, "p")
                text = ""
                here = start = order.get(id(n), 0)
                emit(_text(n, links=True, base=base), "p")
            else:
                if not text.strip():  # the paragraph begins at its first visible text
                    start = order.get(id(n), 0)
                text += str(n) if isinstance(n, NavigableString) else _text(n, links=True, base=base)
        here = start
        emit(text, "p")
        run.clear()

    def walk(node: Tag, children: list[Tag] | None = None) -> None:
        nonlocal here
        run: list[NavigableString | Tag] = []
        for ch in node.children if children is None else children:
            if not isinstance(ch, Tag):
                if type(ch) in (NavigableString, CData):
                    run.append(ch)
                continue
            if ch.name not in BLOCK_LEVEL and not ch.find(list(BLOCK_LEVEL)):
                run.append(ch)
                continue
            flush(run)
            if order:
                here = order[id(ch)]
            if ch.name == "dl":
                # A definition term (a function signature, an option name) becomes the heading of its
                # descriptions; without it "the child process will be killed" loses which function it is about.
                depth = len(path)
                for item in _definition_items(ch):
                    if order:
                        here = order[id(item)]
                    if item.name == "dt":
                        del path[depth:]
                        path.append((99, _norm(_text(item))[:160]))
                        moved(here)
                    elif item.find(list(LEAF_BLOCKS | CONTAINERS | {"div"})):
                        walk(item)
                    else:
                        emit(_text(item, links=True, base=base), "p")
                del path[depth:]
                moved(ends.get(id(ch), here) + 0.5)  # after everything that was in the list, notes included
            elif ch.name in HEADINGS:
                level = int(ch.name[1])
                while path and path[-1][0] >= level:
                    path.pop()
                path.append((level, _norm(_text(ch))))
                moved(here)
            elif ch.name == "tr":
                tags = ch.find_all(["td", "th"], recursive=False)
                cells = [_norm(_text(c, links=True, base=base)) for c in tags]
                table = ch.find_parent("table")
                head = ch.parent.name == "thead" or (
                    table is not None and table.find("tr") is ch and bool(tags) and all(c.name == "th" for c in tags)
                )
                emit(" | ".join(cells), "row", id(table) if table is not None else 0, head)
            elif ch.name == "pre":
                emit(ch.get_text(), "pre")
            elif ch.name == "li":
                if ch.find(list(CONTAINERS)):
                    emit(_own_text(ch, base), "li")  # becomes the lead-in of the nested list
                    walk(ch, ch.find_all(list(CONTAINERS), recursive=False))
                else:
                    emit(_text(ch, links=True, base=base), "li")
            elif ch.name in LEAF_BLOCKS and not ch.find(list((LEAF_BLOCKS - {"tr"}) | CONTAINERS)):
                emit(_text(ch, links=True, base=base), "p")
            else:
                walk(ch)
        flush(run)

    walk(root)
    return out, src, events


def _merge_leadins(blocks: list[Block], notes: set[int] | None = None) -> list[Block]:
    """Join a lead-in ending in a colon with the list items after it under the same heading (up to 1,500 chars).

    `notes` are the indices of blocks read from notes, already grouped within their note. They are never lead-ins
    here; between a lead-in and its list items they do not end the group, and follow it."""
    notes = notes or set()
    merged: list[Block] = []
    i = 0
    while i < len(blocks):
        b = blocks[i]
        parts, end = [b.text], i + 1
        if b.text.rstrip().endswith(":") and b.kind != "pre" and i not in notes:
            j = i + 1
            while j < len(blocks) and len("\n".join(parts)) < 1500:
                if j in notes:
                    j += 1
                    continue
                item = blocks[j]
                if item.kind != "li" or item.path != b.path or item.text.rstrip().endswith(":"):
                    break
                parts.append("- " + item.text)
                j += 1
                end = j
        if len(parts) > 1:
            merged.append(Block(0, b.path, "\n".join(parts), "group", table=b.table, head=b.head))
            merged += [blocks[k] for k in range(i + 1, end) if k in notes]
        else:
            merged.append(b)
            end = i + 1
        i = end
    return merged


def _split_long(blocks: list[Block]) -> list[Block]:
    """Split blocks longer than MAX_BLOCK_CHARS at sentence (or, for code, line) boundaries."""
    out: list[Block] = []
    for b in blocks:
        if len(b.text) <= MAX_BLOCK_CHARS:
            out.append(b)
            continue
        sep = "\n" if b.kind == "pre" else " "
        parts = b.text.split("\n") if b.kind == "pre" else re.split(r"(?<=[.!?。])\s+|\n", b.text)
        cur = ""
        for s in parts:
            if cur and len(cur) + len(s) > MAX_BLOCK_CHARS:
                out.append(Block(0, b.path, cur.rstrip(), b.kind, b.note, b.table, b.head))
                cur = ""
            while len(s) > MAX_BLOCK_CHARS:  # a single sentence or line over the limit is cut by length
                out.append(Block(0, b.path, s[:MAX_BLOCK_CHARS], b.kind, b.note, b.table, b.head))
                s = s[MAX_BLOCK_CHARS:]
            cur += s + sep
        if cur.strip():
            out.append(Block(0, b.path, cur.rstrip(), b.kind, b.note, b.table, b.head))
    return out


def _number(blocks: list[Block]) -> list[Block]:
    """Ids in page order, the page's blocks first and blocks read from notes after them, so that the page's blocks
    have the ids they would have without notes (Jev sees them in its requests)."""
    for k, b in enumerate([b for b in blocks if not b.note] + [b for b in blocks if b.note]):
        b.id = k
    return blocks
