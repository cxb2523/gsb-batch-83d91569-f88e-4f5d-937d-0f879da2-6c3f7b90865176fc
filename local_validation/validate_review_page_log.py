#!/usr/bin/env python3
"""
validate_review_page_log.py
---------------------------
Self-contained validation for the reviews-mode per-page log using LOCALLY
MADE-UP responses. Nothing here talks to a network or reads a capture: the
driver is a scripted fake, every review id and every wire byte is synthetic,
so passing this proves the bookkeeping only — it is NOT evidence that the
real Google Play site behaves this way.

Two scenarios are required by the task this validates:

  A. a two-page continuation-token chain whose second page repeats page 1's
     review_id -> the sidecar's second page must report new_review_ids == 0
     and the run must stop for token exhaustion;
  B. a first batchexecute page answered with HTTP 403 -> exit 5 and no output
     file at all.

A few extra scenarios pin the neighbouring contracts:
  C. a 403 on page 2 AFTER page 1 delivered rows -> exit 6, rows kept, and the
     refused page's basis is the HTTP status;
  D. a refusal with NO status exposed (the Selenium shape) -> refusal_basis is
     "unknown" on an otherwise unreadable body, never a fabricated number;
  E. a transport exception on page 1 -> exit 5, no output, transport_failed;
  F. a healthy two-page chain stopped by --pages -> page 2 keeps
     has_next_token true and stop_reason pages_limit.

Run from anywhere:  python -I validate_review_page_log.py
"""

import json
import os
import sys
import tempfile

# `python -I` puts neither cwd nor the script's directory on sys.path, so the
# repo under test is located explicitly rather than relying on cwd.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
sys.path.insert(0, _REPO)

import engine_core  # noqa: E402


# --------------------------------------------------------------------------
# Synthetic batchexecute wire responses
# --------------------------------------------------------------------------

def _review_record(review_id: str, score: int = 5) -> list:
    """A minimal record with every slot product_parser.parse_review_record
    reads, shaped like Play's own (uuid in slot 0, int score in slot 2)."""
    record = [None] * 12
    record[0] = review_id
    record[1] = ["Mock Reviewer",
                 [None, 2, None,
                  [None, None, "https://play-lh.example.invalid/avatar.png"]]]
    record[2] = score
    record[4] = "synthetic fixture text"
    record[5] = [1_700_000_000, 0]
    record[6] = 0
    record[9] = ["999000111222333", "Mock Reviewer"]
    record[10] = "1.2.3"
    return record


def batchexecute_body(review_ids, token):
    """Wrap review records in the real `)]}'` + wrb.fr envelope shape."""
    records = [_review_record(rid) for rid in review_ids]
    payload = [records, [token] if token else []]
    envelope = [["wrb.fr", "UsvDTd",
                 json.dumps(payload, separators=(",", ":"))]]
    return ")]}'\n" + json.dumps(envelope, separators=(",", ":"))


def app_page_html(review_ids):
    """A synthetic Play app page carrying an AF_initDataCallback reviews
    block, which is the structural signal classify() expects for a reviews
    preflight. The embedded reviews only prove the app exists in this market
    — run_reviews deliberately never uses them as page 1."""
    block = [[_review_record(rid) for rid in review_ids]]
    return (
        "<html><head><title>com.example.mock - Apps on Google Play</title>"
        "</head><body>"
        "<a href=\"https://play.google.com/store/apps/details?id=com.example.mock"
        "&hl=en&gl=US\">com.example.mock</a>"
        "<img src=\"https://play-lh.googleusercontent.com/mock\">"
        "<script>AF_initDataCallback({key: 'ds:5', data: "
        + json.dumps(block)
        + ", sideChannel: {}});</script></body></html>"
    )


APP_ID = "com.example.mock"
TOKEN_1 = "t" * 40          # long enough to pass reviews_from_payload (>20)
ID_A = "aaaaaaaa-0000-1111-2222-333333333333"
ID_B = "bbbbbbbb-0000-1111-2222-333333333333"
ID_C = "cccccccc-0000-1111-2222-333333333333"

# A small app page: classify() must read it as served content for a reviews
# preflight because it carries a recognisable reviews block.
APP_PAGE = app_page_html([ID_A, ID_B])


class ScriptedDriver:
    """Answers fetch()/post_form() from queues; records nothing external."""

    def __init__(self, pages, posts):
        self._pages = list(pages)
        self._posts = list(posts)
        self._url = ""

    def fetch(self, url, mode):
        self._url = url
        step = self._pages.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def read(self, mode):
        return self._pages[0][0] if self._pages else ""

    def evaluate(self, js, arg=None):
        return None

    def post_form(self, url, form):
        step = self._posts.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def current_url(self):
        return self._url

    def close(self):
        pass


