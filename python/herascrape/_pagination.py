import json
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, cast

Page = dict[str, Any]
Item = dict[str, Any]


def _next_cursor(page: Page) -> str | None:
    """Cursor for the following page, or None when the walk is over."""
    next_cursor = page["next_cursor"]
    has_more = page.get("has_more", next_cursor is not None)
    return next_cursor if has_more else None


class _Checkpoint:
    """JSON-file checkpoint shared by `paginate` and `apaginate`.

    Format: ``{"cursor": str | null, "yielded": int, "done": bool}`` —
    the cursor of the next page to fetch, how many items have been
    yielded so far, and whether the walk reached its natural end.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)

    def load(self) -> tuple[str | None, int, bool]:
        """Return (cursor, yielded, done); fresh state on any problem.

        A missing, unreadable, or malformed file (bad JSON, wrong field
        types) falls back to a fresh walk instead of raising.
        """
        try:
            data: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None, 0, False
        if not isinstance(data, dict):
            return None, 0, False
        record = cast("dict[str, Any]", data)
        cursor = record.get("cursor")
        yielded = record.get("yielded")
        done = record.get("done")
        if cursor is not None and not isinstance(cursor, str):
            return None, 0, False
        if (
            not isinstance(yielded, int)
            or isinstance(yielded, bool)
            or yielded < 0
        ):
            return None, 0, False
        if not isinstance(done, bool):
            return None, 0, False
        if cursor is None and not done:
            # Never written by save(): a null cursor means the walk is
            # over. Treat the inconsistent state as a fresh walk.
            return None, 0, False
        return cursor, yielded, done

    def save(self, cursor: str | None, yielded: int, done: bool) -> None:
        """Atomically replace the checkpoint file."""
        payload = json.dumps(
            {"cursor": cursor, "yielded": yielded, "done": done}
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self._path)


def paginate(
    fetch_page: Callable[[str | None], Page],
    *,
    item_key: str = "items",
    max_items: int | None = None,
    checkpoint_file: str | os.PathLike[str] | None = None,
) -> Iterator[Item]:
    """Lazily yield `page[item_key]` across pages, up to `max_items`.

    With `checkpoint_file`, persist ``{cursor, yielded, done}`` to that
    JSON file after every fetched page; a later run with the same file
    resumes from the saved cursor instead of the first page. `max_items`
    caps the total across runs, and a file marked done ends the walk
    immediately without any request.
    """
    checkpoint = _Checkpoint(checkpoint_file) if checkpoint_file else None
    yielded = 0
    cursor: str | None = None
    if checkpoint is not None:
        cursor, yielded, done = checkpoint.load()
        if done:
            return
    while max_items is None or yielded < max_items:
        page = fetch_page(cursor)
        for item in page[item_key]:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                if checkpoint is not None:
                    next_cursor = _next_cursor(page)
                    checkpoint.save(next_cursor, yielded, next_cursor is None)
                return
        cursor = _next_cursor(page)
        if checkpoint is not None:
            checkpoint.save(cursor, yielded, cursor is None)
        if cursor is None:
            return


async def apaginate(
    fetch_page: Callable[[str | None], Awaitable[Page]],
    *,
    item_key: str = "items",
    max_items: int | None = None,
    checkpoint_file: str | os.PathLike[str] | None = None,
) -> AsyncIterator[Item]:
    """Async twin of `paginate` (same checkpoint format)."""
    checkpoint = _Checkpoint(checkpoint_file) if checkpoint_file else None
    yielded = 0
    cursor: str | None = None
    if checkpoint is not None:
        cursor, yielded, done = checkpoint.load()
        if done:
            return
    while max_items is None or yielded < max_items:
        page = await fetch_page(cursor)
        for item in page[item_key]:
            yield item
            yielded += 1
            if max_items is not None and yielded >= max_items:
                if checkpoint is not None:
                    next_cursor = _next_cursor(page)
                    checkpoint.save(next_cursor, yielded, next_cursor is None)
                return
        cursor = _next_cursor(page)
        if checkpoint is not None:
            checkpoint.save(cursor, yielded, cursor is None)
        if cursor is None:
            return
