"""
tests/test_proxy_pool.py
-------------------------
Offline tests for proxy_pool.py: the rotation rules and the run-report data
(duplicates_dropped, rotation_log) a caller reads back after a run.

No network, no browser — the pool is deliberately engine-agnostic so these
rules are checkable here rather than only in a live run. Proxy lists are
small hand-written fixtures written to tmp_path; every host is fictional.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proxy_pool import ProxyError, ProxyPool, from_args, mask  # noqa: E402

# A pasted-together list the way they actually arrive: the same exit repeated
# (someone filled the file by copy-paste), plus two genuinely distinct ones.
REPEATED = "http://10.0.0.1:8001"
OTHER_A = "http://10.0.0.2:8002"
OTHER_B = "http://10.0.0.3:8003"


def make_args(**overrides):
    defaults = dict(proxy_file=None, proxy=None, proxy_rotate="per-run",
                    proxy_shuffle=False)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def write_proxy_file(tmp_path, lines):
    path = tmp_path / "proxies.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def test_duplicates_collapse_count_and_order():
    pool = ProxyPool([REPEATED, OTHER_A, REPEATED, OTHER_B, REPEATED])
    # One exit per distinct address, in first-appearance order.
    assert len(pool) == 3
    assert pool.proxies == [REPEATED, OTHER_A, OTHER_B]
    # The dropped count is caller-readable data, not just a log line.
    assert pool.duplicates_dropped == 2


def test_no_duplicates_reports_zero_dropped():
    pool = ProxyPool([OTHER_A, OTHER_B])
    assert len(pool) == 2
    assert pool.duplicates_dropped == 0


def test_advance_cycles_in_order_and_records_each_switch():
    pool = ProxyPool([REPEATED, OTHER_A, OTHER_B])
    assert pool.current == REPEATED

    assert pool.advance("page 1 done") == OTHER_A
    assert pool.advance("exit got challenged") == OTHER_B
    # Wraps around rather than exhausting the pool.
    assert pool.advance("page 3 done") == REPEATED

    assert pool.rotations == 3
    log = pool.rotation_log
    assert [r["rotation"] for r in log] == [1, 2, 3]
    assert [r["reason"] for r in log] == [
        "page 1 done", "exit got challenged", "page 3 done"]
    # Each record names the exit switched TO.
    assert [r["exit"] for r in log] == [mask(OTHER_A), mask(OTHER_B), mask(REPEATED)]


def test_single_exit_advance_is_a_noop_with_a_hint(caplog):
    pool = ProxyPool([REPEATED])
    with caplog.at_level("WARNING", logger="proxy_pool"):
        assert pool.advance("why not") == REPEATED
    # No error, no count, no record — nothing was switched.
    assert pool.rotations == 0
    assert pool.rotation_log == []
    assert pool.current == REPEATED
    assert any("one exit" in record.message for record in caplog.records)


def test_from_args_file_wins_over_single_proxy(tmp_path):
    path = write_proxy_file(tmp_path, [OTHER_A, OTHER_B])
    pool = from_args(make_args(proxy_file=path, proxy=REPEATED))
    assert pool is not None
    assert pool.proxies == [OTHER_A, OTHER_B]


def test_from_args_single_proxy_makes_a_one_exit_pool():
    pool = from_args(make_args(proxy=REPEATED))
    assert pool is not None
    assert len(pool) == 1
    assert pool.current == REPEATED


def test_from_args_neither_option_returns_none():
    assert from_args(make_args()) is None


def test_from_args_empty_file_raises(tmp_path):
    path = write_proxy_file(tmp_path, ["", "# only comments and blanks", "   "])
    with pytest.raises(ProxyError):
        from_args(make_args(proxy_file=path))


def test_rotation_log_masks_credentials():
    # The fixture uses the repo's allowlisted masking-fixture credential
    # (see CREDENTIAL_ALLOWED in .github/ci_checks.py) — a real-looking
    # password shape is the point of the test.
    password = "secret"
    authed = "http://user:secret@10.0.0.9:8009"
    pool = ProxyPool([REPEATED, authed])
    pool.advance("first exit blocked")

    (record,) = pool.rotation_log
    # Host and port survive — knowing WHICH exit is the point of the record.
    assert record["exit"] == "http://***:***@10.0.0.9:8009"
    # The password appears nowhere in anything the caller can read back.
    assert password not in record["exit"]
    assert password not in repr(record)
    assert password not in repr(pool.rotation_log)
