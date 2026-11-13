"""
Behavioral tests for the per-page outcome ledger ("逐页结局").

Every search page must end a run with a verifiable fate — ok / recovered /
abandoned / aborted — unfinished searches must stay OUT of completed_keys,
and records already collected must survive and be exported.

Run with the project venv:  .venv/Scripts/python.exe test_page_outcomes.py
Pure unit tests — fake pages, fake browser, no network, no real LinkedIn.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import Config
import linkedin_scraper as L


async def _noop(*a, **kw):
    pass


# ─────────────────────────────────────────────────────────────
#  FAKE BROWSER PAGE
# ─────────────────────────────────────────────────────────────

BLOCK_HTML = "<html><body>Too many requests. Please try again later.</body></html>"
NO_RESULTS_HTML = "<html><body>No results found</body></html>"
RESULTS_HTML = "<html><body>search results</body></html>"
PROFILE_HTML = """<html><body>
<h1 class="text-heading-xlarge">Jane Doe</h1>
<div class="text-body-medium break-words">Recruiter at Example</div>
</body></html>"""


class FakeSearchPage:
    """Scripted stand-in for a Playwright Page.

    ``responder(url, page)`` is invoked on every goto() and decides which
    HTML / links / job cards the page serves, so a test can script blocks,
    recoveries and natural ends per URL.
    """

    def __init__(self, responder=None):
        self.url = "https://www.linkedin.com/feed/"
        self.html = RESULTS_HTML
        self.links = []        # /in/ profile links on the current page
        self.job_cards = []    # job-card dicts on the current page
        self.goto_count = 0
        self.responder = responder

    async def goto(self, url, **kwargs):
        self.goto_count += 1
        self.url = url
        if self.responder:
            self.responder(url, self)

    async def content(self):
        return self.html

    async def evaluate(self, *args, **kwargs):
        pass

    async def eval_on_selector_all(self, selector, script):
        if "job-card" in selector:
            return list(self.job_cards)
        return list(self.links)

    async def wait_for_selector(self, *args, **kwargs):
        return None


def _scraper(cfg=None):
    s = L.LinkedInScraper(cfg or Config())
    return s


def _outcomes(s, status):
    return [o for o in s.page_outcomes if o["status"] == status]


# ─────────────────────────────────────────────────────────────
#  PATH 1 — page fetched normally ("ok")
# ─────────────────────────────────────────────────────────────

def test_page_fetched_normally_records_ok():
    L.human_delay = _noop
    L.random_scroll = _noop
    cfg = Config()
    cfg.MAX_PAGES_PER_COMPANY = 3
    s = _scraper(cfg)

    def respond(url, page):
        if "page=" in url:  # page 2+ → natural end
            page.html = NO_RESULTS_HTML
            page.links = []
        else:
            page.html = RESULTS_HTML
            page.links = ["https://www.linkedin.com/in/alice?trk=x"]

    s.page = FakeSearchPage(respond)
    key = "people::Walmart::Recruiter"
    urls = asyncio.run(s.search_people("Walmart", "Recruiter", search_key=key))

    assert urls == ["https://www.linkedin.com/in/alice"], urls
    assert s.last_search_completed is True
    oks = _outcomes(s, "ok")
    assert len(oks) == 1, s.page_outcomes
    assert oks[0]["key"] == key and oks[0]["page"] == 1
    assert oks[0]["mode"] == "people"
    assert not _outcomes(s, "abandoned") and not _outcomes(s, "aborted")


# ─────────────────────────────────────────────────────────────
#  PATH 2 — blocked, then recovered after rotation ("recovered")
# ─────────────────────────────────────────────────────────────

def test_page_recovered_after_rotation():
    L.human_delay = _noop
    L.random_scroll = _noop
    cfg = Config()
    cfg.MAX_BLOCK_RECOVERIES = 2
    cfg.MAX_PAGES_PER_COMPANY = 2
    s = _scraper(cfg)
    state = {"blocked": True}

    def respond(url, page):
        if state["blocked"]:
            page.html = BLOCK_HTML
            page.links = []
        elif "page=" in url:
            page.html = NO_RESULTS_HTML
            page.links = []
        else:
            page.html = RESULTS_HTML
            page.links = ["https://www.linkedin.com/in/bob"]

    rotations = []

    async def rotate():
        rotations.append(1)
        state["blocked"] = False  # the fresh identity is not blocked
        return True

    s._rotate_identity = rotate
    s.page = FakeSearchPage(respond)
    key = "people::BlockCo::Recruiter"
    urls = asyncio.run(s.search_people("BlockCo", "Recruiter", search_key=key))

    assert urls == ["https://www.linkedin.com/in/bob"], urls
    assert s._block_recoveries == 1 and len(rotations) == 1
    assert s.last_search_completed is True
    recovered = _outcomes(s, "recovered")
    assert len(recovered) == 1, s.page_outcomes
    assert recovered[0]["key"] == key and recovered[0]["page"] == 1
    assert s._last_recovery_failure == ""


# ─────────────────────────────────────────────────────────────
#  PATH 3 — recovery budget exhausted ("abandoned"), jobs mode
# ─────────────────────────────────────────────────────────────

def test_page_abandoned_when_budget_exhausted():
    L.human_delay = _noop
    L.random_scroll = _noop
    cfg = Config()
    cfg.SEARCH_MODE = "jobs"
    cfg.MAX_BLOCK_RECOVERIES = 1
    cfg.MAX_JOB_PAGES = 3
    s = _scraper(cfg)

    def respond(url, page):
        page.html = BLOCK_HTML  # every identity stays blocked
        page.job_cards = []

    rotations = []

    async def rotate():
        rotations.append(1)
        return True  # rotation "works" but the page is still blocked

    s._rotate_identity = rotate
    s.page = FakeSearchPage(respond)
    jobs = asyncio.run(s.search_jobs("python", search_key="jobs::python"))

    assert jobs == []
    assert s.last_search_completed is False
    # Budget = 1: exactly one rotation, never a second one.
    assert s._block_recoveries == 1
    assert len(rotations) == 1, "must not rotate beyond MAX_BLOCK_RECOVERIES"
    assert s._last_recovery_failure == "budget_exhausted"
    abandoned = _outcomes(s, "abandoned")
    assert len(abandoned) == 1, s.page_outcomes
    assert abandoned[0]["key"] == "jobs::python" and abandoned[0]["page"] == 1
    assert abandoned[0]["mode"] == "jobs"


# ─────────────────────────────────────────────────────────────
#  PATH 4 — re-login failed ("aborted"), candidates mode
# ─────────────────────────────────────────────────────────────

def test_page_aborted_when_relogin_fails():
    L.human_delay = _noop
    L.random_scroll = _noop
    cfg = Config()
    cfg.SEARCH_MODE = "candidates"
    cfg.MAX_BLOCK_RECOVERIES = 3  # plenty of budget — failure is the re-login
    cfg.MAX_CANDIDATE_PAGES = 3
    s = _scraper(cfg)

    def respond(url, page):
        page.html = "<html><body>Sign in to LinkedIn to see more</body></html>"
        page.links = []

    rotations = []

    async def rotate():
        rotations.append(1)
        return False  # re-login after rotation failed

    s._rotate_identity = rotate
    s.page = FakeSearchPage(respond)
    urls = asyncio.run(s.search_candidates("Python", search_key="candidates::Python"))

    assert urls == []
    assert s.last_search_completed is False
    assert s._block_recoveries == 1 and len(rotations) == 1
    assert s._last_recovery_failure == "relogin_failed"
    aborted = _outcomes(s, "aborted")
    assert len(aborted) == 1, s.page_outcomes
    assert aborted[0]["key"] == "candidates::Python"
    assert aborted[0]["mode"] == "candidates"


# ─────────────────────────────────────────────────────────────
#  RUN LEVEL — completed_keys vs. export, and resume behavior
# ─────────────────────────────────────────────────────────────

def _run_config(tmp):
    cfg = Config()
    cfg.SEARCH_MODE = "people"
    cfg.JOB_TITLES = ["Recruiter"]
    cfg.MAX_PAGES_PER_COMPANY = 3
    cfg.MAX_BLOCK_RECOVERIES = 0   # any block → budget exhausted immediately
    cfg.ENABLE_DATABASE = False
    cfg.ENABLE_EVENT_LOG = False
    cfg.EXPORT_FORMATS = ["json"]
    cfg.RETRY_FAILED_PROFILES = False
    cfg.WARM_UP_BROWSER = False
    cfg.HUMAN_MOUSE = False
    cfg.ROTATE_USER_AGENT = False
    cfg.USE_PERSISTENT_SESSION = False
    cfg.PROGRESS_FILE = str(Path(tmp) / "progress.json")
    cfg.OUTPUT_FILE = str(Path(tmp) / "results.json")
    cfg.PAGE_OUTCOME_FILE = str(Path(tmp) / "page_outcomes.json")
    cfg.SESSION_HEALTH_FILE = str(Path(tmp) / "session_health.json")
    cfg.LOG_FILE = str(Path(tmp) / "scraper.log")
    return cfg


def test_run_keeps_records_but_not_completed_keys_for_abandoned_pages():
    L.human_delay = _noop
    L.random_scroll = _noop
    L.setup_logging = _noop  # keep a real FileHandler off the tmp dir (Windows lock)
    with tempfile.TemporaryDirectory() as tmp:
        cfg = _run_config(tmp)
        state = {"blockco_blocked": True}
        rotations = []

        def respond(url, page):
            if "/in/" in url:
                page.html = PROFILE_HTML          # a profile page
                page.links = []
            elif "BlockCo" in url and "page=" in url:
                # BlockCo page 2+ is a hard rate-limit wall.
                page.html = BLOCK_HTML if state["blockco_blocked"] else NO_RESULTS_HTML
                page.links = []
            elif "BlockCo" in url:
                page.html = RESULTS_HTML          # BlockCo page 1 works
                page.links = ["https://www.linkedin.com/in/block-1"]
            elif "GoodCo" in url and "page=" in url:
                page.html = NO_RESULTS_HTML       # GoodCo ends naturally
                page.links = []
            else:
                page.html = RESULTS_HTML          # GoodCo page 1
                page.links = ["https://www.linkedin.com/in/good-1"]

        page = FakeSearchPage(respond)

        class FakeScraper(L.LinkedInScraper):
            async def _launch_browser(self):
                self.page = page

            async def login(self):
                return True

            async def _rotate_identity(self):
                rotations.append(1)
                return True

        s = FakeScraper(cfg)
        summary = asyncio.run(s.run(["GoodCo", "BlockCo"]))

        good_key = "people::GoodCo::Recruiter"
        bad_key = "people::BlockCo::Recruiter"

        # ── Records from BOTH searches survived and were exported ──
        assert summary is not None
        assert len(s.results) == 2, "GoodCo + BlockCo page-1 profiles must be kept"
        exported = json.loads((Path(tmp) / "results.json").read_text(encoding="utf-8"))
        exported_records = exported["records"] if isinstance(exported, dict) and "records" in exported else exported
        assert len(exported_records) == 2, "partial results must still be exported"

        # ── completed_keys: only the fully-finished search ──
        progress = json.loads((Path(tmp) / "progress.json").read_text(encoding="utf-8"))
        assert progress["completed_keys"] == [good_key], progress["completed_keys"]
        assert bad_key not in progress["completed_keys"]
        # ...but the partial records are checkpointed in progress.json too.
        assert len(progress["results"]) == 2

        # ── No rotation may happen once the budget (0) is spent ──
        assert rotations == [], "budget exhausted → no further rotation"
        assert s._block_recoveries == 0

        # ── The per-page outcome report tells the whole story ──
        report = json.loads((Path(tmp) / "page_outcomes.json").read_text(encoding="utf-8"))
        by_key = {}
        for entry in report["pages"]:
            by_key.setdefault(entry["key"], []).append(entry["status"])
        assert by_key[good_key] == ["ok"], by_key
        assert by_key[bad_key] == ["ok", "abandoned"], by_key
        assert report["summary"]["ok"] == 2
        assert report["summary"]["abandoned"] == 1
        assert report["incomplete_searches"] == [bad_key]
        assert summary["incomplete_searches"] == [bad_key]
        assert summary["page_outcomes"]["abandoned"] == 1

        # ── Resume: GoodCo is skipped, BlockCo is retried and completes ──
        state["blockco_blocked"] = False
        s2 = FakeScraper(cfg)
        summary2 = asyncio.run(s2.run(["GoodCo", "BlockCo"]))
        progress2 = json.loads((Path(tmp) / "progress.json").read_text(encoding="utf-8"))
        assert set(progress2["completed_keys"]) == {good_key, bad_key}, progress2["completed_keys"]
        # block-1 was already scraped in run 1 → deduped, not scraped twice.
        assert len(progress2["results"]) == 2, progress2["results"]
        report2 = json.loads((Path(tmp) / "page_outcomes.json").read_text(encoding="utf-8"))
        assert report2["summary"]["abandoned"] == 0
        assert report2["incomplete_searches"] == []
        assert summary2["page_outcomes"]["ok"] >= 1


if __name__ == "__main__":
    tests = [
        test_page_fetched_normally_records_ok,
        test_page_recovered_after_rotation,
        test_page_abandoned_when_budget_exhausted,
        test_page_aborted_when_relogin_fails,
        test_run_keeps_records_but_not_completed_keys_for_abandoned_pages,
    ]
    failed = 0
    for fn in tests:
        try:
            fn()
        except Exception as exc:
            failed += 1
            import traceback
            print(f"FAIL {fn.__name__}: {exc.__class__.__name__}: {exc}")
            traceback.print_exc()
        else:
            print(f"PASS {fn.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} page-outcome tests passed.")
    sys.exit(1 if failed else 0)
