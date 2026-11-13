// Acceptance checks for the OpenF1 fetch provenance attached to every tool result.
// A stub `fetch` and a temp cache dir (OPENF1_CACHE_DIR) stand in for OpenF1, so no network
// or real cache is touched. Run: npm run test:f1-status

import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const cacheDir = await mkdtemp(join(tmpdir(), "openf1-status-"));
process.env.OPENF1_CACHE_DIR = cacheDir;
process.env.OPENF1_BACKOFF_MS = "20"; // keep retry backoff instant
process.env.OPENF1_PER_MINUTE = "1000"; // the per-minute window must not slow the test

// Imported only after the env above is set: the client reads it at module load.
const { openf1, withFetchLog, summarizeFetches } = await import("../src/lib/f1/openf1");
const { runF1Tool } = await import("../src/lib/f1/tools");
const { POST } = await import("../src/app/api/f1/[tool]/route");

type Handler = (url: string) => Response | Promise<Response>;
let handler: Handler = () => {
  throw new Error("no handler set");
};
let fetchCalls: string[] = [];
globalThis.fetch = (async (input: RequestInfo | URL) => {
  const url = String(input);
  fetchCalls.push(url);
  return handler(url);
}) as typeof fetch;

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), { status, headers: { "content-type": "application/json" } });

let failures = 0;
function check(name: string, condition: boolean, detail?: unknown) {
  if (condition) {
    console.log(`PASS ${name}`);
  } else {
    failures++;
    console.error(`FAIL ${name}`, detail ?? "");
  }
}

