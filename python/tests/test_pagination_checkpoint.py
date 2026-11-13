import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from herascrape._pagination import apaginate, paginate

Page = dict[str, Any]


def _page(items: list[int], *, cursor: str | None, more: bool) -> Page:
    return {
        "items": [{"id": n} for n in items],
        "next_cursor": cursor,
        "has_more": more,
    }


def _ids(items: list[Page]) -> list[int]:
    return [item["id"] for item in items]


class Feed:
    """Fetcher that serves pages by the cursor it is called with.

    `fail_on` cursors raise instead of serving, simulating a crash.
    """

    def __init__(
        self, *pages: Page, fail_on: tuple[str | None, ...] = ()
    ) -> None:
        self._by_cursor: dict[str | None, Page] = {}
        cursor: str | None = None
        for page in pages:
            self._by_cursor[cursor] = page
            cursor = page["next_cursor"]
        self._fail_on = set(fail_on)
        self.cursors: list[str | None] = []

    def _next(self, cursor: str | None) -> Page:
        self.cursors.append(cursor)
        if cursor in self._fail_on:
            raise RuntimeError("fetch failed")
        return self._by_cursor[cursor]

    def __call__(self, cursor: str | None) -> Page:
        return self._next(cursor)

    async def afetch(self, cursor: str | None) -> Page:
        return self._next(cursor)


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _take(walk: AsyncIterator[Page], n: int) -> list[Page]:
    """Pull the first `n` items out of an async walk, then drop it."""
    out: list[Page] = []
    async for item in walk:
        out.append(item)
        if len(out) >= n:
            break
    return out


THREE_PAGES = (
    _page([1, 2], cursor="c1", more=True),
    _page([3, 4], cursor="c2", more=True),
    _page([5], cursor=None, more=False),
)


def test_checkpoint_written_after_each_page(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    fetch = Feed(*THREE_PAGES)
    assert _ids(list(paginate(fetch, checkpoint_file=ckpt))) == [1, 2, 3, 4, 5]
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}


def test_resume_after_interrupt_continues_from_saved_cursor(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES, fail_on=("c2",))
    walk = paginate(first, checkpoint_file=ckpt)
    assert _ids([next(walk) for _ in range(4)]) == [1, 2, 3, 4]
    # The third page's fetch "crashes" the run after two full pages.
    with pytest.raises(RuntimeError):
        next(walk)
    assert _read(ckpt) == {"cursor": "c2", "yielded": 4, "done": False}

    second = Feed(*THREE_PAGES)
    assert _ids(list(paginate(second, checkpoint_file=ckpt))) == [5]
    assert second.cursors == ["c2"]  # never re-fetches from the start
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}


def test_max_items_cap_counts_across_runs(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES)
    walk = paginate(first, max_items=3, checkpoint_file=ckpt)
    assert _ids(list(walk)) == [1, 2, 3]
    assert _read(ckpt)["yielded"] == 3

    # Same cap again: the saved count already exhausts it, no requests.
    second = Feed(*THREE_PAGES)
    assert list(paginate(second, max_items=3, checkpoint_file=ckpt)) == []
    assert second.cursors == []


def test_max_items_boundary_on_resume_fetches_nothing(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES)
    walk = paginate(first, max_items=2, checkpoint_file=ckpt)
    assert _ids(list(walk)) == [1, 2]  # cap lands exactly on a page edge
    assert _read(ckpt) == {"cursor": "c1", "yielded": 2, "done": False}

    second = Feed(*THREE_PAGES)
    assert list(paginate(second, max_items=2, checkpoint_file=ckpt)) == []
    assert second.cursors == []


