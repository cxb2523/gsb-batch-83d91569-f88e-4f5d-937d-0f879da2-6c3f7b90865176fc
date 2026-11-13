// Offline tests for the long-run / resume chain.
//
// No real network and no real APIFY_TOKEN: every test drives handleToolCall()
// with a fake fetch that records requests and serves canned Apify responses.
// Run: npm test   (node --test)
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  collectRun,
  handleToolCall,
  normalizeRunId,
  normalizeWaitSecs,
  WAIT_SECS,
  MAX_WAIT_SECS,
} from "../lib.js";

const TOKEN_ENV = { APIFY_TOKEN: "test-token-not-real" };
const ACTOR = { slug: "poland-kyb-check", tool: "regdata_poland_kyb_check", title: "Poland KYB" };

// A scripted stand-in for api.apify.com. Counts every request so tests can
// prove a resume never starts a second actor run.
function fakeApify({ runs = [] } = {}) {
  const calls = [];
  const state = { runs: new Map(Object.entries(runs)), datasetItems: new Map() };
  const jsonResponse = (data) => ({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ data }),
    json: async () => ({ data }),
  });

  const fetchImpl = async (input, init) => {
    const url = new URL(String(input));
    const method = init?.method || "GET";
    calls.push({ method, path: url.pathname, search: Object.fromEntries(url.searchParams), body: init?.body });

    // POST /acts/regdata~<slug>/runs  -> start a run
    const start = url.pathname.match(/^\/v2\/acts\/regdata~([a-z0-9-]+)\/runs$/);
    if (start && method === "POST") {
      state.starts = (state.starts || 0) + 1;
      state.lastInput = JSON.parse(init.body || "{}");
      const run = state.runs.get(url.pathname) ?? state.nextRun;
      return jsonResponse(run);
    }

    // GET /actor-runs/<id> -> poll
    const poll = url.pathname.match(/^\/v2\/actor-runs\/([A-Za-z0-9]+)$/);
    if (poll) {
      state.polls = (state.polls || 0) + 1;
      state.pollsBy = state.pollsBy || {};
      state.pollsBy[poll[1]] = (state.pollsBy[poll[1]] || 0) + 1;
      return jsonResponse(state.pollScript.shift());
    }

    // GET /datasets/<id>/items -> results
    const items = url.pathname.match(/^\/v2\/datasets\/([A-Za-z0-9_-]+)\/items$/);
    if (items) {
      state.datasetReads = (state.datasetReads || 0) + 1;
      const body = state.datasetItems.get(items[1]) ?? [{ company: "ACME", nik: "123" }];
      return { ok: true, status: 200, text: async () => JSON.stringify(body) };
    }

    throw new Error(`fakeApify: unscripted ${method} ${url.pathname}`);
  };

  return {
    fetchImpl,
    calls,
    state,
    // Script one run: statuses is the sequence returned by each poll; `final`
    // is the run object returned by the actor-start POST.
    scriptRun({ runId = "RunAbc12345678901", statuses = ["RUNNING"], final }) {
      state.nextRun = {
        id: runId,
        status: statuses[0],
        defaultDatasetId: "ds_" + runId,
        ...(final || {}),
      };
      state.pollScript = statuses.map((status, i) => ({
        id: runId,
        status,
        defaultDatasetId: "ds_" + runId,
        actId: "regdata~poland-kyb-check",
        ...(i === statuses.length - 1 ? final || {} : {}),
      }));
      state.runs.set(`/v2/acts/regdata~${ACTOR.slug}/runs`, state.nextRun);
      state.datasetItems.set("ds_" + runId, [{ company: "ACME" }]);
      return runId;
    },
  };
}

const callTool = (fake, name, args) =>
  handleToolCall(name, args, { fetchImpl: fake.fetchImpl, env: TOKEN_ENV, actors: [ACTOR] });

const payloadOf = (res) => JSON.parse(res.content[0].text);

// --- requirement 1: every pending result carries runId + status + blunt note ---
test("actor tool returns pending handle with runId, status and do-not-rerun note", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING"] });

  const res = await callTool(fake, ACTOR.tool, { identifiers: ["6770065406"] });

  assert.equal(res.isError, undefined);
  const payload = payloadOf(res);
  assert.equal(payload.runId, runId);
  assert.equal(payload.status, "RUNNING");
  assert.ok(payload.note.includes(runId), "note must carry the concrete runId");
  assert.match(payload.note, /do NOT re-run/i);
  assert.match(payload.note, /regdata_run_result/i);
  assert.equal(fake.state.starts, 1, "exactly one run started");
});

// --- requirement 2: run_result still pending -> same shape, not an error ---
test("run_result while still running returns the pending handle and keeps the runId", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING", "RUNNING"] });

  // First call (post) hands back a handle, as if the client timed out.
  const pending = payloadOf(await callTool(fake, ACTOR.tool, { identifiers: ["6770065406"] }));

  // Now Apify still says RUNNING on the poll.
  const res = await callTool(fake, "regdata_run_result", { runId, waitSecs: 10 });

  assert.equal(res.isError, undefined, "still-pending must not be reported as an error");
  const payload = payloadOf(res);
  assert.deepEqual(
    { status: payload.status, runId: payload.runId, datasetId: payload.datasetId },
    { status: "RUNNING", runId: pending.runId, datasetId: pending.datasetId }
  );
  assert.match(payload.note, /do NOT re-run/i);
  assert.equal(fake.state.starts, 1, "resume did not start another actor run");
  assert.equal(fake.state.polls, 1);
});

