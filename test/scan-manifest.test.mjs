import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import * as zlib from "node:zlib";
import { analyzeCodexUsage } from "../src/analyzer.mjs";

const zstdSupported = typeof zlib.zstdCompressSync === "function";

async function fixture(t) {
  const codexHome = await mkdtemp(path.join(tmpdir(), "codex-scan-manifest-"));
  t.after(() => rm(codexHome, { recursive: true, force: true }));
  await mkdir(path.join(codexHome, "sessions"));
  await mkdir(path.join(codexHome, "archived_sessions"));
  return codexHome;
}

function sessionRows(id, startTimestamp, tokenCount) {
  const start = Date.parse(startTimestamp);
  return [
    { timestamp: new Date(start).toISOString(), type: "session_meta", payload: { id } },
    { timestamp: new Date(start + 1000).toISOString(), type: "event_msg", payload: { type: "task_started", turn_id: "turn-1" } },
    { timestamp: new Date(start + 2000).toISOString(), type: "event_msg", payload: { type: "token_count", info: { last_token_usage: { input_tokens: tokenCount, output_tokens: 1, total_tokens: tokenCount + 1 } } } },
  ].map(JSON.stringify).join("\n");
}

function manifestEntry(result, filePath) {
  const entry = result.files.find((file) => file.filePath === filePath);
  assert.ok(entry, `manifest lists ${filePath}`);
  return entry;
}

test("both copies of a session appear in the manifest and the newer one is kept", async (t) => {
  const codexHome = await fixture(t);
  const activeFile = path.join(codexHome, "sessions", "rollout.jsonl");
  const archivedFile = path.join(codexHome, "archived_sessions", "rollout.jsonl");
  await writeFile(activeFile, sessionRows("shared", "2026-10-01T08:00:00.000Z", 100));
  await writeFile(archivedFile, sessionRows("shared", "2026-10-02T08:00:00.000Z", 200));

  const result = await analyzeCodexUsage({ codexHome });
  assert.equal(result.sessions.length, 1, "the duplicated session is counted once");
  assert.equal(result.sessions[0].filePath, archivedFile, "the newest copy is kept");
  assert.equal(result.sessions[0].usage.totalTokens, 201);
  assert.equal(result.errors.length, 0);

  assert.equal(result.files.length, 2, "both copies appear in the manifest");
  assert.deepEqual(result.files.map((file) => file.filePath), [...result.files.map((file) => file.filePath)].sort(), "manifest order is stable");
  const active = manifestEntry(result, activeFile);
  assert.equal(active.status, "superseded");
  assert.equal(active.sessionId, "shared");
  assert.equal(active.supersededBy, archivedFile, "the replaced copy points to the kept file");
  assert.equal(active.error, null);
  const archived = manifestEntry(result, archivedFile);
  assert.equal(archived.status, "parsed");
  assert.equal(archived.sessionId, "shared");
  assert.equal(archived.supersededBy, null);

  const rescan = await analyzeCodexUsage({ codexHome, previousData: result });
  assert.equal(manifestEntry(rescan, archivedFile).status, "cached", "unchanged files reuse the cache");
  assert.equal(manifestEntry(rescan, activeFile).status, "superseded", "the replaced copy stays marked as superseded");
  const repeat = await analyzeCodexUsage({ codexHome, previousData: rescan });
  assert.deepEqual(repeat.files, rescan.files, "the manifest is identical between equivalent scans");
});

test("a corrupted plain log fails its own entry without failing the scan or reusing stale cache", async (t) => {
  const codexHome = await fixture(t);
  const goodFile = path.join(codexHome, "sessions", "good.jsonl");
  const brokenFile = path.join(codexHome, "sessions", "broken.jsonl");
  await writeFile(goodFile, sessionRows("good", "2026-10-01T08:00:00.000Z", 100));
  await writeFile(brokenFile, sessionRows("broken", "2026-10-01T09:00:00.000Z", 50));

  const baseline = await analyzeCodexUsage({ codexHome });
  assert.equal(baseline.sessions.length, 2);
  assert.equal(manifestEntry(baseline, brokenFile).status, "parsed");

  await writeFile(brokenFile, "this is not jsonl content at all {{{\n neither is this line\n");
  const result = await analyzeCodexUsage({ codexHome, previousData: baseline });
  assert.equal(result.sessions.length, 1, "the failed file is not counted as a session");
  assert.equal(result.sessions[0].id, "good", "the stale cached copy of the failed file is not served");
  assert.equal(result.errors.length, 1);
  assert.equal(result.errors[0].filePath, brokenFile);

  const broken = manifestEntry(result, brokenFile);
  assert.equal(broken.status, "failed");
  assert.equal(broken.sessionId, null);
  assert.match(broken.error, /aucune ligne JSON valide/i);
  assert.equal(broken.supersededBy, null);
  assert.equal(manifestEntry(result, goodFile).status, "cached", "untouched files still reuse their cache");
});

test("a corrupted archive still fails the whole scan", { skip: !zstdSupported }, async (t) => {
  const codexHome = await fixture(t);
  await writeFile(path.join(codexHome, "sessions", "good.jsonl"), sessionRows("good", "2026-10-01T08:00:00.000Z", 100));
  await writeFile(path.join(codexHome, "archived_sessions", "broken.jsonl.zst"), Buffer.from("corrupted zstd"));

  await assert.rejects(analyzeCodexUsage({ codexHome }), /archive Codex impossible/);
});
