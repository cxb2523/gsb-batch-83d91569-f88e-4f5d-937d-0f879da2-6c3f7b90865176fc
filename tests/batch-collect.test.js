import { test, beforeEach, afterEach } from "node:test";
import assert from "node:assert/strict";

import { request } from "../src/api.js";
import { createBatchCollector, describeCollectionError } from "../src/batch-collect.js";

/* --------------------------------------------------------------------------
   Local test doubles
   -------------------------------------------------------------------------- */

class MemoryStorage {
  #data = new Map();
  getItem(key) {
    return this.#data.has(key) ? this.#data.get(key) : null;
  }
  setItem(key, value) {
    this.#data.set(String(key), String(value));
  }
  removeItem(key) {
    this.#data.delete(key);
  }
  clear() {
    this.#data.clear();
  }
}

/** Deterministic, controllable clock. */
function fakeClock(start = 1_700_000_000_000) {
  let value = start;
  return {
    now: () => value,
    tick(ms = 1) {
      value += ms;
    },
  };
}

/**
 * Build profiles + a fetch router keyed by the request URL. Each entry is one
 * of:
 *   { ok: true, json }                         -> 200 JSON
 *   { ok: false, status }                      -> HTTP error
 *   { invalidJson: true }                      -> 200 but json() throws SyntaxError
 *   { throw: Error|DOMException }              -> network/timeout failure
 *   { pending: { resolve, reject, promise } }  -> manually controlled request
 */
function makeProfiles() {
  return [
    { id: "proxy-a", name: "Proxy A", apiUrl: "https://a.example:8080/", apiToken: "token-a" },
    { id: "proxy-b", name: "Proxy B", apiUrl: "https://b.example:9000/", apiToken: "token-b" },
    { id: "proxy-c", name: "Proxy C", apiUrl: "https://c.example:7000/", apiToken: "" },
  ];
}

function originOf(url) {
  return new URL(url).origin;
}

function installFetch(router) {
  const calls = [];
  globalThis.fetch = async (url, options) => {
    const origin = originOf(url);
    calls.push({ url, options, origin });
    const rule = router[origin];
    if (!rule) throw new TypeError(`Failed to fetch: no route for ${origin}`);
    if (rule.throw) throw rule.throw;
    if (rule.pending) return rule.pending.promise;
    if (rule.invalidJson) {
      return {
        ok: true,
        status: 200,
        async json() {
          throw new SyntaxError("Unexpected token <");
        },
      };
    }
    return {
      ok: rule.ok !== false,
      status: rule.status ?? 200,
      async json() {
        return rule.json;
      },
    };
  };
  return calls;
}

const originalFetch = globalThis.fetch;
const originalDebug = console.debug;
const originalError = console.error;

beforeEach(() => {
  globalThis.localStorage = new MemoryStorage();
  globalThis.sessionStorage = new MemoryStorage();
  console.debug = () => {};
  console.error = () => {};
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  console.debug = originalDebug;
  console.error = originalError;
});

/* --------------------------------------------------------------------------
   1. All profiles succeed
   -------------------------------------------------------------------------- */

test("batch collection: every profile succeeds and records one conclusion each", async () => {
  const profiles = makeProfiles();
  const calls = installFetch({
    "https://a.example:8080": { json: { miners: { now: 5 } } },
    "https://b.example:9000": { json: { miners: { now: 7 } } },
    "https://c.example:7000": { json: { miners: { now: 0 } } },
  });
  const clock = fakeClock();
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
    now: clock.now,
  });

  const batch = await collector.collectAll();

  assert.equal(batch.total, 3);
  assert.equal(batch.succeeded, 3);
  assert.equal(batch.failed, 0);
  assert.deepEqual(batch.results.map(r => r.profileId), ["proxy-a", "proxy-b", "proxy-c"]);
  assert.ok(batch.results.every(r => r.ok === true));
  assert.ok(batch.results.every(r => Number.isFinite(r.collectedAt)));
  assert.equal(collector.getLastBatch(), batch);

  // Exactly one GET per profile, addressed to its own origin, via api.request.
  assert.equal(calls.length, 3);
  const byOrigin = Object.fromEntries(calls.map(c => [c.origin, c]));
  assert.equal(byOrigin["https://a.example:8080"].url, "https://a.example:8080/1/summary");
  assert.equal(byOrigin["https://a.example:8080"].options.method, "GET");
  assert.equal(byOrigin["https://a.example:8080"].options.headers.get("Authorization"), "Bearer token-a");
  // A profile without a token sends no Authorization header.
  assert.equal(byOrigin["https://c.example:7000"].options.headers.get("Authorization"), null);
  // Same read-only/redirect guarantees as the normal client.
  assert.equal(byOrigin["https://b.example:9000"].options.redirect, "error");

  // Last-success store holds each summary with its timestamp.
  const successA = collector.getLastSuccess("proxy-a");
  assert.deepEqual(successA.summary, { miners: { now: 5 } });
  assert.equal(successA.collectedAt, batch.results[0].collectedAt);
  assert.equal(collector.getLastResult("proxy-b").ok, true);
});

