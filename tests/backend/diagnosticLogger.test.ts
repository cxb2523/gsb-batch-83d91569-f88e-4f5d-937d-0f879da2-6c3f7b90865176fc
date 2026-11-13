import { afterEach, describe, expect, test } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createFileDiagnosticLogger } from "../../apps/backend/src/diagnostics/logger";

const dirs: string[] = [];

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

describe("diagnostic file logger", () => {
  test("writes JSON lines and redacts secret-like fields", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-logs-"));
    dirs.push(dir);
    const logger = createFileDiagnosticLogger(dir);

    logger.log("ui.click", { action: "delete", apiKey: "real-secret", nested: { token: "real-token" } });

    const line = readFileSync(join(dir, "game-release-tracker.log"), "utf8").trim();
    const entry = JSON.parse(line);
    expect(entry.event).toBe("ui.click");
    expect(entry.details).toEqual({ action: "delete", apiKey: "[redacted]", nested: { token: "[redacted]" } });
    expect(entry.time).toEqual(expect.any(String));
  });

  test("redacts credentials in header-like keys and inside text such as URLs", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-logs-"));
    dirs.push(dir);
    const logger = createFileDiagnosticLogger(dir);

    logger.log("igdb.error", {
      Authorization: "Bearer abc123",
      "Client-ID": "my-client",
      message: "POST https://id.twitch.tv/oauth2/token?client_id=abc&client_secret=shh&grant_type=client_credentials failed: Bearer xyz789"
    });

    const text = readFileSync(join(dir, "game-release-tracker.log"), "utf8");
    expect(text).not.toMatch(/abc123|my-client|shh|xyz789|client_id=abc/);
    expect(text).toContain("grant_type=client_credentials");
  });

  test("a log that cannot be written never throws into the caller", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-logs-"));
    dirs.push(dir);
    const logger = createFileDiagnosticLogger(dir);
    rmSync(dir, { recursive: true, force: true });

    expect(() => logger.log("ui.click", { action: "after the folder vanished" })).not.toThrow();
  });

  test("rotates the log at the size cap and keeps only a few old files", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-logs-"));
    dirs.push(dir);
    const logger = createFileDiagnosticLogger(dir, { maxBytes: 1_000, keepFiles: 2 });

    for (let index = 0; index < 60; index++) logger.log("ui.click", { action: "filler", index, pad: "x".repeat(40) });

    const log = join(dir, "game-release-tracker.log");
    expect(statSync(log).size).toBeLessThanOrEqual(1_000);
    expect(existsSync(`${log}.1`)).toBe(true);
    expect(existsSync(`${log}.2`)).toBe(true);
    expect(existsSync(`${log}.3`)).toBe(false);
  });
});
