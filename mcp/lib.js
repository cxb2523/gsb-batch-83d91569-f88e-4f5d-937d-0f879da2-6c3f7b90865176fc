// getregdata MCP server - core logic.
//
// Kept separate from index.js (the executable entry point) so the run/resume
// chain can be tested without spawning a stdio server or touching the network.
// See test/run-chain.test.js.
//
// Auth: set APIFY_TOKEN in the environment (get one free at
// https://apify.com?fpr=getregdata - includes $5 credits).

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
} from "@modelcontextprotocol/sdk/types.js";
import { createRequire } from "node:module";
import { ACTORS } from "./actors.js";

const pkg = createRequire(import.meta.url)("./package.json");
const APIFY_BASE = "https://api.apify.com/v2";
// Jurisdictions covered by the actor fleet. Not derivable from actors.js (no
// country field), so it is asserted here and checked by scripts/check-counts.mjs.
const JURISDICTIONS = 20;

// How long we hold a tool call open before handing back a run handle. Must stay
// under the MCP client's default request timeout (60s) with margin: if the CLIENT
// gives up first, the caller sees an error for a run that is still billing.
export const WAIT_SECS = 45;
// Apify itself caps waitForFinish at 60. Anything longer is silently truncated
// by the API, so clamp before sending and keep the contract honest.
export const MAX_WAIT_SECS = 60;
const TERMINAL = new Set(["SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"]);

// Apify run IDs are alphanumeric (e.g. NAMNqpPch7RFSY1oQ, 17 chars). This is
// deliberately strict: the ID is interpolated into the URL path, so anything
// with slashes, spaces, scheme, or punctuation is rejected before a fetch.
const RUN_ID_RE = /^[A-Za-z0-9]{6,64}$/;

export function defaultContext(overrides = {}) {
  return {
    fetchImpl: overrides.fetchImpl || ((...args) => globalThis.fetch(...args)),
    env: overrides.env || process.env,
    actors: overrides.actors || ACTORS,
  };
}

export function requireToken(env = process.env) {
  const t = env.APIFY_TOKEN || env.APIFY_API_TOKEN || "";
  if (!t) {
    throw new Error(
      "APIFY_TOKEN is not set. Get a free token (with $5 credits) at " +
        "https://getregdata.com/go/signup/mcp/ and set APIFY_TOKEN in your MCP client config."
    );
  }
  return t;
}

// Validate a runId before any token check or network call.
//
// Requirement: a missing or obviously malformed runId must produce a readable
// error and must NOT reach Apify. Re-running the original tool instead is what
// double-bills the user, so the error says so explicitly.
export function normalizeRunId(runId) {
  if (runId === undefined || runId === null || (typeof runId === "string" && runId.trim() === "")) {
    return {
      ok: false,
      error:
        "runId is required. Pass the runId returned in the pending result of the original tool call " +
        '(for example {"status":"RUNNING","runId":"NAMNqpPch7RFSY1oQ"}). ' +
        "No network request was made. Do NOT re-run the original check - re-running starts and bills a second run.",
    };
  }
  const raw = String(runId);
  if (typeof runId !== "string" || !RUN_ID_RE.test(raw.trim())) {
    return {
      ok: false,
      error:
        `Invalid runId ${JSON.stringify(raw.slice(0, 80))}: expected the alphanumeric run ID returned in a ` +
        'pending result (e.g. "NAMNqpPch7RFSY1oQ"), not a URL, path or free text. ' +
        "No network request was made. Do NOT re-run the original check - re-running starts and bills a second run.",
    };
  }
  return { ok: true, runId: raw.trim() };
}

// waitSecs contract: > 60 becomes 60, negatives become 0. Missing/invalid
// values fall back to the default rather than making a nonsensical request.
export function normalizeWaitSecs(value, defaultSecs = WAIT_SECS) {
  if (value === undefined || value === null || value === "") return defaultSecs;
  const n = Number(value);
  if (!Number.isFinite(n)) return defaultSecs;
  return Math.max(0, Math.min(MAX_WAIT_SECS, Math.trunc(n)));
}

// The one shape every pending path returns. runId and status are always
// present, and the note carries the runId concretely (a bare "above" is easy
// for a model to misread once the handle is in a later message).
export function pendingPayload(run, runId) {
  const id = runId || run?.id;
  const status = run?.status ?? "RUNNING";
  return {
    status,
    runId: id,
    datasetId: run?.defaultDatasetId ?? null,
    note:
      `This check is STILL RUNNING (status: ${status}) and is already being billed. ` +
      "Do NOT re-run the check and do NOT call the original tool again - a second run is a second charge. " +
      `Call regdata_run_result with runId "${id}" to collect the result; repeat that call until it returns the dataset items.`,
  };
}

