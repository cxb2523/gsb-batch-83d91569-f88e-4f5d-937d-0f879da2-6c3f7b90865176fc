from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from collections.abc import Callable, Iterator

from ..base import SourceUnavailableError

_VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
_SKIP = {'script', 'style', 'noscript', 'template', 'svg', 'nav', 'header', 'footer', 'form', 'button', 'iframe'}
_BLOCK = {'div', 'p', 'section', 'article', 'main', 'h1', 'h2', 'h3', 'h4', 'li', 'ul', 'ol', 'dl', 'tr', 'br', 'hr'}


@dataclass
class Node:
    tag: str
    attrs: dict[str, str]
    children: list[Node | str] = field(default_factory=list)

    def matches(self, selector: str) -> bool:
        if selector.startswith('.'):
            return selector[1:] in self.attrs.get('class', '').split()
        if selector.startswith('#'):
            return self.attrs.get('id') == selector[1:]
        return self.tag == selector

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def select(self, selector: str) -> list[Node]:
        return [node for node in self.walk() if node.matches(selector)]


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node('document', {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.stack) > 150:
            raise SourceUnavailableError('HTML nesting exceeds safety bound')
        node = Node(tag, {key: value or '' for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def parse_html(html: str) -> Node:
    parser = _Parser()
    parser.feed(html)
    return parser.root


def excluded(node: Node, selectors: tuple[str, ...] = ()) -> bool:
    style = re.sub(r'\s', '', node.attrs.get('style', '')).lower()
    return (node.tag in _SKIP or 'hidden' in node.attrs
            or node.attrs.get('role') == 'status' or node.matches('.sr-only')
            or node.attrs.get('aria-hidden') == 'true'
            or 'display:none' in style or 'visibility:hidden' in style
            or any(node.matches(selector) for selector in selectors))


def content_text(node: Node, skip: Callable[[Node], bool] = excluded) -> str:
    def render(part: Node | str) -> str:
        if isinstance(part, str):
            return part
        if skip(part):
            return ''
        # Adjacent flex items may be visually separated solely by a CSS gap.
        # Keep a neutral separator so a date and its recurrence badge do not
        # become a fabricated single word in static HTML extraction.
        style = re.sub(r'\s', '', part.attrs.get('style', '')).lower()
        classes = part.attrs.get('class', '').split()
        separated = ((re.search(r'(?:^|;)display:(?:inline-)?flex(?:;|$)', style) and re.search(r'(?:^|;)gap:[1-9]', style))
                     # Utility-class layouts express the same visual gap with classes.
                     or (any(c in ('flex', 'inline-flex') for c in classes)
                         and any(re.fullmatch(r'gap(?:-[xy])?-(?:\[[1-9][^\]]*\]|[1-9][0-9.]*)', c) for c in classes)))
        text = (' ' if separated else '').join(render(child) for child in part.children)
        return '\n' + text + '\n' if part.tag in _BLOCK else text
    return '\n'.join(line for raw in render(node).splitlines() if (line := ' '.join(raw.split())))
