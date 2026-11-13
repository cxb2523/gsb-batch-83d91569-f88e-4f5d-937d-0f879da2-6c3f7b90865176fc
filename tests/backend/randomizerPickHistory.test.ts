import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createPickHistoryStore, PICK_HISTORY_LIMIT } from "../../apps/backend/src/randomizer/pickHistoryStore";

let cleanup: Array<() => void> = [];

function tempDb(): TrackerDatabase {
  const dir = mkdtempSync(join(tmpdir(), "grt-picks-"));
  const db = openDatabase(join(dir, "tracker.db"));
  runMigrations(db);
  cleanup.push(() => { db.close(); rmSync(dir, { recursive: true, force: true }); });
  return db;
}

afterEach(() => {
  for (const run of cleanup) run();
  cleanup = [];
});

describe("randomizer pick history store", () => {
  test("lists picks newest first with their filters stored", () => {
    const db = tempDb();
    const store = createPickHistoryStore(db);
    store.record({ igdbId: 1, title: "Hades", coverImageId: "c1" }, { genreIds: [12] });
    store.record({ igdbId: 2, title: "Celeste" });

    expect(store.list(10).map(item => [item.igdbId, item.title, item.coverImageId])).toEqual([[2, "Celeste", null], [1, "Hades", "c1"]]);
    expect(db.prepare("select filters_json f from randomizer_picks where igdb_id = 1").get()).toEqual({ f: '{"genreIds":[12]}' });
  });

  test("recent ids are distinct, newest first, and limited", () => {
    const store = createPickHistoryStore(tempDb());
    for (const igdbId of [1, 2, 1, 3]) store.record({ igdbId, title: `Game ${igdbId}` });

    expect(store.recentIgdbIds(4)).toEqual([3, 1, 2]);
    expect(store.recentIgdbIds(1)).toEqual([3]);
    expect(store.recentIgdbIds(0)).toEqual([]);
  });

  test("keeps only the newest rows and clears everything on request", () => {
    const store = createPickHistoryStore(tempDb());
    for (let index = 1; index <= PICK_HISTORY_LIMIT + 5; index++) store.record({ igdbId: index, title: `Game ${index}` });

    const all = store.list(PICK_HISTORY_LIMIT + 10);
    expect(all).toHaveLength(PICK_HISTORY_LIMIT);
    expect(all[0].igdbId).toBe(PICK_HISTORY_LIMIT + 5);
    expect(all.at(-1)?.igdbId).toBe(6);

    store.clear();
    expect(store.list(10)).toEqual([]);
  });
});
