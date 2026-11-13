import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { createReleaseArtworkWorkflow } from "../../apps/backend/src/artwork/releaseArtworkWorkflow";
import { createReleaseStore } from "../../apps/backend/src/database/releaseStore";
import type { ReleaseArtwork } from "../../shared/types";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-artwork-workflow-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  return db;
}

function seedRelease(db: TrackerDatabase) {
  createReleaseStore(db).save({
    id: "manual-1",
    title: "Manual Game",
    normalizedTitle: "manual game",
    dateText: "Feb 18, 2027",
    releaseDate: "2027-02-18",
    datePrecision: "Exact",
    releaseWindow: null,
    sourceConfidence: 70,
    category: "Main",
    publishers: [],
    developers: [],
    platforms: ["Windows PC"],
    genres: [],
    artworks: [{ imageId: "igdb-art", source: "artwork" }]
  });
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("release artwork workflow", () => {
  test("saves local artwork through storage and returns refreshed release detail", async () => {
    const db = tempDb();
    seedRelease(db);
    const saved: ReleaseArtwork = { imageId: "local.png", source: "local", url: "/api/artworks/local/local.png" };
    const workflow = createReleaseArtworkWorkflow(db, {
      prepareLocalArtwork: () => ({ artwork: saved, write: () => undefined }),
      removeLocalArtwork: () => undefined
    });

    const result = await workflow.saveLocalArtworkForRelease("manual-1", { fileName: "hero.png", mimeType: "image/png", dataBase64: "ZmFrZQ==" });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.value.artwork).toEqual(saved);
    expect(result.value.item.artworks.map(art => art.imageId)).toEqual(["igdb-art", "local.png"]);
  });

  test("does not write artwork files for missing releases", async () => {
    const db = tempDb();
    let saveCalls = 0;
    const workflow = createReleaseArtworkWorkflow(db, {
      prepareLocalArtwork: () => ({ artwork: { imageId: "local.png", source: "local" }, write: () => { saveCalls++; } }),
      removeLocalArtwork: () => undefined
    });

    const result = await workflow.saveLocalArtworkForRelease("missing", { fileName: "hero.png", mimeType: "image/png", dataBase64: "ZmFrZQ==" });

    expect(result).toEqual({ ok: false, statusCode: 404, error: "Release not found" });
    expect(saveCalls).toBe(0);
  });

  test("removes local files only when the release artwork source is local", async () => {
    const db = tempDb();
    seedRelease(db);
    db.prepare("insert into release_artworks (release_id, image_id, source, url, sort_order) values (?, ?, ?, ?, ?)").run("manual-1", "local.png", "local", "/api/artworks/local/local.png", 1);
    const removed: string[] = [];
    const workflow = createReleaseArtworkWorkflow(db, {
      prepareLocalArtwork: () => ({ artwork: { imageId: "unused", source: "local" }, write: () => undefined }),
      removeLocalArtwork: imageId => {
        removed.push(imageId);
      }
    });

    await workflow.removeArtworkFromRelease("manual-1", "igdb-art");
    await workflow.removeArtworkFromRelease("manual-1", "local.png");

    expect(removed).toEqual(["local.png"]);
    const reordered = await workflow.reorderReleaseArtworks("manual-1", []);
    expect(reordered.ok && reordered.value.item?.artworks).toEqual([]);
  });
});
