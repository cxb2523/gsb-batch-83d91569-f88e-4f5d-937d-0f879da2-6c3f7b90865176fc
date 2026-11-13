import json
import os
import random
import re
import time
from datetime import datetime, timezone

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

from page_verdict import (
    BLOCKED,
    CHALLENGED,
    FAILED,
    NOT_PUBLIC,
    OK,
    OXYLABS_NETWORK,
    classify_page,
)

USERNAME = os.environ["OXY_AB_USERNAME"]
PASSWORD = os.environ["OXY_AB_PASSWORD"]
ENDPOINT = "hb.oxylabs.io"

# Connection parameters (parameters.md). Most jobs need only p_cc plus an explicit page_handler=false: every session
# already gets a fresh browser configuration (default engine, Windows profile family oxyfp_win) and a fresh residential IP.
PARAMS = {"p_cc": "US", "page_handler": "false"}
# Block or verification page instead of the expected content? Reconnect with this; the page handler then
# identifies every page and reports its state (challenges.md):
CHALLENGE_ESCALATION = {"page_handler": "true"}
# Escalation when a fresh identity with the right geo is still blocked (targets.md, section 4, rung 4):
# the new browser engine with its macOS profile family. Desktop only; keep the pair for every later connection.
ENGINE_ESCALATION = {"p_src": "oxybrowser", "p_fp_tag": "oxyfp_mac_optimized"}

# Identity-retry policy when the target blocks a visitor (challenges.md section 3): close the session,
# back off 10 s doubling, reconnect as a fresh identity with page_handler=true, at most 2 more tries.
BLOCKED_BACKOFF_SECONDS = (10, 20)
MAX_BLOCKED_RETRIES = 2
# Network errors (X-Error-Description / connection and navigation failures) are transient: bounded retries
# with the same backoff shape. The policy in SKILL.md section 2 (connect) already backs off inside connect.
MAX_NETWORK_RETRIES = 3
# How much of the rendered body is kept for classification and in the record (the full HTML is not stored).
BODY_EXCERPT_CHARS = 4096

# Error messages contain the connection URL, i.e. the password. Redact before logging anything.
redact = lambda text: str(text).replace(PASSWORD, "***")  # noqa: E731

# Retry only what the service can recover from. 400/401/403 mean the request is wrong: fix, don't retry.
RETRYABLE = re.compile(
    r"\b(429|50[0234]) [A-Z]|response: (429|50[0234])\b|CDP_SESSION_IN_USE|CDP_NO_BROWSERS_AVAILABLE|"
    r"CDP_BROWSER_OVERWORKED|CDP_BAD_PROXY|CDP_GENERAL_ERROR|[Tt]imeout|ECONNRESET")


