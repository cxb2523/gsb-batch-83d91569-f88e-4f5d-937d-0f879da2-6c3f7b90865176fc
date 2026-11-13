import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import type { IgdbGateway } from "../../apps/backend/src/igdb/gateway";
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

const noKeys = { hasCredentials: () => false } as unknown as IgdbGateway;

async function setup({ sample = true } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "grt-randomizer-sample-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  const app = createBackendApp({ db, autoSync: false, igdb: noKeys });
  if (sample) await app.inject({ method: "POST", url: "/api/demo" });
  return app;
}

const spin = async (app: Awaited<ReturnType<typeof setup>>, filters: object = {}) => (await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: filters })).json();

describe("Randomizer with the sample library and no IGDB keys", () => {
  test("offers the sample's filter lists and spins among its games", async () => {
    const app = await setup();

    const options = (await app.inject({ method: "GET", url: "/api/randomizer/options" })).json();
    expect(options.genres.length).toBeGreaterThan(10);
    expect(options.platforms.length).toBeGreaterThan(5);
    expect(options.sample).toBe(true);

    const result = await spin(app);
    expect(result.pick).toMatchObject({ title: expect.any(String), coverImageId: expect.any(String) });
    expect(result.reels.length).toBeGreaterThan(0);
    expect((await app.inject({ method: "GET", url: "/api/randomizer/history" })).json().items[0].title).toBe(result.pick.title);
  });

  test("applies genre, platform, rating and year filters", async () => {
    const app = await setup();
    const { genres, platforms } = (await app.inject({ method: "GET", url: "/api/randomizer/options" })).json();
    const rpg = genres.find((genre: { name: string }) => genre.name === "Role-playing (RPG)");
    const pc = platforms.find((platform: { name: string }) => platform.name.startsWith("PC"));

    for (let index = 0; index < 5; index++) {
      const { pick } = await spin(app, { genreIds: [rpg.id], platformIds: [pc.id], minRating: 70, releasedFromYear: 2010 });
      expect(pick.genres).toContain("Role-playing (RPG)");
      expect(pick.platforms.some((name: string) => name.startsWith("PC"))).toBe(true);
      expect(pick.totalRating).toBeGreaterThanOrEqual(70);
      expect(pick.releaseYear).toBeGreaterThanOrEqual(2010);
    }
  });

  test("filters that need a live IGDB search explain that they need your own keys", async () => {
    const app = await setup();

    for (const filters of [{ tagIds: [1] }, { presets: ["jrpg"] }, { madeInJapan: true }, { franchiseIds: [1] }, { similarToId: 1 }, { perspectiveIds: [1] }]) {
      const result = await spin(app, filters);
      expect(result.pick, JSON.stringify(filters)).toBeNull();
      expect(result.reason).toContain("IGDB keys");
    }
  });

  test("without the sample library, the Randomizer still asks for IGDB keys", async () => {
    const app = await setup({ sample: false });

    expect((await app.inject({ method: "GET", url: "/api/randomizer/options" })).statusCode).toBe(409);
    expect((await app.inject({ method: "POST", url: "/api/randomizer/spin", payload: {} })).statusCode).toBe(409);
  });
});