async function apiJson(url, init, ctx) {
  const res = await ctx.fetchImpl(url, init);
  const text = await res.text();
  if (!res.ok) throw new Error(`Apify API ${res.status}: ${text.slice(0, 300)}`);
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    throw new Error(`Apify API returned non-JSON: ${text.slice(0, 300)}`);
  }
  return body?.data;
}

async function datasetItems(datasetId, maxItems, ctx) {
  if (!datasetId) {
    throw new Error("The run finished but returned no dataset id, so its items cannot be read.");
  }
  const url = new URL(`${APIFY_BASE}/datasets/${datasetId}/items`);
  url.searchParams.set("token", requireToken(ctx.env));
  if (maxItems) url.searchParams.set("limit", String(maxItems));
  const res = await ctx.fetchImpl(url);
  const text = await res.text();
  if (!res.ok) {
    // The run SUCCEEDED and is billed; only the read failed. Retrying the read
    // (by calling regdata_run_result again) is free, re-running is not.
    throw new Error(
      `The run finished and is billed, but its dataset could not be read (${res.status}). ` +
        "Call regdata_run_result again with the same runId to retry the read - do NOT re-run the original check."
    );
  }
  return text; // JSON array of dataset items
}

// Either the items, a redeemable pending handle, or a readable terminal error.
// Never a lost run. `runId` is the handle the caller holds, so it is used even
// if Apify echoes a different id - the caller must be able to keep resuming
// with exactly the ID it was given.
export async function settle(run, runId, label, maxItems, ctx) {
  if (!run || typeof run !== "object" || !run.status) {
    throw new Error(
      `Apify did not return a run status for ${label} (runId: ${runId || "unknown"}). ` +
        "If you have a runId from an earlier pending result, call regdata_run_result with it; do not re-run blindly."
    );
  }
  const id = runId || run.id;
  // actId looks like "regdata~poland-kyb-check"; show it as "regdata/poland-kyb-check".
  const name = label === "run" ? label : String(label).replace(/^regdata~/, "");
  if (run.status === "SUCCEEDED") return await datasetItems(run.defaultDatasetId, maxItems, ctx);
  if (TERMINAL.has(run.status)) {
    throw new Error(
      `regdata/${name} run ${id} ended as ${run.status}` +
        (run.statusMessage ? `: ${run.statusMessage}` : "") +
        ". A finished run cannot be resumed - do not call regdata_run_result for it again. " +
        "Re-running the check would start (and bill) a new run."
    );
  }
  return JSON.stringify(pendingPayload(run, id), null, 2);
}

// Start the actor and wait briefly.
//
// Started ASYNC on purpose. This previously used run-sync-get-dataset-items, which
// holds one connection open until the run ends. Per Apify's docs, "if the connection
// breaks, you will not receive any information about the run and its output" and
// "this won't abort the run itself" - so a client timeout destroyed the only handle
// to a run that then completed and BILLED. Measured durations for the Poland KYB
// composite were 21-148s against a 60s client default, so this was routine, not rare.
// Starting async means the runId exists from the first response and a disconnect is
// always recoverable.
export async function runActor(slug, input, { maxItems } = {}, ctx = defaultContext()) {
  const url = new URL(`${APIFY_BASE}/acts/regdata~${slug}/runs`);
  url.searchParams.set("token", requireToken(ctx.env));
  url.searchParams.set("waitForFinish", String(WAIT_SECS)); // Apify caps this at 60
  if (maxItems) url.searchParams.set("maxItems", String(maxItems));
  let run;
  try {
    run = await apiJson(
      url,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input ?? {}),
      },
      ctx
    );
  } catch (err) {
    // An HTTP error status from Apify is a definite answer and is passed through.
    // A transport failure (no response at all) is ambiguous: the run may exist on
    // the server even though the reply was lost. Warn rather than invite a blind
    // retry that could bill a second run.
    if (/^Apify API \d/.test(String(err?.message))) throw err;
    throw new Error(
      `Could not start regdata/${slug}: the request failed in transit (${err?.message || err}). ` +
        "The run may nonetheless have started on Apify. Check the account's recent runs before retrying - " +
        "if a run exists, collect it with regdata_run_result instead of starting another (a retry is a second charge)."
    );
  }
  if (!run?.id) {
    throw new Error(
      `Apify did not return a run id for regdata/${slug}; nothing can be resumed. Do not re-run blindly - ` +
        "check the Apify account for a run that may already be billing."
    );
  }
  return await settle(run, run.id, slug, maxItems, ctx);
}

