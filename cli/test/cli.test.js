import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { runCli } from "../src/cli.js";

test("easypost help returns schema and exitCode 0", async () => {
  let stdoutData = "";
  let exitCode = null;

  const mockStdout = {
    write(chunk) {
      stdoutData += chunk;
    },
  };

  await runCli(["help"], {
    stdout: mockStdout,
    stderr: { write() {} },
    setExitCode: (code) => {
      exitCode = code;
    },
  });

  assert.equal(exitCode, 0);
  const parsed = JSON.parse(stdoutData);
  assert.equal(parsed.ok, true);
  assert.equal(parsed.command, "help");
  assert.equal(parsed.result.name, "easypost-cli");
  assert.ok(parsed.result.commands.fill);
  assert.ok(parsed.result.commands.publish);
});

test("easypost prepare validates inputs successfully from file", async () => {
  const tmpFile = path.join(os.tmpdir(), `easypost-test-${Date.now()}.json`);
  await fs.writeFile(
    tmpFile,
    JSON.stringify({
      type: "imageText",
      platforms: ["xiaohongshu"],
      data: {
        title: "测试标题",
        content: "测试正文",
      },
    }),
  );

  let stdoutData = "";
  let exitCode = null;

  const mockStdout = {
    write(chunk) {
      stdoutData += chunk;
    },
  };

  try {
    await runCli(["prepare", "--input", tmpFile], {
      stdout: mockStdout,
      stderr: { write() {} },
      setExitCode: (code) => {
        exitCode = code;
      },
    });

    assert.equal(exitCode, 0);
    const parsed = JSON.parse(stdoutData);
    assert.equal(parsed.ok, true);
    assert.equal(parsed.result.status, "prepared_local");
    assert.equal(parsed.result.schema, "easypost.cli.prepared.v1");
  } finally {
    await fs.unlink(tmpFile).catch(() => {});
  }
});
