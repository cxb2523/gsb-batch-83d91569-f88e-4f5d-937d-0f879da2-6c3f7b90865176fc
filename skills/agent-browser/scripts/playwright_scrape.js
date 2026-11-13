"use strict";

const {
  OK,
  CHALLENGED,
  BLOCKED,
  NOT_PUBLIC,
  OXYLABS_NETWORK,
  FAILED,
  classifyPage,
} = require("./page_verdict");

const USERNAME = process.env.OXY_AB_USERNAME;
const PASSWORD = process.env.OXY_AB_PASSWORD;
const ENDPOINT = "hb.oxylabs.io";

// Test seam: offline samples swap the connect implementation so no browser is
// launched and the "playwright" package never has to be installed. Production
// code leaves this at the lazy real CDP connector.
let connectOverCdp = (url, options) => require("playwright").chromium.connectOverCDP(url, options);
function _setConnector(fn) { connectOverCdp = fn; }

// Connection parameters (parameters.md). Most jobs need only p_cc plus an explicit page_handler=false: every session
// already gets a fresh browser configuration (default engine, Windows profile family oxyfp_win) and a fresh residential IP.
const PARAMS = { p_cc: "US", page_handler: "false" };
// Block or verification page instead of the expected content? Reconnect with this; the page handler then
// identifies every page and reports its state (challenges.md):
const CHALLENGE_ESCALATION = { page_handler: "true" };
// Escalation when a fresh identity with the right geo is still blocked (targets.md, section 4, rung 4):
// the new browser engine with its macOS profile family. Desktop only; keep the pair for every later connection.
const ENGINE_ESCALATION = { p_src: "oxybrowser", p_fp_tag: "oxyfp_mac_optimized" };

// Identity-retry policy when the target blocks a visitor (challenges.md section 3): close the session,
// back off 10 s doubling, reconnect as a fresh identity with page_handler=true, at most 2 more tries.
const BLOCKED_BACKOFF_SECONDS = [10, 20];
const MAX_BLOCKED_RETRIES = 2;
// Network errors (X-Error-Description / connection and navigation failures) are transient: bounded retries.
const MAX_NETWORK_RETRIES = 3;
// How much of the rendered body is kept for classification and in the record (the full HTML is not stored).
const BODY_EXCERPT_CHARS = 4096;

// Concatenate; never round-trip the result through `new URL()` (re-encodes the password -> 401).
function endpointUrl(params = {}) {
  const q = new URLSearchParams(params).toString();
  return `wss://${USERNAME}:${PASSWORD}@${ENDPOINT}${q ? "?" + q : ""}`;
}

// Error messages contain the connection URL, i.e. the password. Redact before logging anything.
const redact = (text) => String(text).split(PASSWORD).join("***");

// Retry only what the service can recover from. 400/401/403 mean the request is wrong: fix, don't retry.
// Playwright: "... wss://user:***@hb.oxylabs.io/ 429 Too Many Requests\nCDP_SESSION_RATE_LIMIT_REACHED"
// Puppeteer:  "Unexpected server response: 429"
const RETRYABLE =
  /\b(429|50[0234]) [A-Z]|response: (429|50[0234])\b|CDP_SESSION_IN_USE|CDP_NO_BROWSERS_AVAILABLE|CDP_BROWSER_OVERWORKED|CDP_BAD_PROXY|CDP_GENERAL_ERROR|[Tt]imeout|ECONNRESET/;

const sleep = (seconds) => new Promise((resolve) => setTimeout(resolve, seconds * 1000));

// Test seam for timestamps so offline samples stay deterministic.
const utcNowIso = () => new Date().toISOString().replace(/\.\d{3}Z$/, "Z");

// Exponential backoff: 1s base, 60s cap, full jitter. Six attempts span roughly two minutes.
// The service admits at most 10 new sessions per second per account, so space parallel launches >= 150 ms.
async function connectWithBackoff(params, { attempts = 6, baseMs = 1000, capMs = 60000 } = {}) {
  let lastErr;
  for (let attempt = 0; attempt < attempts; attempt++) {
    try {
      return await connectOverCdp(endpointUrl(params), { timeout: 60000 });
    } catch (err) {
      lastErr = err;
      if (!RETRYABLE.test(String(err.message))) throw err; // 400/401/403: stop and fix the request
      console.warn(`connect attempt ${attempt + 1} failed: ${redact(err.message).split("\n")[0]}`);
      const delay = Math.min(capMs, baseMs * 2 ** attempt) * (0.5 + Math.random());
      await new Promise((r) => setTimeout(r, delay));
    }
  }
  throw lastErr;
}

