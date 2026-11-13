"""
tests/test_merge_sorts.py
-------------------------
Offline tests for the --merge-sorts feature's engine-independent machinery:
the two-ordering merge itself (page_flow.merge_sort_rounds / finish_merged),
driven through the shared fetch loop with a fake browser driver, and the
?sort=title query builder.

Everything here is served from hand-built HTML strings in this file. Nothing
opens a socket: the fake driver answers goto() from an in-memory map, exactly
like smoke_test.py's _FakeOps. The Playwright-only argparse switch itself is
exercised in test_merge_sorts_cli.py, which skips cleanly when the engine
library is not installed.

The three paths the feature promises:
  1. merge + dedupe: a book the popularity ordering repeats is one row, and a
     book whose two rows disagree keeps the FIRST occurrence's fields;
  2. second-round-only: a book the first ordering never serves is appended by
     the title ordering and counted in the sidecar;
  3. the switch is refused (exit 2) on any mode or url it does not apply to.
"""

import json
import os
import sys
import tempfile
import types

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

import page_flow  # noqa: E402
import product_parser as P  # noqa: E402

AUTHOR_URL = "https://www.goodreads.com/author/list/656983.J_R_R_Tolkien"


# ---------------------------------------------------------------------------
# Hand-built author-list HTML
# ---------------------------------------------------------------------------

def _book_tile(sku, title, rating="4.30", ratings="100", year="1937"):
    """One schema.org/Book table row, the shape product_parser._parse_microdata
    reads. Kept minimal but real: the same selectors a captured author page
    uses, so parse_page() rather than a hand-made row drives every test."""
    return (
        '<tr itemscope="" itemtype="http://schema.org/Book">'
        '<td>'
        '<a href="/book/show/{sku}.The_Book_{sku}" title="{title}">'
        '<img class="bookCover" itemprop="image" '
        'src="https://i.gr-assets.com/cover_{sku}.jpg"/></a>'
        '</td><td>'
        '<a class="bookTitle" href="/book/show/{sku}.The_Book_{sku}" itemprop="url">'
        '<span itemprop="name">{title}</span></a><br/>'
        '<span itemprop="author" itemscope="" itemtype="http://schema.org/Person">'
        '<a class="authorName" href="https://www.goodreads.com/author/show/1.A" '
        'itemprop="url"><span itemprop="name">A. Author</span></a></span><br/>'
        '<span class="minirating">{rating} avg rating — {ratings} ratings</span> '
        'published {year} '
        '<a href="/work/editions/10{sku}-the-book">2 editions</a>'
        '</td></tr>'
    ).format(sku=sku, title=title, rating=rating, ratings=ratings, year=year)


def _pagination(total_pages, current):
    """will_paginate's own markup: an em.current naming the page SERVED plus
    links to the others. fetch_one_page compares em.current to the page the
    run asked for, so it must match `current` or page 2 reads as past-end."""
    parts = ['<div><em class="current">%d</em>' % current]
    for n in range(1, total_pages + 1):
        if n != current:
            parts.append('<a href="/author/list/656983.J_R_R_Tolkien?page=%d">%d</a>'
                         % (n, n))
    parts.append("</div>")
    return "".join(parts)


def author_page(books, total_pages=2, current=1):
    """A full author-list document serving `books` (a list of tile strings).

    The gr-assets stylesheet is what detect_page_state uses to tell a served
    page from an interstitial; without it a 200 page classifies as unknown.
    """
    return (
        '<!DOCTYPE html><html><head>'
        '<title>Books by A. Author (5 books)</title>'
        '<link rel="stylesheet" href="https://s.gr-assets.com/assets/cut.css">'
        '</head><body><table>'
        + "".join(books)
        + "</table>"
        + (_pagination(total_pages, current) if total_pages > 1 else "")
        + "</body></html>"
    )


