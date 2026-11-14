import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { fetchRemoteAssets } from "../src/asset-fetch.js";
import { runCli } from "../src/cli.js";

const FAST = { timeoutMs: 3_000, maxAttempts: 3, backoffMs: 5 };

function sha256(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

async function makeTempDir(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "easypost-fetch-"));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  return dir;
}

// Local throwaway HTTP server: routes map pathname -> handler, and every
// request is counted as `${METHOD} ${pathname}` for retry/write assertions.
async function startServer(t, routes) {
  const counts = new Map();
  const server = http.createServer((request, response) => {
    const pathname = String(request.url || "").split("?", 1)[0];
    const key = `${request.method} ${pathname}`;
    counts.set(key, (counts.get(key) || 0) + 1);
    const handler = routes[pathname];
    if (!handler) {
      response.writeHead(404, { "Content-Length": "0" });
      response.end();
      return;
    }
    handler(request, response);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const port = server.address().port;
  return {
    url: (pathname) => `http://127.0.0.1:${port}${pathname}`,
    count: (method, pathname) => counts.get(`${method} ${pathname}`) || 0,
  };
}

function serveBody(body, extraHeaders = {}) {
  const buffer = Buffer.isBuffer(body) ? body : Buffer.from(body);
  return (request, response) => {
    const headers = { "Content-Length": String(buffer.length), ...extraHeaders };
    if (request.method === "HEAD") {
      response.writeHead(200, headers);
      response.end();
      return;
    }
    response.writeHead(200, headers);
    response.end(buffer);
  };
}

function runCliCapture(argv) {
  let stdoutData = "";
  let stderrData = "";
  let exitCode = null;
  return runCli(argv, {
    stdout: { write(chunk) { stdoutData += chunk; } },
    stderr: { write(chunk) { stderrData += chunk; } },
    setExitCode: (code) => { exitCode = code; },
  }).then(() => ({
    exitCode,
    stdout: stdoutData ? JSON.parse(stdoutData) : null,
    stderr: stderrData ? JSON.parse(stderrData) : null,
  }));
}

test("正常下载并校验：落盘内容与远端一致", async (t) => {
  const dir = await makeTempDir(t);
  const body = Buffer.from(`easypost-asset-${"x".repeat(4096)}`);
  const server = await startServer(t, { "/asset.bin": serveBody(body) });
  const target = path.join(dir, "asset.bin");

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: server.url("/asset.bin") }],
    FAST,
  );

  assert.equal(summary.total, 1);
  assert.equal(summary.downloaded, 1);
  assert.equal(summary.failed, 0);
  assert.equal(summary.skipped, 0);
  const [record] = summary.results;
  assert.equal(record.status, "downloaded");
  assert.equal(record.size, body.length);
  assert.equal(record.sha256, sha256(body));
  assert.deepEqual(await fs.readFile(target), body);
  // 临时文件不得残留
  assert.deepEqual(await fs.readdir(dir), ["asset.bin"]);
});

test("4xx 直接判失败且不重试", async (t) => {
  const dir = await makeTempDir(t);
  const server = await startServer(t, {
    "/missing.bin": (_request, response) => {
      response.writeHead(404, { "Content-Length": "0" });
      response.end();
    },
  });
  const target = path.join(dir, "missing.bin");

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: server.url("/missing.bin") }],
    FAST,
  );

  assert.equal(summary.failed, 1);
  const [record] = summary.results;
  assert.equal(record.status, "failed");
  assert.equal(record.httpStatus, 404);
  assert.equal(record.attempts, 1);
  assert.equal(server.count("GET", "/missing.bin"), 1);
  // 失败不得留下成品或半成品
  await assert.rejects(fs.stat(target));
  assert.deepEqual(await fs.readdir(dir), []);
});

