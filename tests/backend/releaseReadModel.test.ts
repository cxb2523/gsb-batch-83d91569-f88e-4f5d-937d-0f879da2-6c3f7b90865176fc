import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { getRelease, listReleases } from "../../apps/backend/src/database/releaseReadModel";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-read-model-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return db;
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("release read model", () => {
  test("lists filtered releases with related artwork and state", () => {
    const db = tempDb();
    createReleaseStore(db).save({
      id: "p4",
      title: "Persona 4 Revival",
      normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027",
      releaseDate: "2027-02-18",
      datePrecision: "Exact",
      releaseWindow: null,
      sourceConfidence: 90,
      category: "Remake",
      publishers: ["Atlus"],
      developers: ["P-Studio"],
      platforms: ["Windows PC"],
      genres: ["Role-playing (RPG)", "Adventure"],
      artworks: [{ imageId: "sgdb-p4", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/p4.jpg" }]
    });
    db.prepare("insert into user_release_state (release_id, watched) values (?, 1)").run("p4");

    const result = listReleases(db, { search: "persona", publisher: "Atlus" });

    expect(result.items).toHaveLength(1);
    expect(result.items[0]).toMatchObject({
      id: "p4",
      title: "Persona 4 Revival",
      watched: true,
      genres: ["Adventure", "Role-playing (RPG)"],
      artworks: [{ imageId: "sgdb-p4", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/p4.jpg" }]
    });
  });

  test("returns release detail with sources and user state", () => {
    const db = tempDb();
    createReleaseStore(db).save({
      id: "manual-1",
      title: "Manual Game",
      normalizedTitle: "manual game",
      dateText: "2027",
      releaseDate: null,
      datePrecision: "Year",
      releaseWindow: "2027",
      sourceConfidence: 70,
      category: "Main",
      publishers: ["NIS America"],
      developers: [],
      platforms: ["Windows PC"],
      genres: [],
      sourceUrls: ["https://example.test/manual-game"],
      artworks: []
    });
    db.prepare("insert into user_release_state (release_id, hidden, released) values (?, 1, 1)").run("manual-1");

    expect(getRelease(db, "manual-1")).toMatchObject({
      id: "manual-1",
      hidden: true,
      released: true,
      sources: [{ sourceName: "Release", sourceUrl: "https://example.test/manual-game", field: "release" }]
    });
  });

  test("watched only lists just the releases the user is watching", () => {
    const db = tempDb();
    const store = createReleaseStore(db);
    for (const id of ["a", "b"]) {
      store.save({
        id, title: `Game ${id}`, normalizedTitle: `game ${id}`, dateText: "2027", releaseDate: null, datePrecision: "Year",
        releaseWindow: "2027", sourceConfidence: 70, category: "Main", publishers: [], developers: [], platforms: [], genres: [], artworks: []
      });
    }
    db.prepare("insert into user_release_state (release_id, watched) values (?, 1)").run("b");

    expect(listReleases(db, {}).items.map(item => item.id)).toEqual(["a", "b"]);
    expect(listReleases(db, { watchedOnly: true }).items.map(item => item.id)).toEqual(["b"]);
  });
});
