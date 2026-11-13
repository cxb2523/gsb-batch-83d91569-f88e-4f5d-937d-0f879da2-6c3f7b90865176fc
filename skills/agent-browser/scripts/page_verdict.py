"""Collection verdict for a target page.

Pure classification logic, no Playwright, no network: it turns what an
attempt observed into one of five verdicts so a caller can decide whether to
retry, change identity or stop.

    ok              the expected, publicly available page
    challenged      a challenge stood in the way and the page handler cleared it (closed -> open)
    blocked         the site refused this visitor (failed handling, 403/503, block/verify page)
    not-public      the target redirected to a sign-in wall; the data is not public
    oxylabs-network an Oxylabs-side network error (X-Error-Description on a response)

The decision only uses generic HTTP signals (status code, response headers,
final URL, body text) and the page handler's state machine. It never keys on
vendor-specific markup, fingerprint headers or product names embedded in a
page. The one header it looks at, X-Error-Description, is the generic
"upstream network error on this response" signal the platform documents.
"""

import re

# Five possible verdicts.
OK = "ok"
CHALLENGED = "challenged"
BLOCKED = "blocked"
NOT_PUBLIC = "not-public"
OXYLABS_NETWORK = "oxylabs-network"
VERDICTS = (OK, CHALLENGED, BLOCKED, NOT_PUBLIC, OXYLABS_NETWORK)

# Page-handler terminal/transient states (window message "oxylabs-page-status").
IDENTIFYING = "identifying"
CLOSED = "closed"
OPEN = "open"
FAILED = "failed"

# HTTP walls the target itself raises. 401/402/404 etc. are deliberately not
# here: the task defines the blocked wall as 403/503 plus block-page wording.
BLOCK_STATUSES = frozenset({403, 503})

# Generic "you are refused" wording, independent of any bot-management vendor.
BLOCK_PATTERN = re.compile(r"access denied|verify you are human", re.IGNORECASE)

# A sign-in wall in the final URL: /login, /signin, /sign-in (path boundary).
LOGIN_PATH_PATTERN = re.compile(r"/(login|signin|sign-in)(?:/|$|\?)", re.IGNORECASE)


def has_error_header(headers):
    """True when a response carries the upstream network-error header.

    Header names are case-insensitive; Playwright lowercases them but callers
    may pass plain dicts straight from other clients.
    """
    if not headers:
        return False
    lowered = {str(k).lower(): v for k, v in headers.items()}
    return lowered.get("x-error-description") not in (None, "")


def is_login_url(final_url):
    return bool(final_url) and bool(LOGIN_PATH_PATTERN.search(final_url))


def is_block_content(status_code, body_excerpt):
    if status_code in BLOCK_STATUSES:
        return True
    return bool(body_excerpt) and bool(BLOCK_PATTERN.search(body_excerpt))


def classify_page(headers, final_url, status_code, body_excerpt, terminal_state):
    """Classify one observed page.

    Arguments:
        headers:        response headers of the main document (mapping or None)
        final_url:      URL after all redirects
        status_code:    HTTP status of the main document (int or None)
        body_excerpt:   leading slice of the rendered body (str or None)
        terminal_state: the page handler's waited-out state, or None when the
                        handler was off (page_handler=false). A mapping with at
                        least {"status": ...} and optionally "error" and
                        "challenged"; a bare status string is accepted too.

    Returns one of the VERDICTS strings.

    Precedence (first match wins):
      1. X-Error-Description ............ oxylabs-network
      2. final URL on a login path ...... not-public
      3. terminal failed, or a 403/503 /
         "access denied" / "verify you are human" page ... blocked
      4. a closed -> open transition .... challenged; a plain open ... ok
      5. handler on but no usable terminal state (e.g. a 90 s timeout) ... blocked
      6. a plain (no-handler) attempt with no wall ... ok
    """
    # 1. Upstream network failure on this response. Checked first: a network
    #    error is not the site's answer, regardless of what else was observed.
    if has_error_header(headers):
        return OXYLABS_NETWORK

    # 2. A sign-in wall means the content is only for logged-in users and is
    #    out of scope for public-data collection. No retry can make it public.
    if is_login_url(final_url):
        return NOT_PUBLIC

    # Normalise the terminal state to a dict-shaped view.
    state = terminal_state or {}
    if isinstance(state, str):
        state = {"status": state}
    status = state.get("status")
    saw_challenge = bool(state.get("challenged") or state.get("saw_closed"))

    # 3. A wall the site itself raised: the handler gave up (failed with an
    #    error), or the page is still a 403/503 / access-denied / human-check
    #    page even though the handler may have reported "open".
    if status == FAILED or is_block_content(status_code, body_excerpt):
        return BLOCKED

    # 4. The handler saw a challenge (closed) and the page became usable
    #    afterwards (open). Keep page_handler=true for this target.
    if status == OPEN:
        return CHALLENGED if saw_challenge else OK

    # 5. The handler was on (a state object was supplied) but never reported a
    #    usable terminal state - e.g. the 90 s wait timed out, or only a
    #    transient identifying/closed was captured. Usability was never
    #    confirmed: treat as blocked so the caller rotates identity instead of
    #    accepting an unverified page. A plain page_handler=false attempt passes
    #    no state object at all and is not affected (it falls through to ok).
    if state:
        return BLOCKED

    # 6. Plain attempt (no handler) with no wall: a usable public page.
    return OK
