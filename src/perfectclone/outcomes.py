"""Per-page outcome book: one record per candidate page URL, spanning crawl and mirror.

A candidate page can fail at several distinct stages - robots.txt may forbid it, the browser
navigation may time out, the response may not be an HTML page, or the mirror pass may fail to
download it. The old manifest only scattered those endings across `skipped` and `failures`, so
this book keeps exactly one record per URL that says which stage it ended at and why.
"""

# Outcome categories written to manifest.json's "page_outcomes" list.
SAVED = "saved"                    # page was crawled and written to the site folder
ROBOTS_SKIPPED = "robots_skipped"  # robots.txt disallowed the URL
CRAWL_ERROR = "crawl_error"        # navigation raised, including timeouts
RESPONSE_REJECTED = "response_rejected"  # 4xx/5xx status or a non-HTML content type
MIRROR_FAILED = "mirror_failed"    # mirror pass could not download/save the crawled page
NOT_VISITED = "not_visited"        # still queued when the --max-pages limit stopped the crawl


class OutcomeBook:
    """Collects exactly one record per candidate page URL.

    Each record is ``{"url", "outcome", "reason"}``. Repeated observations of the same URL
    merge into one entry: reasons accumulate (keeping their order, no duplicates), and a
    failure category replaces a provisional success while a success never erases a failure.
    """

    def __init__(self):
        self._outcomes = {}
        self._reasons = {}

    def record(self, url, outcome, reason):
        reason = str(reason)
        if url not in self._outcomes:
            self._outcomes[url] = outcome
            self._reasons[url] = [reason]
            return
        if reason not in self._reasons[url]:
            self._reasons[url].append(reason)
        current = self._outcomes[url]
        if current == outcome or outcome == SAVED:
            return
        # A mirror download failure can only be observed after the crawl succeeded, and any
        # failure outranks a provisional "saved" record. Two different failures cannot occur
        # for one URL in the current pipeline; if they ever did, the first (root) cause stays.
        if current == SAVED or outcome == MIRROR_FAILED:
            self._outcomes[url] = outcome

    def outcome_of(self, url):
        return self._outcomes.get(url)

    def urls(self, outcome):
        return [url for url, o in self._outcomes.items() if o == outcome]

    def as_list(self):
        return [
            {"url": url, "outcome": outcome, "reason": "; ".join(self._reasons[url])}
            for url, outcome in self._outcomes.items()
        ]
