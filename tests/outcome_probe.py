"""Drive `scrape()` end-to-end for each engine's per-symbol outcome sidecar.

Run by smoke_test.py in a subprocess (the stubs replace the driver modules in
`sys.modules`, which must not leak into the suite's own real-engine checks).
Needs no engine library installed, no network, no proxy and no 2captcha key:
the browser is a fake page that serves `fixtures_generated.json` html.

What is REAL here, and that is the point: `parse_args` (so `--symbols`
deduping and the symbol->url mapping are the shipped code), `_fetch_one_page`
(so the real classifier, retry policy and rotation decision run), and the
whole of `scrape` — the page loop, the arrival-order-independent merge, the
sidecar and `finish_run`'s status/exit-code mapping. Only the driver is fake.

Prints one JSON object. For each scenario it reports the exit code, the row
file's exact bytes and the sidecar's per-symbol records, so the suite can
assert what a live run could not show it offline:

  * every requested symbol has exactly one outcome, in request order;
  * `ok + not_found + failed == requested`;
  * a `not_found` symbol leaves the run `complete` with exit 0, spends no
    retry and rotates no exit, while a FAILED symbol makes it `partial`;
  * `--concurrency 2`, with the workers deliberately completing in REVERSE
    request order, produces the same row bytes and the same outcome order as
    `--concurrency 1`.
"""
import contextlib
import io
import json
import logging
import os
import sys
import tempfile
import threading
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

logging.disable(logging.CRITICAL)
_results_out = sys.stdout           # captured BEFORE the redirect below, so
sys.stdout = io.StringIO()          # the probe can still print its own JSON
sys.stderr = io.StringIO()


def mod(name, **kw):
    m = types.ModuleType(name)
    m.__dict__.update(kw)
    sys.modules[name] = m
    return m


class PWError(Exception):
    pass


class PWTimeout(PWError):
    pass


mod("playwright")
mod("playwright.sync_api", sync_playwright=lambda: None, Error=PWError,
    TimeoutError=PWTimeout)

import product_parser as pp          # noqa: E402
import playwright_scraper as pw      # noqa: E402

with io.open(os.path.join(REPO, "fixtures_generated.json"), encoding="utf-8") as f:
    FX = json.load(f)["fixtures"]

WORK = tempfile.mkdtemp(prefix="gf-outcome-")

# symbol (upper) -> (fixture name, http status) or None-ish for the special
# cases below. `not_found` is the REAL capture, so the classifier decides it
# rather than this script declaring what it should be.
SERVED = {
    "GOOGL:NASDAQ": ("quote_stock_us", 200),
    "BMW:ETR": ("quote_stock_de", 200),
    "ZZZZQQ:NASDAQ": ("not_found", 200),
    "QQQQQQ:NASDAQ": ("not_found", 200),
}
# A page the classifier reads as `blocked`: HTTP 403 with a body that is
# neither Google's non-browser redirect, its regional refusal nor a Page Not
# Found — `detect_page_state` settles it on the status.
BLOCKED_SYMBOL = "BANNED:NASDAQ"
BLOCKED_HTML = "<html><body>refused</body></html>"
# A symbol whose navigation never completes.
FAIL_SYMBOL = "TIMEOUT:NASDAQ"


class _Resp:
    def __init__(self, status):
        self.status = status


class FakePage:
    """One browser page per session/worker; serves by URL."""

    def __init__(self, nav_log, lock):
        self.url = "about:blank"
        self._nav_log = nav_log
        self._lock = lock

    def goto(self, url, wait_until=None, timeout=None):
        with self._lock:
            self._nav_log.append(url)
        symbol = (pp.symbol_from_url(url) or "").upper()
        if symbol == FAIL_SYMBOL:
            raise PWTimeout("Navigation Timeout Exceeded: 60000 ms exceeded")
        self.url = url
        if symbol == BLOCKED_SYMBOL:
            return _Resp(403)
        fixture, status = SERVED.get(symbol, ("not_found", 200))
        return _Resp(status)

    def content(self):
        symbol = (pp.symbol_from_url(self.url) or "").upper()
        if symbol == BLOCKED_SYMBOL:
            return BLOCKED_HTML
        fixture, _status = SERVED.get(symbol, ("not_found", 200))
        return FX[fixture]["html"]

    def query_selector_all(self, selector):
        return []

    def wait_for_timeout(self, ms):
        return None

    def screenshot(self, **kw):
        return None

    def reload(self, **kw):
        return None


class FakeSession:
    """Stands in for `_BrowserSession`; one page per session."""

    def __init__(self, args, nav_log, lock, **kw):
        self.args = args
        self.pool = None
        self.page = FakePage(nav_log, lock)

    def open(self):
        return self

    def close(self):
        return None

    def relaunch(self):
        self.page = FakePage(self.page._nav_log, self.page._lock)
        return self


class CountingPool:
    """A pool whose `advance` is recorded, so a rotation can be PROVEN absent."""

    def __init__(self, exits=3):
        self.proxies = ["http://exit%d.example:8080" % i for i in range(exits)]
        self.current = self.proxies[0]
        self.advances = 0
        self._rotate = "per-run"

    def __len__(self):
        return len(self.proxies)

    def __getitem__(self, i):
        return self.proxies[i]

    def advance(self, why=""):
        self.advances += 1
        self.current = self.proxies[self.advances % len(self.proxies)]

    def rotates_per_page(self):
        return False


class FakePW:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