test("repeated run_result polling never starts a second actor run", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING", "RUNNING", "RUNNING", "SUCCEEDED"] });

  await callTool(fake, ACTOR.tool, { identifiers: ["6770065406"] });
  for (let i = 0; i < 3; i++) {
    const res = await callTool(fake, "regdata_run_result", { runId, waitSecs: 5 });
    assert.equal(res.isError, undefined);
    const payload = payloadOf(res);
    assert.equal(payload.runId, runId);
    assert.equal(payload.status, "RUNNING");
  }

  const done = await callTool(fake, "regdata_run_result", { runId, waitSecs: 5 });
  assert.equal(done.isError, undefined);
  assert.deepEqual(JSON.parse(done.content[0].text), [{ company: "ACME" }]);
  assert.equal(fake.state.starts, 1, "only the original POST started a run");
  assert.equal(fake.state.polls, 4);
});

// --- success and failure states ---
test("run that finishes inside the wait returns dataset items", async () => {
  const fake = fakeApify();
  fake.scriptRun({ statuses: ["SUCCEEDED"], final: { defaultDatasetId: "ds_done" }, runId: "RunDone123456789" });
  fake.state.datasetItems.set("ds_done", [{ company: "ACME", status: "clear" }]);

  const res = await callTool(fake, ACTOR.tool, { identifiers: ["6770065406"] });
  assert.equal(res.isError, undefined);
  assert.deepEqual(JSON.parse(res.content[0].text), [{ company: "ACME", status: "clear" }]);
});

test("failed run is a readable error and points at the runId, not a re-run", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ runId: "RunFail123456789", statuses: ["FAILED"], final: { statusMessage: "actor crashed" } });

  const res = await callTool(fake, "regdata_run_result", { runId, waitSecs: 10 });
  assert.equal(res.isError, true);
  const msg = res.content[0].text;
  assert.match(msg, /RunFail123456789/);
  assert.match(msg, /FAILED/);
  assert.match(msg, /actor crashed/);
  assert.match(msg, /do not call regdata_run_result/i);
  assert.equal(fake.state.starts ?? 0, 0, "run_result must never start a run");
});

test("actor start failure surfaces as an error without inventing a runId", async () => {
  const fake = fakeApify();
  fake.scriptRun({ statuses: ["TIMED-OUT"], final: { statusMessage: "timeout" } });
  const res = await callTool(fake, ACTOR.tool, { identifiers: ["6770065406"] });
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /TIMED-OUT/);
});

// --- requirement 3: bad runId -> readable error, zero network calls ---
test("missing runId returns a readable error and makes no network request", async () => {
  const fake = fakeApify();
  const res = await callTool(fake, "regdata_run_result", {});
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /runId is required/);
  assert.match(res.content[0].text, /No network request was made/);
  assert.match(res.content[0].text, /Do NOT re-run/i);
  assert.equal(fake.calls.length, 0);
});

test("malformed runIds are rejected before any fetch", async () => {
  const bad = ["", "   ", "https://api.apify.com/v2/actor-runs/abc", "abc/def", "../etc/passwd", "run id with space", "x", null, 42];
  for (const runId of bad) {
    const fake = fakeApify();
    const res = await callTool(fake, "regdata_run_result", { runId });
    assert.equal(res.isError, true, `runId ${JSON.stringify(runId)} should be rejected`);
    assert.match(res.content[0].text, /Invalid runId|runId is required/i);
    assert.match(res.content[0].text, /No network request was made/i);
    assert.equal(fake.calls.length, 0, `runId ${JSON.stringify(runId)} must not hit the network`);
  }
});

test("normalizeRunId accepts a real-shaped id and trims whitespace", () => {
  assert.deepEqual(normalizeRunId(" NAMNqpPch7RFSY1oQ "), { ok: true, runId: "NAMNqpPch7RFSY1oQ" });
});

// --- requirement 4: waitSecs clamp ---
test("normalizeWaitSecs clamps above 60 to 60 and negatives to 0", () => {
  assert.equal(normalizeWaitSecs(120), MAX_WAIT_SECS);
  assert.equal(normalizeWaitSecs(61), MAX_WAIT_SECS);
  assert.equal(normalizeWaitSecs(60), 60);
  assert.equal(normalizeWaitSecs(-5), 0);
  assert.equal(normalizeWaitSecs(-0.5), 0);
  assert.equal(normalizeWaitSecs(0), 0);
  assert.equal(normalizeWaitSecs(undefined), WAIT_SECS);
  assert.equal(normalizeWaitSecs(null), WAIT_SECS);
  assert.equal(normalizeWaitSecs("15"), 15);
  assert.equal(normalizeWaitSecs(Number.NaN), WAIT_SECS);
});

