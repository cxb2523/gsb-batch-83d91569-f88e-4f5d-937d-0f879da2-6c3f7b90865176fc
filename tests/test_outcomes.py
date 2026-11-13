from perfectclone.outcomes import CRAWL_ERROR, MIRROR_FAILED, NOT_VISITED, RESPONSE_REJECTED, ROBOTS_SKIPPED, SAVED, OutcomeBook


def test_one_record_per_url_with_accumulated_reasons():
    book = OutcomeBook()
    book.record("https://acme.com/a", SAVED, "first")
    book.record("https://acme.com/a", MIRROR_FAILED, "second")
    book.record("https://acme.com/a", MIRROR_FAILED, "second")  # duplicate reason is dropped
    entries = book.as_list()
    assert len(entries) == 1
    assert entries[0]["url"] == "https://acme.com/a"
    assert entries[0]["outcome"] == MIRROR_FAILED
    assert entries[0]["reason"] == "first; second"


def test_failure_overrides_success_but_success_never_erases_failure():
    book = OutcomeBook()
    book.record("https://acme.com/a", SAVED, "saved to site folder")
    assert book.outcome_of("https://acme.com/a") == SAVED
    book.record("https://acme.com/a", MIRROR_FAILED, "HTTP 503")
    assert book.outcome_of("https://acme.com/a") == MIRROR_FAILED
    book.record("https://acme.com/a", SAVED, "saved to site folder")
    assert book.outcome_of("https://acme.com/a") == MIRROR_FAILED
    assert book.urls(MIRROR_FAILED) == ["https://acme.com/a"]
    assert book.urls(SAVED) == []


def test_distinct_urls_keep_their_own_outcomes():
    book = OutcomeBook()
    book.record("https://acme.com/a", ROBOTS_SKIPPED, "blocked by robots.txt")
    book.record("https://acme.com/b", CRAWL_ERROR, "Timeout 1000ms exceeded")
    book.record("https://acme.com/c", RESPONSE_REJECTED, "HTTP 500 text/html")
    book.record("https://acme.com/d", NOT_VISITED, "not visited: --max-pages limit reached")
    by_url = {e["url"]: e["outcome"] for e in book.as_list()}
    assert by_url == {
        "https://acme.com/a": ROBOTS_SKIPPED,
        "https://acme.com/b": CRAWL_ERROR,
        "https://acme.com/c": RESPONSE_REJECTED,
        "https://acme.com/d": NOT_VISITED,
    }
