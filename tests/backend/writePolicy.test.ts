import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { listReleases } from "../../apps/backend/src/database/releaseReadModel";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import { createManualRelease, deleteReleaseWithOptionalBlock } from "../../apps/backend/src/actions/releaseActions";
import { createReleaseArtworkWorkflow } from "../../apps/backend/src/artwork/releaseArtworkWorkflow";
import { ArtworkValidationError } from "../../apps/backend/src/artwork/localArtworkStorage";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import type { IgdbGameLike } from "../../shared/types";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-write-policy-"));
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

const silentLogger = { log: () => undefined };
const noArtwork = { steamGridClient: { findArtwork: async () => [] } };

function game(id: number, name: string): IgdbGameLike {
  return {
    id,
    name,
    game_type: 0,
    first_release_date: 1802908800,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
  };
}

function seedRelease(db: TrackerDatabase, id = "manual-1") {
  createReleaseStore(db).save({
    id,
    title: "Manual Game",
    normalizedTitle: "manual game",
    dateText: "2027",
    releaseDate: null,
    datePrecision: "Year",
    releaseWindow: "2027",
    sourceConfidence: 70,
    category: "Main",
    publishers: [],
    developers: [],
    platforms: ["Windows PC"],
    genres: [],
    artworks: [],
    screenshots: [],
    trailers: []
  } as never);
}

describe("sync run writes", () => {
  test("a game that fails to save is skipped and the rest of the sync is kept", async () => {
    const db = tempDb();
    db.exec("create trigger boom before insert on releases when new.title = 'Boom Game' begin select raise(abort, 'boom'); end");

    const status = await runSync(db, [game(1, "Boom Game"), game(2, "Good Game")], undefined, noArtwork);

    expect(listReleases(db, {}).items.map(item => item.title)).toEqual(["Good Game"]);
    expect(status).toMatchObject({ status: "partial", failed: 1 });
  });

  test("finishing a sync keeps log rows only for the latest 20 runs", async () => {
    const db = tempDb();
    const insertRun = db.prepare("insert into sync_runs (status, finished_at) values ('success', current_timestamp)");
    const insertLog = db.prepare("insert into sync_log (sync_run_id, title, action, reason) values (?, 'Older Game', 'accept', 'seed')");
    for (let index = 0; index < 21; index++) insertLog.run(insertRun.run().lastInsertRowid);

    await runSync(db, [game(501, "New Game")], undefined, noArtwork);

    expect(db.prepare("select count(*) n from sync_runs").get()).toEqual({ n: 22 });
    expect(db.prepare("select count(*) n from sync_log").get()).toEqual({ n: 20 });
    expect(db.prepare("select count(*) n from sync_log where sync_run_id <= 2").get()).toEqual({ n: 0 });
    expect(db.prepare("select title from sync_log order by id desc limit 1").get()).toEqual({ title: "New Game" });
  });

  test("a sync that hits a malformed game reports the failure and never stays running", async () => {
    const db = tempDb();

    const status = await runSync(db, [{ id: 3 } as IgdbGameLike], undefined, noArtwork);

    expect(status.status).not.toBe("success");
    expect(status.failed).toBeGreaterThan(0);
    expect(db.prepare("select count(*) n from sync_runs where status = 'running'").get()).toEqual({ n: 0 });
  });
});

describe("actions are atomic", () => {
  test("delete and block is all-or-nothing", async () => {
    const db = tempDb();
    seedRelease(db);
    db.exec("create trigger no_delete before delete on releases begin select raise(abort, 'locked'); end");

    await expect(deleteReleaseWithOptionalBlock(db, "manual-1", true, silentLogger)).rejects.toThrow("locked");

    expect(db.prepare("select count(*) n from blocked_releases").get()).toEqual({ n: 0 });
  });

  test("a manual release and its source link are saved together", async () => {
    const db = tempDb();
    db.exec("create trigger no_sources before insert on sources begin select raise(abort, 'no sources'); end");

    await expect(createManualRelease(db, { title: "Linked Game", dateText: "2027", datePrecision: "Year", sourceUrl: "https://example.test/linked" })).rejects.toThrow("no sources");

    expect(db.prepare("select count(*) n from releases").get()).toEqual({ n: 0 });
  });
});

describe("artwork writes", () => {
  function storage() {
    const written: string[] = [];
    const removed: string[] = [];
    return {
      written,
      removed,
      adapter: {
        prepareLocalArtwork: (payload: { mimeType?: string }) => {
          if (payload.mimeType === "image/gif") throw new ArtworkValidationError("Unsupported artwork file type");
          return { artwork: { imageId: "local.png", source: "local" as const, url: "/api/artworks/local/local.png" }, write: () => { written.push("local.png"); } };
        },
        removeLocalArtwork: (imageId: string) => { removed.push(imageId); }
      }
    };
  }

  test("an unsupported file type is rejected as a bad request", async () => {
    const db = tempDb();
    seedRelease(db);
    const files = storage();

    const result = await createReleaseArtworkWorkflow(db, files.adapter).saveLocalArtworkForRelease("manual-1", { mimeType: "image/gif", dataBase64: "eA==" });

    expect(result).toEqual({ ok: false, statusCode: 400, error: "Unsupported artwork file type" });
  });

  test("the file is not written when the database insert fails", async () => {
    const db = tempDb();
    seedRelease(db);
    db.exec("create trigger no_art before insert on release_artworks begin select raise(abort, 'no art'); end");
    const files = storage();

    await expect(createReleaseArtworkWorkflow(db, files.adapter).saveLocalArtworkForRelease("manual-1", { mimeType: "image/png", dataBase64: "eA==" })).rejects.toThrow("no art");

    expect(files.written).toEqual([]);
  });

  test("removing or reordering artwork on a missing release is a 404", async () => {
    const db = tempDb();
    const workflow = createReleaseArtworkWorkflow(db, storage().adapter);

    expect(await workflow.removeArtworkFromRelease("missing", "local.png")).toEqual({ ok: false, statusCode: 404, error: "Release not found" });
    expect(await workflow.reorderReleaseArtworks("missing", [])).toEqual({ ok: false, statusCode: 404, error: "Release not found" });
  });
});
