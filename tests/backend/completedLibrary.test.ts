import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { completedIdentityKey } from "../../apps/backend/src/completed/completedIdentity";
import { normalizeText } from "../../apps/backend/src/text/normalizeText";
import { createCompletedGameStore } from "../../apps/backend/src/completed/completedGameStore";
import { updateCompletedGame } from "../../apps/backend/src/actions/completedActions";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-completed-"));
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
  resetWriteQueueForTests();
});

// Fixture: a manual IGDB match saved earlier for a title and platform.
function seedMatchOverride(db: TrackerDatabase, title: string, userPlatform: string, igdbId: number) {
  db.prepare("insert into completed_match_overrides (identity_key, normalized_title, user_platform, igdb_id) values (?, ?, ?, ?)")
    .run(completedIdentityKey(title, userPlatform), normalizeText(title), userPlatform, igdbId);
}

function matchOverride(db: TrackerDatabase, identityKey: string) {
  return db.prepare("select igdb_id igdbId from completed_match_overrides where identity_key = ?").get(identityKey);
}

describe("completed library", () => {
  test("migration creates completed-library tables without changing release tables", async () => {
    const db = tempDb();

    expect(db.prepare("select name from sqlite_master where type = 'table' and name = 'completed_games'").get()).toEqual({ name: "completed_games" });
    expect(db.prepare("select name from sqlite_master where type = 'table' and name = 'releases'").get()).toEqual({ name: "releases" });
  });

  test("a rating typed in the app sets its score, when adding a game and when editing it", () => {
    const store = createCompletedGameStore(tempDb());
    const manual = store.createManual({ title: "Nioh 3", userPlatform: "PC", ratingRaw: "8.5/10", completionDate: "2026-03-01" });
    expect(store.getDetail(manual.id)).toMatchObject({ ratingRaw: "8.5/10", ratingScore: 8.5 });

    expect(store.edit(manual.id, { ratingRaw: "95%" })).toEqual({ ok: true });
    expect(store.getDetail(manual.id)).toMatchObject({ ratingRaw: "95%", ratingScore: 9.5 });
    expect(store.edit(manual.id, { ratingRaw: null })).toEqual({ ok: true });
    expect(store.getDetail(manual.id)).toMatchObject({ ratingRaw: null, ratingScore: null });
  });

  test("manual completed games derive grouping date fields", async () => {
    const db = tempDb();
    const store = createCompletedGameStore(db);

    const manual = store.createManual({ title: "Manual Game", completionDate: "17 07 2026" });
    expect(manual).toMatchObject({
      title: "Manual Game",
      completionDate: "2026-07-17",
      completionMonth: "2026-07",
      completionYear: 2026,
      completionPrecision: "exact"
    });
  });

  test("migration v16 backfills completion dates written by older versions", async () => {
    const db = tempDb();
    db.prepare("update schema_version set version = 15").run();
    db.prepare(`
      insert into completed_games (
        id, title, normalized_title, user_platform, identity_key,
        platforms_json, completion_date, completion_month, completion_year, completion_precision
      ) values (?, ?, ?, ?, ?, ?, ?, null, null, 'none')
    `).run(
      "completed-adventure-of-elliot-pc",
      "Adventure of Elliot",
      "adventure of elliot",
      "PC",
      "adventure of elliot::PC",
      JSON.stringify(["PC"]),
      "17 07 2026"
    );

    runMigrations(db);

    const item = createCompletedGameStore(db).getDetail("completed-adventure-of-elliot-pc");
    expect(item).toMatchObject({
      completionDate: "2026-07-17",
      completionMonth: "2026-07",
      completionYear: 2026,
      completionPrecision: "exact"
    });
  });
});

describe("completed library identity", () => {
  test("a match override follows a renamed game", async () => {
    const db = tempDb();
    const store = createCompletedGameStore(db);
    store.createManual({ title: "Hollow Knight", userPlatform: "PC" });
    seedMatchOverride(db, "Hollow Knight", "PC", 77);

    await updateCompletedGame(db, "completed-hollow-knight-pc", { title: "Hollow Knight (Voidheart)" });

    expect(matchOverride(db, "hollow knight voidheart|pc")).toEqual({ igdbId: 77 });
    expect(matchOverride(db, "hollow knight|pc")).toBeUndefined();
  });

  test("renaming onto another game's title and platform is refused", async () => {
    const db = tempDb();
    const store = createCompletedGameStore(db);
    store.createManual({ title: "Celeste", userPlatform: "PC" });
    store.createManual({ title: "Celeste B-Sides", userPlatform: "PC" });

    const result = await updateCompletedGame(db, "completed-celeste-b-sides-pc", { title: "Celeste" });

    expect(result).toMatchObject({ ok: false, statusCode: 409 });
    expect(store.getDetail("completed-celeste-b-sides-pc")?.title).toBe("Celeste B-Sides");
  });

  test("a new game can reuse a title that another game was renamed away from", async () => {
    const db = tempDb();
    const store = createCompletedGameStore(db);
    store.createManual({ title: "Okami", userPlatform: "PS2" });
    await updateCompletedGame(db, "completed-okami-ps2", { title: "Okami HD" });

    const again = store.createManual({ title: "Okami", userPlatform: "PS2" });

    expect(again.title).toBe("Okami");
    expect(store.list({}).items.map(item => item.title).sort()).toEqual(["Okami", "Okami HD"]);
  });
});
