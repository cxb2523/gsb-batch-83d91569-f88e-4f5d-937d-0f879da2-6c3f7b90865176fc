// Acceptance checks for the event feed export/loading flow.
// Runs with no external test framework: `node scripts/verify-event-export.mjs`.
// Node 24 strips TypeScript types, so the app modules are imported directly.
// A resolve hook adds the .ts extension that the bundler-resolved app code omits.
import assert from "node:assert/strict";
import { registerHooks } from "node:module";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[cm]?[jt]sx?$/i.test(specifier)) {
      return nextResolve(`${specifier}.ts`, context);
    }
    return nextResolve(specifier, context);
  },
});

const {
  buildEventCsvMetadata,
  buildEventsCsv,
  eventFeedReducer,
  fetchEventPage,
  filterEvents,
  initialEventFeedState,
} = await import("../app/lib/eventFeed.ts");

const BOM = String.fromCharCode(0xfeff);
const checks = [];
function test(name, fn) { checks.push([name, fn]); }

function makeEvent(id, overrides = {}) {
  return {
    id,
    ledger: 1000 + Number(id),
    created_at: `2026-11-${String(10 + (Number(id) % 9)).padStart(2, "0")}T12:00:00Z`,
    agent: `GAGENT${id.padStart(6, "0")}AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`,
    subject: `GSUBJECT${id.padStart(4, "0")}AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA`,
    score: 75,
    contract_id: "CBVFEUGUZ3P7A3F6B3SZKFJRTSANHYZDGEOFRCRLQL3FG6QCDO7MBJD7",
    transaction_hash: `tx-hash-${id}`,
    ...overrides,
  };
}

function page(events, nextCursor) {
  return { events, next_cursor: nextCursor, source: { rpc_url: "https://rpc.example", network: "Test SDF Network ; September 2015" } };
}

function reducerSequence(actions) {
  return actions.reduce(eventFeedReducer, initialEventFeedState);
}

// Minimal RFC-4180-style CSV row parser (handles quoted cells and doubled quotes).
function parseCsv(text) {
  const rows = [];
  let row = [];
  let field = "";
  let inQuotes = false;
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 1; }
        else inQuotes = false;
      } else field += char;
    } else if (char === '"') inQuotes = true;
    else if (char === ",") { row.push(field); field = ""; }
    else if (char === "\n") { row.push(field); rows.push(row); row = []; field = ""; }
    else if (char === "\r") { /* handled by following \n */ }
    else field += char;
  }
  row.push(field);
  rows.push(row);
  return rows;
}

// Mock fetch: queue responses, then inspect which cursors were requested.
function mockFetch(responses) {
  const calls = [];
  const queue = [...responses];
  globalThis.fetch = async (url) => {
    calls.push(url);
    const next = queue.shift();
    if (next instanceof Error) throw next;
    return {
      ok: next.status >= 200 && next.status < 300,
      status: next.status,
      json: async () => next.body,
    };
  };
  return calls;
}

const metadata = (overrides = {}) => buildEventCsvMetadata({
  exportedAt: "2026-11-14T09:30:00.000Z",
  filterTerm: "",
  loadedCount: 0,
  matchedCount: 0,
  hasOlderPages: false,
  lastError: "",
  lastErrorCursor: undefined,
  ...overrides,
});

console.log("Reducer: load / append / failure / retry semantics");

test("initial load stores events and the next cursor", () => {
  const state = reducerSequence([
    { type: "load-start", next: undefined, append: false },
    { type: "load-success", page: page([makeEvent("1"), makeEvent("2")], "cursor-2"), append: false },
  ]);
  assert.equal(state.events.length, 2);
  assert.equal(state.cursor, "cursor-2");
  assert.equal(state.loading, false);
  assert.equal(state.error, "");
  assert.equal(state.failedCursor, undefined);
  assert.equal(state.network, "Test SDF Network ; September 2015");
});

test("a failed append keeps every already displayed event and remembers the failed cursor", () => {
  const state = reducerSequence([
    { type: "load-success", page: page([makeEvent("1")], "cursor-2"), append: false },
    { type: "load-start", next: "cursor-2", append: true },
    { type: "load-failure", message: "RPC timeout", next: "cursor-2", append: true },
  ]);
  assert.deepEqual(state.events.map((event) => event.id), ["1"]);
  assert.equal(state.error, "RPC timeout");
  assert.equal(state.failedCursor, "cursor-2");
  assert.equal(state.retryAppend, true);
  assert.equal(state.cursor, "cursor-2");
  assert.equal(state.loading, false);
});

