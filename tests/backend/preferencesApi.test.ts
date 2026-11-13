import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createBackendApp } from "../../apps/backend/src/server";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
});

function openApp(dir = mkdtempSync(join(tmpdir(), "grt-prefs-api-"))) {
  if (!dirs.includes(dir)) dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return { dir, app: createBackendApp({ db, autoSync: false }) };
}

describe("Preferences API", () => {
  test("no palette is chosen until one is saved", async () => {
    const { app } = openApp();
    expect((await app.inject({ method: "GET", url: "/api/preferences" })).json()).toEqual({ palette: null, themeAutoplay: false });
  });

  test("the chosen palette is kept in app data, so it survives a restart", async () => {
    const first = openApp();
    const saved = await first.app.inject({ method: "PUT", url: "/api/preferences/palette", payload: { palette: "moonlit-teal" } });
    expect(saved.statusCode).toBe(200);
    await first.app.close();

    const second = openApp(first.dir);
    expect((await second.app.inject({ method: "GET", url: "/api/preferences" })).json()).toEqual({ palette: "moonlit-teal", themeAutoplay: false });
  });

  test("a palette id that isn't a short slug is refused", async () => {
    const { app } = openApp();
    for (const palette of ["", "Not A Slug", "x".repeat(80), 5]) {
      const response = await app.inject({ method: "PUT", url: "/api/preferences/palette", payload: { palette } });
      expect(response.statusCode).toBe(400);
    }
    expect((await app.inject({ method: "GET", url: "/api/preferences" })).json()).toEqual({ palette: null, themeAutoplay: false });
  });

  test("Year in Review theme music waits for a click unless the user turns autoplay on", async () => {
    const { app } = openApp();

    const saved = await app.inject({ method: "PUT", url: "/api/preferences/theme-autoplay", payload: { themeAutoplay: true } });

    expect(saved.json()).toEqual({ themeAutoplay: true });
    expect((await app.inject({ method: "GET", url: "/api/preferences" })).json()).toEqual({ palette: null, themeAutoplay: true });
    expect((await app.inject({ method: "PUT", url: "/api/preferences/theme-autoplay", payload: { themeAutoplay: "on" } })).statusCode).toBe(400);
  });
});