def utc_now_iso():
    """Test seam: timestamps go through one function so offline samples stay deterministic."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def endpoint_url(params=None):
    # Concatenate with the raw password; do not urlencode or parse the full URL.
    q = "&".join(f"{k}={v}" for k, v in (params or {}).items())
    return f"wss://{USERNAME}:{PASSWORD}@{ENDPOINT}" + (f"?{q}" if q else "")


def connect_with_backoff(pw, params, attempts=6, base=1.0, cap=60.0):
    """Exponential backoff, 1s base, 60s cap, full jitter. Never retries 400/401/403."""
    last = None
    for attempt in range(attempts):
        try:
            return pw.chromium.connect_over_cdp(endpoint_url(params), timeout=60_000)
        except Exception as err:  # noqa: BLE001
            last = err
            if not RETRYABLE.search(str(err)):
                raise
            print(f"connect attempt {attempt + 1} failed: {redact(err).splitlines()[0]}")
            time.sleep(min(cap, base * 2 ** attempt) * (0.5 + random.random()))
    raise last


def block_heavy_resources(page):
    page.route("**/*", lambda route: route.abort()
               if route.request.resource_type in {"image", "stylesheet", "media", "font"}
               else route.continue_())


def watch_oxylabs_errors(page, on_infra_error):
    def handler(resp):
        desc = resp.headers.get("x-error-description")
        if desc:
            on_infra_error({"status": resp.status, "url": resp.url, "description": desc})
    page.on("response", handler)


# With page_handler=true the browser reports each page's state as a window message
# { source: "oxylabs-runtime", type: "oxylabs-page-status", status, error? }, status one of identifying |
# closed (challenge being handled) | open (page usable) | failed (with error); the last message wins
# (challenges.md). The same status is also a console line, but the remote browser does not deliver console
# output live to CDP clients, so an init script keeps the latest status on every document instead.
PAGE_STATUS_INIT_SCRIPT = """
window.addEventListener("message", (e) => {
  const d = e.data;
  if (d?.source !== "oxylabs-runtime" || d.type !== "oxylabs-page-status") return;
  const prev = window.__oxyPageStatus;
  window.__oxyPageStatus = {
    status: d.status,
    error: d.error,
    sawClosed: d.status === "closed" || prev?.sawClosed === true, // latched: a closed was ever seen
    challenged: d.status === "closed" || (d.status !== "identifying" && prev?.challenged === true), // a `closed` since the last `identifying`
  };
});
"""
TERMINAL_PAGE_STATUS = """() => {
  const s = window.__oxyPageStatus;
  return s && s.status !== "identifying" && s.status !== "closed" ? s : null;
}"""


def watch_page_status(context):
    context.add_init_script(PAGE_STATUS_INIT_SCRIPT)


def wait_for_page_status(page, timeout=90.0):
    """Wait for the page to be open (about 8 s after load without a challenge; a widget challenge usually 30 to 45 s);
    raises on failed. identifying and closed are transient. Playwright re-runs the predicate after a navigation,
    so a challenge page that turns into the real page is followed."""
    try:
        handle = page.wait_for_function(TERMINAL_PAGE_STATUS, timeout=timeout * 1000, polling=500)
    except PlaywrightTimeout:
        raise RuntimeError("CHALLENGE_HANDLING_TIMEOUT") from None
    s = handle.json_value()
    if s["status"] == "failed":
        raise RuntimeError(f"CHALLENGE_HANDLING_ERROR: {s.get('error')}")  # challenges.md section 3: fresh identity, max 2 retries
    return s  # {"status": "open", "challenged": True | False}


def observe_page_status(page, timeout=90.0):
    """Non-throwing variant for the verdict layer: returns the terminal state as plain data so a failed
    challenge or a 90 s timeout can be classified instead of aborting the run.

    Returns {"status": open|failed, "error": str|None, "challenged": bool} or, on timeout,
    {"status": None, "error": "CHALLENGE_HANDLING_TIMEOUT", "challenged": False}.
    """
    try:
        state = wait_for_page_status(page, timeout=timeout)
    except RuntimeError as err:
        message = str(err)
        if message.startswith("CHALLENGE_HANDLING_ERROR:"):
            return {"status": FAILED, "error": message.split(": ", 1)[1],
                    "challenged": True, "saw_closed": True}
        return {"status": None, "error": message, "challenged": False, "saw_closed": False}
    return {
        "status": state.get("status"),
        "error": state.get("error"),
        "challenged": bool(state.get("challenged")),
        "saw_closed": bool(state.get("sawClosed")),
    }


def clear_page_status(page):
    """Before a manual trigger (challenges.md section 4): forget the stored status, so the earlier open cannot
    satisfy the next wait while the handle request is still queued."""
    page.evaluate("() => { window.__oxyPageStatus = null; }")


def get_session_id(context, page):
    """Fetch the session id with the CDP command __session_id (SKILL.md section 7). Tolerates both the
    raw-CDP shape {"value": id} and Playwright's unwrapped shape. Never raises: the record still gets built."""
    try:
        cdp = context.new_cdp_session(page)
        result = cdp.send("__session_id")
        return result.get("value") if isinstance(result, dict) else result
    except Exception as err:  # noqa: BLE001
        print(f"could not fetch session id: {redact(err).splitlines()[0]}")
        return None


