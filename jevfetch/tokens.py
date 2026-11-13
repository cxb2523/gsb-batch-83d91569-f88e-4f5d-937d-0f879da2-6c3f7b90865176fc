"""Token counts with the cl100k encoding, used to size Jev requests and to measure output length."""

import tiktoken

_ENC = tiktoken.get_encoding("cl100k_base")


def count(text: str) -> int:
    # Pages can contain special-token strings such as "<|endoftext|>"; count them as ordinary text.
    return len(_ENC.encode(text, disallowed_special=()))


def truncate(text: str, n: int) -> str:
    """The first n tokens of text."""
    ids = _ENC.encode(text, disallowed_special=())
    return text if len(ids) <= n else _ENC.decode(ids[:n])