/* --------------------------------------------------------------------------
   2. Partial failure: timeout / HTTP error / invalid JSON are isolated
   -------------------------------------------------------------------------- */

test("batch collection: one profile's failures never block the others", async () => {
  const profiles = makeProfiles();
  installFetch({
    "https://a.example:8080": { json: { miners: { now: 2 } } },
    "https://b.example:9000": { ok: false, status: 503 },
    "https://c.example:7000": { invalidJson: true },
  });
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
  });

  const batch = await collector.collectAll();

  assert.equal(batch.total, 3);
  assert.equal(batch.succeeded, 1);
  assert.equal(batch.failed, 2);

  const a = batch.results.find(r => r.profileId === "proxy-a");
  const b = batch.results.find(r => r.profileId === "proxy-b");
  const c = batch.results.find(r => r.profileId === "proxy-c");
  assert.equal(a.ok, true);

  assert.equal(b.ok, false);
  assert.match(b.reason, /HTTP 503/);
  assert.equal("summary" in b, false);

  assert.equal(c.ok, false);
  assert.match(c.reason, /JSON/);

  // A thrown timeout is normalised into a readable reason too.
  installFetch({
    "https://a.example:8080": { throw: new DOMException("The operation timed out", "TimeoutError") },
    "https://b.example:9000": { json: { miners: { now: 1 } } },
    "https://c.example:7000": { throw: new TypeError("Failed to fetch") },
  });
  const second = await collector.collectAll();
  const timeoutResult = second.results.find(r => r.profileId === "proxy-a");
  assert.equal(timeoutResult.ok, false);
  assert.match(timeoutResult.reason, /超时/);
  const networkResult = second.results.find(r => r.profileId === "proxy-c");
  assert.equal(networkResult.ok, false);
  assert.match(networkResult.reason, /无法连接/);
  // B still succeeds despite A and C failing.
  assert.equal(second.results.find(r => r.profileId === "proxy-b").ok, true);
});

/* --------------------------------------------------------------------------
   3. A failure must not overwrite the previous successful result
   -------------------------------------------------------------------------- */