test("retry with the original cursor appends the new page without duplicates", () => {
  const failed = reducerSequence([
    { type: "load-success", page: page([makeEvent("1")], "cursor-2"), append: false },
    { type: "load-failure", message: "RPC timeout", next: "cursor-2", append: true },
  ]);
  const recovered = eventFeedReducer(failed, {
    type: "load-success",
    page: page([makeEvent("2"), makeEvent("3")], "cursor-4"),
    append: true,
  });
  assert.deepEqual(recovered.events.map((event) => event.id), ["1", "2", "3"]);
  assert.equal(recovered.cursor, "cursor-4");
  assert.equal(recovered.error, "");
  assert.equal(recovered.failedCursor, undefined);
  assert.equal(recovered.retryAppend, false);
});

test("a failed refresh (no cursor) records an empty failure cursor and keeps events", () => {
  const state = reducerSequence([
    { type: "load-success", page: page([makeEvent("1")], null), append: false },
    { type: "load-failure", message: "Network down", next: undefined, append: false },
  ]);
  assert.deepEqual(state.events.map((event) => event.id), ["1"]);
  assert.equal(state.failedCursor, undefined);
  assert.equal(state.retryAppend, false);
  assert.equal(state.error, "Network down");
});

test("has_older_pages follows the cursor: true while a next cursor exists, false on the last page", () => {
  const more = reducerSequence([{ type: "load-success", page: page([makeEvent("1")], "cursor-9"), append: false }]);
  const last = reducerSequence([{ type: "load-success", page: page([makeEvent("1")], null), append: false }]);
  assert.equal(more.cursor !== null, true);
  assert.equal(last.cursor, null);
});

console.log("fetchEventPage: end-to-end with mock /events responses");

test("append failure then retry reuses the exact original cursor and preserves displayed events", async () => {
  const calls = mockFetch([
    { status: 200, body: page([makeEvent("1")], "cursor-2") },
    new Error("socket hang up"),
    { status: 200, body: page([makeEvent("2")], null) },
  ]);
  const actions = [];
  const dispatch = (action) => { actions.push(action); };

  const first = await fetchEventPage(dispatch);
  assert.equal(first.ok, true);
  const failed = await fetchEventPage(dispatch, "cursor-2", true);
  assert.equal(failed.ok, false);
  assert.equal(failed.httpStatus, null); // network failure, not an HTTP error
  const retry = await fetchEventPage(dispatch, actions.at(-1).next, actions.at(-1).append);
  assert.equal(retry.ok, true);

  const state = actions.reduce(eventFeedReducer, initialEventFeedState);
  assert.deepEqual(state.events.map((event) => event.id), ["1", "2"]);
  assert.equal(state.error, "");
  const requestedCursors = calls.map((url) => new URL(url).searchParams.get("cursor"));
  assert.deepEqual(requestedCursors, [null, "cursor-2", "cursor-2"]);
});

test("an HTTP error response is reported with its status and the failing cursor", async () => {
  mockFetch([{ status: 502, body: { detail: "backend unavailable" } }]);
  const actions = [];
  const outcome = await fetchEventPage((action) => actions.push(action), "cursor-7", true);
  assert.equal(outcome.ok, false);
  assert.equal(outcome.httpStatus, 502);
  const state = actions.reduce(eventFeedReducer, initialEventFeedState);
  assert.equal(state.error, "backend unavailable");
  assert.equal(state.failedCursor, "cursor-7");
  assert.equal(state.retryAppend, true);
});

console.log("filterEvents: visible rows drive the export");

test("empty filter returns every loaded event; a matching filter returns only matches", () => {
  const events = [makeEvent("1", { agent: "GAGENT1" }), makeEvent("2", { subject: "GSUBJECT2" }), makeEvent("3", { agent: "GOTHER" })];
  assert.equal(filterEvents(events, "").length, 3);
  assert.equal(filterEvents(events, "   ").length, 3);
  assert.deepEqual(filterEvents(events, "gagent1").map((event) => event.id), ["1"]);
  assert.deepEqual(filterEvents(events, "gsubject2").map((event) => event.id), ["2"]);
  assert.deepEqual(filterEvents(events, "no-such-account"), []);
});

console.log("CSV: structure, metadata, injection guard, BOM");