// Default on: images, styles, media and fonts are not needed for data extraction and cost time.
async function blockHeavyResources(page) {
  await page.route("**/*", (route) => {
    const type = route.request().resourceType();
    return ["image", "stylesheet", "media", "font"].includes(type) ? route.abort() : route.continue();
  });
}

// X-Error-Description present => the error came from the upstream network (retry / adjust per errors table).
// Absent on a 4xx/5xx => the target itself answered (a block page, a 403): change approach, do not blindly retry.
function watchOxylabsErrors(page, onInfraError) {
  page.on("response", (resp) => {
    const description = resp.headers()["x-error-description"];
    if (description) onInfraError({ status: resp.status(), url: resp.url(), description });
  });
}

// With page_handler=true the browser reports each page's state as a window message
// { source: "oxylabs-runtime", type: "oxylabs-page-status", status, error? }, status one of identifying |
// closed (challenge being handled) | open (page usable) | failed (with error); the last message wins
// (challenges.md). The same status is also a console line, but the remote browser does not deliver console
// output live to CDP clients, so an init script keeps the latest status on every document instead.
async function watchPageStatus(context) {
  await context.addInitScript(() => {
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
  });
}

// Resolves once the page is open (about 8 s after load without a challenge; a widget challenge usually 30 to 45 s);
// throws on failed. identifying and closed are transient. Playwright re-runs the predicate after a navigation,
// so a challenge page that turns into the real page is followed.
async function waitForPageStatus(page, timeoutMs = 90000) {
  const terminal = await page
    .waitForFunction(
      () => {
        const s = window.__oxyPageStatus;
        return s && s.status !== "identifying" && s.status !== "closed" ? s : null;
      },
      null,
      { timeout: timeoutMs, polling: 500 },
    )
    .then((handle) => handle.jsonValue(), () => null);
  if (!terminal) throw new Error("CHALLENGE_HANDLING_TIMEOUT");
  if (terminal.status === "failed") throw new Error(`CHALLENGE_HANDLING_ERROR: ${terminal.error}`); // challenges.md section 3: fresh identity, max 2 retries
  return terminal; // { status: "open", challenged: true | false }
}

// Non-throwing variant for the verdict layer: returns the terminal state as plain data so a failed
// challenge or a 90 s timeout can be classified instead of aborting the run.
async function observePageStatus(page, timeoutMs = 90000) {
  try {
    const state = await waitForPageStatus(page, timeoutMs);
    return {
      status: state.status ?? null,
      error: state.error ?? null,
      challenged: Boolean(state.challenged),
      saw_closed: Boolean(state.sawClosed),
    };
  } catch (err) {
    const message = String(err.message);
    if (message.startsWith("CHALLENGE_HANDLING_ERROR:")) {
      return { status: FAILED, error: message.split(": ")[1], challenged: true, saw_closed: true };
    }
    return { status: null, error: message, challenged: false, saw_closed: false };
  }
}

// Before a manual trigger (challenges.md section 4): forget the stored status, so the earlier "open" cannot
// satisfy the next wait while the handle request is still queued.
async function clearPageStatus(page) {
  await page.evaluate(() => { window.__oxyPageStatus = null; });
}

// Fetch the session id with the CDP command __session_id (SKILL.md section 7). Tolerates both the
// raw-CDP shape { value: id } and an unwrapped shape. Never throws: the record still gets built.
async function getSessionId(context, page) {
  try {
    const cdp = await context.newCDPSession(page);
    const result = await cdp.send("__session_id");
    return result && typeof result === "object" && "value" in result ? result.value : result;
  } catch (err) {
    console.warn(`could not fetch session id: ${redact(err.message).split("\n")[0]}`);
    return null;
  }
}

