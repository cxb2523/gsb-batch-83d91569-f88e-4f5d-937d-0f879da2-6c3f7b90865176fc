"use strict";

// Offline sample for the full collection flow in playwright_scrape.collectTarget.
//
// Everything is faked: no browser is launched and no network is touched. A tiny
// in-memory CDP double stands in for the remote browser (injected through the
// module's _setConnector test seam), and each connection is scripted with the
// same observations a real run produces (status code, headers, final URL,
// body, page-handler terminal state).
//
// It verifies the policy around the verdict layer:
//
//   A. a plain ok page ends immediately (1 attempt, page_handler stays off)
//   B. a blocked plain attempt is retried on a new connection with
//      page_handler=true, a handled challenge ends as "challenged" and the
//      handler is kept on
//   C. blocked -> close, back off 10 s then 20 s, fresh identity, at most 2
//      more tries, then stop (4 attempts, delays [10, 20])
//   D. not-public stops at once, with no backoff and no retry
//   E. oxylabs-network is retried as a network error and then succeeds
//   F. a connection URL with the password inside an error string is redacted
//
// Run it:
//
//   cd skills/agent-browser/scripts
//   node collect_flow_sample.js   // exit code 0 means every check held

process.env.OXY_AB_USERNAME = process.env.OXY_AB_USERNAME || "demo-user";
process.env.OXY_AB_PASSWORD = process.env.OXY_AB_PASSWORD || "s3cr3t-pw";

const ps = require("./playwright_scrape");

class FakeHandle {
  constructor(state) { this._state = state; }
  async jsonValue() { return this._state; }
}

class FakeResponse {
  constructor(outcome) {
    this._status = outcome.status;
    this._headers = { ...(outcome.headers || {}) };
    this.url = outcome.url;
  }
  status() { return this._status; } // Playwright Response methods
  headers() { return this._headers; }
}

class FakePage {
  constructor(outcome) {
    this._outcome = outcome;
    this.url = outcome.url; // Playwright exposes url as a property
  }
  setDefaultTimeout() {}
  async route() {}
  on() {}
  async goto() {
    if (this._outcome.goto_error) throw this._outcome.goto_error;
    return new FakeResponse(this._outcome);
  }
  async waitForTimeout() {}
  async content() { return this._outcome.body; }
  async evaluate() {}
  async waitForFunction() {
    const state = this._outcome.state;
    if (state === null) throw new Error("CHALLENGE_HANDLING_TIMEOUT"); // scripted "no state in 90 s"
    return new FakeHandle(state);
  }
}

class FakeCDP {
  constructor(sessionId) { this._sessionId = sessionId; }
  async send(method) { return method === "__session_id" ? { value: this._sessionId } : {}; }
}

class FakeContext {
  constructor(sessionId, outcome) {
    this._sessionId = sessionId;
    this._outcome = outcome;
  }
  async addInitScript() {}
  newPage() { return new FakePage(this._outcome); }
  async newCDPSession() { return new FakeCDP(this._sessionId); }
}

class FakeBrowser {
  constructor(sessionId, outcome) {
    // The template uses browser.contexts()[0] ?? newContext(); expose one backed default context.
    this._context = new FakeContext(sessionId, outcome);
    this.contexts = () => [this._context];
    this.closed = false;
    this._sessionId = sessionId;
    this._outcome = outcome;
  }
  async newContext() { return this._context; }
  async close() { this.closed = true; }
}

// Each connection consumes the next scripted outcome; the connector returns
// the FakeBrowser connectWithBackoff would have handed back.
function installConnector(outcomes, connections) {
  let index = 0;
  ps._setConnector(async () => {
    const i = index++;
    const browser = new FakeBrowser(`sess-${i + 1}`, outcomes[i]);
    connections.push(browser);
    return browser;
  });
}

const BLOCKED_BODY = "<html><body>Access denied</body></html>";
const OK_BODY = "<html><body><h1>Acme wireless mouse</h1></body></html>";
const TARGET = "https://shop.example.com/products/42";

async function runScenario(outcomes) {
  const connections = [];
  const delays = [];
  installConnector(outcomes, connections);
  const originalLog = console.log;
  const originalWarn = console.warn;
  const logs = [];
  console.log = (...parts) => logs.push(parts.join(" "));
  console.warn = (...parts) => logs.push(parts.join(" "));
  let result;
  try {
    result = await ps.collectTarget(TARGET, ps.PARAMS, { sleeper: async (s) => delays.push(s) });
  } finally {
    console.log = originalLog;
    console.warn = originalWarn;
    ps._setConnector((url, options) => require("playwright").chromium.connectOverCDP(url, options));
  }
  return { result, delays, connections, logs: logs.join("\n") };
}

const scenarios = [];

// A. plain page is fine: nothing else should happen.
scenarios.push(["A plain ok ends on attempt 1", [
  { status: 200, headers: {}, url: TARGET, body: OK_BODY, state: null },
], ({ result: r, delays: d }) =>
  r.verdict === ps.OK && r.attempt_count === 1 && r.challenged === false &&
  r.attempts[0].page_handler === false && r.session_id === "sess-1" &&
  r.last_page_status === null && d.length === 0]);

