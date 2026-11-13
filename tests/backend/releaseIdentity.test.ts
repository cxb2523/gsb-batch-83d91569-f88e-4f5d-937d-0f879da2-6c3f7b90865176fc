import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { listReleases } from "../../apps/backend/src/database/releaseReadModel";
import { createManualRelease, updateRelease } from "../../apps/backend/src/actions/releaseActions";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import type { IgdbGameLike } from "../../shared/types";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-release-identity-"));
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
    id: 777,
    name: "Trails Beyond the Horizon",
    game_type: 0,
    first_release_date: 1802908800,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [{ publisher: true, company: { id: 1, name: "NIS America" } }],
    ...overrides
  };
}

async function manualFromIgdb(db: TrackerDatabase) {
  return createManualRelease(db, {
    igdbId: 777,
    title: "Trails Beyond the Horizon",
    publishers: "NIS America",
    platforms: "Windows PC",
    dateText: "2027",
    datePrecision: "Year",
    releaseWindow: "2027"
  });
}

describe("release identity", () => {
  test("a game added from IGDB search is not duplicated by the next sync", async () => {
    const db = tempDb();
    const created = await manualFromIgdb(db);
    expect(created.ok).toBe(true);

    await runSync(db, [igdbGame()], undefined, noArtwork);

    const items = listReleases(db, {}).items;
    expect(items).toHaveLength(1);
    expect(items[0].id).toMatch(/^manual-/);
  });

  test("sync keeps a manually added IGDB game up to date and respects later edits", async () => {
    const db = tempDb();
    await manualFromIgdb(db);
    const [manual] = listReleases(db, {}).items;
    await updateRelease(db, manual.id, { title: "Trails (my name)" });

    await runSync(db, [igdbGame({ involved_companies: [{ publisher: true, company: { id: 1, name: "NIS America" } }, { developer: true, company: { id: 2, name: "Nihon Falcom" } }] })], undefined, noArtwork);

    const items = listReleases(db, {}).items;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ id: manual.id, title: "Trails (my name)", developers: ["Nihon Falcom"] });
  });

  test("adding a game from IGDB that sync already tracks returns the tracked release", async () => {
    const db = tempDb();
    await runSync(db, [igdbGame()], undefined, noArtwork);

    const created = await manualFromIgdb(db);

    expect(created).toMatchObject({ ok: true, value: { item: { id: "igdb-777" } } });
    expect(listReleases(db, {}).items).toHaveLength(1);
  });
});
