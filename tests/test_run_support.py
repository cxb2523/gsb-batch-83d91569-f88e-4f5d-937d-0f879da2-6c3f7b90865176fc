"""Tests for the resume bookkeeping and CSV consolidation in run_support.

The scraping callback is replaced by a local function that writes small
CSV files into a temporary account directory.  This exercises the merge
and progress logic without pretending to be the production download path:
main.py always wires run_batch() to the real Selenium functions.
"""

import csv
import json
import os

import pytest

import run_support
from run_support import (
    PROGRESS_FILENAME,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_SUCCESS,
    consolidate_csvs,
    load_progress,
    run_batch,
    should_skip_account,
    summarise_results,
)

ACCOUNTS = ["ACC-NRE-111", "ACC-NRO-222", "ACC-NPNRO-333"]
ORDER_HEADERS = ["Stock", "Order Type", "Status"]


def write_orders_csv(directory, account_id, rows):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{account_id}_orders_cleaned.csv")
    with open(path, "w", newline="", encoding="utf-8") as outfile:
        writer = csv.writer(outfile)
        writer.writerow(ORDER_HEADERS)
        writer.writerows(rows)
    return path


def read_csv(path):
    with open(path, "r", encoding="utf-8") as infile:
        return list(csv.reader(infile))


def make_processor(base_dir, fail_for=None):
    """Return a callback writing one orders CSV per account."""

    def process(account_id):
        if account_id == fail_for:
            raise RuntimeError(f"download failed for {account_id}")
        directory = os.path.join(base_dir, account_id)
        return write_orders_csv(
            directory, account_id, [[f"{account_id}-STOCK", "Buy", "Active"]]
        )

    return process


@pytest.fixture
def download_root(tmp_path):
    root = os.path.join(tmp_path, "downloads")
    os.makedirs(root, exist_ok=True)
    return root


def test_all_three_accounts_succeed_and_merge_contains_all(download_root, caplog):
    """All three accounts succeed: consolidation includes every account."""
    results = run_batch(
        ACCOUNTS,
        make_processor(download_root),
        download_root,
        PROGRESS_FILENAME,
    )

    assert [r.status for r in results] == [STATUS_SUCCESS] * 3

    # Each account conclusion is persisted, with its file list.
    progress = load_progress(download_root)
    for account_id in ACCOUNTS:
        entry = progress["accounts"][account_id]
        assert entry["status"] == STATUS_SUCCESS
        assert entry["files"] == [
            os.path.abspath(
                os.path.join(
                    download_root, account_id, f"{account_id}_orders_cleaned.csv"
                )
            )
        ]

    merged = consolidate_csvs(
        "orders",
        [path for r in results for path in r.files],
        download_root,
    )
    assert merged is not None

    rows = read_csv(merged)
    assert rows[0] == ["Account ID"] + ORDER_HEADERS
    assert {row[0] for row in rows[1:]} == set(ACCOUNTS)
    assert len(rows) == 4

    summary = summarise_results(results)
    assert summary == {STATUS_SUCCESS: 3, STATUS_SKIPPED: 0, STATUS_FAILED: 0}


def test_one_account_failing_does_not_stop_the_batch(download_root, caplog):
    """A raised download error fails that account only; others complete."""
    failing = ACCOUNTS[1]
    results = run_batch(
        ACCOUNTS,
        make_processor(download_root, fail_for=failing),
        download_root,
    )

    assert len(results) == 3
    by_account = {r.account_id: r for r in results}
    assert by_account[ACCOUNTS[0]].status == STATUS_SUCCESS
    assert by_account[ACCOUNTS[2]].status == STATUS_SUCCESS
    assert by_account[failing].status == STATUS_FAILED
    assert by_account[failing].error is not None
    assert "download failed" in by_account[failing].error
    assert by_account[failing].files == []

    # The failure is written to the progress file so the next run retries it.
    progress = load_progress(download_root)
    assert progress["accounts"][failing]["status"] == STATUS_FAILED
    assert progress["accounts"][failing]["error"] == by_account[failing].error

    # Consolidation only takes the successful accounts' files.
    merged = consolidate_csvs(
        "orders",
        [
            path
            for r in results
            if r.status == STATUS_SUCCESS
            for path in r.files
        ],
        download_root,
    )
    rows = read_csv(merged)
    assert {row[0] for row in rows[1:]} == {ACCOUNTS[0], ACCOUNTS[2]}

    summary = summarise_results(results)
    assert summary == {STATUS_SUCCESS: 2, STATUS_SKIPPED: 0, STATUS_FAILED: 1}