// B. blocked plain attempt -> handler connection handles a challenge -> challenged.
scenarios.push(["B blocked plain attempt, then a handled challenge", [
  { status: 403, headers: {}, url: TARGET, body: BLOCKED_BODY, state: null },
  { status: 200, headers: {}, url: TARGET, body: OK_BODY,
    state: { status: "open", error: null, challenged: true, sawClosed: true } },
], ({ result: r, delays: d, connections }) =>
  r.verdict === ps.CHALLENGED && r.attempt_count === 2 && r.challenged === true &&
  JSON.stringify(r.attempts.map((a) => a.page_handler)) === JSON.stringify([false, true]) &&
  r.attempts[1].terminal_status === "open" && r.attempts[1].session_id === "sess-2" &&
  r.attempts.every((a) => a.started_at && a.ended_at) &&
  d.length === 0 && connections.every((b) => b.closed)]); // every session closed in finally

// C. blocked three identities in a row: 10 s then 20 s backoff, max 2 retries, then stop.
scenarios.push(["C blocked: 10s/20s backoff, two fresh identities, then stop", [
  { status: 403, headers: {}, url: TARGET, body: BLOCKED_BODY, state: null },
  { status: 403, headers: {}, url: TARGET, body: BLOCKED_BODY,
    state: { status: "failed", error: "bad_token", challenged: true } },
  { status: 200, headers: {}, url: "https://shop.example.com/blocked",
    body: "<html>Verify you are human</html>",
    state: { status: "open", error: null, challenged: false } },
  { status: 503, headers: {}, url: "https://shop.example.com/blocked", body: BLOCKED_BODY,
    state: { status: "open", error: null, challenged: false } },
], ({ result: r, delays: d }) =>
  r.verdict === ps.BLOCKED && r.attempt_count === 4 && JSON.stringify(d) === JSON.stringify([10, 20]) &&
  JSON.stringify(r.attempts.map((a) => a.page_handler)) === JSON.stringify([false, true, true, true]) &&
  r.last_page_status === "open" && r.stopped_reason.includes("stop") &&
  r.attempts[1].page_error === "bad_token"]);

// D. sign-in wall on the handler connection: stop immediately, no backoff.
scenarios.push(["D not-public stops without retry or backoff", [
  { status: 403, headers: {}, url: TARGET, body: BLOCKED_BODY, state: null },
  { status: 200, headers: {}, url: "https://account.example.com/login?next=/products/42",
    body: "<html>sign in</html>",
    state: { status: "open", error: null, challenged: false } },
], ({ result: r, delays: d }) =>
  r.verdict === ps.NOT_PUBLIC && r.attempt_count === 2 && d.length === 0 &&
  r.stopped_reason.includes("not public")]);

// E. Oxylabs network error on the handler connection: network retry, then ok.
scenarios.push(["E oxylabs-network retried as a network error, then ok", [
  { status: 403, headers: {}, url: TARGET, body: BLOCKED_BODY, state: null },
  { status: 502, headers: { "X-Error-Description": "upstream timeout" }, url: TARGET,
    body: "Bad Gateway", state: null },
  { status: 200, headers: {}, url: TARGET, body: OK_BODY,
    state: { status: "open", error: null, challenged: false } },
], ({ result: r, delays: d }) =>
  r.verdict === ps.OK && r.attempt_count === 3 && JSON.stringify(d) === JSON.stringify([10]) &&
  r.attempts[1].verdict === ps.OXYLABS_NETWORK]);

// F. an error string carrying the connection URL must never leak the password.
const secretUrl = `WebSocket error: wss://demo-user:${process.env.OXY_AB_PASSWORD}@hb.oxylabs.io/ 503`;
scenarios.push(["F password-bearing errors are redacted everywhere", [
  { status: 200, headers: {}, url: TARGET, body: OK_BODY, state: null, goto_error: new Error(secretUrl) },
  { status: 200, headers: {}, url: TARGET, body: OK_BODY,
    state: { status: "open", error: null, challenged: false } },
], ({ result: r, logs }) =>
  !JSON.stringify(r).includes(process.env.OXY_AB_PASSWORD) &&
  !logs.includes(process.env.OXY_AB_PASSWORD) &&
  JSON.stringify(r).includes("***") &&
  r.attempts[0].verdict === ps.OXYLABS_NETWORK]);

(async () => {
  let failures = 0;
  for (const [name, outcomes, check] of scenarios) {
    let held = false;
    let detail = "";
    try {
      const ctx = await runScenario(outcomes);
      held = check(ctx);
      detail = `verdict=${ctx.result.verdict} attempts=${ctx.result.attempt_count} ` +
        `backoff=[${ctx.delays.join(", ")}] challenged=${ctx.result.challenged}`;
    } catch (err) {
      detail = `scenario raised: ${err.stack}`;
    }
    if (!held) failures += 1;
    console.log(`[${held ? "PASS" : "FAIL"}] ${name}\n        ${detail}`);
  }
  console.log();
  if (failures) {
    console.log(`${failures} scenario(s) failed`);
    process.exit(1);
  }
  console.log(`all ${scenarios.length} flow scenarios passed; no browser was launched and no network was used`);
})();