test("batch collection: a failed attempt preserves the prior successful summary", async () => {
  const profiles = makeProfiles().slice(0, 2);
  installFetch({
    "https://a.example:8080": { json: { miners: { now: 9 } } },
    "https://b.example:9000": { json: { miners: { now: 1 } } },
  });
  const clock = fakeClock();
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
    now: clock.now,
  });

  const first = await collector.collectAll();
  const firstSuccessAt = first.results.find(r => r.profileId === "proxy-a").collectedAt;
  const firstSuccess = collector.getLastSuccess("proxy-a");
  assert.deepEqual(firstSuccess.summary, { miners: { now: 9 } });

  // Proxy A now fails (HTTP 401); Proxy B keeps working.
  clock.tick(5_000);
  installFetch({
    "https://a.example:8080": { ok: false, status: 401 },
    "https://b.example:9000": { json: { miners: { now: 3 } } },
  });
  const second = await collector.collectAll();

  const failedA = second.results.find(r => r.profileId === "proxy-a");
  assert.equal(failedA.ok, false);
  assert.match(failedA.reason, /HTTP 401/);
  assert.ok(failedA.collectedAt > firstSuccessAt, "the failure itself carries a fresh timestamp");

  // The latest conclusion is the failure, but last-success is untouched.
  assert.equal(collector.getLastResult("proxy-a").ok, false);
  const preserved = collector.getLastSuccess("proxy-a");
  assert.deepEqual(preserved.summary, { miners: { now: 9 } });
  assert.equal(preserved.collectedAt, firstSuccessAt, "old success timestamp must not move");

  // A later success updates the last-success store again.
  clock.tick(5_000);
  installFetch({
    "https://a.example:8080": { json: { miners: { now: 11 } } },
    "https://b.example:9000": { json: { miners: { now: 4 } } },
  });
  await collector.collectAll();
  const recovered = collector.getLastSuccess("proxy-a");
  assert.deepEqual(recovered.summary, { miners: { now: 11 } });
  assert.ok(recovered.collectedAt > firstSuccessAt);
  assert.equal(collector.getLastResult("proxy-a").ok, true);
});

/* --------------------------------------------------------------------------
   4. Re-triggering while a batch is in flight reuses it (no request stacking)
   -------------------------------------------------------------------------- */

test("batch collection: duplicate triggers reuse the in-flight batch", async () => {
  const profiles = makeProfiles();
  let releaseA;
  let releaseB;
  const pendingA = new Promise(resolve => { releaseA = resolve; });
  const pendingB = new Promise(resolve => { releaseB = resolve; });
  const calls = installFetch({
    "https://a.example:8080": { pending: { promise: pendingA } },
    "https://b.example:9000": { pending: { promise: pendingB } },
    "https://c.example:7000": { json: { miners: { now: 0 } } },
  });
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
  });

  const first = collector.collectAll();
  // Second and third triggers before the first settles must be the same promise.
  const second = collector.collectAll();
  const third = collector.collectAll();
  assert.equal(first, second);
  assert.equal(second, third);
  assert.equal(collector.isCollecting(), true);

  await Promise.resolve();
  // Only one request per profile was ever dispatched.
  assert.equal(calls.length, 3);

  releaseA({ ok: true, status: 200, json: async () => ({ miners: { now: 1 } }) });
  releaseB({ ok: true, status: 200, json: async () => ({ miners: { now: 2 } }) });

  const batch = await first;
  assert.equal(batch.succeeded, 3);
  assert.equal(calls.length, 3, "no duplicate requests after reuse");
  assert.equal(collector.isCollecting(), false);

  // After the batch settles, a fresh trigger starts a new batch.
  const next = collector.collectAll();
  assert.notEqual(next, first);
  await next;
  assert.equal(calls.length, 6);
});

/* --------------------------------------------------------------------------
   5. Cross-profile results never bleed into each other
   -------------------------------------------------------------------------- */

test("batch collection: conclusions stay keyed to their own profile", async () => {
  const profiles = makeProfiles();
  installFetch({
    "https://a.example:8080": { json: { miners: { now: 100 }, worker_id: "worker-a" } },
    "https://b.example:9000": { ok: false, status: 500 },
    "https://c.example:7000": { json: { miners: { now: 200 }, worker_id: "worker-c" } },
  });
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
  });
  await collector.collectAll();

  // Each profile id resolves only its own conclusion and summary.
  assert.deepEqual(collector.getLastSuccess("proxy-a").summary.worker_id, "worker-a");
  assert.deepEqual(collector.getLastSuccess("proxy-c").summary.worker_id, "worker-c");
  assert.equal(collector.getLastSuccess("proxy-b"), null, "failed profile has no success record");
  assert.equal(collector.getLastResult("proxy-b").ok, false);
  assert.equal(collector.getLastResult("proxy-a").profileId, "proxy-a");
  assert.equal(collector.getLastResult("proxy-c").profileId, "proxy-c");
  assert.equal(collector.getLastResult("unknown-id"), null);

  // Simulate the UI switching the active profile: the highlighted conclusion
  // for the new active id must be that profile's own record, never a
  // neighbour's summary.
  let activeId = "proxy-a";
  const renderForActive = () => collector.getLastResult(activeId);
  assert.equal(renderForActive().profileId, "proxy-a");
  activeId = "proxy-c";
  assert.deepEqual(renderForActive().summary.worker_id, "worker-c");
  activeId = "proxy-b";
  assert.equal(renderForActive().ok, false);
});