def run_attempt(pw, target_url, params):
    """One connection to one target. Always returns an attempt record (never raises for page-level outcomes):
    connection/navigation failures come back as verdict oxylabs-network so the orchestrator can retry them."""
    started_at = utc_now_iso()
    attempt = {
        "started_at": started_at,
        "ended_at": None,
        "page_handler": params.get("page_handler") == "true",
        "params": dict(params),
        "session_id": None,
        "final_url": None,
        "http_status": None,
        "terminal_status": None,
        "page_error": None,
        "saw_challenge": False,
        "verdict": None,
        "error": None,
    }
    browser = None
    try:
        browser = connect_with_backoff(pw, params)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        watch_page_status(context)  # before the page exists, so a page-load challenge is captured
        page = context.new_page()
        page.set_default_timeout(30_000)
        block_heavy_resources(page)

        infra_errors = []
        watch_oxylabs_errors(page, lambda e: infra_errors.append(e))

        try:
            response = page.goto(target_url, wait_until="domcontentloaded")
        except Exception as err:  # noqa: BLE001  # navigation never produced a document
            attempt["error"] = redact(err).splitlines()[0]
            attempt["verdict"] = OXYLABS_NETWORK
            attempt["ended_at"] = utc_now_iso()
            return attempt

        page.wait_for_timeout(2000 + random.random() * 3000)  # let late JS settle

        if params.get("page_handler") == "true":
            state = observe_page_status(page)  # the status only exists with page_handler=true
        else:
            state = None  # plain attempt: no state messages, judge by status code and body only

        attempt["session_id"] = get_session_id(context, page)
        attempt["final_url"] = page.url
        attempt["http_status"] = response.status if response else None
        attempt["terminal_status"] = state["status"] if state else None
        attempt["page_error"] = state["error"] if state else None
        attempt["saw_challenge"] = bool(state and state.get("saw_closed"))

        body = page.content()
        headers = response.headers if response else {}
        # An X-Error-Description on any page response (subresource included) is the same upstream signal.
        if infra_errors and not any(k.lower() == "x-error-description" for k in headers):
            headers = dict(headers)
            headers["X-Error-Description"] = infra_errors[0]["description"]

        attempt["verdict"] = classify_page(
            headers, page.url, attempt["http_status"], body[:BODY_EXCERPT_CHARS], state)
        attempt["ended_at"] = utc_now_iso()
        return attempt
    except Exception as err:  # noqa: BLE001  # connect failure or anything session-level: treat as network
        attempt["error"] = redact(err).splitlines()[0]
        attempt["verdict"] = OXYLABS_NETWORK
        attempt["ended_at"] = utc_now_iso()
        return attempt
    finally:
        if browser is not None:
            browser.close()  # always: an unclosed session keeps its concurrency slot


def fresh_identity_params(params, identity_index):
    """Parameters for a blocked-retry connection. A new session already means a new IP and browser
    configuration; if the identity was pinned (sticky id / stored profile), rotate those names too
    (targets.md section 4, rung 2). page_handler stays true."""
    next_params = dict(params)
    next_params["page_handler"] = "true"
    if next_params.get("proxy_resi_ses_id"):
        next_params["proxy_resi_ses_id"] = f"{next_params['proxy_resi_ses_id']}-{identity_index}"
    if next_params.get("o_profile"):
        next_params["o_profile"] = f"{next_params['o_profile']}-{identity_index}"
    return next_params


def build_result(target_url, attempts, stopped_reason):
    last = attempts[-1]
    # Whether the target ever put a challenge in the way: a handled one (closed -> open), or one the
    # handler could not clear (failed always follows a closed). The init script records the closed in
    # "challenged"/saw_challenge; a bare timeout without a closed is not counted.
    ever_challenged = any(a["saw_challenge"] for a in attempts)
    return {
        "target_url": target_url,
        "verdict": last["verdict"],
        "challenged": ever_challenged,
        "attempt_count": len(attempts),
        "last_page_status": last["terminal_status"],
        "last_page_error": last["page_error"] or last["error"],
        "session_id": last["session_id"],
        "stopped_reason": stopped_reason,
        "attempts": [
            {
                "started_at": a["started_at"],
                "ended_at": a["ended_at"],
                "page_handler": a["page_handler"],
                "verdict": a["verdict"],
                "http_status": a["http_status"],
                "final_url": a["final_url"],
                "terminal_status": a["terminal_status"],
                "page_error": a["page_error"],
                "saw_challenge": a["saw_challenge"],
                "error": a["error"],
                "session_id": a["session_id"],
                "params": a["params"],
            }
            for a in attempts
        ],
    }