def run(pages, posts, pages_requested=3):
    """One engine_core.main() run into a fresh temp output prefix."""
    tmp = tempfile.mkdtemp(prefix="reviewlog_")
    prefix = os.path.join(tmp, "run")

    def launch(args, proxy_url):
        return ScriptedDriver(pages, posts)

    argv = ["--mode", "reviews", "--app-id", APP_ID,
            "--pages", str(pages_requested), "--reviews-per-call", "10",
            "--delay", "0", "--out", prefix, "--format", "both"]
    rc = engine_core.main(launch, argv)
    files = {}
    for ext in (".json", ".csv", ".meta.json"):
        path = prefix + ext
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                files[ext] = fh.read()
    meta = json.loads(files[".meta.json"]) if ".meta.json" in files else None
    rows = json.loads(files[".json"]) if ".json" in files else None
    return rc, sorted(os.listdir(tmp)), meta, rows


FAILURES = []


def check(label, condition, detail=""):
    mark = "ok  " if condition else "FAIL"
    print(f"[{mark}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(label)


def main() -> int:
    # -- A: two-page chain, page 2 repeats page 1's id ---------------------
    page1 = (batchexecute_body([ID_A], TOKEN_1), 200)
    page2_duplicate = (batchexecute_body([ID_A], TOKEN_1), 200)
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [page1, page2_duplicate], pages_requested=3)
    logs = meta["review_pages"]
    print("scenario A logs:", json.dumps(logs, indent=2))
    check("A: exit 0 (a repeated page is the catalogue's end, not a failure)",
          rc == 0, f"rc={rc}")
    check("A: two batchexecute pages were logged", len(logs) == 2, str(len(logs)))
    check("A: page 1 gl/hl recorded per page",
          logs[0]["gl"] == "US" and logs[0]["hl"] == "en", str(logs[0]))
    check("A: page 1 returned 1 record and added 1 new id",
          logs[0]["records_returned"] == 1 and logs[0]["new_review_ids"] == 1)
    check("A: page 1 saw a next token", logs[0]["has_next_token"] is True)
    check("A: page 2 returned 1 record but added ZERO new ids",
          logs[1]["records_returned"] == 1 and logs[1]["new_review_ids"] == 0,
          str(logs[1]))
    check("A: page 2 stop_reason is token_exhausted",
          logs[1]["stop_reason"] == "token_exhausted", str(logs[1].get("stop_reason")))
    check("A: only the final page carries a stop_reason",
          logs[0]["stop_reason"] is None and logs[1]["stop_reason"] is not None)
    check("A: run-level stop_reason stays end_of_listing",
          meta["stop_reason"] == "end_of_listing", meta["stop_reason"])
    check("A: one unique review row written", rows is not None and len(rows) == 1)
    check("A: the per-page log lives in the sidecar, not the review row",
          all("review_pages" not in row for row in rows))

    # -- B: first page 403, zero reviews -> exit 5, no files ---------------
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [("<html>forbidden</html>", 403)], pages_requested=2)
    print("scenario B files:", written)
    check("B: a first-page 403 with no rows is exit 5", rc == 5, f"rc={rc}")
    check("B: no output file is written on exit 5", written == [], str(written))
    check("B: no sidecar contradicts an earlier good run", meta is None)

    # -- C: page 2 403 after page 1 rows -> exit 6, rows kept --------------
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)],
        [page1, ("<html>rate limited</html>", 429)], pages_requested=3)
    logs = meta["review_pages"]
    print("scenario C logs:", json.dumps(logs, indent=2))
    check("C: a refusal after gathered rows is exit 6", rc == 6, f"rc={rc}")
    check("C: page 1's rows are kept", rows is not None and len(rows) == 1)
    check("C: output + sidecar are both written",
          any(f.endswith(".json") and not f.endswith(".meta.json") for f in written)
          and any(f.endswith(".meta.json") for f in written), str(written))
    check("C: the failed page is numbered 2 in the sidecar",
          meta["pages_failed"] == [2], str(meta["pages_failed"]))
    check("C: page 2 is marked refused on an HTTP status",
          logs[1]["outcome"] == "refused"
          and logs[1]["refusal_basis"] == "http_status"
          and logs[1]["http_status"] == 429, str(logs[1]))
    check("C: page 2 stop_reason is refused",
          logs[1]["stop_reason"] == "refused", str(logs[1].get("stop_reason")))
    check("C: page 1 log remains a healthy ok page",
          logs[0]["outcome"] == "ok" and logs[0]["refusal_basis"] is None)

    # -- D: refusal shape with NO status exposed (Selenium) ----------------
    # A challenge-marker body and post_status None: the structural marker is
    # the basis, and http_status must stay null rather than invent a number.
    # With the refusal on page 1 there are no rows, so no sidecar exists to
    # inspect — the basis itself is therefore observed on a page-2 refusal
    # after a healthy page 1, where the sidecar IS written.
    challenge_body = ('<html><body><div class="g-recaptcha" '
                      'data-sitekey="6Lx"></div>Our systems have detected '
                      'unusual traffic.</body></html>')
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [(challenge_body, None)], pages_requested=2)
    check("D: a marker-only refusal with no status is exit 5", rc == 5, f"rc={rc}")
    check("D: nothing was written", written == [], str(written))
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [page1, (challenge_body, None)], pages_requested=3)
    logs = meta["review_pages"]
    print("scenario D logs:", json.dumps(logs, indent=2))
    check("D: marker body with no status -> basis 'structure', status null",
          logs[1]["outcome"] == "refused"
          and logs[1]["refusal_basis"] == "structure"
          and logs[1]["http_status"] is None, str(logs[1]))
    # And a genuinely unreadable body (no marker either), still no status:
    # the honest basis is "unknown", never a guessed status code.
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [page1, ("", None)], pages_requested=3)
    logs = meta["review_pages"]
    print("scenario D (blank body) logs:", json.dumps(logs, indent=2))
    check("D: blank unreadable body with no status -> basis 'unknown'",
          logs[1]["outcome"] == "refused"
          and logs[1]["refusal_basis"] == "unknown"
          and logs[1]["http_status"] is None, str(logs[1]))

    # -- E: transport failure on page 1 -> exit 5, no files ----------------
    # No sidecar is written on the zero-row case, so the transport_failed
    # log itself is observed on the equivalent page-2 failure below.
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [TimeoutError("connection reset")], pages_requested=2)
    print("scenario E files:", written)
    check("E: a page-1 transport failure is exit 5", rc == 5, f"rc={rc}")
    check("E: no output file is written", written == [], str(written))
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)],
        [page1, TimeoutError("connection reset")], pages_requested=3)
    logs = meta["review_pages"]
    print("scenario E logs:", json.dumps(logs, indent=2))
    check("E: a later transport failure is exit 6", rc == 6, f"rc={rc}")
    check("E: page 2 outcome is transport_failed and so is its stop_reason",
          logs[1]["outcome"] == "transport_failed"
          and logs[1]["stop_reason"] == "transport_failed", str(logs[1]))
    check("E: no HTTP status is fabricated for a transport failure",
          logs[1]["http_status"] is None)

    # -- F: healthy chain stopped by the --pages budget --------------------
    page2_healthy = (batchexecute_body([ID_B, ID_C], TOKEN_1), 200)
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [page1, page2_healthy], pages_requested=2)
    logs = meta["review_pages"]
    print("scenario F logs:", json.dumps(logs, indent=2))
    check("F: a budget stop completes with exit 0", rc == 0, f"rc={rc}")
    check("F: both pages are ok",
          all(entry["outcome"] == "ok" for entry in logs))
    check("F: page 2 kept 2 returned / 2 new",
          logs[1]["records_returned"] == 2 and logs[1]["new_review_ids"] == 2)
    check("F: page 2 still held a next token", logs[1]["has_next_token"] is True)
    check("F: stop_reason is pages_limit, not token exhaustion",
          logs[1]["stop_reason"] == "pages_limit", str(logs[1].get("stop_reason")))
    check("F: three unique rows across the two pages",
          rows is not None and len(rows) == 3)

    # -- G: final page answers without a continuation token ----------------
    last_page = (batchexecute_body([ID_B], None), 200)
    rc, written, meta, rows = run(
        [(APP_PAGE, 200)], [page1, last_page], pages_requested=3)
    logs = meta["review_pages"]
    check("G: a page with no next token reports has_next_token false",
          logs[1]["has_next_token"] is False)
    check("G: and stops for token_exhausted",
          logs[1]["stop_reason"] == "token_exhausted", str(logs[1].get("stop_reason")))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED:")
        for item in FAILURES:
            print("  -", item)
        return 1
    print("all synthetic-scenario checks passed")
    print("(mock responses only — no request reached the real Google Play site)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
