"""Offline sample for the collection verdict (page_verdict.classify_page).

Runs entirely locally with faked inputs - no Playwright, no browser, no network
connection of any kind. Each case forges the five things a real attempt would
observe (response headers, final URL after redirects, HTTP status code, a body
excerpt, and the page handler's waited-out terminal state) and checks that
classify_page returns the expected one of:

    ok | challenged | blocked | not-public | oxylabs-network

Run it:

    cd skills/agent-browser/scripts
    python verdict_sample.py            # exit code 0 means every case matched

The script also works from any directory and under an isolated interpreter:

    python -I skills/agent-browser/scripts/verdict_sample.py
"""

import os
import sys

# Make the sibling page_verdict.py importable no matter where the script is started from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from page_verdict import (  # noqa: E402
    BLOCKED,
    CHALLENGED,
    NOT_PUBLIC,
    OK,
    OXYLABS_NETWORK,
    classify_page,
)

# Every case is a forged observation of one target page.
CASES = [
    {
        "name": "1. plain public page, page handler off (page_handler=false)",
        "headers": {"content-type": "text/html; charset=utf-8"},
        "final_url": "https://shop.example.com/products/42",
        "status_code": 200,
        "body_excerpt": "<html><body><h1>Acme wireless mouse</h1><p>In stock, $19.99</p></body></html>",
        "terminal_state": None,  # no window messages without page_handler
        "expect": OK,
    },
    {
        "name": "2. challenge handled: identifying -> closed -> open",
        "headers": {"content-type": "text/html"},
        "final_url": "https://shop.example.com/products/42",
        "status_code": 200,
        "body_excerpt": "<html><body><h1>Acme wireless mouse</h1></body></html>",
        # observe_page_status() returns this shape after the handler cleared a widget challenge.
        "terminal_state": {"status": "open", "error": None, "challenged": True, "sawClosed": True},
        "expect": CHALLENGED,
    },
    {
        "name": "3. blocked: handler failed after a closed",
        "headers": {"content-type": "text/html"},
        "final_url": "https://shop.example.com/products/42",
        "status_code": 403,
        "body_excerpt": "<html><body>Access denied</body></html>",
        "terminal_state": {"status": "failed", "error": "bad_token", "challenged": True},
        "expect": BLOCKED,
    },
    {
        "name": "4. blocked: handler says open but the page is still a human-check wall",
        "headers": {"content-type": "text/html"},
        "final_url": "https://shop.example.com/blocked",
        "status_code": 503,
        "body_excerpt": "<html><body><h1>Verify you are human</h1></body></html>",
        "terminal_state": {"status": "open", "error": None, "challenged": False},
        "expect": BLOCKED,
    },
    {
        "name": "5. not-public: redirect landed on a sign-in wall",
        "headers": {"content-type": "text/html"},
        "final_url": "https://account.example.com/login?next=/products/42",
        "status_code": 200,
        "body_excerpt": "<html><body><form>Sign in to continue</form></body></html>",
        "terminal_state": {"status": "open", "error": None, "challenged": False},
        "expect": NOT_PUBLIC,
    },
    {
        "name": "6. oxylabs-network: response carries X-Error-Description",
        "headers": {"Content-Type": "text/plain", "X-Error-Description": "upstream connection timed out"},
        "final_url": "https://shop.example.com/products/42",
        "status_code": 502,
        "body_excerpt": "Bad Gateway",
        "terminal_state": None,
        "expect": OXYLABS_NETWORK,
    },
]

# Extra precedence probes: the first matching rule must win over the later ones.
EDGE_CASES = [
    {
        "name": "7. network header beats a login redirect (header checked first)",
        "headers": {"x-error-description": "proxy failure"},
        "final_url": "https://account.example.com/login",
        "status_code": 200,
        "body_excerpt": "<html>sign in</html>",
        "terminal_state": None,
        "expect": OXYLABS_NETWORK,
    },
    {
        "name": "8. login URL beats a block-looking body (not-public before blocked)",
        "headers": {"content-type": "text/html"},
        "final_url": "https://example.com/sign-in",
        "status_code": 403,
        "body_excerpt": "Access denied",
        "terminal_state": None,
        "expect": NOT_PUBLIC,
    },
    {
        "name": "9. block content beats a challenged flag (a failed wall is not a success)",
        "headers": {"content-type": "text/html"},
        "final_url": "https://example.com/widget",
        "status_code": 200,
        "body_excerpt": "<html>Please verify you are human to continue.</html>",
        "terminal_state": {"status": "open", "challenged": True},
        "expect": BLOCKED,
    },
    {
        "name": "10. straight open without a closed is just ok",
        "headers": {"content-type": "text/html"},
        "final_url": "https://example.com/",
        "status_code": 200,
        "body_excerpt": "<html><body>Welcome</body></html>",
        "terminal_state": {"status": "open", "challenged": False},
        "expect": OK,
    },
    {
        "name": "11. handler on but it never reached a terminal state (90 s timeout): unverified, blocked",
        "headers": {"content-type": "text/html"},
        "final_url": "https://example.com/widget",
        "status_code": 200,
        "body_excerpt": "<html><body>Welcome</body></html>",
        # observe_page_status() returns this shape on CHALLENGE_HANDLING_TIMEOUT.
        "terminal_state": {"status": None, "error": "CHALLENGE_HANDLING_TIMEOUT",
                           "challenged": False, "saw_closed": False},
        "expect": BLOCKED,
    },
]


def main():
    failures = 0
    for case in CASES + EDGE_CASES:
        got = classify_page(
            case["headers"],
            case["final_url"],
            case["status_code"],
            case["body_excerpt"],
            case["terminal_state"],
        )
        ok = got == case["expect"]
        failures += 0 if ok else 1
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case['name']}\n        -> {got}" + ("" if ok else f" (expected {case['expect']})"))

    print()
    if failures:
        print(f"{failures} case(s) failed")
        sys.exit(1)
    print(f"all {len(CASES) + len(EDGE_CASES)} cases passed; no network was used")


if __name__ == "__main__":
    main()
