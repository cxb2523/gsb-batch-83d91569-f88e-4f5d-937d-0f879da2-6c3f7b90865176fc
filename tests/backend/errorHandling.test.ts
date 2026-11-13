import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createBackendApp } from "../../apps/backend/src/server";

const dirs: string[] = [];
const dbs: Array<{ close(): void }> = [];

afterEach(() => {
  for (const db of dbs) db.close();
  dbs.length = 0;
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

describe("backend error handling", () => {
  test("logs unexpected route errors while returning a safe response", async () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-error-handling-"));
    dirs.push(dir);
    const db = openDatabase(join(dir, "tracker.db"));
    dbs.push(db);
    runMigrations(db);

    const events: Array<{ event: string; details?: Record<string, unknown> }> = [];
    const app = createBackendApp({
      db,
      autoSync: false,
      logger: { log: (event, details) => events.push({ event, details }) }
    });
    app.get("/test-error", async () => {
      throw new Error("private database detail");
    });

    const response = await app.inject({ method: "GET", url: "/test-error" });

    expect(response.statusCode).toBe(500);
    expect(response.json()).toEqual({ error: "Something went wrong. Check the diagnostics log for details." });
    expect(response.body).not.toContain("private database detail");
    expect(events).toContainEqual({
      event: "http.error",
      details: expect.objectContaining({
        method: "GET",
        url: "/test-error",
        statusCode: 500,
        message: "private database detail"
      })
    });

    await app.close();
  });
});
