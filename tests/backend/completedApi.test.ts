import { afterEach, describe, expect, test, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createBackendApp } from "../../apps/backend/src/server";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];
let previousIgdbEnv: {
  IGDB_CLIENT_ID?: string;
  IGDB_CLIENT_SECRET?: string;
  IGDB_ACCESS_TOKEN?: string;
} = {};

function setup() {
  const dir = mkdtempSync(join(tmpdir(), "grt-completed-api-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return { app: createBackendApp({ db, autoSync: false }), db, dir };
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
  restoreIgdbEnv();
  vi.unstubAllGlobals();
});

describe("completed library API", () => {
  test("lists cards and returns detail for a game added in the app, and the Excel sync is gone", async () => {
    withoutIgdbEnv();
    const { app } = setup();
    await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "Persona 4 Golden", userPlatform: "PC", ratingRaw: "9", completionDate: "2026-01-07" } });

    expect((await app.inject({ method: "GET", url: "/api/completed-library/settings" })).statusCode).toBe(404);
    expect((await app.inject({ method: "POST", url: "/api/completed-library/sync" })).statusCode).toBe(404);

    const list = await app.inject({ method: "GET", url: "/api/completed-games?platform=PC&year=2026" });
    expect(list.statusCode).toBe(200);
    expect(list.json().items[0]).toMatchObject({ title: "Persona 4 Golden", userPlatform: "PC", ratingScore: 9 });

    const detail = await app.inject({ method: "GET", url: "/api/completed-games/completed-persona-4-golden-pc" });
    expect(detail.statusCode).toBe(200);
    expect(detail.json()).toMatchObject({ title: "Persona 4 Golden", completionDate: "2026-01-07" });
  });

  test("creates manual completed games and returns 400 for missing title", async () => {
    withoutIgdbEnv();
    const { app } = setup();

    expect((await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: {} })).statusCode).toBe(400);
    const created = await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "Manual Game", igdbId: null } });

    expect(created.statusCode).toBe(200);
    expect(created.json().item).toMatchObject({ title: "Manual Game" });
  });

  test("clearing the exact date while setting a month keeps the month", async () => {
    withoutIgdbEnv();
    const { app } = setup();
    const created = await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "Persona 3 Reload", completionDate: "2024-02-02" } });
    const id = created.json().item.id;

    const edited = await app.inject({ method: "PATCH", url: `/api/completed-games/${id}`, payload: { completionDate: null, completionMonth: "2024-03" } });

    expect(edited.statusCode).toBe(200);
    const detail = (await app.inject({ method: "GET", url: `/api/completed-games/${id}` })).json();
    expect(detail).toMatchObject({ completionDate: null, completionMonth: "2024-03", completionPrecision: "month" });
  });

  test("a manual game's rating score follows its rating text, not a client-sent score", async () => {
    withoutIgdbEnv();
    const { app } = setup();

    const created = await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "Metaphor", ratingRaw: "8/10", ratingScore: 3 } });

    expect(created.json().item).toMatchObject({ ratingRaw: "8/10", ratingScore: 8 });
  });

  test("manual IGDB search validates title and credentials", async () => {
    withoutIgdbEnv();
    const { app } = setup();

    expect((await app.inject({ method: "GET", url: "/api/completed-games/manual/search" })).statusCode).toBe(400);
    expect((await app.inject({ method: "GET", url: "/api/completed-games/manual/search?q=Bloodborne" })).statusCode).toBe(409);
  });

  test("manual IGDB search returns ranked completed-game candidates", async () => {
    withoutIgdbEnv();
    const { app } = setup();
    await app.inject({ method: "PATCH", url: "/api/settings", payload: { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "token" } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([
      {
        id: 19560,
        name: "Bloodborne",
        first_release_date: 1427155200,
        cover: { image_id: "cover-bloodborne" },
        platforms: [{ abbreviation: "PS4" }],
        summary: "Hunt your nightmares."
      }
    ]), { status: 200 })));

    const response = await app.inject({ method: "GET", url: "/api/completed-games/manual/search?q=Bloodborne&platform=PS4&completionYear=2026" });

    expect(response.statusCode).toBe(200);
    expect(response.json().items[0]).toMatchObject({ igdbId: 19560, title: "Bloodborne", platforms: ["PS4"], coverImageId: "cover-bloodborne" });
  });

  test("invalid selected IGDB match does not leave a partial manual game", async () => {
    withoutIgdbEnv();
    const { app } = setup();
    await app.inject({ method: "PATCH", url: "/api/settings", payload: { IGDB_CLIENT_ID: "client", IGDB_ACCESS_TOKEN: "token" } });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("[]", { status: 200 })));

    const response = await app.inject({
      method: "POST",
      url: "/api/completed-games/manual",
      payload: { title: "Missing IGDB Game", userPlatform: "PC", igdbId: 999999 }
    });

    expect(response.statusCode).toBe(404);
    expect((await app.inject({ method: "GET", url: "/api/completed-games" })).json().items).toEqual([]);
  });

  test("deletes a completed game", async () => {
    withoutIgdbEnv();
    const { app } = setup();
    await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "Bloodborne", userPlatform: "PC", ratingRaw: "9/10" } });

    const deleted = await app.inject({ method: "DELETE", url: "/api/completed-games/completed-bloodborne-pc" });
    expect(deleted.statusCode).toBe(200);
    expect(deleted.json()).toEqual({ ok: true });
    expect((await app.inject({ method: "GET", url: "/api/completed-games/completed-bloodborne-pc" })).statusCode).toBe(404);
  });
});

function withoutIgdbEnv() {
  previousIgdbEnv = {
    IGDB_CLIENT_ID: process.env.IGDB_CLIENT_ID,
    IGDB_CLIENT_SECRET: process.env.IGDB_CLIENT_SECRET,
    IGDB_ACCESS_TOKEN: process.env.IGDB_ACCESS_TOKEN
  };
  delete process.env.IGDB_CLIENT_ID;
  delete process.env.IGDB_CLIENT_SECRET;
  delete process.env.IGDB_ACCESS_TOKEN;
}

function restoreIgdbEnv() {
  for (const key of ["IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET", "IGDB_ACCESS_TOKEN"] as const) {
    if (previousIgdbEnv[key] === undefined) delete process.env[key];
    else process.env[key] = previousIgdbEnv[key];
  }
  previousIgdbEnv = {};
}
