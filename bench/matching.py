import re
import string

from jevfetch.blocks import Block

_SINGLE = re.compile(r"(?<!\w)([*_])(?!\1)(\S(?:.*?\S)?)(?<!\1)\1(?!\w)")
_DOUBLE = re.compile(r"\*\*(\S(?:.*?\S)?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")  # jevfetch renders links as [text](url)
_CODE = re.compile(r"`([^`\n]+)`")
_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCT = set(string.punctuation)


def fact_spans(fact: str | list[str]) -> list[str]:
    return [fact] if isinstance(fact, str) else fact


def alias_text(alias: str | dict) -> str:
    return alias["text"] if isinstance(alias, dict) else alias


def strip_emphasis(text: str) -> str:
    text = _LINK.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    text = _DOUBLE.sub(r"\1", text)
    return _SINGLE.sub(r"\2", text)


def collapse(text: str) -> str:
    return " ".join(text.split())


def squash(text: str) -> str:
    return "".join(text.split())


def output_blocks(text: str, blocks: list[Block] | None = None) -> list[str]:
    if blocks is None:
        return [ln for ln in text.split("\n") if not ln.startswith("## ")]
    lines, out, pos, last_path = text.split("\n"), [], 0, None
    for b in blocks:
        start = pos
        if b.path and b.path != last_path and lines[pos : pos + 1] == ["## " + b.heading]:
            start = pos + 1
        body = b.text.split("\n")
        if lines[start : start + len(body)] == body:
            out.append(b.text)
            pos, last_path = start + len(body), b.path
    return out


def fact_in_blocks(fact: str | list[str], blocks: list[str]) -> bool:
    spans = [collapse(s) for s in fact_spans(fact)]
    for block in blocks:
        hay, cursor = collapse(strip_emphasis(block)), 0
        for span in spans:
            i = hay.find(span, cursor)
            if i < 0:
                break
            cursor = i + len(span)
        else:
            return True
    return False


def squad_normalize(text: str) -> str:
    text = "".join(ch for ch in text.lower() if ch not in _PUNCT)
    return collapse(_ARTICLES.sub(" ", text))


def _tokens(text: str, exact: bool) -> list[str]:
    return (collapse(text.lower()) if exact else squad_normalize(text)).split()


def key_in_text(key: str, text: str, exact: bool = False) -> bool:
    needle, hay = _tokens(key, exact), _tokens(strip_emphasis(text), exact)
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))


def key_group_in_text(group: list, text: str) -> bool:
    for alias in group:
        exact = isinstance(alias, dict) and bool(alias.get("exact"))
        if key_in_text(alias_text(alias), text, exact=exact):
            return True
    return False


def in_raw_text(needle: str, raw: str) -> bool:
    """Existence check for annotations: ignores all whitespace so inline/block boundaries do not matter."""
    return squash(needle) in squash(raw)