# ---------------------------------------------------------------------------
# The fake browser driver, answering from an in-memory map
# ---------------------------------------------------------------------------

class FakeOps:
    """page_flow's named operations. `routes(url)` returns (status, html)."""

    def __init__(self, routes):
        self.routes = routes
        self.doc = ""
        self.landed = False
        self.pool = None
        self.gotos = []
        self.closed = False

    def goto(self, url):
        self.gotos.append(url)
        status, self.doc = self.routes(url)
        return status, ("challenge" if status == 202 else None)

    def document_text(self):
        return self.doc

    def wait_ms(self, ms):
        pass

    def solve_captcha(self):
        return False

    def fetch(self, req):
        return None, "", None, "listings navigate, they never fetch"

    def relaunch(self):
        self.landed = False

    def proxy_failure(self, text):
        return ""

    def close(self):
        self.closed = True


def _is_title(url):
    return "sort=title" in url


def _requested_page(url):
    return P.requested_page(url)


def _args(tmp, **kw):
    """The SimpleNamespace page_flow reads; same fields smoke_test.py's _args
    sets, plus the merge switch."""
    args = types.SimpleNamespace(
        url=AUTHOR_URL, mode=None, pages=2, retries=2, retry_delay=0, delay=0,
        proxy_block_retries=2, out=os.path.join(tmp, "out"), format="json",
        allow_empty=False, dump_html=None, cdp_endpoint=None, concurrency=1,
        headless=True, sort=None, rating=None, review_language=None,
        search_text=None, page_size=None, max_books=None, merge_sorts=True)
    for k, v in kw.items():
        setattr(args, k, v)
    return args


def _author_query():
    q, why = P.query_from_url(AUTHOR_URL)
    assert q is not None and q.kind == "author", why
    q.mode = "list"
    return q


def _run_merged(routes, tmp, **kw):
    """One full --merge-sorts run through the shared loop with the fake driver.
    Returns (rc, meta, rows, ops)."""
    args = _args(tmp, **kw)
    query = _author_query()
    ops = FakeOps(routes)
    rc = page_flow.run_pages_merged(
        lambda: ops, lambda o: o.close(),
        lambda pages, q: ([], [], False), args, None, query, 1)
    meta_path = args.out + ".meta.json"
    meta = json.load(open(meta_path, encoding="utf-8")) if os.path.exists(meta_path) else None
    rows_path = args.out + ".json"
    rows = json.load(open(rows_path, encoding="utf-8")) if os.path.exists(rows_path) else None
    return rc, meta, rows, ops


# ---------------------------------------------------------------------------
# Unit level: the merge itself
# ---------------------------------------------------------------------------

def _listed(sku, title=None, **fields):
    from output_writer import ListedBook
    row = ListedBook(sku=(None if sku is None else str(sku)),
                     title=title or "Book %s" % sku,
                     author="A. Author", mode="list", listing_kind="author")
    for k, v in fields.items():
        setattr(row, k, v)
    return row


def test_merge_keeps_first_occurrence_and_appends_second_round_only():
    # Round 1 (popularity): A, B repeated on its second page, C.
    first = [_listed(1, "Alpha", ratings_count=100, page=1, position=1),
             _listed(2, "Bravo", ratings_count=200, page=1, position=2),
             _listed(2, "Bravo", ratings_count=200, page=2, position=1),
             _listed(3, "Charlie", ratings_count=300, page=2, position=2)]
    # Round 2 (title): A with a moved rating, B identically, D only here.
    second = [_listed(1, "Alpha", ratings_count=105, page=1, position=1),
              _listed(2, "Bravo", ratings_count=200, page=1, position=2),
              _listed(4, "Delta", ratings_count=40, page=1, position=3)]

    result = page_flow.merge_sort_rounds(first, second)

    # One row per sku, first-round order first, the new book appended.
    assert [r.sku for r in result.rows] == ["1", "2", "3", "4"]
    # The repeated sku 2 collapsed to its first row object.
    assert sum(1 for r in result.rows if r.sku == "2") == 1
    # Fields come from the FIRST occurrence even though round 2 disagreed:
    # the merged sku 1 keeps the popularity round's rating count.
    alpha = next(r for r in result.rows if r.sku == "1")
    assert alpha.ratings_count == 100
    # The disagreement was noticed and named by field (page/position differ too
    # but describe the run, so they must not be reported).
    assert result.different and result.different[0]["sku"] == "1"
    assert result.different[0]["fields"] == ["ratings_count"]
    assert result.second_only_skus == ["4"]