try {
  // ── 1. A fresh cache hit serves without any network request ──────────────
  handler = () => json([{ lap: 1 }]);
  const first = await withFetchLog([], () => openf1("laps", { session_key: 9001 }, { final: true }));
  check("seed fetch returns data", first.length === 1);
  fetchCalls = [];
  const log1: import("../src/lib/f1/openf1").FetchRecord[] = [];
  const second = await withFetchLog(log1, () => openf1("laps", { session_key: 9001 }, { final: true }));
  check("fresh cache: no network request", fetchCalls.length === 0, fetchCalls);
  check("fresh cache: data served", second.length === 1);
  check("fresh cache: state is cache", log1[0]?.state === "cache", log1);
  check("fresh cache: summary is cache", summarizeFetches(log1).state === "cache");

  // ── 2. A 404 is an empty result, not an error ────────────────────────────
  handler = () => new Response("No results found", { status: 404 });
  const log2: import("../src/lib/f1/openf1").FetchRecord[] = [];
  const empty = await withFetchLog(log2, () => openf1("pit", { session_key: 9002 }));
  check("404: resolves to an empty list", Array.isArray(empty) && empty.length === 0);
  check("404: state is empty", log2[0]?.state === "empty", log2);
  check("404: summary is empty", summarizeFetches(log2).state === "empty");

  // ── 3. Persistent 429 with no cache fails, with the reason ───────────────
  handler = () => new Response("slow down", { status: 429 });
  const log3: import("../src/lib/f1/openf1").FetchRecord[] = [];
  let error3: unknown;
  try {
    await withFetchLog(log3, () => openf1("stints", { session_key: 9003 }));
  } catch (e) {
    error3 = e;
  }
  const failed3 = log3.find((r) => r.state === "failed");
  check("429: rejects", error3 instanceof Error, error3);
  check("429: state is failed", !!failed3, log3);
  check("429: reason names the cause", !!failed3?.reason && /429/.test(failed3.reason), failed3);
  const summary3 = summarizeFetches(log3);
  check("429: summary is failed with reason", summary3.state === "failed" && /429/.test(summary3.reason ?? ""), summary3);

  // ── 4. A network failure with an old copy falls back to it, marked stale ──
  handler = () => json([{ temp: 31 }]);
  await openf1("weather", { session_key: 9004 }, { ttl: 0 }); // cached, but immediately stale
  handler = () => {
    throw new Error("connection reset");
  };
  const log4: import("../src/lib/f1/openf1").FetchRecord[] = [];
  const stale = await withFetchLog(log4, () => openf1("weather", { session_key: 9004 }, { ttl: 0 }));
  const staleRecord = log4.find((r) => r.state === "stale");
  check("stale: old copy is served", (stale as { temp: number }[])[0]?.temp === 31, stale);
  check("stale: state is stale", !!staleRecord, log4);
  check("stale: marked as possibly outdated", staleRecord?.stale === true && typeof staleRecord.fetchedAt === "number", staleRecord);
  const summary4 = summarizeFetches(log4);
  check("stale: summary is stale and flagged", summary4.state === "stale" && summary4.stale === true, summary4);

  // ── 5. Concurrent requests for one URL trigger one network request ────────
  handler = async () => {
    await new Promise((r) => setTimeout(r, 50));
    return json([{ pos: 1 }]);
  };
  fetchCalls = [];
  const [a, b] = await Promise.all([
    openf1("position", { session_key: 9005 }),
    openf1("position", { session_key: 9005 }),
  ]);
  const positionCalls = fetchCalls.filter((u) => u.includes("/position"));
  check("concurrent: one network request", positionCalls.length === 1, positionCalls);
  check("concurrent: both callers get the data", a.length === 1 && b.length === 1);

  // ── 6. Tool results carry the source status ──────────────────────────────
  handler = (url) => {
    if (url.includes("/meetings"))
      return json([
        {
          meeting_key: 1, meeting_name: "Sample Grand Prix", location: "Sampleville",
          country_name: "Sampleland", country_code: "TT", circuit_short_name: "Sample Circuit",
          date_start: "2026-03-01T00:00:00", date_end: "2026-03-03T00:00:00", year: 2026,
        },
      ]);
    if (url.includes("/sessions"))
      return json([
        {
          session_key: 9100, session_name: "Race", session_type: "Race",
          date_start: "2026-03-03T13:00:00", date_end: "2026-03-03T15:00:00",
          meeting_key: 1, circuit_short_name: "Sample Circuit",
          country_name: "Sampleland", country_code: "TT", location: "Sampleville", year: 2026,
        },
      ]);
    throw new Error(`unexpected fetch: ${url}`);
  };
  const toolResult = await runF1Tool("get_schedule", {});
  check("tool: rows returned", toolResult.rows.length === 1, toolResult.rows);
  check("tool: source attached and fetched", toolResult.source?.state === "fetched", toolResult.source);
  const toolAgain = await runF1Tool("get_schedule", {});
  check("tool: second run is served from cache", toolAgain.source?.state === "cache", toolAgain.source);

  // ── 7. The API route returns the status, in success and in failure ────────
  const okResponse = await POST(
    new Request("http://localhost/api/f1/get_schedule", {
      method: "POST",
      headers: { origin: "http://localhost", host: "localhost", "content-type": "application/json" },
      body: "{}",
    }),
    { params: Promise.resolve({ tool: "get_schedule" }) },
  );
  const okBody = await okResponse.json();
  check("route: 200 with source status", okResponse.status === 200 && okBody.source?.state === "cache", okBody.source);

  handler = () => {
    throw new Error("openf1 is down");
  };
  const failResponse = await POST(
    new Request("http://localhost/api/f1/get_schedule", {
      method: "POST",
      headers: { origin: "http://localhost", host: "localhost", "content-type": "application/json" },
      body: '{"year": 2024}',
    }),
    { params: Promise.resolve({ tool: "get_schedule" }) },
  );
  const failBody = await failResponse.json();
  check("route: failure is a 502", failResponse.status === 502, failResponse.status);
  check(
    "route: failure carries source.state=failed with reason",
    failBody.source?.state === "failed" && typeof failBody.source?.reason === "string" && typeof failBody.error === "string",
    failBody,
  );
} finally {
  await rm(cacheDir, { recursive: true, force: true });
}

if (failures) {
  console.error(`\n${failures} check(s) failed.`);
  process.exit(1);
}
console.log("\nAll checks passed.");