// One connection to one target. Always returns an attempt record (never throws for page-level outcomes):
// connection/navigation failures come back as verdict oxylabs-network so the orchestrator can retry them.
async function runAttempt(targetUrl, params) {
  const startedAt = utcNowIso();
  const attempt = {
    started_at: startedAt,
    ended_at: null,
    page_handler: params.page_handler === "true",
    params: { ...params },
    session_id: null,
    final_url: null,
    http_status: null,
    terminal_status: null,
    page_error: null,
    saw_challenge: false,
    verdict: null,
    error: null,
  };
  let browser;
  try {
    browser = await connectWithBackoff(params);
    const context = browser.contexts()[0] ?? (await browser.newContext());
    await watchPageStatus(context); // before the page exists, so a page-load challenge is captured
    const page = await context.newPage();
    page.setDefaultTimeout(30000);
    await blockHeavyResources(page);

    const infraErrors = [];
    watchOxylabsErrors(page, (e) => infraErrors.push(e));

    let response;
    try {
      response = await page.goto(targetUrl, { waitUntil: "domcontentloaded" });
    } catch (err) {
      attempt.error = redact(err.message).split("\n")[0]; // navigation never produced a document
      attempt.verdict = OXYLABS_NETWORK;
      attempt.ended_at = utcNowIso();
      return attempt;
    }
    await page.waitForTimeout(2000 + Math.random() * 3000); // let late JS settle

    const state = params.page_handler === "true" ? await observePageStatus(page) : null; // no status without the handler

    attempt.session_id = await getSessionId(context, page);
    attempt.final_url = page.url;
    attempt.http_status = response ? response.status() : null;
    attempt.terminal_status = state ? state.status : null;
    attempt.page_error = state ? state.error : null;
    attempt.saw_challenge = Boolean(state && state.saw_closed);

    const body = await page.content();
    let headers = response ? response.headers() : {};
    // An X-Error-Description on any page response (subresource included) is the same upstream signal.
    if (infraErrors.length && !Object.keys(headers).some((k) => k.toLowerCase() === "x-error-description")) {
      headers = { ...headers, "X-Error-Description": infraErrors[0].description };
    }

    attempt.verdict = classifyPage(
      headers,
      page.url,
      attempt.http_status,
      body.slice(0, BODY_EXCERPT_CHARS),
      state,
    );
    attempt.ended_at = utcNowIso();
    return attempt;
  } catch (err) {
    attempt.error = redact(err.message).split("\n")[0]; // connect failure or anything session-level: network
    attempt.verdict = OXYLABS_NETWORK;
    attempt.ended_at = utcNowIso();
    return attempt;
  } finally {
    if (browser) await browser.close(); // always: an unclosed session keeps its concurrency slot
  }
}

// Parameters for a blocked-retry connection. A new session already means a new IP and browser configuration;
// if the identity was pinned (sticky id / stored profile), rotate those names too (targets.md section 4,
// rung 2). page_handler stays true.
function freshIdentityParams(params, identityIndex) {
  const nextParams = { ...params, page_handler: "true" };
  if (nextParams.proxy_resi_ses_id) nextParams.proxy_resi_ses_id = `${nextParams.proxy_resi_ses_id}-${identityIndex}`;
  if (nextParams.o_profile) nextParams.o_profile = `${nextParams.o_profile}-${identityIndex}`;
  return nextParams;
}

function buildResult(targetUrl, attempts, stoppedReason) {
  const last = attempts[attempts.length - 1];
  // Whether the target ever put a challenge in the way: a handled one (closed -> open), or one the
  // handler could not clear (failed always follows a closed). A bare timeout without a closed is not counted.
  const challenged = attempts.some((a) => a.saw_challenge);
  return {
    target_url: targetUrl,
    verdict: last.verdict,
    challenged,
    attempt_count: attempts.length,
    last_page_status: last.terminal_status,
    last_page_error: last.page_error || last.error,
    session_id: last.session_id,
    stopped_reason: stoppedReason,
    attempts: attempts.map((a) => ({
      started_at: a.started_at,
      ended_at: a.ended_at,
      page_handler: a.page_handler,
      verdict: a.verdict,
      http_status: a.http_status,
      final_url: a.final_url,
      terminal_status: a.terminal_status,
      page_error: a.page_error,
      saw_challenge: a.saw_challenge,
      error: a.error,
      session_id: a.session_id,
      params: a.params,
    })),
  };
}