def test_done_checkpoint_ends_walk_without_requests(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    fetch = Feed(*THREE_PAGES)
    assert _ids(list(paginate(fetch, checkpoint_file=ckpt))) == [1, 2, 3, 4, 5]

    again = Feed(*THREE_PAGES)
    assert list(paginate(again, checkpoint_file=ckpt)) == []
    assert again.cursors == []


def test_missing_checkpoint_file_is_a_fresh_walk(tmp_path: Path):
    ckpt = tmp_path / "does-not-exist.json"
    fetch = Feed(*THREE_PAGES)
    assert _ids(list(paginate(fetch, checkpoint_file=ckpt))) == [1, 2, 3, 4, 5]
    assert fetch.cursors == [None, "c1", "c2"]


def test_corrupt_checkpoint_falls_back_to_fresh_walk(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text("{not json", encoding="utf-8")
    fetch = Feed(*THREE_PAGES)
    assert _ids(list(paginate(fetch, checkpoint_file=ckpt))) == [1, 2, 3, 4, 5]
    assert fetch.cursors == [None, "c1", "c2"]
    # The garbage is overwritten with a valid checkpoint.
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}


@pytest.mark.parametrize(
    "bad",
    [
        ["not", "a", "dict"],
        {"cursor": 123, "yielded": 4, "done": False},
        {"cursor": "c2", "yielded": "4", "done": False},
        {"cursor": "c2", "yielded": 4, "done": "no"},
        {"cursor": None, "yielded": 4, "done": False},
    ],
    ids=["list", "int-cursor", "str-yielded", "str-done", "null-cursor-open"],
)
def test_wrong_field_types_fall_back_to_fresh_walk(tmp_path: Path, bad: Any):
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text(json.dumps(bad), encoding="utf-8")
    fetch = Feed(*THREE_PAGES)
    assert _ids(list(paginate(fetch, checkpoint_file=ckpt))) == [1, 2, 3, 4, 5]
    assert fetch.cursors == [None, "c1", "c2"]
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}


@pytest.mark.asyncio
async def test_async_resume_after_interrupt(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES, fail_on=("c2",))
    walk = apaginate(first.afetch, checkpoint_file=ckpt)
    assert _ids(await _take(walk, 4)) == [1, 2, 3, 4]
    with pytest.raises(RuntimeError):
        await anext(walk)
    assert _read(ckpt) == {"cursor": "c2", "yielded": 4, "done": False}

    second = Feed(*THREE_PAGES)
    items = apaginate(second.afetch, checkpoint_file=ckpt)
    assert _ids([item async for item in items]) == [5]
    assert second.cursors == ["c2"]


@pytest.mark.asyncio
async def test_async_done_checkpoint_ends_walk_without_requests(
    tmp_path: Path,
):
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text(
        json.dumps({"cursor": None, "yielded": 5, "done": True}),
        encoding="utf-8",
    )
    fetch = Feed(*THREE_PAGES)
    items = apaginate(fetch.afetch, checkpoint_file=ckpt)
    assert [item async for item in items] == []
    assert fetch.cursors == []


@pytest.mark.asyncio
async def test_async_max_items_cap_counts_across_runs(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES)
    walk = apaginate(first.afetch, max_items=3, checkpoint_file=ckpt)
    assert _ids([item async for item in walk]) == [1, 2, 3]

    second = Feed(*THREE_PAGES)
    walk2 = apaginate(second.afetch, max_items=3, checkpoint_file=ckpt)
    assert [item async for item in walk2] == []
    assert second.cursors == []


@pytest.mark.asyncio
async def test_async_corrupt_checkpoint_falls_back(tmp_path: Path):
    ckpt = tmp_path / "ckpt.json"
    ckpt.write_text('{"cursor": "c2", "yielded":', encoding="utf-8")
    fetch = Feed(*THREE_PAGES)
    items = apaginate(fetch.afetch, checkpoint_file=ckpt)
    assert _ids([item async for item in items]) == [1, 2, 3, 4, 5]
    assert fetch.cursors == [None, "c1", "c2"]
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}


@pytest.mark.asyncio
async def test_sync_and_async_share_the_checkpoint_format(tmp_path: Path):
    # A sync walk checkpoints after two pages; an async walk resumes it.
    ckpt = tmp_path / "ckpt.json"
    first = Feed(*THREE_PAGES, fail_on=("c2",))
    walk = paginate(first, checkpoint_file=ckpt)
    assert _ids([next(walk) for _ in range(4)]) == [1, 2, 3, 4]
    with pytest.raises(RuntimeError):
        next(walk)

    second = Feed(*THREE_PAGES)
    items = apaginate(second.afetch, checkpoint_file=ckpt)
    assert _ids([item async for item in items]) == [5]
    assert second.cursors == ["c2"]
    assert _read(ckpt) == {"cursor": None, "yielded": 5, "done": True}
