"""Tests for SitemapCrawler's auditable crawl summary.

Scenarios covered (all against a local static HTTP site):

1. normal nested sitemap index;
2. partial failure (one broken child sitemap, one working);
3. total failure (every child sitemap fails);
4. duplicate references (the same child sitemap listed twice).

Plus: duplicate page URLs across sitemaps keep first-occurrence order,
deduplication accounting, per-page fetch failures, and the no-sitemap case.
"""

import csv

import pytest

from sitemap_harvester.cli import format_summary, main
from sitemap_harvester.sitemap_harvester import (
    SITEMAP_STATUS_PARSE_FAILED,
    SITEMAP_STATUS_REQUEST_FAILED,
    SITEMAP_STATUS_SKIPPED,
    SITEMAP_STATUS_SUCCESS,
    SitemapCrawler,
)

from conftest import index_sitemap, url_sitemap, write_page


def _attempts_by_url(crawler):
    return {a.url: a for a in crawler.get_summary().sitemap_attempts}


def test_nested_index_normal(site_server):
    """Scenario 1: a sitemap index referencing two valid child sitemaps."""
    site = site_server

    page_a1 = write_page(site, "pages/a1.html", "a1")
    page_a2 = write_page(site, "pages/a2.html", "a2")
    page_b1 = write_page(site, "pages/b1.html", "b1")

    child_a = site.write("sitemaps/a.xml", url_sitemap([page_a1, page_a2]))
    child_b = site.write("sitemaps/b.xml", url_sitemap([page_b1]))
    site.write("sitemap.xml", index_sitemap([child_a, child_b]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    # All three sitemap documents were parsed exactly once and succeeded.
    assert summary.sitemaps_found == 1
    assert summary.sitemaps_attempted == 3
    assert summary.sitemaps_succeeded == 3
    assert summary.sitemaps_failed == 0
    assert summary.sitemaps_skipped == 0
    assert summary.all_sitemaps_failed is False
    assert summary.no_sitemaps_found is False

    attempts = _attempts_by_url(crawler)
    assert attempts[site.url("/sitemap.xml")].status == SITEMAP_STATUS_SUCCESS
    assert attempts[child_a].status == SITEMAP_STATUS_SUCCESS
    assert attempts[child_a].url_count == 2
    assert attempts[child_b].url_count == 1

    # URL accounting and first-occurrence order.
    assert summary.total_urls_before_dedup == 3
    assert summary.total_urls_after_dedup == 3
    assert summary.duplicates_removed == 0
    assert [r["url"] for r in results] == [page_a1, page_a2, page_b1]

    # Every page was fetched successfully.
    assert summary.pages_fetched == 3
    assert summary.pages_succeeded == 3
    assert summary.pages_failed == 0
    assert all("error" not in r for r in results)
    assert results[0]["title"] == "Page a1"
    assert results[0]["canonical"] == page_a1
    assert results[0]["og_title"] == "OG a1"

    # get_summary() exposes the same object via the documented new method.
    assert crawler.get_summary() is crawler.summary
    # The CLI summary renders without error and reports the same numbers.
    text = format_summary(crawler)
    assert "3 succeeded" in text
    assert "3 unique" in text


def test_partial_failure_keeps_working_results(site_server):
    """Scenario 2: one child returns invalid XML, another 404s, one works."""
    site = site_server

    page_good = write_page(site, "pages/good.html", "good")
    child_good = site.write("sitemaps/good.xml", url_sitemap([page_good]))
    child_bad_xml = site.write("sitemaps/bad.xml", "<not-valid-xml><")
    missing = site.url("/sitemaps/missing.xml")
    site.write(
        "sitemap.xml",
        index_sitemap([child_bad_xml, missing, child_good]),
    )

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    attempts = _attempts_by_url(crawler)
    assert attempts[child_bad_xml].status == SITEMAP_STATUS_PARSE_FAILED
    assert attempts[child_bad_xml].error
    assert attempts[missing].status == SITEMAP_STATUS_REQUEST_FAILED
    assert "404" in attempts[missing].error
    assert attempts[child_good].status == SITEMAP_STATUS_SUCCESS

    assert summary.sitemaps_parse_failed == 1
    assert summary.sitemaps_request_failed == 1
    assert summary.sitemaps_succeeded == 2  # index itself + good child
    assert summary.all_sitemaps_failed is False

    # URLs from the healthy child survive the broken siblings.
    assert summary.total_urls_after_dedup == 1
    assert [r["url"] for r in results] == [page_good]
    assert summary.pages_succeeded == 1
    assert summary.pages_failed == 0

    text = format_summary(crawler)
    assert "parse failed" in text
    assert "request failed" in text
    assert "1 unique" in text


def test_all_sub_sitemaps_fail_returns_empty(site_server):
    """Scenario 3: every child sitemap fails -> empty result, no crash."""
    site = site_server

    bad_xml = site.write("sitemaps/bad.xml", "<<<not xml>>>")
    missing = site.url("/sitemaps/missing.xml")
    site.write("sitemap.xml", index_sitemap([bad_xml, missing]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    assert results == []
    assert summary.all_sitemaps_failed is True
    assert summary.sitemaps_parse_failed == 1
    assert summary.sitemaps_request_failed == 1
    assert summary.sitemaps_succeeded == 1  # only the index document itself
    assert summary.total_urls_before_dedup == 0
    assert summary.total_urls_after_dedup == 0
    assert summary.pages_fetched == 0
    assert summary.no_sitemaps_found is False


def test_duplicate_sitemap_reference_parsed_once(site_server):
    """Scenario 4: the same child sitemap referenced twice is parsed once."""
    site = site_server

    page_1 = write_page(site, "pages/one.html", "one")
    page_2 = write_page(site, "pages/two.html", "two")
    child = site.write("sitemaps/child.xml", url_sitemap([page_1, page_2]))

    # The child is referenced twice, including from a nested index.
    nested = site.write("sitemaps/nested.xml", index_sitemap([child]))
    site.write("sitemap.xml", index_sitemap([child, nested]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    attempts = _attempts_by_url(crawler)
    # Exactly one real parse of the child; the second reference is skipped.
    assert attempts[child].status == SITEMAP_STATUS_SKIPPED or (
        # depending on traversal order the first occurrence is the success
        attempts[child].status == SITEMAP_STATUS_SUCCESS
    )
    statuses = [a.status for a in summary.sitemap_attempts if a.url == child]
    assert statuses.count(SITEMAP_STATUS_SUCCESS) == 1
    assert statuses.count(SITEMAP_STATUS_SKIPPED) == 1
    assert summary.sitemaps_skipped == 1

    # Skipped references must not contribute URLs a second time.
    assert summary.total_urls_before_dedup == 2
    assert summary.total_urls_after_dedup == 2
    assert [r["url"] for r in results] == [page_1, page_2]
    assert summary.pages_succeeded == 2


def test_duplicate_page_urls_keep_first_order(site_server):
    """The same page URL in two child sitemaps is counted once, first order."""
    site = site_server

    shared = write_page(site, "pages/shared.html", "shared")
    only_b = write_page(site, "pages/only-b.html", "only-b")
    child_a = site.write("sitemaps/a.xml", url_sitemap([shared]))
    child_b = site.write("sitemaps/b.xml", url_sitemap([shared, only_b]))
    site.write("sitemap.xml", index_sitemap([child_a, child_b]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    assert summary.total_urls_before_dedup == 3
    assert summary.total_urls_after_dedup == 2
    assert summary.duplicates_removed == 1
    # First appearance of the shared URL is in child_a, so it stays first.
    assert [r["url"] for r in results] == [shared, only_b]


def test_page_fetch_failure_recorded_without_stopping(site_server):
    """A page that 404s stays in the output with url + error columns."""
    site = site_server

    good = write_page(site, "pages/good.html", "good")
    dead = site.url("/pages/does-not-exist.html")
    child = site.write("sitemaps/child.xml", url_sitemap([dead, good]))
    site.write("sitemap.xml", index_sitemap([child]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    assert summary.pages_fetched == 2
    assert summary.pages_succeeded == 1
    assert summary.pages_failed == 1

    by_url = {r["url"]: r for r in results}
    assert "error" in by_url[dead]
    assert "404" in by_url[dead]["error"]
    assert "error" not in by_url[good]
    # The failed row still carries its URL.
    assert set(by_url[dead].keys()) >= {"url", "error"}


def test_no_sitemaps_found_distinguishable(site_server):
    """Discovery finding nothing is distinct from all-sitemaps-failed."""
    site = site_server  # serves an empty document root (no sitemap files)

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    assert results == []
    assert summary.no_sitemaps_found is True
    assert summary.all_sitemaps_failed is False
    assert summary.sitemaps_found == 0
    assert summary.sitemaps_attempted == 0


def test_robots_txt_discovery(site_server):
    """Sitemaps advertised through robots.txt are also picked up."""
    site = site_server

    page = write_page(site, "pages/p.html", "p")
    child = site.write("custom/secret-sitemap.xml", url_sitemap([page]))
    site.write(
        "robots.txt",
        "User-agent: *\nDisallow:\nSitemap: " + child + "\n",
    )

    crawler = SitemapCrawler(site.base_url, timeout=5)
    results = crawler.crawl()
    summary = crawler.get_summary()

    assert summary.sitemaps_found == 1
    assert [r["url"] for r in results] == [page]
    assert summary.pages_succeeded == 1


def test_repeated_crawl_resets_summary(site_server):
    """A second crawl() on the same instance must not accumulate state."""
    site = site_server

    page = write_page(site, "pages/p.html", "p")
    child = site.write("sitemaps/child.xml", url_sitemap([page]))
    site.write("sitemap.xml", index_sitemap([child]))

    crawler = SitemapCrawler(site.base_url, timeout=5)
    crawler.crawl()
    first = crawler.get_summary()
    assert first.sitemaps_attempted == 2

    crawler.crawl()
    second = crawler.get_summary()
    assert second is not first
    assert second.sitemaps_attempted == 2
    assert second.total_urls_after_dedup == 1
    assert second.pages_succeeded == 1


# ---------------------------------------------------------------------------
# CLI-level tests: exit codes, stderr summary, and unchanged CSV layout.
# ---------------------------------------------------------------------------


def _run_cli(monkeypatch, capsys, url, output, timeout=5):
    monkeypatch.setattr(
        "sys.argv",
        ["sitemap-harvester", "--url", url, "--output", str(output),
         "--timeout", str(timeout)],
    )
    try:
        main()
        code = 0  # main() returns normally on success -> exit code 0
    except SystemExit as exc:
        code = exc.code
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_success_writes_csv_with_priority_columns(
    site_server, tmp_path, monkeypatch, capsys
):
    site = site_server

    good = write_page(site, "pages/good.html", "good")
    dead = site.url("/pages/gone.html")
    child = site.write("sitemaps/child.xml", url_sitemap([good, dead]))
    site.write("sitemap.xml", index_sitemap([child]))

    output = tmp_path / "out.csv"
    code, _, err = _run_cli(monkeypatch, capsys, site.base_url, output)

    assert code == 0
    assert "Crawl summary:" in err
    assert "succeeded: 1, failed: 1" in err

    with open(output, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    # Existing column priority/order is unchanged; url stays first.
    assert header[0] == "url"
    priority = [
        "url", "title", "description", "keywords",
        "author", "canonical", "og_title", "image",
    ]
    present_priority = [c for c in priority if c in header]
    assert header[: len(present_priority)] == present_priority
    # Remaining columns are sorted.
    remainder = header[len(present_priority):]
    assert remainder == sorted(remainder)

    row_by_url = {row[header.index("url")]: row for row in rows}
    failed_row = row_by_url[dead]
    # Failed pages keep their url and error columns.
    assert failed_row[header.index("url")] == dead
    assert failed_row[header.index("error")]


def test_cli_all_failed_exits_nonzero_with_reason(
    site_server, tmp_path, monkeypatch, capsys
):
    site = site_server

    bad = site.write("sitemaps/bad.xml", "<broken><")
    site.write("sitemap.xml", index_sitemap([bad]))

    output = tmp_path / "out.csv"
    code, _, err = _run_cli(monkeypatch, capsys, site.base_url, output)

    assert code == 1
    assert "all" in err.lower() and "failed" in err.lower()
    assert "Crawl summary:" in err
    assert not output.exists()


def test_cli_no_sitemap_exits_nonzero_with_reason(
    site_server, tmp_path, monkeypatch, capsys
):
    site = site_server
    output = tmp_path / "out.csv"
    code, _, err = _run_cli(
        monkeypatch, capsys, site.base_url, output
    )

    assert code == 1
    assert "no sitemaps found" in err.lower()
    assert "Crawl summary:" in err
    assert not output.exists()
