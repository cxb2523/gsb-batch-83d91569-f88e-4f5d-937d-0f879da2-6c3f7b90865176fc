"""jevfetch: a web-reading tool for LLM agents that returns the parts of a page relevant to a question, verbatim."""

from jevfetch.blocks import Block, parse, render
from jevfetch.jev import Jev, JevError
from jevfetch.pipeline import (
    Config,
    Result,
    fetch_relevant,
    fetch_relevant_async,
    select_relevant,
    select_relevant_async,
)
from jevfetch.web import FetchResult, RenderResult, fetch_page_result, fetch_rendered_result

__all__ = [
    "Block",
    "Config",
    "FetchResult",
    "Jev",
    "JevError",
    "RenderResult",
    "Result",
    "fetch_page_result",
    "fetch_relevant",
    "fetch_relevant_async",
    "fetch_rendered_result",
    "parse",
    "render",
    "select_relevant",
    "select_relevant_async",
]