def test_corrupt_progress_file_is_treated_as_a_fresh_run(download_root, caplog):
    """Garbage in the progress file must not crash or skip anything."""
    with open(
        os.path.join(download_root, PROGRESS_FILENAME), "w", encoding="utf-8"
    ) as outfile:
        outfile.write('{"accounts": {"ACC-NRE-111": ')  # truncated JSON

    progress = load_progress(download_root)
    assert progress["accounts"] == {}

    results = run_batch(
        ACCOUNTS,
        make_processor(download_root),
        download_root,
    )
    assert [r.status for r in results] == [STATUS_SUCCESS] * 3

    # The fresh run overwrote the corrupt file with valid progress.
    saved = load_progress(download_root)
    assert set(saved["accounts"]) == set(ACCOUNTS)


def test_missing_progress_file_is_a_fresh_run(download_root):
    assert load_progress(download_root)["accounts"] == {}
    assert not os.path.exists(os.path.join(download_root, PROGRESS_FILENAME))


def test_non_object_progress_file_is_a_fresh_run(download_root):
    path = os.path.join(download_root, PROGRESS_FILENAME)
    with open(path, "w", encoding="utf-8") as outfile:
        json.dump([1, 2, 3], outfile)

    assert load_progress(download_root)["accounts"] == {}


def test_completed_accounts_are_skipped_while_missing_files_are_retried(
    download_root,
):
    """Resume: success + files present => skipped, missing file => retried."""
    progress = {"version": 1, "accounts": {}}
    for account_id in ACCOUNTS:
        path = write_orders_csv(
            os.path.join(download_root, account_id),
            account_id,
            [["X", "S", "A"]],
        )
        progress["accounts"][account_id] = {
            "status": STATUS_SUCCESS,
            "error": None,
            "files": [os.path.abspath(path)],
        }
    run_support.save_progress(download_root, progress)

    loaded = load_progress(download_root)
    assert should_skip_account(loaded, ACCOUNTS[0])
    assert should_skip_account(loaded, ACCOUNTS[1])

    # Delete the third account's file; it must be re-collected.
    os.remove(
        os.path.join(download_root, ACCOUNTS[2], f"{ACCOUNTS[2]}_orders_cleaned.csv")
    )
    assert not should_skip_account(loaded, ACCOUNTS[2])

    calls = []
    results = run_batch(
        ACCOUNTS,
        lambda account_id: calls.append(account_id)
        or make_processor(download_root)(account_id),
        download_root,
    )

    assert calls == [ACCOUNTS[2]]
    assert [r.status for r in results] == [
        STATUS_SKIPPED,
        STATUS_SKIPPED,
        STATUS_SUCCESS,
    ]
    summary = summarise_results(results)
    assert summary == {STATUS_SUCCESS: 1, STATUS_SKIPPED: 2, STATUS_FAILED: 0}


def test_progress_is_written_after_each_account(download_root):
    """After account N is done, account N's conclusion is already on disk."""
    seen_at_next_account = []
    processor = make_processor(download_root)

    def tracking_process(account_id):
        # Read progress as it stands when the *next* account starts.
        seen_at_next_account.append(load_progress(download_root)["accounts"])
        return processor(account_id)

    run_batch(ACCOUNTS, tracking_process, download_root)

    assert len(seen_at_next_account) == 3
    # Before the first account nothing is recorded; before the second the
    # first account is already recorded; before the third, two are.
    assert seen_at_next_account[0] == {}
    assert list(seen_at_next_account[1]) == [ACCOUNTS[0]]
    assert set(seen_at_next_account[2]) == {ACCOUNTS[0], ACCOUNTS[1]}

