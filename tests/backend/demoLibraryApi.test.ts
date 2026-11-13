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

function setup(today = new Date("2026-09-25T12:00:00Z")) {
  const dir = mkdtempSync(join(tmpdir(), "grt-demo-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return createBackendApp({ db, autoSync: false, today: () => today });
}

describe("sample library", () => {
  test("loads upcoming releases and a finished-games library with made-up ratings, dates and platforms", async () => {
    const app = setup();

    const loaded = await app.inject({ method: "POST", url: "/api/demo" });

    expect(loaded.json()).toEqual({ loaded: true, releases: 30, completedGames: 46 });
    const releases = (await app.inject({ method: "GET", url: "/api/releases" })).json().items;
    expect(releases).toHaveLength(30);
    expect(releases.every((release: { artworks: unknown[] }) => release.artworks.length > 0)).toBe(true);
    const completed = (await app.inject({ method: "GET", url: "/api/completed-games" })).json().items;
    expect(completed).toHaveLength(46);
    expect(completed.every((game: { coverImageId: string | null; ratingScore: number | null }) => game.coverImageId && game.ratingScore !== null)).toBe(true);
  });

  test("last year gets a full Year in Review, and this year only has finishes up to today", async () => {
    const app = setup(new Date("2026-03-10T12:00:00Z"));
    await app.inject({ method: "POST", url: "/api/demo" });

    const years = (await app.inject({ method: "GET", url: "/api/year-in-review/years" })).json().years;
    const lastYear = years.find((entry: { year: number }) => entry.year === 2025);
    expect(lastYear.count).toBe(38);
    const thisYear = (await app.inject({ method: "GET", url: "/api/completed-games?year=2026" })).json().items;
    expect(thisYear.every((game: { completionDate: string }) => game.completionDate <= "2026-03-10")).toBe(true);
  });

  test.each([
    ["2026-09-25", "2026-08-07", "Aug 07, 2026"],
    ["2031-05-15", "2031-04-07", "Apr 07, 2031"],
    // In January, last month is last year, which the default "from January 1" filter would hide.
    ["2031-01-15", "2031-01-07", "Jan 07, 2031"]
  ])("on %s the sample's upcoming list starts last month or January, with most games still to come", async (today, firstDate, firstText) => {
    const app = setup(new Date(`${today}T12:00:00Z`));
    await app.inject({ method: "POST", url: "/api/demo" });

    const releases = (await app.inject({ method: "GET", url: "/api/releases" })).json().items as Array<{ releaseDate: string | null; dateText: string; datePrecision: string }>;
    expect(releases).toHaveLength(30);
    expect(releases[0]).toMatchObject({ releaseDate: firstDate, dateText: firstText });
    const exact = releases.filter(release => release.datePrecision === "Exact");
    expect(exact.every(release => /^\d{4}-\d{2}-\d{2}$/.test(release.releaseDate!) && !Number.isNaN(Date.parse(release.releaseDate!)))).toBe(true);
    expect(exact.filter(release => release.releaseDate! >= today).length).toBeGreaterThan(20);
  });

  test("is loaded once, and removing it leaves the user's own games alone", async () => {
    const app = setup();
    await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { title: "My Own Game", userPlatform: "PC" } });
    await app.inject({ method: "POST", url: "/api/demo" });

    expect((await app.inject({ method: "POST", url: "/api/demo" })).statusCode).toBe(409);
    expect((await app.inject({ method: "GET", url: "/api/demo" })).json()).toEqual({ loaded: true });

    expect((await app.inject({ method: "DELETE", url: "/api/demo" })).json()).toEqual({ loaded: false });
    expect((await app.inject({ method: "GET", url: "/api/releases" })).json().items).toEqual([]);
    expect((await app.inject({ method: "GET", url: "/api/completed-games" })).json().items.map((game: { title: string }) => game.title)).toEqual(["My Own Game"]);
    expect((await app.inject({ method: "GET", url: "/api/demo" })).json()).toEqual({ loaded: false });
  });
});
