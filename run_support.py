"""Per-account run bookkeeping, resume support and CSV consolidation.

The helpers in this module intentionally depend only on the standard
library.  That keeps the orchestration, progress-file and consolidation
logic testable without Selenium, a browser or the live ICICI site.

A batch run works like this:

* ``load_progress`` reads the progress file from the download root.  A
  missing or unreadable/corrupt file is treated as a fresh run.
* ``run_batch`` processes the accounts one by one.  An account whose
  previous run succeeded and whose recorded files are still present is
  skipped.  Every other account is handed to the supplied callback; a
  single failure is recorded and the next account is still attempted.
* After each account (including failures) the progress file is rewritten
  immediately, so an interrupted run can always be resumed.
* ``consolidate_csvs`` merges only the CSV files that the caller passes
  in, i.e. files produced by accounts that succeeded in this run (or were
  skipped because their files already existed).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Iterable, List, Optional, Sequence

PROGRESS_FILENAME = "run_progress.json"
PROGRESS_VERSION = 1

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
_KNOWN_STATUSES = {STATUS_SUCCESS, STATUS_FAILED, STATUS_SKIPPED}

# Partial Chrome downloads must never be reported as collected files.
_PARTIAL_EXTENSIONS = (".crdownload", ".part", ".tmp")


def _logger(logger: Optional[logging.Logger]) -> logging.Logger:
    return logger if logger is not None else logging.getLogger(__name__)


def progress_path(download_base_dir: str, filename: str = PROGRESS_FILENAME) -> str:
    """Absolute path of the progress file for a download root."""
    return os.path.join(os.path.abspath(download_base_dir), filename)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class AccountResult:
    """The conclusion recorded for one account after it was processed."""

    account_id: str
    status: str
    error: Optional[str] = None
    files: List[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == STATUS_SUCCESS

    @property
    def skipped(self) -> bool:
        return self.status == STATUS_SKIPPED

    @property
    def failed(self) -> bool:
        return self.status == STATUS_FAILED

    def as_dict(self) -> Dict[str, object]:
        return {
            "account_id": self.account_id,
            "status": self.status,
            "error": self.error,
            "files": list(self.files),
        }


def _sanitise_entry(entry: object) -> Optional[Dict[str, object]]:
    """Return a usable progress entry, or None when it is unusable."""
    if not isinstance(entry, dict):
        return None
    status = entry.get("status")
    if status not in _KNOWN_STATUSES:
        status = None
    raw_files = entry.get("files")
    files = (
        [f for f in raw_files if isinstance(f, str)]
        if isinstance(raw_files, list)
        else []
    )
    error = entry.get("error") if isinstance(entry.get("error"), str) else None
    updated_at = (
        entry.get("updated_at") if isinstance(entry.get("updated_at"), str) else None
    )
    return {
        "status": status,
        "error": error,
        "files": files,
        "updated_at": updated_at,
    }


def load_progress(
    download_base_dir: str,
    filename: str = PROGRESS_FILENAME,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, object]:
    """Load the progress file, always returning a usable structure.

    A missing file means a fresh run.  A corrupt/unreadable file is logged
    and also treated as a fresh run; this function never raises because of
    the file contents.
    """
    log = _logger(logger)
    path = progress_path(download_base_dir, filename)
    if not os.path.exists(path):
        log.info("Progress file %s not found; starting a fresh run", path)
        return {"version": PROGRESS_VERSION, "accounts": {}}

    try:
        with open(path, "r", encoding="utf-8") as infile:
            raw = json.load(infile)
    except Exception as exc:  # corrupt JSON, unreadable file, wrong encoding...
        log.warning(
            "Ignoring unusable progress file %s (%s: %s); starting a fresh run",
            path,
            type(exc).__name__,
            exc,
        )
        return {"version": PROGRESS_VERSION, "accounts": {}}

    if not isinstance(raw, dict):
        log.warning(
            "Ignoring progress file %s: expected an object, got %s; starting a fresh run",
            path,
            type(raw).__name__,
        )
        return {"version": PROGRESS_VERSION, "accounts": {}}

    raw_accounts = raw.get("accounts", {})
    if not isinstance(raw_accounts, dict):
        log.warning(
            "Ignoring progress file %s: 'accounts' is not an object; starting a fresh run",
            path,
        )
        return {"version": PROGRESS_VERSION, "accounts": {}}

    accounts: Dict[str, Dict[str, object]] = {}
    for account_id, entry in raw_accounts.items():
        if not isinstance(account_id, str):
            continue
        sanitised = _sanitise_entry(entry)
        if sanitised is not None:
            accounts[account_id] = sanitised

    return {"version": PROGRESS_VERSION, "accounts": accounts}


def save_progress(
    download_base_dir: str,
    progress: Dict[str, object],
    filename: str = PROGRESS_FILENAME,
    logger: Optional[logging.Logger] = None,
) -> bool:
    """Atomically write the progress file.

    Returns ``True`` on success.  A write failure is logged but never
    propagates: losing resume information must not abort an otherwise
    successful collection run.
    """
    log = _logger(logger)
    path = progress_path(download_base_dir, filename)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        progress = dict(progress)
        progress["version"] = PROGRESS_VERSION
        progress["updated_at"] = _now_iso()
        tmp_path = path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as outfile:
            json.dump(progress, outfile, indent=2, ensure_ascii=False)
            outfile.write("\n")
        os.replace(tmp_path, path)
        return True
    except Exception as exc:
        log.error("Failed to write progress file %s: %s", path, exc)
        return False


def should_skip_account(
    progress: Dict[str, object], account_id: str
) -> bool:
    """True when the account already completed and all its files remain."""
    accounts = progress.get("accounts", {})
    if not isinstance(accounts, dict):
        return False
    entry = accounts.get(account_id)
    if not isinstance(entry, dict) or entry.get("status") != STATUS_SUCCESS:
        return False
    files = entry.get("files") or []
    if not isinstance(files, list) or not files:
        return False
    return all(isinstance(f, str) and os.path.isfile(f) for f in files)


def _account_dir(download_base_dir: str, account_id: str) -> str:
    return os.path.join(os.path.abspath(download_base_dir), account_id)


def _snapshot(account_dir: str) -> Dict[str, tuple]:
    """Capture name -> (size, mtime_ns) for files currently present."""
    snapshot: Dict[str, tuple] = {}
    try:
        with os.scandir(account_dir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                stat = entry.stat()
                snapshot[entry.name] = (stat.st_size, stat.st_mtime_ns)
    except FileNotFoundError:
        pass
    return snapshot


def _collect_produced_files(
    account_dir: str, before: Dict[str, tuple]
) -> List[str]:
    """Files created or rewritten in the account directory since ``before``."""
    produced: List[str] = []
    try:
        with os.scandir(account_dir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                name = entry.name
                if name.lower().endswith(_PARTIAL_EXTENSIONS):
                    continue
                stat = entry.stat()
                if before.get(name) != (stat.st_size, stat.st_mtime_ns):
                    produced.append(os.path.abspath(entry.path))
    except FileNotFoundError:
        pass
    return sorted(produced)


def short_error(exc: BaseException, limit: int = 240) -> str:
    """A one-line, bounded description of the first error for an account."""
    message = " ".join(str(exc).split())
    text = f"{type(exc).__name__}: {message}" if message else type(exc).__name__
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def _merge_files(returned: object, produced: Iterable[str]) -> List[str]:
    """Combine explicitly returned files with the inferred ones."""
    merged: List[str] = []
    seen = set()

    def add(path: object) -> None:
        if not isinstance(path, str) or not os.path.isfile(path):
            return
        absolute = os.path.abspath(path)
        if absolute not in seen:
            seen.add(absolute)
            merged.append(absolute)

    if isinstance(returned, (list, tuple, set)):
        for path in returned:
            add(path)
    else:
        add(returned)
    for path in produced:
        add(path)
    return merged


def _account_progress(progress: Dict[str, object]) -> Dict[str, object]:
    accounts_progress = progress.get("accounts")
    if not isinstance(accounts_progress, dict):
        accounts_progress = {}
        progress["accounts"] = accounts_progress
    return accounts_progress


def _record_progress(
    progress: Dict[str, object],
    account_id: str,
    status: str,
    error: Optional[str],
    files: Sequence[str],
    download_base_dir: str,
    progress_filename: str,
    log: logging.Logger,
) -> None:
    """Store one account conclusion and flush it to disk immediately."""
    _account_progress(progress)[account_id] = {
        "status": status,
        "error": error,
        "files": list(files),
        "updated_at": _now_iso(),
    }
    save_progress(download_base_dir, progress, progress_filename, log)


def run_batch(
    accounts: Sequence[str],
    process_account: Callable[[str], object],
    download_base_dir: str,
    progress_filename: str = PROGRESS_FILENAME,
    logger: Optional[logging.Logger] = None,
    pre_run: Optional[Callable[[], None]] = None,
    progress: Optional[Dict[str, object]] = None,
) -> List[AccountResult]:
    """Process accounts one by one, recording a conclusion for each.

    ``process_account`` performs the real scraping for one account.  It may
    return a sequence of file paths it produced; files written into the
    account's directory are also detected automatically.

    ``pre_run`` (usually login) runs once, immediately before the first
    account that actually needs processing.  When every account is skipped
    it never runs, so a resumed no-op does not open a browser.  A failed
    ``pre_run`` marks every account still needing work as failed, since
    none of them can be collected.
    """
    log = _logger(logger)
    if progress is None:
        progress = load_progress(download_base_dir, progress_filename, log)

    results: List[AccountResult] = []
    pre_run_done = False

    for index, account_id in enumerate(accounts):
        if should_skip_account(progress, account_id):
            entry = _account_progress(progress)[account_id]
            files = list(entry.get("files") or [])
            results.append(AccountResult(account_id, STATUS_SKIPPED, None, files))
            log.info(
                "Account %s: status=skipped reason=already completed (%d files still present)",
                account_id,
                len(files),
            )
            continue

        if pre_run is not None and not pre_run_done:
            try:
                pre_run()
            except Exception as exc:
                error = short_error(exc)
                log.error(
                    "Batch setup failed before account %s: %s\n%s",
                    account_id,
                    error,
                    traceback.format_exc(),
                )
                for pending in accounts[index:]:
                    if should_skip_account(progress, pending):
                        continue
                    results.append(AccountResult(pending, STATUS_FAILED, error, []))
                    _record_progress(
                        progress,
                        pending,
                        STATUS_FAILED,
                        error,
                        [],
                        download_base_dir,
                        progress_filename,
                        log,
                    )
                    log.info(
                        "Account %s: status=failed error=%s reason=batch setup failed",
                        pending,
                        error,
                    )
                return results
            pre_run_done = True

        account_dir = _account_dir(download_base_dir, account_id)
        os.makedirs(account_dir, exist_ok=True)
        before = _snapshot(account_dir)

        returned: object = None
        error: Optional[str] = None
        status = STATUS_SUCCESS
        try:
            returned = process_account(account_id)
        except Exception as exc:
            status = STATUS_FAILED
            error = short_error(exc)
            log.error(
                "Account %s: first error: %s\n%s",
                account_id,
                error,
                traceback.format_exc(),
            )

        files = _merge_files(returned, _collect_produced_files(account_dir, before))
        results.append(AccountResult(account_id, status, error, files))
        _record_progress(
            progress,
            account_id,
            status,
            error,
            files,
            download_base_dir,
            progress_filename,
            log,
        )
        log.info(
            "Account %s: status=%s error=%s files=%s",
            account_id,
            status,
            error if error else "-",
            ", ".join(os.path.basename(f) for f in files) if files else "-",
        )

    return results


def summarise_results(results: Sequence[AccountResult]) -> Dict[str, int]:
    summary = {STATUS_SUCCESS: 0, STATUS_SKIPPED: 0, STATUS_FAILED: 0}
    for result in results:
        if result.status in summary:
            summary[result.status] += 1
    return summary


def files_for_consolidation(
    results: Sequence[AccountResult], suffix: str
) -> List[str]:
    """Files from accounts that succeeded or were skipped, matching suffix.

    Failed accounts are excluded even if they produced some files before
    failing, so the merged output only contains complete account data.
    """
    collected: List[str] = []
    for result in results:
        if result.status not in (STATUS_SUCCESS, STATUS_SKIPPED):
            continue
        for path in result.files:
            if path.endswith(suffix) and os.path.isfile(path):
                collected.append(path)
    return collected


def _account_id_for_file(file_path: str, output_dir: str) -> str:
    """Account ID from the file's parent directory (fallback: file prefix)."""
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent != os.path.abspath(output_dir):
        return os.path.basename(parent)
    return os.path.basename(file_path).split("_")[0]