test("5xx 重试后成功", async (t) => {
  const dir = await makeTempDir(t);
  const body = Buffer.from("flaky-but-eventually-fine");
  let calls = 0;
  const server = await startServer(t, {
    "/flaky.bin": (_request, response) => {
      calls += 1;
      if (calls < 3) {
        response.writeHead(500, { "Content-Length": "0" });
        response.end();
        return;
      }
      response.writeHead(200, { "Content-Length": String(body.length) });
      response.end(body);
    },
  });
  const target = path.join(dir, "flaky.bin");

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: server.url("/flaky.bin") }],
    FAST,
  );

  assert.equal(summary.failed, 0);
  const [record] = summary.results;
  assert.equal(record.status, "downloaded");
  assert.equal(record.attempts, 3);
  assert.equal(server.count("GET", "/flaky.bin"), 3);
  assert.deepEqual(await fs.readFile(target), body);
});

test("单条失败不影响其他条，且 prepare 以非零退出并保留已下载素材", async (t) => {
  const dir = await makeTempDir(t);
  const goodBody = Buffer.from("good-asset-content");
  const server = await startServer(t, {
    "/good.bin": serveBody(goodBody),
    "/bad.bin": (_request, response) => {
      response.writeHead(404, { "Content-Length": "0" });
      response.end();
    },
  });
  const goodPath = path.join(dir, "good.bin");
  const badPath = path.join(dir, "bad.bin");

  const summary = await fetchRemoteAssets(
    [
      { path: goodPath, role: "media", sourceUrl: server.url("/good.bin") },
      { path: badPath, role: "media", sourceUrl: server.url("/bad.bin") },
    ],
    FAST,
  );
  assert.equal(summary.total, 2);
  assert.equal(summary.downloaded, 1);
  assert.equal(summary.failed, 1);
  assert.equal(summary.results[0].status, "downloaded");
  assert.equal(summary.results[1].status, "failed");
  // 已成功素材保留可用
  assert.deepEqual(await fs.readFile(goodPath), goodBody);
  await assert.rejects(fs.stat(badPath));

  // 同一批素材走真实 prepare 命令：非零退出码 + 逐条结局汇总
  const inputFile = path.join(dir, "input.json");
  await fs.writeFile(inputFile, JSON.stringify({
    type: "imageText",
    platforms: ["xiaohongshu"],
    data: { title: "t", content: "c" },
    assets: [
      { path: goodPath, sourceUrl: server.url("/good.bin") },
      { path: badPath, sourceUrl: server.url("/bad.bin") },
    ],
  }));
  const { exitCode, stderr } = await runCliCapture(["prepare", "--input", inputFile]);
  assert.equal(exitCode, 40);
  assert.equal(stderr.ok, false);
  assert.equal(stderr.error.code, "ASSET_FETCH_FAILED");
  const assetFetch = stderr.error.details.assetFetch;
  assert.equal(assetFetch.total, 2);
  assert.equal(assetFetch.failed, 1);
  // 重跑时已就绪素材跳过下载，只有失败条重新取
  assert.equal(assetFetch.skipped + assetFetch.downloaded, 1);
  assert.equal(assetFetch.results.length, 2);
  assert.deepEqual(await fs.readFile(goodPath), goodBody);
});

test("已存在且大小与 SHA256 一致时跳过下载", async (t) => {
  const dir = await makeTempDir(t);
  const body = Buffer.from("already-on-disk");
  const target = path.join(dir, "ready.bin");
  await fs.writeFile(target, body);
  const server = await startServer(t, {
    "/ready.bin": serveBody(body, { ETag: `"sha256-${sha256(body)}"` }),
  });

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: server.url("/ready.bin") }],
    FAST,
  );

  assert.equal(summary.skipped, 1);
  assert.equal(summary.downloaded, 0);
  const [record] = summary.results;
  assert.equal(record.status, "skipped");
  assert.equal(record.reason, "already_ready");
  assert.equal(record.sha256, sha256(body));
  // 只发 HEAD 比对，不触发 GET 下载
  assert.equal(server.count("HEAD", "/ready.bin"), 1);
  assert.equal(server.count("GET", "/ready.bin"), 0);
  assert.deepEqual(await fs.readFile(target), body);
});