test("run_result sends the clamped waitForFinish to Apify", async () => {
  const checks = [
    { waitSecs: 120, expected: "60" },
    { waitSecs: -10, expected: "0" },
    { waitSecs: 0, expected: "0" },
    { waitSecs: 30, expected: "30" },
  ];
  for (const { waitSecs, expected } of checks) {
    const fake = fakeApify();
    const runId = fake.scriptRun({ statuses: ["RUNNING"] });
    await callTool(fake, "regdata_run_result", { runId, waitSecs });
    const poll = fake.calls.find((c) => c.path.startsWith("/v2/actor-runs/"));
    assert.ok(poll, "a poll must have happened");
    assert.equal(poll.search.waitForFinish, expected, `waitSecs ${waitSecs}`);
    assert.equal(fake.state.starts ?? 0, 0);
  }
});

test("missing waitSecs defaults to the server's short wait", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING"] });
  await callTool(fake, "regdata_run_result", { runId });
  const poll = fake.calls.find((c) => c.path.startsWith("/v2/actor-runs/"));
  assert.equal(poll.search.waitForFinish, String(WAIT_SECS));
});

// --- token handling stays explicit ---
test("a missing token is a readable error, not a network call", async () => {
  const fake = fakeApify();
  const res = await handleToolCall("regdata_run_result", { runId: "RunAbc12345678901" }, { fetchImpl: fake.fetchImpl, env: {}, actors: [ACTOR] });
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /APIFY_TOKEN is not set/);
  assert.equal(fake.calls.length, 0);
});

test("collectRun is reusable directly and keeps the caller's runId", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING"] });
  const out = await collectRun(runId, { waitSecs: 3 }, { fetchImpl: fake.fetchImpl, env: TOKEN_ENV });
  assert.equal(JSON.parse(out).runId, runId);
});

test("a transport failure while resuming keeps the runId and forbids a re-run", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING"] });
  const failing = async () => {
    throw new Error("fetch failed");
  };
  const res = await handleToolCall(
    "regdata_run_result",
    { runId, waitSecs: 5 },
    { fetchImpl: failing, env: TOKEN_ENV, actors: [ACTOR] }
  );
  assert.equal(res.isError, true);
  const msg = res.content[0].text;
  assert.match(msg, new RegExp(runId));
  assert.match(msg, /call regdata_run_result again/i);
  assert.match(msg, /do not re-run/i);
  assert.match(msg, /NOT started again/);
});

test("pending run_result does not touch the dataset endpoint", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["RUNNING"] });
  await callTool(fake, "regdata_run_result", { runId, waitSecs: 5 });
  assert.equal(fake.state.datasetReads ?? 0, 0);
});

test("ambiguous start failure warns about a possible billable run instead of inviting a retry", async () => {
  const failing = async () => {
    throw new Error("fetch failed");
  };
  const res = await handleToolCall(ACTOR.tool, { identifiers: ["6770065406"] }, { fetchImpl: failing, env: TOKEN_ENV, actors: [ACTOR] });
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /may nonetheless have started/);
  assert.match(res.content[0].text, /second charge/);
});

test("an HTTP error from Apify on start is passed through as-is", async () => {
  const fake = fakeApify();
  const res = await handleToolCall(
    ACTOR.tool,
    { identifiers: ["6770065406"] },
    {
      fetchImpl: async (input, init) => {
        const url = new URL(String(input));
        if (url.pathname.endsWith("/runs")) {
          return { ok: false, status: 401, text: async () => "invalid token" };
        }
        return fake.fetchImpl(input, init);
      },
      env: TOKEN_ENV,
      actors: [ACTOR],
    }
  );
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /Apify API 401/);
});

test("an HTTP error while resuming is passed through and keeps the runId", async () => {
  const res = await handleToolCall(
    "regdata_run_result",
    { runId: "RunAbc12345678901", waitSecs: 5 },
    {
      fetchImpl: async () => ({ ok: false, status: 404, text: async () => "run not found" }),
      env: TOKEN_ENV,
      actors: [ACTOR],
    }
  );
  assert.equal(res.isError, true);
  assert.match(res.content[0].text, /Apify API 404/);
});

test("a finished run whose dataset cannot be read tells the caller to retry the read, not the run", async () => {
  const fake = fakeApify();
  const runId = fake.scriptRun({ statuses: ["SUCCEEDED"] });
  const res = await handleToolCall(
    "regdata_run_result",
    { runId, waitSecs: 5 },
    {
      fetchImpl: async (input, init) => {
        const url = new URL(String(input));
        if (url.pathname.includes("/datasets/")) {
          return { ok: false, status: 500, text: async () => "boom" };
        }
        return fake.fetchImpl(input, init);
      },
      env: TOKEN_ENV,
      actors: [ACTOR],
    }
  );
  assert.equal(res.isError, true);
  const msg = res.content[0].text;
  assert.match(msg, /is billed/);
  assert.match(msg, /same runId/i);
  assert.match(msg, /do NOT re-run/i);
});