// Drive one target through the full policy and return one checkable record.
//
// Flow (targets.md section 1, challenges.md section 3):
//   1. plain attempt, page_handler=false: no state messages, status code + body only.
//   2. anything but the expected page -> retry on a NEW connection with page_handler=true.
//   3. ok / challenged -> keep page_handler=true and continue (same target, done for this page).
//   4. blocked -> close, back off 10 s then 20 s, fresh identity, at most 2 more tries, then stop.
//   5. oxylabs-network -> network-error retry (bounded); not-public -> stop immediately, no retry.
async function collectTarget(targetUrl, baseParams = PARAMS, { sleeper = sleep } = {}) {
  const plainParams = { ...baseParams, page_handler: "false" };
  const attempts = [];

  // Step 1: the cheap plain attempt.
  const first = await runAttempt(targetUrl, plainParams);
  attempts.push(first);
  console.log(
    `[attempt 1] page_handler=false verdict=${first.verdict} http=${first.http_status} ` +
      `session=${first.session_id} error=${first.error ? redact(first.error) : "-"}`,
  );

  if (first.verdict === OK) return buildResult(targetUrl, attempts, "ok-on-plain-attempt");
  if (first.verdict === NOT_PUBLIC) {
    return buildResult(targetUrl, attempts, "sign-in wall: content not public, stop without retry");
  }

  let handlerParams = { ...plainParams, ...CHALLENGE_ESCALATION };
  let blockedRetries = 0;
  let networkRetries = 0;

  // Steps 3-5 on page_handler=true connections.
  while (true) {
    const attemptNo = attempts.length + 1;
    const current = await runAttempt(targetUrl, handlerParams);
    attempts.push(current);
    const shownError = current.page_error || current.error;
    console.log(
      `[attempt ${attemptNo}] page_handler=true verdict=${current.verdict} ` +
        `terminal=${current.terminal_status} session=${current.session_id} error=${shownError ? redact(shownError) : "-"}`,
    );

    const verdict = current.verdict;

    if (verdict === OK || verdict === CHALLENGED) {
      return buildResult(
        targetUrl,
        attempts,
        verdict === CHALLENGED ? "challenge handled" : "page usable with page handler",
      );
    }

    if (verdict === NOT_PUBLIC) {
      return buildResult(targetUrl, attempts, "sign-in wall: content not public, stop without retry");
    }

    if (verdict === OXYLABS_NETWORK) {
      if (networkRetries >= MAX_NETWORK_RETRIES) {
        return buildResult(targetUrl, attempts, `network error persisted after ${networkRetries} retries: stop`);
      }
      const delay = BLOCKED_BACKOFF_SECONDS[Math.min(networkRetries, BLOCKED_BACKOFF_SECONDS.length - 1)];
      networkRetries += 1;
      console.log(`network error; retry ${networkRetries}/${MAX_NETWORK_RETRIES} after ${delay}s backoff`);
      await sleeper(delay);
      continue; // new connection, same parameters (the network, not the identity, was at fault)
    }

    if (verdict === BLOCKED) {
      if (blockedRetries >= MAX_BLOCKED_RETRIES) {
        return buildResult(
          targetUrl,
          attempts,
          `blocked on ${blockedRetries + 1} page-handler identities: stop and report`,
        );
      }
      const delay = BLOCKED_BACKOFF_SECONDS[blockedRetries]; // 10 s, then 20 s
      blockedRetries += 1;
      console.log(`blocked; fresh identity ${blockedRetries}/${MAX_BLOCKED_RETRIES} after ${delay}s backoff`);
      await sleeper(delay);
      handlerParams = freshIdentityParams(handlerParams, blockedRetries);
      continue;
    }

    return buildResult(targetUrl, attempts, `unknown verdict ${verdict}: stop`); // defensive: never loop forever
  }
}

module.exports = {
  OK,
  CHALLENGED,
  BLOCKED,
  NOT_PUBLIC,
  OXYLABS_NETWORK,
  FAILED,
  PARAMS,
  CHALLENGE_ESCALATION,
  ENGINE_ESCALATION,
  redact,
  endpointUrl,
  connectWithBackoff,
  blockHeavyResources,
  watchOxylabsErrors,
  watchPageStatus,
  waitForPageStatus,
  observePageStatus,
  clearPageStatus,
  getSessionId,
  runAttempt,
  freshIdentityParams,
  buildResult,
  collectTarget,
  _setConnector,
};

if (require.main === module) {
  const targetUrl = process.argv[2] || "https://example.com";
  collectTarget(targetUrl)
    .then((result) => console.log(JSON.stringify(result, null, 2)))
    .catch((err) => { console.error(redact(err.message)); process.exitCode = 1; });
}

// This content is not intended to provide legal advice, and scraping activities may be subject to applicable laws and regulations.
