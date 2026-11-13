"use strict";

// Offline sample for the collection verdict (page_verdict.classifyPage).
//
// Runs entirely locally with faked inputs - no Playwright, no browser, no
// network connection of any kind. Each case forges the five things a real
// attempt would observe (response headers, final URL after redirects, HTTP
// status code, a body excerpt, and the page handler's waited-out terminal
// state) and checks that classifyPage returns the expected one of:
//
//   ok | challenged | blocked | not-public | oxylabs-network
//
// Run it:
//
//   cd skills/agent-browser/scripts
//   node verdict_sample.js        // exit code 0 means every case matched

const {
  OK,
  CHALLENGED,
  BLOCKED,
  NOT_PUBLIC,
  OXYLABS_NETWORK,
  classifyPage,
} = require("./page_verdict");

const CASES = [
  {
    name: "1. plain public page, page handler off (page_handler=false)",
    headers: { "content-type": "text/html; charset=utf-8" },
    finalUrl: "https://shop.example.com/products/42",
    statusCode: 200,
    bodyExcerpt: "<html><body><h1>Acme wireless mouse</h1><p>In stock, $19.99</p></body></html>",
    terminalState: null, // no window messages without page_handler
    expect: OK,
  },
  {
    name: "2. challenge handled: identifying -> closed -> open",
    headers: { "content-type": "text/html" },
    finalUrl: "https://shop.example.com/products/42",
    statusCode: 200,
    bodyExcerpt: "<html><body><h1>Acme wireless mouse</h1></body></html>",
    terminalState: { status: "open", error: null, challenged: true, sawClosed: true },
    expect: CHALLENGED,
  },
  {
    name: "3. blocked: handler failed after a closed",
    headers: { "content-type": "text/html" },
    finalUrl: "https://shop.example.com/products/42",
    statusCode: 403,
    bodyExcerpt: "<html><body>Access denied</body></html>",
    terminalState: { status: "failed", error: "bad_token", challenged: true },
    expect: BLOCKED,
  },
  {
    name: "4. blocked: handler says open but the page is still a human-check wall",
    headers: { "content-type": "text/html" },
    finalUrl: "https://shop.example.com/blocked",
    statusCode: 503,
    bodyExcerpt: "<html><body><h1>Verify you are human</h1></body></html>",
    terminalState: { status: "open", error: null, challenged: false },
    expect: BLOCKED,
  },
  {
    name: "5. not-public: redirect landed on a sign-in wall",
    headers: { "content-type": "text/html" },
    finalUrl: "https://account.example.com/login?next=/products/42",
    statusCode: 200,
    bodyExcerpt: "<html><body><form>Sign in to continue</form></body></html>",
    terminalState: { status: "open", error: null, challenged: false },
    expect: NOT_PUBLIC,
  },
  {
    name: "6. oxylabs-network: response carries X-Error-Description",
    headers: { "Content-Type": "text/plain", "X-Error-Description": "upstream connection timed out" },
    finalUrl: "https://shop.example.com/products/42",
    statusCode: 502,
    bodyExcerpt: "Bad Gateway",
    terminalState: null,
    expect: OXYLABS_NETWORK,
  },
];

// Extra precedence probes: the first matching rule must win over the later ones.
const EDGE_CASES = [
  {
    name: "7. network header beats a login redirect (header checked first)",
    headers: { "x-error-description": "proxy failure" },
    finalUrl: "https://account.example.com/login",
    statusCode: 200,
    bodyExcerpt: "<html>sign in</html>",
    terminalState: null,
    expect: OXYLABS_NETWORK,
  },
  {
    name: "8. login URL beats a block-looking body (not-public before blocked)",
    headers: { "content-type": "text/html" },
    finalUrl: "https://example.com/sign-in",
    statusCode: 403,
    bodyExcerpt: "Access denied",
    terminalState: null,
    expect: NOT_PUBLIC,
  },
  {
    name: "9. block content beats a challenged flag (a failed wall is not a success)",
    headers: { "content-type": "text/html" },
    finalUrl: "https://example.com/widget",
    statusCode: 200,
    bodyExcerpt: "<html>Please verify you are human to continue.</html>",
    terminalState: { status: "open", challenged: true },
    expect: BLOCKED,
  },
  {
    name: "10. straight open without a closed is just ok",
    headers: { "content-type": "text/html" },
    finalUrl: "https://example.com/",
    statusCode: 200,
    bodyExcerpt: "<html><body>Welcome</body></html>",
    terminalState: { status: "open", challenged: false },
    expect: OK,
  },
  {
    name: "11. handler on but it never reached a terminal state (90 s timeout): unverified, blocked",
    headers: { "content-type": "text/html" },
    finalUrl: "https://example.com/widget",
    statusCode: 200,
    bodyExcerpt: "<html><body>Welcome</body></html>",
    // observePageStatus() returns this shape on CHALLENGE_HANDLING_TIMEOUT.
    terminalState: { status: null, error: "CHALLENGE_HANDLING_TIMEOUT", challenged: false, saw_closed: false },
    expect: BLOCKED,
  },
];

let failures = 0;
for (const c of CASES.concat(EDGE_CASES)) {
  const got = classifyPage(c.headers, c.finalUrl, c.statusCode, c.bodyExcerpt, c.terminalState);
  const ok = got === c.expect;
  if (!ok) failures += 1;
  console.log(`[${ok ? "PASS" : "FAIL"}] ${c.name}\n        -> ${got}${ok ? "" : ` (expected ${c.expect})`}`);
}

console.log();
if (failures) {
  console.log(`${failures} case(s) failed`);
  process.exit(1);
}
console.log(`all ${CASES.length + EDGE_CASES.length} cases passed; no network was used`);