def consolidate_csvs(
    data_type: str,
    account_files: Sequence[str],
    output_dir: str,
    enabled: bool = True,
    logger: Optional[logging.Logger] = None,
) -> Optional[str]:
    """Merge the supplied per-account CSVs into one file.

    Only the file paths handed in are merged, so callers control exactly
    which accounts are included.  Missing files are logged and skipped
    instead of failing the whole merge.
    """
    log = _logger(logger)

    files: List[str] = []
    seen = set()
    for file_path in account_files:
        if not isinstance(file_path, str):
            continue
        absolute = os.path.abspath(file_path)
        if absolute in seen:
            continue
        seen.add(absolute)
        if not os.path.isfile(absolute):
            log.warning("Skipping missing %s file for consolidation: %s", data_type, file_path)
            continue
        files.append(absolute)

    if not enabled:
        log.info("Consolidation disabled; %d %s file(s) not merged", len(files), data_type)
        return None
    if not files:
        log.warning("No %s files to consolidate", data_type)
        return None

    os.makedirs(output_dir, exist_ok=True)
    stamp = int(time.time())
    output_path = os.path.join(os.path.abspath(output_dir), f"all_{data_type}_{stamp}.csv")
    # Two runs finishing in the same second must not overwrite each other.
    counter = 1
    while os.path.exists(output_path):
        counter += 1
        output_path = os.path.join(
            os.path.abspath(output_dir), f"all_{data_type}_{stamp}_{counter}.csv"
        )

    headers_written = False
    with open(output_path, "w", newline="", encoding="utf-8") as outfile:
        writer = csv.writer(outfile)
        for file_path in files:
            with open(file_path, "r", encoding="utf-8") as infile:
                reader = csv.reader(infile)
                headers = next(reader, None)
                if not headers:
                    log.warning("Skipping %s file without a header row: %s", data_type, file_path)
                    continue
                if not headers_written:
                    writer.writerow(["Account ID"] + headers)
                    headers_written = True
                account_id = _account_id_for_file(file_path, output_dir)
                for row in reader:
                    if row:
                        writer.writerow([account_id] + row)

    log.info(
        "Consolidated %d %s CSV(s) from %d account file(s) to %s",
        len(files),
        data_type,
        len(files),
        output_path,
    )
    return output_path