test("已存在但内容与远端不一致时重取", async (t) => {
  const dir = await makeTempDir(t);
  const stale = Buffer.from("stale-content");
  const fresh = Buffer.from("fresh-remote-content");
  const target = path.join(dir, "stale.bin");
  await fs.writeFile(target, stale);
  const server = await startServer(t, {
    "/stale.bin": serveBody(fresh, { ETag: `"sha256-${sha256(fresh)}"` }),
  });

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: server.url("/stale.bin") }],
    FAST,
  );

  assert.equal(summary.downloaded, 1);
  assert.equal(server.count("GET", "/stale.bin"), 1);
  assert.deepEqual(await fs.readFile(target), fresh);
});

test("并发同一 path 只允许一个写入者，其余复用结果", async (t) => {
  const dir = await makeTempDir(t);
  const body = Buffer.from("shared-target-content");
  const server = await startServer(t, { "/shared.bin": serveBody(body) });
  const target = path.join(dir, "shared.bin");

  const summary = await fetchRemoteAssets(
    [
      { path: target, role: "media", sourceUrl: server.url("/shared.bin") },
      { path: target, role: "cover", sourceUrl: server.url("/shared.bin") },
      { path: target, role: "media", sourceUrl: server.url("/shared.bin") },
    ],
    FAST,
  );

  assert.equal(summary.total, 3);
  assert.equal(summary.failed, 0);
  // 远端只被取一次：一个写入者，其余等待并复用
  assert.equal(server.count("GET", "/shared.bin"), 1);
  const writers = summary.results.filter((r) => !r.reused);
  const reusers = summary.results.filter((r) => r.reused);
  assert.equal(writers.length, 1);
  assert.equal(reusers.length, 2);
  for (const record of summary.results) {
    assert.equal(record.status, "downloaded");
    assert.equal(record.sha256, sha256(body));
  }
  assert.deepEqual(await fs.readFile(target), body);
  assert.deepEqual(await fs.readdir(dir), ["shared.bin"]);
});

test("非法 sourceUrl 直接判失败不发请求", async (t) => {
  const dir = await makeTempDir(t);
  const target = path.join(dir, "bad-url.bin");

  const summary = await fetchRemoteAssets(
    [{ path: target, role: "media", sourceUrl: "http://user:secret@127.0.0.1:1/x.bin" }],
    FAST,
  );

  assert.equal(summary.failed, 1);
  const [record] = summary.results;
  assert.equal(record.status, "failed");
  assert.equal(record.code, "INVALID_SOURCE_URL");
  assert.equal(record.attempts, 0);
  await assert.rejects(fs.stat(target));
});

test("prepare 成功时输出逐条采集汇总", async (t) => {
  const dir = await makeTempDir(t);
  const body = Buffer.from("prepare-e2e-asset");
  const server = await startServer(t, { "/e2e.bin": serveBody(body) });
  const target = path.join(dir, "e2e.bin");
  const inputFile = path.join(dir, "input.json");
  await fs.writeFile(inputFile, JSON.stringify({
    type: "imageText",
    platforms: ["xiaohongshu"],
    data: { title: "标题", content: "正文" },
    assets: [{ path: target, sourceUrl: server.url("/e2e.bin") }],
  }));

  const { exitCode, stdout } = await runCliCapture(["prepare", "--input", inputFile]);

  assert.equal(exitCode, 0);
  assert.equal(stdout.ok, true);
  assert.equal(stdout.result.status, "prepared_local");
  const assetFetch = stdout.result.assetFetch;
  assert.equal(assetFetch.total, 1);
  assert.equal(assetFetch.downloaded, 1);
  assert.equal(assetFetch.failed, 0);
  assert.equal(assetFetch.results[0].status, "downloaded");
  assert.equal(stdout.result.assets[0].sha256, sha256(body));
  assert.equal(stdout.result.assets[0].size, body.length);
});