# ---------------------------------------------------------------------------
# Scenario driver
# ---------------------------------------------------------------------------
def run(argv, pool=None, reverse_delay=False):
    """Run `scrape(parse_args(argv))` against the fake browser.

    `reverse_delay` makes the LAST-requested symbol finish FIRST, so the
    worker result list arrives in reverse request order — the exact arrival
    order a sidecar must not inherit.
    """
    out = os.path.join(WORK, "run-%d" % run.counter)
    run.counter += 1
    os.environ.pop("GOOGLE_FINANCE_URL", None)

    nav_log, lock = [], threading.Lock()
    completions = []

    real_fetch = pw._fetch_one_page

    def fetch(session, args, pool_, page_num, url):
        if reverse_delay:
            import time as _t
            # Later symbols wait less: worker completion order is then the
            # reverse of request order.
            _t.sleep(0.04 * (args.pages - page_num))
        oc = real_fetch(session, args, pool_, page_num, url)
        # `scraped_at` is the wall clock at row construction, and it differs
        # between ANY two runs — sequential or not. Pinning it is what lets
        # the two runs be compared byte-for-byte on everything else; every
        # other column must be identical.
        for r in getattr(oc, "products", ()) or ():
            r.scraped_at = "2026-01-01T00:00:00+00:00"
        with lock:
            completions.append(oc.page_num)
        return oc

    saved = {n: getattr(pw, n) for n in
             ("_fetch_one_page", "_BrowserSession", "sync_playwright",
              "handle_captcha_if_present", "proxy_pool_from_args")}
    pw._fetch_one_page = fetch
    pw._BrowserSession = lambda *a, **k: FakeSession(args=None, nav_log=nav_log,
                                                     lock=lock)
    pw.sync_playwright = lambda: FakePW()
    pw.handle_captcha_if_present = lambda *a, **k: False
    if pool is not None:
        pw.proxy_pool_from_args = lambda a: pool
    try:
        sys.argv = ["playwright_scraper.py"] + list(argv) + ["--out", out]
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            args = pw.parse_args()
            rc = pw.scrape(args)
    finally:
        for n, v in saved.items():
            setattr(pw, n, v)
        os.environ.pop("GOOGLE_FINANCE_URL", None)

    blob = None
    if os.path.exists(out + ".json"):
        with io.open(out + ".json", encoding="utf-8") as f:
            blob = f.read()
    meta = None
    if os.path.exists(out + ".meta.json"):
        with io.open(out + ".meta.json", encoding="utf-8") as f:
            meta = json.load(f)
    return {
        "argv": list(argv),
        "exit": rc,
        "rows": blob,
        "status": None if meta is None else meta.get("status"),
        "stop_reason": None if meta is None else meta.get("stop_reason"),
        "products": None if meta is None else meta.get("products"),
        "pages_failed": None if meta is None else meta.get("pages_failed"),
        "requested": None if meta is None else meta.get("symbols_requested"),
        "ok": None if meta is None else meta.get("symbols_ok"),
        "not_found": None if meta is None else meta.get("symbols_not_found"),
        "failed": None if meta is None else meta.get("symbols_failed"),
        "outcomes": None if meta is None else meta.get("symbol_outcomes"),
        "navigations": len(nav_log),
        "completions": completions,
        "rotations": 0 if pool is None else pool.advances,
    }


run.counter = 0

RESULTS = {}

# 1. All symbols have rows.
RESULTS["all_ok"] = run(["--mode", "quote", "--symbols", "GOOGL:NASDAQ,BMW:ETR",
                         "--delay", "0", "--retries", "1"])

# 2. One misspelt symbol among good ones: complete, exit 0. Driven WITH a
#    pool, so the check also proves `not_found` rotates no exit and spends no
#    re-fetch.
RESULTS["one_not_found"] = run(
    ["--mode", "quote", "--symbols", "GOOGL:NASDAQ,ZZZZQQ:NASDAQ,BMW:ETR",
     "--delay", "0", "--retries", "1"], pool=CountingPool())

# 3. Every symbol misspelt, no --allow-empty: nothing written, exit 4.
RESULTS["all_not_found"] = run(
    ["--mode", "quote", "--symbols", "ZZZZQQ:NASDAQ,QQQQQQ:NASDAQ",
     "--delay", "0", "--retries", "1"])

# 4. The same with --allow-empty: a file and a sidecar, still exit 4.
RESULTS["all_not_found_allow_empty"] = run(
    ["--mode", "quote", "--symbols", "ZZZZQQ:NASDAQ,QQQQQQ:NASDAQ",
     "--delay", "0", "--retries", "1", "--allow-empty"])

# 5. A symbol that is blocked, then one whose load times out: partial.
RESULTS["one_failed"] = run(
    ["--mode", "quote", "--symbols", "GOOGL:NASDAQ,BANNED:NASDAQ,BMW:ETR",
     "--delay", "0", "--retries", "1"])
RESULTS["load_timeout"] = run(
    ["--mode", "quote", "--symbols", "GOOGL:NASDAQ,TIMEOUT:NASDAQ,BMW:ETR",
     "--delay", "0", "--retries", "1"])

# 6. The same symbol list (with a DUPLICATE) sequentially and through 2
#    workers that finish in reverse request order.
SEQ = ["GOOGL:NASDAQ", "ZZZZQQ:NASDAQ", "BMW:ETR", "BMW:etr", "QQQQQQ:NASDAQ"]
RESULTS["seq"] = run(["--mode", "quote", "--symbols", ",".join(SEQ),
                      "--delay", "0", "--retries", "1"])
RESULTS["par"] = run(["--mode", "quote", "--symbols", ",".join(SEQ),
                      "--delay", "0", "--retries", "1", "--concurrency", "2"],
                     reverse_delay=True)

_results_out.write(json.dumps(RESULTS) + "\n")
