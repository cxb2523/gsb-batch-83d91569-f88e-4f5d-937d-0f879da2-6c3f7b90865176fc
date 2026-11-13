import { afterEach, describe, expect, test, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { listReleases } from "../../apps/backend/src/database/releaseReadModel";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import { updateRelease } from "../../apps/backend/src/actions/releaseActions";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import type { IgdbGameLike } from "../../shared/types";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-release-edits-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  // Sync fixtures are credited to IGDB company 1.
  createSyncSettingsStore(db).addPublishers([{ id: 1, name: "Atlus" }]);
  return db;
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  resetWriteQueueForTests();
});

const noArtwork = { steamGridClient: { findArtwork: async () => [] } };

function igdbGame(overrides: Partial<IgdbGameLike> = {}): IgdbGameLike {
  return {
    id: 501,
    name: "Persona 4 Revival",
    game_type: 0,
    first_release_date: 1802908800,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [
      { publisher: true, company: { id: 1, name: "Atlus" } },
      { developer: true, company: { id: 2, name: "P-Studio" } }
    ],
    ...overrides
  };
}

describe("release edits and sync", () => {
  test("user edits to a synced release survive the next IGDB sync", async () => {
    const db = tempDb();
    await runSync(db, [igdbGame()], undefined, noArtwork);

    const result = await updateRelease(db, "igdb-501", {
      title: "Persona 4 Revival (my name)",
      publishers: "Sega, Atlus",
      platforms: "PC, PS5",
      category: "Remake",
      datePrecision: "Year",
      dateText: "2028",
      releaseDate: "",
      releaseWindow: "2028"
    });
    expect(result.ok).toBe(true);

    await runSync(db, [igdbGame()], undefined, noArtwork);

    const [item] = listReleases(db, {}).items;
    expect(item).toMatchObject({
      id: "igdb-501",
      title: "Persona 4 Revival (my name)",
      publishers: ["Atlus", "Sega"],
      platforms: ["PC", "PS5"],
      category: "Remake",
      datePrecision: "Year",
      dateText: "2028",
      releaseDate: null,
      releaseWindow: "2028"
    });
  });

  test("fields the user did not edit still follow IGDB", async () => {
    const db = tempDb();
    await runSync(db, [igdbGame()], undefined, noArtwork);
    await updateRelease(db, "igdb-501", { title: "Renamed" });

    await runSync(db, [igdbGame({
      involved_companies: [
        { publisher: true, company: { id: 1, name: "Atlus" } },
        { developer: true, company: { id: 3, name: "New Studio" } }
      ]
    })], undefined, noArtwork);

    const [item] = listReleases(db, {}).items;
    expect(item).toMatchObject({ title: "Renamed", developers: ["New Studio"] });
  });

  test("renamed releases stay searchable by their new title after sync", async () => {
    const db = tempDb();
    await runSync(db, [igdbGame()], undefined, noArtwork);
    await updateRelease(db, "igdb-501", { title: "Golden Tomorrow" });
    await runSync(db, [igdbGame()], undefined, noArtwork);

    expect(listReleases(db, { search: "golden" }).items.map(item => item.id)).toEqual(["igdb-501"]);
    expect(listReleases(db, { search: "Atlus" }).items.map(item => item.id)).toEqual(["igdb-501"]);
    expect(listReleases(db, { platform: "PC" }).items.map(item => item.id)).toEqual(["igdb-501"]);
  });

  test("editing the category keeps the category index in step", async () => {
    const db = tempDb();
    await runSync(db, [igdbGame()], undefined, noArtwork);
    await updateRelease(db, "igdb-501", { category: "DLC" });

    expect(db.prepare("select category from release_categories where release_id = ?").get("igdb-501")).toEqual({ category: "DLC" });
    expect(listReleases(db, { category: "DLC" }).items.map(item => item.id)).toEqual(["igdb-501"]);
  });

  test("listing releases uses a fixed number of queries regardless of list size", async () => {
    const db = tempDb();
    for (let index = 0; index < 40; index++) {
      createReleaseStore(db).save({
        id: `r-${index}`,
        title: `Game ${index}`,
        normalizedTitle: `game ${index}`,
        dateText: "2027",
        releaseDate: null,
        datePrecision: "Year",
        releaseWindow: "2027",
        sourceConfidence: 80,
        category: "Main",
        publishers: ["Atlus"],
        developers: ["Studio"],
        platforms: ["PC"],
        genres: ["RPG"],
        artworks: [{ imageId: `cover-${index}`, source: "cover" }],
        screenshots: [],
        trailers: []
      } as never);
    }
    const prepare = vi.spyOn(db, "prepare");

    const result = listReleases(db, {});

    expect(result.items).toHaveLength(40);
    expect(result.items.find(item => item.id === "r-39")).toMatchObject({ publishers: ["Atlus"], developers: ["Studio"], platforms: ["PC"], genres: ["RPG"], artworks: [{ imageId: "cover-39", source: "cover" }] });
    expect(prepare.mock.calls.length).toBeLessThanOrEqual(8);
  });
});