def test_merge_ignores_run_only_fields_when_comparing():
    first = [_listed(7, page=1, position=5)]
    second = [_listed(7, page=2, position=9)]
    result = page_flow.merge_sort_rounds(first, second)
    assert [r.sku for r in result.rows] == ["7"]
    assert result.different == []  # page/position alone is not a conflict


def test_merge_never_drops_a_row_without_a_sku():
    first = [_listed(1), _listed(None, title="No id")]
    second = [_listed(1), _listed(None, title="No id too")]
    result = page_flow.merge_sort_rounds(first, second)
    # Both keyless rows survive, and neither is counted as second-round-only.
    assert len(result.rows) == 3
    assert result.second_only_skus == []


def test_title_sorted_query_reuses_the_list_with_sort_title_and_restarts_at_page_1():
    q = _author_query()
    q.start_page = 3
    tq = page_flow.title_sorted_query(q)
    assert tq.kind == "author" and tq.mode == "list"
    assert tq.url == "https://www.goodreads.com/author/list/656983.J_R_R_Tolkien?sort=title"
    assert tq.start_page == 1
    # Any pre-existing sort parameter is replaced, not duplicated.
    q2, _ = P.query_from_url(AUTHOR_URL + "?sort=popularity")
    tq2 = page_flow.title_sorted_query(q2)
    assert tq2.url.endswith("?sort=title") and tq2.url.count("sort=") == 1


# ---------------------------------------------------------------------------
# End to end through the shared fetch loop with the fake driver
# ---------------------------------------------------------------------------

def test_end_to_end_merge_dedupe_second_round_only_and_meta(tmp_path):
    # Popularity ordering, two pages. Book 2 is repeated onto page 2; book 5
    # never appears under this ordering.
    popularity = {
        1: author_page([_book_tile(1, "Alpha", ratings="100"),
                        _book_tile(2, "Bravo", ratings="200")], current=1),
        2: author_page([_book_tile(2, "Bravo", ratings="200"),
                        _book_tile(3, "Charlie", ratings="300"),
                        _book_tile(4, "Delta", ratings="400")], current=2),
    }
    # Title ordering, two pages. Book 1's rating moved (a real disagreement to
    # log); book 5 is served only here.
    title = {
        1: author_page([_book_tile(1, "Alpha", ratings="105"),
                        _book_tile(2, "Bravo", ratings="200")], current=1),
        2: author_page([_book_tile(3, "Charlie", ratings="300"),
                        _book_tile(4, "Delta", ratings="400"),
                        _book_tile(5, "Echo", ratings="50")], current=2),
    }

    def routes(url):
        page = _requested_page(url)
        return 200, (title if _is_title(url) else popularity)[page]

    rc, meta, rows, ops = _run_merged(routes, str(tmp_path))

    assert rc == 0
    # Four navigations: each ordering's pages 1 and 2; round 2 carries sort.
    assert len(ops.gotos) == 4
    assert any("sort=title" in u for u in ops.gotos)
    assert all("sort=title" not in u for u in ops.gotos[:2])
    assert ops.closed  # the driver the run opened was shut down

    # 2 + 3 raw slots in round 1 (one repeated), but the union is the five
    # distinct books in first-round order with the title-only book appended.
    assert [r["sku"] for r in rows] == ["1", "2", "3", "4", "5"]
    # First-occurrence wins: sku 1 keeps the popularity round's rating count.
    assert next(r for r in rows if r["sku"] == "1")["ratings_count"] == 100

    block = meta["merge_sorts"]
    assert block["enabled"] is True
    # Popularity served 2 + 3 = 5 raw slots, one of them (sku 2) repeated,
    # so 4 distinct books under that ordering.
    assert block["rounds"]["default"]["rows_fetched"] == 5
    assert block["rounds"]["default"]["internal_duplicate_rows"] == 1
    assert block["rounds"]["default"]["distinct_rows"] == 4
    assert block["rounds"]["title"]["rows_fetched"] == 5
    assert block["rounds"]["title"]["internal_duplicate_rows"] == 0
    assert block["rounds"]["title"]["distinct_rows"] == 5
    assert block["merged_rows"] == 5
    assert block["second_round_only_rows"] == 1
    assert block["second_round_only_skus"] == ["5"]
    assert block["conflicting_rows"] == 1
    assert block["conflicts"][0]["sku"] == "1"
    # Both rounds really fetched the full --pages 2, so more could exist.
    assert block["may_have_more_books"] is True
    # The plain-run fields keep their meaning; repeats are the two rounds' sum.
    assert meta["repeated_across_pages"] == 1
    assert meta["mode"] == "list"
    assert meta["status"] == "complete" and meta["pages_failed"] == []


