import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createBackendApp } from "../../apps/backend/src/server";

const token = "a".repeat(64);
let cleanups: Array<() => void> = [];

afterEach(() => {
  for (const cleanup of cleanups) cleanup();
  cleanups = [];
  delete process.env.GRT_DATA_DIR;
});

function setup(apiToken: string | null = token) {
  const dir = mkdtempSync(join(tmpdir(), "grt-guard-"));
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  runMigrations(db);
  cleanups.push(() => {
    db.close();
    rmSync(dir, { recursive: true, force: true });
  });
  const logger = { log: () => undefined };
  return createBackendApp({ db, autoSync: false, logger, apiToken: apiToken ?? undefined });
}

const withToken = { "x-grt-token": token };

describe("local backend request guard", () => {
  test("rejects requests addressed to a non-loopback host (DNS rebinding)", async () => {
    const app = setup();

    const read = await app.inject({ method: "GET", url: "/api/releases", headers: { ...withToken, host: "attacker.example:4000" } });
    const write = await app.inject({ method: "PATCH", url: "/api/settings", headers: { ...withToken, host: "attacker.example:4000" }, payload: { STEAMGRIDDB_API_KEY: "x" } });

    expect(read.statusCode).toBe(403);
    expect(write.statusCode).toBe(403);
  });

  test("API calls without the per-launch token are refused", async () => {
    const app = setup();

    const noToken = await app.inject({ method: "POST", url: "/api/sync/igdb", headers: { host: "127.0.0.1:4000", "content-type": "text/plain" }, payload: "x" });
    const wrongToken = await app.inject({ method: "GET", url: "/api/releases", headers: { host: "127.0.0.1:4000", "x-grt-token": "b".repeat(64) } });

    expect(noToken.statusCode).toBe(401);
    expect(wrongToken.statusCode).toBe(401);
  });

  test("API calls with the token from a loopback host work", async () => {
    const app = setup();

    for (const host of ["127.0.0.1:4000", "localhost:4000", "[::1]:4000"]) {
      const response = await app.inject({ method: "GET", url: "/api/releases", headers: { ...withToken, host } });
      expect(response.statusCode).toBe(200);
    }
  });

  test("images and the app shell load without the token, since <img> and page loads cannot send headers", async () => {
    const app = setup();
    const host = { host: "127.0.0.1:4000" };

    expect((await app.inject({ method: "GET", url: "/api/wallpaper/current", headers: host })).statusCode).not.toBe(401);
    expect((await app.inject({ method: "GET", url: "/api/artworks/local/missing.png", headers: host })).statusCode).not.toBe(401);
    expect((await app.inject({ method: "GET", url: "/", headers: host })).statusCode).not.toBe(401);
    expect((await app.inject({ method: "DELETE", url: "/api/wallpaper", headers: host })).statusCode).toBe(401);
  });

  test("without a configured token (development) only the host check applies", async () => {
    const app = setup(null);

    expect((await app.inject({ method: "GET", url: "/api/releases", headers: { host: "127.0.0.1:4000" } })).statusCode).toBe(200);
    expect((await app.inject({ method: "GET", url: "/api/releases", headers: { host: "attacker.example" } })).statusCode).toBe(403);
  });

  test("every response carries a content security policy that only allows the app's own code and known media hosts", async () => {
    const app = setup();

    const response = await app.inject({ method: "GET", url: "/", headers: { host: "127.0.0.1:4000" } });
    const csp = String(response.headers["content-security-policy"]);

    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("script-src 'self'");
    expect(csp).not.toMatch(/script-src[^;]*unsafe-inline/);
    expect(csp).toContain("frame-src https://www.youtube-nocookie.com");
    expect(csp).toContain("img-src 'self' data: blob: https://images.igdb.com https://i.ytimg.com https://*.steamgriddb.com");
    expect(csp).toContain("object-src 'none'");
    expect(response.headers["x-content-type-options"]).toBe("nosniff");
  });
});
