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

function setup() {
  const dir = mkdtempSync(join(tmpdir(), "grt-yir-api-"));
  dirs.push(dir);
  process.env.GRT_DATA_DIR = dir;
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  const app = createBackendApp({ db, autoSync: false, today: () => new Date(2027, 0, 5) });
  const addGame = async (payload: Record<string, unknown>) => {
    const response = await app.inject({ method: "POST", url: "/api/completed-games/manual", payload: { userPlatform: "PC", ...payload } });
    expect(response.statusCode).toBe(200);
    return (response.json() as { item: { id: string } }).item;
  };
  return { app, db, addGame };
}

describe("Year in Review API", () => {
  test("lists years with games plus the current year, newest first", async () => {
    const { app, addGame } = setup();
    await addGame({ title: "Hades", completionDate: "2026-03-02", ratingRaw: "9" });
    await addGame({ title: "Celeste", completionYear: 2024 });

    const response = await app.inject({ method: "GET", url: "/api/year-in-review/years" });

    expect(response.json()).toEqual({ years: [
      { year: 2027, count: 0, inProgress: true },
      { year: 2026, count: 1, inProgress: false },
      { year: 2024, count: 1, inProgress: false }
    ] });
  });

  test("returns the summary of a year from the Completed Library", async () => {
    const { app, addGame } = setup();
    await addGame({ title: "Hades", completionDate: "2026-03-02", ratingRaw: "9", notes: "Run 40 finally." });
    await addGame({ title: "Celeste", completionDate: "2025-05-01" });

    const summary = (await app.inject({ method: "GET", url: "/api/year-in-review/2026" })).json();

    expect(summary).toMatchObject({ year: 2026, count: 1, previousYearCount: 1, goty: { game: { title: "Hades" }, note: "Run 40 finally." } });
    expect((await app.inject({ method: "GET", url: "/api/year-in-review/2019" })).json()).toMatchObject({ year: 2019, count: 0, goty: null });
  });

  test("refuses a year that is not a whole number between 1970 and 2100", async () => {
    const { app } = setup();
    for (const year of ["1969", "2101", "20x6", "2026.5"]) {
      expect((await app.inject({ method: "GET", url: `/api/year-in-review/${year}` })).statusCode).toBe(400);
    }
  });

  test("saves a GOTY override and theme music, and clears them", async () => {
    const { app, addGame } = setup();
    await addGame({ title: "Hades", completionDate: "2026-03-02", ratingRaw: "9" });
    const pick = await addGame({ title: "Tunic", completionDate: "2026-08-02", ratingRaw: "7" });

    const saved = await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { gotyCompletedId: pick.id, musicLink: "https://youtu.be/dQw4w9WgXcQ" } });
    expect(saved.statusCode).toBe(200);
    expect(saved.json().goty).toMatchObject({ game: { title: "Tunic" }, isOverride: true, musicVideoId: "dQw4w9WgXcQ" });

    const musicOnly = await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { musicLink: null } });
    expect(musicOnly.json().goty).toMatchObject({ game: { title: "Tunic" }, musicVideoId: null });

    const cleared = await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { gotyCompletedId: null } });
    expect(cleared.json().goty).toMatchObject({ game: { title: "Hades" }, isOverride: false });
  });

  test("refuses a bad music link or a game from another year", async () => {
    const { app, addGame } = setup();
    await addGame({ title: "Hades", completionDate: "2026-03-02" });
    const other = await addGame({ title: "Celeste", completionDate: "2025-05-01" });

    const badLink = await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { musicLink: "https://vimeo.com/123" } });
    expect(badLink.statusCode).toBe(400);
    const wrongYear = await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { gotyCompletedId: other.id } });
    expect(wrongYear.statusCode).toBe(400);
    const badYear = await app.inject({ method: "PUT", url: "/api/year-in-review/1900/settings", payload: { musicLink: null } });
    expect(badYear.statusCode).toBe(400);
  });

  test("deleting the chosen game clears the override", async () => {
    const { app, db, addGame } = setup();
    await addGame({ title: "Hades", completionDate: "2026-03-02", ratingRaw: "9" });
    const pick = await addGame({ title: "Tunic", completionDate: "2026-08-02", ratingRaw: "7" });
    await app.inject({ method: "PUT", url: "/api/year-in-review/2026/settings", payload: { gotyCompletedId: pick.id, musicLink: "dQw4w9WgXcQ" } });

    expect((await app.inject({ method: "DELETE", url: `/api/completed-games/${pick.id}` })).statusCode).toBe(200);

    expect(db.prepare("select goty_completed_id id, music_video_id music from year_in_review_settings where year = 2026").get()).toEqual({ id: null, music: "dQw4w9WgXcQ" });
    expect((await app.inject({ method: "GET", url: "/api/year-in-review/2026" })).json().goty).toMatchObject({ game: { title: "Hades" }, musicVideoId: "dQw4w9WgXcQ" });
  });

  test("matched IGDB fields reach the summary, including the rating count the hidden gem needs", async () => {
    const { app, db, addGame } = setup();
    const gem = await addGame({ title: "Tiny Gem", completionDate: "2026-04-02", ratingRaw: "9", genres: [] });
    // Stands in for an IGDB match; matching itself is covered by the Completed Library tests.
    db.prepare(`
      update completed_games set igdb_id = 77, igdb_total_rating_count = 12, igdb_genres_json = '["Puzzle"]',
        igdb_release_date = '2001-03-01', screenshots_json = '[{"imageId":"shot7"}]'
      where id = ?
    `).run(gem.id);

    const summary = (await app.inject({ method: "GET", url: "/api/year-in-review/2026" })).json();

    expect(summary.ratings.hiddenGem).toEqual({ game: expect.objectContaining({ title: "Tiny Gem" }), ratingCount: 12 });
    expect(summary.taste.genres).toEqual([{ name: "Puzzle", count: 1, share: 1, ids: ["completed-tiny-gem-pc"] }]);
    expect(summary.timing.lateToTheParty).toMatchObject({ years: 25, releaseYear: 2001 });
    expect(summary.goty.backdrop).toEqual({ imageId: "shot7", kind: "screenshot" });
  });
});
