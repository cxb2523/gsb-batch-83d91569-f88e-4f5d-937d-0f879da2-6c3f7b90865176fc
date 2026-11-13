import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createBackendApp } from "../../apps/backend/src/server";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";
import type { IgdbGameLike } from "../../shared/types";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-alerts-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
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
const game = (id: number, name: string, day: string): IgdbGameLike => ({
  id,
  name,
  game_type: 0,
  first_release_date: Date.parse(`${day}T12:00:00Z`) / 1000,
  platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
  involved_companies: [{ publisher: true, company: { id: 1, name: "NIS America" } }]
});
const watch = (db: TrackerDatabase, id: string) => db.prepare("insert into user_release_state (release_id, watched) values (?, 1)").run(id);
const today = new Date(2027, 2, 14, 9, 0);

async function takeAlerts(db: TrackerDatabase) {
  const response = await createBackendApp({ db, autoSync: false, today: () => today }).inject({ method: "POST", url: "/api/alerts/take" });
  return response.json().items as Array<{ releaseId: string; kind: string; title: string; body: string }>;
}

describe("release alerts", () => {
  test("a watched game out today and a watched game's new date each alert once; unwatched games never do", async () => {
    const db = tempDb();
    await runSync(db, [game(1, "Out Now", "2027-03-14"), game(2, "Slipping", "2027-04-01"), game(3, "Not Watched", "2027-03-14")], undefined, noArtwork);
    watch(db, "igdb-1");
    watch(db, "igdb-2");
    await runSync(db, [game(1, "Out Now", "2027-03-14"), game(2, "Slipping", "2027-09-01"), game(3, "Not Watched", "2027-03-14")], undefined, noArtwork);

    const alerts = await takeAlerts(db);
    expect(alerts.map(alert => [alert.releaseId, alert.kind, alert.title])).toEqual([
      ["igdb-1", "out", "Out today: Out Now"],
      ["igdb-2", "delayed", "Delayed: Slipping"]
    ]);
    expect(alerts[1].body).toMatch(/^Now .+, was .+\.$/);

    expect(await takeAlerts(db)).toEqual([]);
  });

  test("turning alerts off in sync settings stops them", async () => {
    const db = tempDb();
    await runSync(db, [game(1, "Out Now", "2027-03-14")], undefined, noArtwork);
    watch(db, "igdb-1");
    createSyncSettingsStore(db).update({ alerts: false });

    expect(await takeAlerts(db)).toEqual([]);
    createSyncSettingsStore(db).update({ alerts: true });
    expect(await takeAlerts(db)).toHaveLength(1);
  });

  test("a date change from before you watched the game is history, not an alert", async () => {
    const db = tempDb();
    await runSync(db, [game(2, "Slipping", "2027-04-01")], undefined, noArtwork);
    await runSync(db, [game(2, "Slipping", "2027-09-01")], undefined, noArtwork);
    db.prepare("update release_date_changes set changed_at = datetime('now', '-2 days')").run();
    watch(db, "igdb-2");

    expect(await takeAlerts(db)).toEqual([]);
  });

  test("a date change older than a week is history, not an alert", async () => {
    const db = tempDb();
    await runSync(db, [game(2, "Slipping", "2027-04-01")], undefined, noArtwork);
    await runSync(db, [game(2, "Slipping", "2027-09-01")], undefined, noArtwork);
    db.prepare("update release_date_changes set changed_at = datetime('now', '-8 days')").run();
    watch(db, "igdb-2");

    expect(await takeAlerts(db)).toEqual([]);
  });
});