/* --------------------------------------------------------------------------
   6. Constraints: read-only / same-origin / token masking still hold
   -------------------------------------------------------------------------- */

test("batch collection: requests stay read-only, same-origin, and mask tokens", async () => {
  const profiles = makeProfiles().slice(0, 1);
  installFetch({ "https://a.example:8080": { json: {} } });
  const debugMessages = [];
  console.debug = message => debugMessages.push(message);

  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
  });
  await collector.collectAll();

  assert.equal(debugMessages.length, 1);
  assert.match(debugMessages[0], /Bearer \*{10}/);
  assert.doesNotMatch(debugMessages[0], /token-a/);
});

test("batch collection: an origin escape attempt fails closed without fetching", async () => {
  // A profile URL is validated at storage time; even so, api.request must
  // reject any path that leaves the configured origin.
  const profiles = [
    { id: "evil", name: "Evil", apiUrl: "https://a.example:8080/", apiToken: "t" },
  ];
  // Use a custom requestFn that passes an absolute external URL through the
  // real request wrapper to prove the guard is independent of the batch loop.
  const calls = [];
  globalThis.fetch = async () => {
    calls.push("fetched");
    return { ok: true, status: 200, json: async () => ({}) };
  };
  await assert.rejects(
    request("https://attacker.example/collect", {}, { apiUrl: "https://a.example:8080/", apiToken: "t" }),
    { message: "API request URL must stay on the configured proxy origin" },
  );
  assert.equal(calls.length, 0);

  // And the collector itself tolerates a profile whose request throws: it is
  // recorded as a failure rather than rejecting the whole batch.
  const collector = createBatchCollector({
    requestFn: () => Promise.reject(new Error("API configuration missing")),
    getProfiles: () => profiles,
  });
  const batch = await collector.collectAll();
  assert.equal(batch.failed, 1);
  assert.equal(batch.results[0].ok, false);
  assert.match(batch.results[0].reason, /API 地址/);
});

/* --------------------------------------------------------------------------
   7. Error description helper and edge cases
   -------------------------------------------------------------------------- */

test("describeCollectionError maps every failure shape to readable text", () => {
  assert.match(describeCollectionError({ name: "TimeoutError" }), /超时/);
  assert.match(describeCollectionError({ name: "AbortError" }), /取消/);
  assert.match(describeCollectionError({ status: 404 }), /HTTP 404/);
  assert.match(
    describeCollectionError(new Error("Invalid JSON response from Proxy API")),
    /JSON/,
  );
  assert.match(describeCollectionError(new TypeError("Failed to fetch")), /无法连接/);
  assert.match(describeCollectionError(new Error("boom")), /boom/);
  assert.match(describeCollectionError(null), /未知错误/);
});

test("batch collection: empty profile list finishes as an empty batch", async () => {
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => [],
  });
  const batch = await collector.collectAll();
  assert.equal(batch.total, 0);
  assert.equal(batch.succeeded, 0);
  assert.equal(batch.failed, 0);
  assert.deepEqual(batch.results, []);
  assert.equal(collector.isCollecting(), false);
});

test("batch collector reset clears retained conclusions", async () => {
  const profiles = makeProfiles().slice(0, 1);
  installFetch({ "https://a.example:8080": { json: { miners: { now: 1 } } } });
  const collector = createBatchCollector({
    requestFn: request,
    getProfiles: () => profiles,
  });
  await collector.collectAll();
  assert.ok(collector.getLastResult("proxy-a"));
  collector.reset();
  assert.equal(collector.getLastResult("proxy-a"), null);
  assert.equal(collector.getLastSuccess("proxy-a"), null);
  assert.equal(collector.getLastBatch(), null);
  assert.equal(collector.isCollecting(), false);
});
