"""
tests/test_merge_sorts_cli.py
-----------------------------
The Playwright-only surface of --merge-sorts: argparse must accept it on an
/author/list/ url and refuse it (exit 2, with a reason) on every other mode or
url. Nothing here launches a browser or touches the network — only
parse_args() runs, and the engine module is skipped when the Playwright
library is not installed (CI's offline job installs no engine).
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Importing the engine imports its driver at module level (by design). When it
# is absent the whole file is skipped, and recorded as such rather than erroring.
playwright_scraper = pytest.importorskip("playwright_scraper")

AUTHOR = "https://www.goodreads.com/author/list/656983.J_R_R_Tolkien"
LIST = "https://www.goodreads.com/list/show/1.Best_Books_Ever"
BOOK = "https://www.goodreads.com/book/show/5907.The_Hobbit"


def _rejected(argv):
    """Run parse_args; return (exit_code, stderr). argparse's p.error exits 2."""
    with pytest.raises(SystemExit) as exc:
        playwright_scraper.parse_args(argv)
    return exc.value.code


def test_merge_sorts_accepted_on_an_author_list_url():
    args = playwright_scraper.parse_args(
        ["--merge-sorts", "--url", AUTHOR, "--pages", "2"])
    assert args.merge_sorts is True
    assert args.query.mode == "list" and args.query.kind == "author"


def test_merge_sorts_refused_on_a_listopia_list():
    code = _rejected(["--merge-sorts", "--url", LIST])
    assert code == 2


def test_merge_sorts_refused_in_book_mode():
    code = _rejected(["--merge-sorts", "--mode", "book", "--url", AUTHOR])
    assert code == 2


def test_merge_sorts_refused_in_reviews_mode():
    code = _rejected(["--merge-sorts", "--mode", "reviews", "--url", BOOK])
    assert code == 2


def test_merge_sorts_refused_on_a_search_url():
    code = _rejected(
        ["--merge-sorts", "--url", "https://www.goodreads.com/search?q=dune"])
    assert code == 2


def test_switch_defaults_off_and_ordinary_parsing_is_unchanged():
    args = playwright_scraper.parse_args(["--url", AUTHOR, "--pages", "1"])
    assert args.merge_sorts is False
