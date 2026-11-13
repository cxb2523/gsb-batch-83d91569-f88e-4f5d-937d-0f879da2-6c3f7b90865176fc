"""
cli_types.py
-------------
argparse types that refuse a value the engines cannot honour, shared by all
four CLIs so a bound added here applies everywhere.

These exist because argparse's `type=int` accepts numbers that quietly turn
the run into something other than what was asked for. The measured example:
`--retries 0` made the attempt loop `range(1, 1)`, so the engine never
navigated at all, classified the blank tab as an interstitial and reported
exit 3 "blocked" — a verdict about the site, reached without sending it a
single request, after burning a proxy rotation.
"""

import argparse
from urllib.parse import urlparse

# The only host these engines know how to read. Not a hard refusal: a mirror,
# a locale host or a recorded fixture served locally are all legitimate, and
# the parser will simply say what it found. A typo'd host is the case this
# catches.
EXPECTED_HOST_SUFFIX = "flippa.com"


def positive_int(value: str) -> int:
    """An int >= 1. For counts where zero means "do nothing, silently"."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number")
    if number < 1:
        raise argparse.ArgumentTypeError(
            f"must be 1 or more, got {number} — zero or less does not mean "
            f"'no limit' here, it means the loop never runs")
    return number


def non_negative_int(value: str) -> int:
    """An int >= 0. For budgets where zero legitimately means "none"."""
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a whole number")
    if number < 0:
        raise argparse.ArgumentTypeError(f"cannot be negative, got {number}")
    return number


def non_negative_float(value: str) -> float:
    """A float >= 0, for delays. A negative sleep is not a faster run."""
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a number")
    if number < 0:
        raise argparse.ArgumentTypeError(f"cannot be negative, got {number}")
    return number


def check_listing_url(url: str) -> list:
    """Return the problems with `url`, worst first; empty means usable.

    Separate from the argparse types because --url may also arrive from the
    environment or .env, and that path has to be checked too.
    """
    problems = []
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        problems.append(
            f"--url must start with http:// or https://, got {url!r}")
    elif not parsed.netloc:
        problems.append(f"--url has no host: {url!r}")
    return problems


def host_is_expected(url: str) -> bool:
    host = (urlparse(url or "").hostname or "").lower()
    return host == EXPECTED_HOST_SUFFIX or host.endswith("." + EXPECTED_HOST_SUFFIX)
