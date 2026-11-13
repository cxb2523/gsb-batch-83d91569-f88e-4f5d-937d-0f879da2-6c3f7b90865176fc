import { afterEach, describe, expect, test, vi } from "vitest";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
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

const JPEG = Buffer.from([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3, 4]);

function openApp(fetchCover: (url: string) => Promise<Response>, apiToken?: string) {
  const dir = mkdtempSync(join(tmpdir(), "grt-covers-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return { dir, app: createBackendApp({ db, autoSync: false, fetchCover, apiToken }) };
}

const imageResponse = () => new Response(JPEG, { status: 200, headers: { "content-type": "image/jpeg" } });

describe("cover cache", () => {
  test("downloads a cover once into app data, then serves it from disk", async () => {
    const fetchCover = vi.fn(async () => imageResponse());
    const { app, dir } = openApp(fetchCover);

    const first = await app.inject({ method: "GET", url: "/api/covers/co2vvt" });
    expect(first.statusCode).toBe(200);
    expect(first.headers["content-type"]).toBe("image/jpeg");
    expect(first.rawPayload.equals(JPEG)).toBe(true);
    expect(fetchCover).toHaveBeenCalledWith("https://images.igdb.com/igdb/image/upload/t_cover_big_2x/co2vvt.jpg");
    expect(existsSync(join(dir, "covers", "co2vvt.jpg"))).toBe(true);

    const second = await app.inject({ method: "GET", url: "/api/covers/co2vvt" });
    expect(second.rawPayload.equals(JPEG)).toBe(true);
    expect(fetchCover).toHaveBeenCalledTimes(1);
  });

  test("only IGDB image ids are accepted, so the path can't leave the covers folder", async () => {
    const fetchCover = vi.fn(async () => imageResponse());
    const { app } = openApp(fetchCover);
    for (const id of ["..%2Fsecret", "CO2VVT", "a".repeat(41), "co2vvt.png"]) {
      expect((await app.inject({ method: "GET", url: `/api/covers/${id}` })).statusCode).toBe(400);
    }
    expect(fetchCover).not.toHaveBeenCalled();
  });

  test("a failed or non-image download is a 404 and nothing is saved", async () => {
    for (const response of [new Response("nope", { status: 500 }), new Response("<html>", { status: 200, headers: { "content-type": "text/html" } })]) {
      const { app, dir } = openApp(async () => response);
      expect((await app.inject({ method: "GET", url: "/api/covers/co2vvt" })).statusCode).toBe(404);
      expect(existsSync(join(dir, "covers", "co2vvt.jpg"))).toBe(false);
    }
    const { app } = openApp(async () => { throw new Error("offline"); });
    expect((await app.inject({ method: "GET", url: "/api/covers/co2vvt" })).statusCode).toBe(404);
  });

  test("an <img> can load covers without the app token", async () => {
    const { app } = openApp(async () => imageResponse(), "secret-token");
    const response = await app.inject({ method: "GET", url: "/api/covers/co2vvt", headers: { host: "127.0.0.1:1234" } });
    expect(response.statusCode).toBe(200);
  });
});
