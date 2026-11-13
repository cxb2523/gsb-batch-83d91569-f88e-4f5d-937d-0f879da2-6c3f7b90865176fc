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

__all__ = [
    "Block",
    "Config",
    "Jev",
    "JevError",
    "Result",
    "fetch_relevant",
    "fetch_relevant_async",
    "parse",
    "render",
    "select_relevant",
    "select_relevant_async",
]