def collect_target(target_url, base_params=None, sleeper=time.sleep):
    """Drive one target through the full policy and return one checkable record.

    Flow (targets.md section 1, challenges.md section 3):
      1. plain attempt, page_handler=false: no state messages, status code + body only.
      2. anything but the expected page -> retry on a NEW connection with page_handler=true.
      3. ok / challenged -> keep page_handler=true and continue (same target, done for this page).
      4. blocked -> close, back off 10 s then 20 s, fresh identity, at most 2 more tries, then stop.
      5. oxylabs-network -> network-error retry (bounded); not-public -> stop immediately, no retry.
    """
    base_params = dict(base_params or PARAMS)
    base_params["page_handler"] = "false"
    attempts = []

    with sync_playwright() as pw:
        # Step 1: the cheap plain attempt.
        first = run_attempt(pw, target_url, base_params)
        attempts.append(first)
        print(f"[attempt 1] page_handler=false verdict={first['verdict']} "
              f"http={first['http_status']} session={first['session_id']} "
              f"error={redact(first['error']) if first['error'] else '-'}")

        # Step 2: only an ok plain page ends here. Every other verdict escalates to the page handler.
        if first["verdict"] == OK:
            return build_result(target_url, attempts, "ok-on-plain-attempt")
        if first["verdict"] == NOT_PUBLIC:
            return build_result(target_url, attempts, "sign-in-wall: content not public, stop without retry")

        handler_params = dict(base_params, **CHALLENGE_ESCALATION)
        blocked_retries = 0
        network_retries = 0

        # Steps 3-5 on page_handler=true connections.
        while True:
            attempt_no = len(attempts) + 1
            current = run_attempt(pw, target_url, handler_params)
            attempts.append(current)
            print(f"[attempt {attempt_no}] page_handler=true verdict={current['verdict']} "
                  f"terminal={current['terminal_status']} session={current['session_id']} "
                  f"error={redact(current['page_error'] or current['error']) if (current['page_error'] or current['error']) else '-'}")

            verdict = current["verdict"]

            if verdict in (OK, CHALLENGED):
                # Usable page. page_handler stays true for every later connection to this target.
                return build_result(target_url, attempts,
                                    "challenge handled" if verdict == CHALLENGED else "page usable with page handler")

            if verdict == NOT_PUBLIC:
                return build_result(target_url, attempts, "sign-in wall: content not public, stop without retry")

            if verdict == OXYLABS_NETWORK:
                if network_retries >= MAX_NETWORK_RETRIES:
                    return build_result(target_url, attempts,
                                        f"network error persisted after {network_retries} retries: stop")
                delay = BLOCKED_BACKOFF_SECONDS[min(network_retries, len(BLOCKED_BACKOFF_SECONDS) - 1)]
                network_retries += 1
                print(f"network error; retry {network_retries}/{MAX_NETWORK_RETRIES} after {delay}s backoff")
                sleeper(delay)
                continue  # new connection, same parameters (the network, not the identity, was at fault)

            if verdict == BLOCKED:
                if blocked_retries >= MAX_BLOCKED_RETRIES:
                    return build_result(
                        target_url, attempts,
                        f"blocked on {blocked_retries + 1} page-handler identities: stop and report")
                delay = BLOCKED_BACKOFF_SECONDS[blocked_retries]  # 10 s, then 20 s
                blocked_retries += 1
                print(f"blocked; fresh identity {blocked_retries}/{MAX_BLOCKED_RETRIES} after {delay}s backoff")
                sleeper(delay)
                handler_params = fresh_identity_params(handler_params, blocked_retries)
                continue

            # Defensive: an unknown verdict must not loop forever.
            return build_result(target_url, attempts, f"unknown verdict {verdict}: stop")


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else "https://example.com"
    result = collect_target(url)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    # quick single-shot helper kept for backwards compatibility with the old template:
    # challenge? collect_target(url, {**PARAMS, **CHALLENGE_ESCALATION}); blocked? {**PARAMS, **ENGINE_ESCALATION}

# This content is not intended to provide legal advice, and scraping activities may be subject to applicable laws and regulations.
