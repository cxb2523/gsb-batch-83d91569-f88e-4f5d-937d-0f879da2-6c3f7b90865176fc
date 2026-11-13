import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { enqueueWrite, resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import { getRelease, listReleases } from "../../apps/backend/src/database/releaseReadModel";

let dirs: string[] = [];
let dbs: Array<{ close(): void }> = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return db;
}

afterEach(() => {
  resetWriteQueueForTests();
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("database migrations and FTS", () => {
  test("enables WAL, tracks schema version, and preserves user state", () => {
    const db = tempDb();
    expect(db.pragma("journal_mode", { simple: true })).toBe("wal");
    expect(db.prepare("select version from schema_version").get()).toEqual({ version: 21 });
    expect(db.prepare("select name from sqlite_master where type = 'table' and name = 'release_trailers'").get()).toEqual({ name: "release_trailers" });

    db.prepare("insert into releases (id, title, normalized_title, date_text, date_precision, category) values (?, ?, ?, ?, ?, ?)").run("r1", "Exodus", "exodus", "2027", "Year", "Main");
    db.prepare("insert into user_release_state (release_id, hidden, watched) values (?, 1, 1)").run("r1");
    runMigrations(db);
    expect(db.prepare("select hidden, watched from user_release_state where release_id = ?").get("r1")).toEqual({ hidden: 1, watched: 1 });
  });

  test("v14 drops the unused backlog tables and v15 replaces the old randomizer table", () => {
    const db = tempDb();
    db.exec(`
      drop table randomizer_picks;
      create table backlog_games (id text primary key);
      create table randomizer_picks (id integer primary key, backlog_game_id text);
      update schema_version set version = 13;
    `);
    runMigrations(db);
    const leftovers = db.prepare("select name from sqlite_master where type = 'table' and (name like 'backlog_%' or name like 'game_length%')").all();
    expect(leftovers).toEqual([]);
    const columns = (db.prepare("pragma table_info(randomizer_picks)").all() as Array<{ name: string }>).map(column => column.name);
    expect(columns).toContain("igdb_id");
    expect(columns).not.toContain("backlog_game_id");
  });

  test("v15 creates the randomizer pick history table", () => {
    const db = tempDb();
    expect(db.prepare("select version from schema_version").get()).toEqual({ version: 21 });
    expect(db.prepare("select name from sqlite_master where type = 'table' and name = 'randomizer_picks'").get()).toEqual({ name: "randomizer_picks" });
    db.prepare("insert into randomizer_picks (igdb_id, title) values (?, ?)").run(1942, "The Witcher 3");
    expect(db.prepare("select igdb_id igdbId, filters_json filtersJson from randomizer_picks").get()).toEqual({ igdbId: 1942, filtersJson: "{}" });
  });

  test("v19 indexes sources and the Release Store keeps FTS synchronized", () => {
    const db = tempDb();
    const indexes = db.prepare("pragma index_list(sources)").all() as Array<{ name: string }>;
    expect(indexes.map(index => index.name)).toContain("idx_sources_release_id");
    const triggers = db.prepare("select name from sqlite_master where type = 'trigger' and name like 'releases_a%'").all() as Array<{ name: string }>;
    expect(triggers.map(trigger => trigger.name)).toEqual(["releases_ad"]);

    const release = {
      id: "r1", title: "Persona 4 Revival", normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027", releaseDate: "2027-02-18", datePrecision: "Exact" as const,
      releaseWindow: null, sourceConfidence: 90, category: "Remake" as const,
      publishers: ["Atlus"], developers: [], platforms: ["PC"], genres: [], artworks: []
    };
    const store = createReleaseStore(db);
    store.save(release);
    expect(db.prepare("select rowid from releases_fts where releases_fts match ?").all("persona")).toHaveLength(1);

    store.save({ ...release, title: "Metaphor Expansion", normalizedTitle: "metaphor expansion" });
    expect(db.prepare("select rowid from releases_fts where releases_fts match ?").all("persona")).toHaveLength(0);
    expect(db.prepare("select rowid from releases_fts where releases_fts match ?").all("metaphor")).toHaveLength(1);

    store.delete("r1");
    expect(db.prepare("select rowid from releases_fts where releases_fts match ?").all("metaphor")).toHaveLength(0);
  });

  test("migrations recompute eligibility from the date alone, and the list applies the track-from date", () => {
    const db = tempDb();
    db.prepare("update schema_version set version = 15").run();
    const insert = db.prepare("insert into releases (id, title, normalized_title, date_text, release_date, date_precision, category, source_confidence) values (?, ?, ?, ?, ?, ?, ?, ?)");
    insert.run("old", "Old Game", "old game", "Dec 31, 2025", "2025-12-31", "Exact", "Main", 90);
    insert.run("new", "New Game", "new game", "Jan 1, 2026", "2026-01-01", "Exact", "Main", 90);
    insert.run("tba", "Someday Game", "someday game", "TBA", null, "TBA", "Main", 10);

    runMigrations(db);

    expect(db.prepare("select id, eligible from releases order by id").all()).toEqual([{ id: "new", eligible: 1 }, { id: "old", eligible: 1 }, { id: "tba", eligible: 0 }]);
    expect(listReleases(db, { includeHidden: true, includeReleased: true }).items.map(item => item.id)).toEqual(["old", "new"]);
    expect(listReleases(db, { includeHidden: true, includeReleased: true, releasedFrom: "2026-01-01" }).items.map(item => item.id)).toEqual(["new"]);
  });

  test("v20 keeps the publishers an older version had looked up as the user's tracked publishers", () => {
    const db = tempDb();
    db.prepare("update schema_version set version = 19").run();
    db.exec(`
      drop table tracked_publishers;
      create table publisher_sync_state (approved_term text primary key, company_ids text, company_names text, last_error text, updated_at text);
      insert into publisher_sync_state values ('Atlus', '[1]', '["Atlus"]', null, current_timestamp);
      insert into publisher_sync_state values ('Sega', '[2,3]', '["Sega","Sega Corporation"]', null, current_timestamp);
      insert into publisher_sync_state values ('Nobody', '[]', '[]', 'No IGDB company match', current_timestamp);
    `);

    runMigrations(db);

    expect(db.prepare("select company_id id, name from tracked_publishers order by company_id").all()).toEqual([
      { id: 1, name: "Atlus" },
      { id: 2, name: "Sega" },
      { id: 3, name: "Sega Corporation" }
    ]);
  });

  test("v21 adds date history and alert bookkeeping to a v20 library, keeping its releases and watchlist", () => {
    const db = tempDb();
    db.prepare("insert into releases (id, title, normalized_title, date_text, date_precision, category, source_confidence) values ('r1', 'Kept', 'kept', '2027', 'Year', 'Main', 70)").run();
    db.prepare("insert into user_release_state (release_id, watched) values ('r1', 1)").run();
    db.exec("drop table release_date_changes; drop table release_alerts_sent; update schema_version set version = 20;");

    runMigrations(db);

    expect(db.prepare("select version from schema_version").get()).toEqual({ version: 21 });
    expect(db.prepare("select name from sqlite_master where type = 'table' and name in ('release_date_changes', 'release_alerts_sent') order by name").all())
      .toEqual([{ name: "release_alerts_sent" }, { name: "release_date_changes" }]);
    expect(db.prepare("select releases.title, state.watched from releases join user_release_state state on state.release_id = releases.id").all()).toEqual([{ title: "Kept", watched: 1 }]);
  });

  test("v20 replaces the built-in publisher list with the user's tracked publishers", () => {
    const db = tempDb();

    expect(db.prepare("select name from sqlite_master where name in ('tracked_publishers', 'publisher_sync_state')").all()).toEqual([{ name: "tracked_publishers" }]);
  });

  test("migration v18 fills the rating score from the rating text where it was never set", () => {
    const db = tempDb();
    db.prepare("update schema_version set version = 17").run();
    const insert = db.prepare("insert into completed_games (id, title, normalized_title, user_platform, identity_key, rating_raw, rating_score, source_type) values (?, ?, ?, 'PC', ?, ?, ?, 'manual')");
    insert.run("a", "A", "a", "a|pc", "8.5/10", null);
    insert.run("b", "B", "b", "b|pc", "7.5.10", null);
    insert.run("c", "C", "c", "c|pc", "9/10", 6);

    runMigrations(db);

    const scores = db.prepare("select id, rating_score score from completed_games order by id").all();
    expect(scores).toEqual([{ id: "a", score: 8.5 }, { id: "b", score: null }, { id: "c", score: 6 }]);
  });

  test("Release Store save persists artwork ids and effective sort metadata", () => {
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
      developers: ["Atlus"],
      platforms: ["Windows PC"],
      genres: ["Role-playing (RPG)"],
      artworks: [{ imageId: "art-a" }, { imageId: "art-b" }],
      screenshots: [{ imageId: "sc-1" }, { imageId: "sc-2" }]
    });

    const item = listReleases(db, {}).items[0];
    expect(item.effectiveSortDate).toBe("2027-02-18");
    expect(item.artworks.map(art => art.imageId)).toEqual(["art-a", "art-b"]);
    expect("screenshots" in item).toBe(false);
    const detail = getRelease(db, "p4")!;
    expect(detail.screenshots.map(art => art.imageId)).toEqual(["sc-1", "sc-2"]);
  });

  test("list reads preserve IGDB artwork and cover source metadata", () => {
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
      developers: ["Atlus"],
      platforms: ["Windows PC"],
      genres: ["Role-playing (RPG)"],
      artworks: [
        { imageId: "wide-art", source: "artwork" },
        { imageId: "cover-art", source: "cover" }
      ]
    });

    expect(listReleases(db, {}).items[0].artworks).toEqual([
      { imageId: "wide-art", source: "artwork" },
      { imageId: "cover-art", source: "cover" }
    ]);
  });

  test("Release Store save persists and replaces screenshots independently from artworks", () => {
    const db = tempDb();
    const base = {
      id: "p4",
      title: "Persona 4 Revival",
      normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027",
      releaseDate: "2027-02-18",
      datePrecision: "Exact" as const,
      releaseWindow: null,
      sourceConfidence: 90,
      category: "Remake" as const,
      publishers: ["Atlus"],
      developers: ["Atlus"],
      platforms: ["Windows PC"],
      genres: [],
      artworks: [{ imageId: "art-a", source: "artwork" as const }],
      screenshots: [{ imageId: "sc-1", source: "artwork" as const }, { imageId: "sc-2", source: "artwork" as const }]
    };

    createReleaseStore(db).save(base);
    expect(getRelease(db, "p4")!.screenshots.map(s => s.imageId)).toEqual(["sc-1", "sc-2"]);

    createReleaseStore(db).save({ ...base, screenshots: [{ imageId: "sc-3", source: "artwork" as const }] });
    const detail = getRelease(db, "p4")!;
    expect(detail.screenshots.map(s => s.imageId)).toEqual(["sc-3"]);
    expect(detail.artworks.map(a => a.imageId)).toEqual(["art-a"]);
  });

  test("Release Store save persists and replaces trailers independently from screenshots", () => {
    const db = tempDb();
    const base = {
      id: "p4",
      title: "Persona 4 Revival",
      normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027",
      releaseDate: "2027-02-18",
      datePrecision: "Exact" as const,
      releaseWindow: null,
      sourceConfidence: 90,
      category: "Remake" as const,
      publishers: ["Atlus"],
      developers: ["Atlus"],
      platforms: ["Windows PC"],
      genres: [],
      artworks: [{ imageId: "art-a", source: "artwork" as const }],
      screenshots: [{ imageId: "sc-1", source: "artwork" as const }],
      trailers: [{ videoId: "gameplay-1", name: "Gameplay Trailer", provider: "youtube" as const }]
    };

    createReleaseStore(db).save(base);
    expect(getRelease(db, "p4")!.trailers).toEqual([{ videoId: "gameplay-1", name: "Gameplay Trailer", provider: "youtube" }]);

    createReleaseStore(db).save({ ...base, trailers: [{ videoId: "announce-2", name: "Announcement Trailer", provider: "youtube" as const }] });
    const detail = getRelease(db, "p4")!;
    expect(detail.trailers).toEqual([{ videoId: "announce-2", name: "Announcement Trailer", provider: "youtube" }]);
    expect(detail.screenshots.map(s => s.imageId)).toEqual(["sc-1"]);
  });

  test("Release Store save preserves local artwork ordering while merging provider artwork", () => {
    const db = tempDb();
    const baseRelease = {
      id: "p4",
      title: "Persona 4 Revival",
      normalizedTitle: "persona 4 revival",
      dateText: "Feb 18, 2027",
      releaseDate: "2027-02-18",
      datePrecision: "Exact" as const,
      releaseWindow: null,
      sourceConfidence: 90,
      category: "Remake" as const,
      publishers: ["Atlus"],
      developers: ["Atlus"],
      platforms: ["Windows PC"],
      genres: ["Role-playing (RPG)"],
      artworks: [{ imageId: "igdb-art", source: "artwork" as const }]
    };

    createReleaseStore(db).save(baseRelease);
    createReleaseStore(db).addArtwork("p4", { imageId: "local.png", source: "local", url: "/api/artworks/local/local.png" });
    createReleaseStore(db).reorderArtworks("p4", ["local.png", "igdb-art"]);
    createReleaseStore(db).save({
      ...baseRelease,
      artworks: [
        { imageId: "igdb-art-2", source: "artwork" as const },
        { imageId: "sgdb-grid", source: "steamgriddb" as const, url: "https://cdn2.steamgriddb.com/grid/sgdb-grid.jpg" }
      ]
    });

    expect(listReleases(db, {}).items[0].artworks).toEqual([
      { imageId: "local.png", source: "local", url: "/api/artworks/local/local.png" },
      { imageId: "igdb-art-2", source: "artwork" },
      { imageId: "sgdb-grid", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/sgdb-grid.jpg" }
    ]);
  });

  test("Release Store save refreshes FTS for publisher, developer, and source fields", () => {
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
      genres: [],
      sourceUrls: ["https://example.test/persona"],
      artworks: []
    });

    expect(listReleases(db, { search: "Atlus" }).items.map(item => item.id)).toEqual(["p4"]);
    expect(listReleases(db, { search: "P-Studio" }).items.map(item => item.id)).toEqual(["p4"]);
    expect(listReleases(db, { search: "example" }).items.map(item => item.id)).toEqual(["p4"]);
  });

  test("punctuation-only search does not issue an invalid FTS query", () => {
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
      developers: [],
      platforms: ["Windows PC"],
      genres: [],
      artworks: []
    });

    expect(listReleases(db, { search: "!!!" }).items.map(item => item.id)).toEqual(["p4"]);
  });
});

describe("write queue", () => {
  test("serializes writes so patch and sync mutations do not race", async () => {
    const order: string[] = [];
    await Promise.all([
      enqueueWrite(async () => {
        order.push("sync-start");
        await new Promise(resolve => setTimeout(resolve, 20));
        order.push("sync-end");
      }),
      enqueueWrite(async () => {
        order.push("patch");
      })
    ]);

    expect(order).toEqual(["sync-start", "sync-end", "patch"]);
  });
});
