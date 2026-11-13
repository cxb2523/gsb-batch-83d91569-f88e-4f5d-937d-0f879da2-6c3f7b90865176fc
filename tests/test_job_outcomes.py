"""
tests/test_job_outcomes.py
--------------------------
The `--mode job` batch contract, as a pytest module.

`smoke_test.py` is the project's single offline runner (see CONTRIBUTING.md)
and `tests/test_smoke.py` wraps the whole of it. This file exists beside that
wrapper for one reason: the full suite also covers every engine's driver
import and the `.env.example` round-trip, and on a machine where pyppeteer
cannot resolve its home directory or that file is absent, the wrapper fails
for reasons that have nothing to do with job batches. That makes it a poor
signal for THIS change.

So the same check is invoked directly — no network, no browser, only the
engine's own `scrape()` with its fetch and session stubbed — and it asserts
that the check appended no failures. The check itself lives in smoke_test.py
rather than here so `python3 smoke_test.py` runs it too; both entry points
therefore exercise one implementation, not two.

It needs `playwright` INSTALLED (the engine imports its driver at module
level by design), but never launches a browser: the CI job that installs no
engine skips this rather than passing vacuously.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import smoke_test  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_suite_state():
    """The suite's counters are module globals; leave them as we found them."""
    yield
    smoke_test.FAILURES.clear()
    smoke_test.SKIPS.clear()


def _run(check):
    smoke_test.FAILURES.clear()
    smoke_test.SKIPS.clear()
    check()
    assert smoke_test.FAILURES == [], "\n".join(smoke_test.FAILURES)
    if smoke_test.SKIPS:
        # The engine's driver library is not installed here (the offline CI
        # job installs no engine on purpose). The check then cannot run at
        # all, and reporting green would be a lie — skip, naming why.
        pytest.skip("; ".join(smoke_test.SKIPS))


def test_every_enumerated_job_address_is_tried_and_recorded():
    """A 404 between live addresses does not end the batch; a 5xx does not
    either; the per-address list names each address's outcome and attempt
    count; a one-URL run has a one-entry list."""
    _run(smoke_test.check_every_enumerated_job_address_is_tried_and_recorded)


def test_a_withdrawn_listing_does_not_end_the_job_queue():
    """The queue keeps walking, and the run stays complete at exit 0."""
    _run(smoke_test.check_a_withdrawn_listing_does_not_end_the_job_queue)