// Collect a run that was still going when its tool call returned.
//
// NOTE on access: we send the caller's token, but Apify does NOT scope runs or
// datasets to it - verified 2026-07-23, `GET /actor-runs/{id}` and
// `/datasets/{id}/items` both return 200 with a foreign token AND with no token
// at all, on a dataset whose isPublic is unset. The storage ID is itself the
// capability. So this tool grants nothing a runId holder could not already fetch
// straight from the public API; it is convenience, not an access boundary.
// Treat a runId as a secret and do not log or forward it.
export async function collectRun(runId, { waitSecs, maxItems } = {}, ctx = defaultContext()) {
  // Validate first: a bad runId must not cause a token check or a fetch.
  const check = normalizeRunId(runId);
  if (!check.ok) throw new Error(check.error);

  const url = new URL(`${APIFY_BASE}/actor-runs/${encodeURIComponent(check.runId)}`);
  url.searchParams.set("token", requireToken(ctx.env));
  url.searchParams.set("waitForFinish", String(normalizeWaitSecs(waitSecs)));
  let run;
  try {
    run = await apiJson(url, undefined, ctx);
  } catch (err) {
    // An HTTP status from Apify is a real answer (unknown runId, bad token, outage)
    // and is passed through. A transport failure (no response at all) is different:
    // the run still exists on the server and is still billed, so say so - with the
    // handle - rather than letting the caller mistake it for a dead check and re-run.
    if (/^Apify API \d/.test(String(err?.message))) throw err;
    throw new Error(
      `Could not reach Apify to collect run ${check.runId}: ${err?.message || err}. ` +
        "The run was NOT started again and may still be running or finished - " +
        `call regdata_run_result again with runId "${check.runId}"; do not re-run the original check.`
    );
  }
  return await settle(run, check.runId, run?.actId ?? "run", maxItems, ctx);
}

// Fetch an actor's live input schema so the model can construct correct input.
export async function describeActor(slug, ctx = defaultContext()) {
  const url = `${APIFY_BASE}/acts/regdata~${slug}?token=${requireToken(ctx.env)}`;
  const res = await ctx.fetchImpl(url);
  if (!res.ok) throw new Error(`Could not fetch regdata/${slug} (${res.status})`);
  const { data } = await res.json();
  // The build's input schema lives on the default build; fall back to a hint.
  const schema =
    data?.defaultRunOptions?.inputSchema ||
    data?.exampleRunInput ||
    "See https://getregdata.com/go/" + slug + "/mcp/ for the input schema.";
  return { slug, title: data?.title, description: data?.description, schema };
}

const indexBy = (actors, key) => Object.fromEntries(actors.map((a) => [a[key], a]));

// One tool per actor + three helpers (catalog, run_result, describe).
const MAX_ITEMS_PROP = {
  type: "integer",
  description: "Optional cap on billed dataset items returned.",
};