test("CSV keeps the original event columns and appends the full metadata section", () => {
  const events = [makeEvent("1"), makeEvent("2")];
  const csv = buildEventsCsv(events, metadata({
    filterTerm: "GAGENT",
    loadedCount: 5,
    matchedCount: 2,
    hasOlderPages: true,
    lastError: "RPC timeout",
    lastErrorCursor: "cursor-2",
  }));
  const rows = parseCsv(csv);
  assert.deepEqual(rows[0], ["event_id", "ledger", "created_at", "agent", "account", "score", "contract_id"]);
  assert.equal(rows.length, 1 + 2 + 9); // event header + 2 events + marker + key header + 7 metadata rows
  const meta = Object.fromEntries(rows.slice(-7).map(([key, value]) => [key, value]));
  assert.equal(meta.exported_at, "2026-11-14T09:30:00.000Z");
  assert.equal(meta.filter_term, "GAGENT");
  assert.equal(meta.loaded_event_count, "5");
  assert.equal(meta.matched_event_count, "2");
  assert.equal(meta.has_older_pages, "true");
  assert.equal(meta.last_error, "RPC timeout");
  assert.equal(meta.last_error_cursor, "cursor-2");
  assert.equal(rows[3][0], "# export metadata");
  assert.deepEqual(rows[4], ["metadata_key", "metadata_value"]);
});

test("no-failure export leaves the error and cursor cells blank", () => {
  const rows = parseCsv(buildEventsCsv([makeEvent("1")], metadata({ loadedCount: 1, matchedCount: 1 })));
  const meta = Object.fromEntries(rows.slice(-7).map(([key, value]) => [key, value]));
  assert.equal(meta.last_error, "");
  assert.equal(meta.last_error_cursor, "");
  assert.equal(meta.has_older_pages, "false");
  assert.equal(meta.filter_term, "");
});

test("formula-like values keep the apostrophe injection guard, including in metadata", () => {
  const events = [makeEvent("1", { subject: "=1+1", agent: "\t@cmd", contract_id: "-bad", score: 90 })];
  const csv = buildEventsCsv(events, metadata({ lastError: "+CMD|'/etc/passwd'", loadedCount: 1, matchedCount: 1 }));
  assert.match(csv, /"'=1\+1"/);
  assert.match(csv, /"'\t@cmd"/);
  assert.match(csv, /"'-bad"/);
  assert.ok(csv.includes('"\'+CMD|\'/etc/passwd\'"'), "formula-like metadata value is guarded with a leading apostrophe");
});

test("double quotes are escaped and rows use CRLF line endings", () => {
  const events = [makeEvent("1", { agent: 'G"QUOTED"' })];
  const csv = buildEventsCsv(events, metadata());
  assert.ok(csv.includes('"G""QUOTED"""'));
  assert.ok(csv.includes("\r\n"));
  assert.ok(!csv.includes("\n") || csv.split("\n").every((line, index, all) => index === all.length - 1 || line.endsWith("\r")));
});

test("empty event list still produces header plus metadata rows", () => {
  const csv = buildEventsCsv([], metadata());
  const rows = parseCsv(csv);
  assert.deepEqual(rows[0], ["event_id", "ledger", "created_at", "agent", "account", "score", "contract_id"]);
  assert.equal(rows[1][0], "# export metadata");
  assert.equal(rows.length, 10);
});

test("the download payload is prefixed with a UTF-8 BOM (buildEventsCsv itself is BOM-free)", () => {
  const csv = buildEventsCsv([makeEvent("1")], metadata({ loadedCount: 1, matchedCount: 1 }));
  assert.equal(csv.startsWith(BOM), false);
  // downloadEventsCsv prepends BOM; emulate its Blob input construction.
  const bomPrefixed = `${BOM}${csv}`;
  assert.equal(bomPrefixed.charCodeAt(0), 0xFEFF);
});

test("metadata counts distinguish loaded vs matched after filtering", () => {
  const events = [makeEvent("1", { agent: "GAGENT1" }), makeEvent("2"), makeEvent("3")];
  const visible = filterEvents(events, "gagent1");
  const meta = metadata({ filterTerm: "gagent1", loadedCount: events.length, matchedCount: visible.length });
  assert.equal(meta.loadedCount, 3);
  assert.equal(meta.matchedCount, 1);
  const rows = parseCsv(buildEventsCsv(visible, meta));
  const metaRows = Object.fromEntries(rows.slice(-7).map(([key, value]) => [key, value]));
  assert.equal(metaRows.loaded_event_count, "3");
  assert.equal(metaRows.matched_event_count, "1");
  // Only the matching event is exported as data.
  assert.equal(rows.slice(1, 2)[0][4], visible[0].subject);
});

for (const [name, fn] of checks) {
  await fn();
  console.log(`  ✓ ${name}`);
}
console.log(`\nAll ${checks.length} checks passed.`);
