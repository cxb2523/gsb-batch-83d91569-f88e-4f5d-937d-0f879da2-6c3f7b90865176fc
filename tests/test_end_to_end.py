"""End to end on a page written for this test: parse, score with Jev, select, render.

Jev responses recorded in tests/fixtures/e2e/jev are replayed by request hash, so the test needs no API key. A change
to extraction, prompts or thresholds changes the requests, and the test then fails because a response is missing.
Re-record with a key after checking the change:  JEVFETCH_RECORD=1 uv run pytest tests/test_end_to_end.py"""

import json
import os
import shutil
from pathlib import Path

import pytest

from jevfetch import select_relevant
from jevfetch.jev import JevError

FIXTURES = Path(__file__).parent / "fixtures" / "e2e"
PAGE = (FIXTURES / "queue-limits.html").read_text()
CASES = json.loads((FIXTURES / "cases.json").read_text())
RECORD = bool(os.environ.get("JEVFETCH_RECORD"))


@pytest.fixture(scope="module")
def jev_cache(tmp_path_factory) -> Path:
    if RECORD:
        shutil.rmtree(FIXTURES / "jev", ignore_errors=True)
        return FIXTURES
    cache = tmp_path_factory.mktemp("cache")
    shutil.copytree(FIXTURES / "jev", cache / "jev")
    return cache


def normalized(text: str) -> str:
    return " ".join(text.split())


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_page_answers_come_back_verbatim(case, jev_cache, monkeypatch):
    monkeypatch.setenv("JEVFETCH_CACHE_DIR", str(jev_cache))
    if not RECORD:
        monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    try:
        res = select_relevant(PAGE, case["question"])
    except JevError as e:
        pytest.fail(f"no recorded Jev response for this request ({e}); re-record with JEVFETCH_RECORD=1")
    assert res.status == case.get("status", "filtered")
    for fact in case["facts"]:
        assert normalized(fact) in normalized(res.text)
    if "heading" in case:
        assert any(line.startswith("## ") and case["heading"] in line for line in res.text.splitlines())
    assert res.out_tokens < res.doc_tokens / 3