export function buildToolList(actors = ACTORS) {
  const actorTools = actors.map((a) => {
    // Deployed input schema baked in by scripts/gen-manifest.mjs; freeform fallback.
    const schema = a.inputSchema
      ? {
          ...a.inputSchema,
          properties: { ...a.inputSchema.properties, maxItems: MAX_ITEMS_PROP },
        }
      : {
          type: "object",
          description: `Input for regdata/${a.slug}. Freeform - matches the actor's Apify input schema.`,
          properties: { maxItems: MAX_ITEMS_PROP },
          additionalProperties: true,
        };
    const hint = a.inputSchema
      ? `Advanced fields beyond this schema are also accepted (regdata_describe lists them).`
      : `Pass the registry's search input as a flat object (e.g. name, tax ID, or registration number); ` +
        `call regdata_describe with slug "${a.slug}" first if unsure of the exact fields.`;
    return {
      name: a.tool,
      description: `${a.title}. ${a.description} ${hint}`,
      inputSchema: schema,
    };
  });

  return [
    {
      name: "regdata_catalog",
      description:
        `List the getregdata business-registry tools (KYC/AML, credit-risk, due-diligence, B2B) across ${JURISDICTIONS} jurisdictions, with each tool name and what it returns. ` +
        `For a Polish company, prefer regdata_poland_kyb_check: one call takes a NIP or KRS and returns a complete KYB verdict (identity + beneficial owners + insolvency screened against the company and every owner), instead of chaining several registry tools yourself. ` +
        `Use this catalog to find the right single-registry tool for other jurisdictions, or when you need one specific source in depth.`,
      inputSchema: { type: "object", properties: {}, additionalProperties: false },
    },
    {
      name: "regdata_run_result",
      description:
        "Collect the result of a regdata check that was still running when its tool call returned. " +
        "When any regdata tool returns {status, runId, note} instead of results, the check is running and already billed - " +
        "call THIS tool with that runId rather than re-running the check, which would charge the user twice. " +
        "Returns the dataset items once the run finishes. If the run is still going when the wait elapses, it returns the same " +
        "{status, runId, note} handle - not an error - so call it again with the same runId. " +
        "waitSecs is clamped to 0-60 (values above 60 wait 60; negatives wait 0). " +
        "A missing or malformed runId returns a readable error and makes no network request.",
      inputSchema: {
        type: "object",
        properties: {
          runId: {
            type: "string",
            description: "The runId returned by the pending tool call, e.g. NAMNqpPch7RFSY1oQ",
          },
          waitSecs: {
            type: "integer",
            description: "Seconds to wait for the run to finish before returning (0-60, default 45; >60 is treated as 60, negatives as 0).",
          },
          maxItems: MAX_ITEMS_PROP,
        },
        required: ["runId"],
        additionalProperties: false,
      },
    },
    {
      name: "regdata_describe",
      description:
        "Fetch the live input schema + description for one actor so you can construct a correct call. Provide either the actor slug or its tool name.",
      inputSchema: {
        type: "object",
        properties: {
          slug: { type: "string", description: "Actor slug, e.g. crbr-beneficial-owners-scraper" },
          tool: { type: "string", description: "Tool name, e.g. regdata_crbr_beneficial_owners" },
        },
        additionalProperties: false,
      },
    },
    ...actorTools,
  ];
}

// Dispatch one tool call. Pure(ish): all I/O goes through ctx.fetchImpl, so tests
// can drive the whole pending -> resume chain against a fake Apify.
export async function handleToolCall(name, args, overrides = {}) {
  const ctx = defaultContext(overrides);
  const input = args || {};
  try {
    if (name === "regdata_catalog") {
      const list = ctx.actors.map((a) => ({ tool: a.tool, slug: a.slug, title: a.title }));
      return { content: [{ type: "text", text: JSON.stringify(list, null, 2) }] };
    }
    if (name === "regdata_run_result") {
      // collectRun validates the runId before requireToken/fetch. That ordering
      // is the "no network request for a bad runId" guarantee.
      const out = await collectRun(input.runId, { waitSecs: input.waitSecs, maxItems: input.maxItems }, ctx);
      return { content: [{ type: "text", text: out }] };
    }
    if (name === "regdata_describe") {
      const slug = input.slug || indexBy(ctx.actors, "tool")[input.tool]?.slug;
      if (!slug || !indexBy(ctx.actors, "slug")[slug]) throw new Error(`Unknown actor: ${input.slug || input.tool}`);
      const info = await describeActor(slug, ctx);
      return { content: [{ type: "text", text: JSON.stringify(info, null, 2) }] };
    }
    const actor = indexBy(ctx.actors, "tool")[name];
    if (!actor) throw new Error(`Unknown tool: ${name}`);
    const { maxItems, ...actorInput } = input;
    const items = await runActor(actor.slug, actorInput, { maxItems }, ctx);
    return { content: [{ type: "text", text: items }] };
  } catch (err) {
    return {
      isError: true,
      content: [{ type: "text", text: String(err?.message || err) }],
    };
  }
}

export async function startServer() {
  const server = new Server(
    { name: "getregdata", version: pkg.version },
    { capabilities: { tools: {} } }
  );

  server.setRequestHandler(ListToolsRequestSchema, async () => ({
    tools: buildToolList(),
  }));

  server.setRequestHandler(CallToolRequestSchema, async (req) => {
    const { name, arguments: args } = req.params;
    return await handleToolCall(name, args ?? {});
  });

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error(`getregdata MCP server ready - ${ACTORS.length} registry tools + catalog/run_result/describe.`);
  return server;
}
