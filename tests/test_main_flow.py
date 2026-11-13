"""Orchestration tests for the batch flow in main.py.

main.py cannot be imported in a headless environment (selenium and the
webdriver manager are production-only dependencies), so this module loads it
with stub modules and replaces the Selenium steps with local functions that
write small CSVs.  The resume bookkeeping, per-account conclusions, merge
input selection and summary logging exercise the real code paths.
"""

import csv
import importlib.util
import logging
import os
import sys
import types

import pytest

import run_support

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_PATH = os.path.join(REPO_ROOT, "main.py")

ACCOUNTS = [
    "IN303028-76957800-6500081466-NRE",
    "IN303028-76957818-7500062485-NRO",
    "IN303028-76957826-7510072528-NPNRO",
]
ORDER_HEADERS = ["Stock", "Order Type", "Status"]


@pytest.fixture(autouse=True)
def _restore_modules():
    """Undo the stub-module injection so other test modules see real ones."""
    snapshot = dict(sys.modules)
    yield
    sys.modules.clear()
    sys.modules.update(snapshot)


def _install_stub_module(name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    sys.modules[name] = module
    return module


def load_main(tmp_path):
    """Import main.py with the browser stack replaced by harmless stubs."""
    _install_stub_module("selenium", webdriver=None)
    _install_stub_module(
        "selenium.webdriver",
        common=types.SimpleNamespace(by=None),
        support=types.SimpleNamespace(),
        chrome=types.SimpleNamespace(service=None),
    )
    _install_stub_module("selenium.webdriver.common.by", By=object)
    _install_stub_module("selenium.webdriver.common.action_chains", ActionChains=object)
    _install_stub_module(
        "selenium.webdriver.support.ui",
        WebDriverWait=lambda *a, **k: None,
        Select=object,
    )
    _install_stub_module(
        "selenium.webdriver.support", expected_conditions=types.SimpleNamespace()
    )
    _install_stub_module("selenium.webdriver.chrome.service", Service=object)
    _install_stub_module("webdriver_manager.chrome", ChromeDriverManager=object)
    _install_stub_module("retrying", retry=lambda **kwargs: (lambda fn: fn))
    _install_stub_module("tabulate", tabulate=lambda *a, **k: "")
    _install_stub_module("dotenv", load_dotenv=lambda *a, **k: None)

    spec = importlib.util.spec_from_file_location(
        f"main_under_test_{len(sys.modules)}", MAIN_PATH
    )
    module = importlib.util.module_from_spec(spec)
    # main.py installs a file handler on import; keep test runs from writing
    # icici_extract.log into the repository.
    original_basic_config = logging.basicConfig
    logging.basicConfig = lambda *a, **k: None
    try:
        spec.loader.exec_module(module)
    finally:
        logging.basicConfig = original_basic_config

    # Point the run at a scratch download root and out of the repo.
    module.CONFIG["download_base_dir"] = str(tmp_path / "downloads")
    module.SUB_ACCOUNTS = list(ACCOUNTS)
    return module


def write_csv(directory, account_id, data_type, rows):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{account_id}_{data_type}.csv")
    with open(path, "w", newline="", encoding="utf-8") as outfile:
        writer = csv.writer(outfile)
        writer.writerow(ORDER_HEADERS)
        writer.writerows(rows)
    return path


def read_csv(path):
    with open(path, "r", encoding="utf-8") as infile:
        return list(csv.reader(infile))


def wire_local_collection(module, fail_for=None, fail_step=None):
    """Replace the Selenium steps with local CSV writes."""
    base = module.CONFIG["download_base_dir"]

    def step(account_id, data_type):
        if account_id == fail_for and data_type == (fail_step or data_type):
            raise RuntimeError(f"{data_type} download failed for {account_id}")
        return write_csv(
            module.get_account_download_dir(account_id),
            account_id,
            data_type,
            [[f"{account_id}-{data_type}", "Buy", "Active"]],
        )

    def show_orderbook(account_id):
        step(account_id, "orders_cleaned")
        return [["row"]]

    module.init_driver = lambda: None
    module.login = lambda: None
    module.switch_account = lambda account_id: None
    module.download_tradebook = lambda account_id: step(account_id, "tradebook")
    module.download_portfolio = lambda account_id: step(account_id, "portfolio")
    module.download_myportfolio = lambda account_id: step(account_id, "myportfolio")
    module.download_orderbook = lambda account_id: step(account_id, "orderbook")
    module.show_orderbook = show_orderbook
    return base


def merged_orders(base):
    names = [name for name in os.listdir(base) if name.startswith("all_orders_")]
    assert len(names) == 1, names
    return read_csv(os.path.join(base, names[0]))


def test_three_accounts_succeed_and_consolidated_file_has_every_account(tmp_path, caplog):
    module = load_main(tmp_path)
    wire_local_collection(module)

    with caplog.at_level(logging.INFO):
        module.main()

    progress = run_support.load_progress(module.CONFIG["download_base_dir"])
    assert set(progress["accounts"]) == set(ACCOUNTS)
    for account_id in ACCOUNTS:
        entry = progress["accounts"][account_id]
        assert entry["status"] == run_support.STATUS_SUCCESS
        assert entry["error"] is None
        assert any(path.endswith("_orders_cleaned.csv") for path in entry["files"])

    rows = merged_orders(module.CONFIG["download_base_dir"])
    assert rows[0] == ["Account ID"] + ORDER_HEADERS
    assert {row[0] for row in rows[1:]} == set(ACCOUNTS)
    assert "3 succeeded, 0 skipped, 0 failed" in caplog.text


def test_account_failure_is_recorded_and_others_complete(tmp_path, caplog):
    module = load_main(tmp_path)
    wire_local_collection(module, fail_for=ACCOUNTS[1])

    with caplog.at_level(logging.INFO):
        module.main()

    progress = run_support.load_progress(module.CONFIG["download_base_dir"])
    assert progress["accounts"][ACCOUNTS[0]]["status"] == run_support.STATUS_SUCCESS
    assert progress["accounts"][ACCOUNTS[2]]["status"] == run_support.STATUS_SUCCESS
    failed = progress["accounts"][ACCOUNTS[1]]
    assert failed["status"] == run_support.STATUS_FAILED
    assert "download failed" in failed["error"]

    rows = merged_orders(module.CONFIG["download_base_dir"])
    assert {row[0] for row in rows[1:]} == {ACCOUNTS[0], ACCOUNTS[2]}

    assert "2 succeeded, 0 skipped, 1 failed" in caplog.text


def test_failure_after_partial_download_excludes_that_account_from_merge(tmp_path):
    """A failure midway through an account keeps the merge to complete ones."""
    module = load_main(tmp_path)
    wire_local_collection(module, fail_for=ACCOUNTS[1], fail_step="portfolio")

    module.main()

    progress = run_support.load_progress(module.CONFIG["download_base_dir"])
    failed = progress["accounts"][ACCOUNTS[1]]
    assert failed["status"] == run_support.STATUS_FAILED
    assert "portfolio download failed" in failed["error"]
    # Files written before the failure are still listed for diagnosis.
    assert any(path.endswith("_tradebook.csv") for path in failed["files"])

    rows = merged_orders(module.CONFIG["download_base_dir"])
    assert {row[0] for row in rows[1:]} == {ACCOUNTS[0], ACCOUNTS[2]}


def test_resume_skips_completed_accounts_and_recollects_missing_files(tmp_path, caplog):
    base = str(tmp_path / "downloads")
    os.makedirs(base, exist_ok=True)
    progress = {"version": 1, "accounts": {}}
    for account_id in ACCOUNTS:
        path = write_csv(
            os.path.join(base, account_id),
            account_id,
            "orders_cleaned",
            [["A", "Buy", "Active"]],
        )
        progress["accounts"][account_id] = {
            "status": run_support.STATUS_SUCCESS,
            "error": None,
            "files": [os.path.abspath(path)],
        }
    os.remove(os.path.join(base, ACCOUNTS[2], f"{ACCOUNTS[2]}_orders_cleaned.csv"))
    run_support.save_progress(base, progress)

    module = load_main(tmp_path)
    calls = []
    base = wire_local_collection(module)
    original_process = module.process_account

    def tracking(account_id):
        calls.append(account_id)
        return original_process(account_id)

    module.process_account = tracking
    with caplog.at_level(logging.INFO):
        module.main()

    assert calls == [ACCOUNTS[2]]
    assert "1 succeeded, 2 skipped, 0 failed" in caplog.text

    rows = merged_orders(base)
    # Skipped accounts' files are still part of this run's merge.
    assert {row[0] for row in rows[1:]} == set(ACCOUNTS)


def test_corrupt_progress_file_starts_a_fresh_run(tmp_path):
    base = str(tmp_path / "downloads")
    os.makedirs(base, exist_ok=True)
    with open(
        os.path.join(base, run_support.PROGRESS_FILENAME), "w", encoding="utf-8"
    ) as outfile:
        outfile.write("not json at all")

    module = load_main(tmp_path)
    wire_local_collection(module)
    module.main()

    progress = run_support.load_progress(base)
    assert set(progress["accounts"]) == set(ACCOUNTS)
    assert all(
        entry["status"] == run_support.STATUS_SUCCESS
        for entry in progress["accounts"].values()
    )


def test_stale_files_from_previous_run_do_not_enter_the_merge(tmp_path):
    """An account that fails this run must not contribute yesterday's file."""
    base = str(tmp_path / "downloads")
    os.makedirs(base, exist_ok=True)
    account_dir = os.path.join(base, ACCOUNTS[1])

    # Yesterday's run recorded this account as successful, but the file it
    # produced no longer exists, so this run must collect it again.
    stale = write_csv(account_dir, ACCOUNTS[1], "orders_cleaned", [["STALE", "Sell", "Old"]])
    run_support.save_progress(
        base,
        {
            "version": 1,
            "accounts": {
                ACCOUNTS[1]: {
                    "status": run_support.STATUS_SUCCESS,
                    "error": None,
                    "files": [os.path.abspath(stale)],
                }
            },
        },
    )
    os.remove(stale)

    module = load_main(tmp_path)
    wire_local_collection(module, fail_for=ACCOUNTS[1])

    # Re-create the old artefact while the failing account is processed,
    # simulating a leftover file the failed account never replaced.
    original_switch = module.switch_account

    def switch_then_restore(account_id):
        original_switch(account_id)
        if account_id == ACCOUNTS[1]:
            write_csv(account_dir, ACCOUNTS[1], "orders_cleaned", [["STALE", "Sell", "Old"]])

    module.switch_account = switch_then_restore
    module.main()

    progress = run_support.load_progress(base)
    assert progress["accounts"][ACCOUNTS[1]]["status"] == run_support.STATUS_FAILED

    rows = merged_orders(base)
    assert {row[0] for row in rows[1:]} == {ACCOUNTS[0], ACCOUNTS[2]}
    assert all(row[1] != "STALE" for row in rows[1:])