def test_may_have_more_is_false_when_an_ordering_ends_before_the_cap(tmp_path):
    popularity = {
        1: author_page([_book_tile(1, "Alpha"), _book_tile(2, "Bravo")],
                       total_pages=1, current=1),
    }
    title = {
        1: author_page([_book_tile(1, "Alpha"), _book_tile(3, "Charlie")],
                       total_pages=1, current=1),
    }

    def routes(url):
        page = _requested_page(url)
        bucket = title if _is_title(url) else popularity
        # A page past the one-page listing: the site's own 404 (empty answer),
        # which page_flow reads as the listing genuinely ending.
        if page not in bucket:
            return 404, ("<!DOCTYPE html><html><head>"
                         '<link rel="stylesheet" href="https://s.gr-assets.com/x.css">'
                         "</head><body>not found</body></html>")
        return 200, bucket[page]

    rc, meta, rows, ops = _run_merged(routes, str(tmp_path), pages=3)

    assert rc == 0
    assert [r["sku"] for r in rows] == ["1", "2", "3"]
    # Neither ordering walked three pages, so nothing of either can be missing.
    assert meta["merge_sorts"]["may_have_more_books"] is False
    # The run still asked for two rounds of three; only the served pages count.
    assert meta["pages_requested"] == 6
    assert meta["merge_sorts"]["rounds"]["default"]["pages_fetched"] == 1


def test_a_failed_round_is_named_in_the_sidecar_and_the_other_round_kept(tmp_path):
    popularity = {
        1: author_page([_book_tile(1, "Alpha"), _book_tile(2, "Bravo")], current=1),
        2: author_page([_book_tile(3, "Charlie")], current=2),
    }
    title = {
        1: author_page([_book_tile(1, "Alpha"), _book_tile(4, "Delta")], current=1),
    }

    def routes(url):
        page = _requested_page(url)
        if _is_title(url) and page == 2:
            return 403, "<html><head></head><body></body></html>"
        return 200, (title if _is_title(url) else popularity)[page]

    rc, meta, rows, _ = _run_merged(routes, str(tmp_path))

    # Partial: the good pages are written, the block is reported, exit 6.
    assert rc == 6
    assert meta["status"] == "partial"
    # Namespaced page label shows WHICH round's page 2 failed.
    assert meta["pages_failed"] == ["title-2"]
    assert {r["sku"] for r in rows} == {"1", "2", "3", "4"}
    assert meta["merge_sorts"]["may_have_more_books"] is False
