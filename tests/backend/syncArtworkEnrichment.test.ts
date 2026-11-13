import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { fetchSyncArtworkEnrichment } from "../../apps/backend/src/sync/syncArtworkEnrichment";
import { prepareSyncCandidate } from "../../apps/backend/src/sync/releaseSyncPlanner";
import { createReleasePolicy } from "../../apps/backend/src/sync/releasePolicy";
import type { IgdbGameLike } from "../../shared/types";

// The sync rules these tests run under: Atlus (IGDB company 1) on PC from 2026.
const policy = createReleasePolicy({ publisherIds: [1], platforms: ["pc"], trackFrom: "2026-01-01" });
const prepare = (game: IgdbGameLike) => prepareSyncCandidate(game, policy);

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb() {
  const dir = mkdtempSync(join(tmpdir(), "grt-enrichment-"));
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

describe("sync artwork enrichment", () => {
  test("enriches only accepted candidates that still need provider artwork", async () => {
    const db = tempDb();
    const calls: string[] = [];
    const enrichment = await fetchSyncArtworkEnrichment(db, [
      game(101, "Needs Artwork"),
      game(102, "Too Old", 1735603200),
      {
        ...game(103, "Already Has Cover"),
        cover: { image_id: "cover-103" }
      }
    ].map(prepare), {
      findArtwork: async title => {
        calls.push(title);
        return [{ imageId: `sgdb-${title}`, source: "steamgriddb" as const, url: `https://cdn2.steamgriddb.com/grid/${encodeURIComponent(title)}.jpg` }];
      }
    });

    expect(calls).toEqual(["Needs Artwork"]);
    expect(enrichment.failed).toBe(0);
    expect(enrichment.artworksByIgdbId.get(101)).toEqual([
      { imageId: "sgdb-Needs Artwork", source: "steamgriddb", url: "https://cdn2.steamgriddb.com/grid/Needs%20Artwork.jpg" }
    ]);
    expect(enrichment.artworksByIgdbId.has(102)).toBe(false);
    expect(enrichment.artworksByIgdbId.has(103)).toBe(false);
  });

  test("looks up up to four games at a time and keeps every result", async () => {
    const db = tempDb();
    let running = 0;
    let peak = 0;
    const games = Array.from({ length: 10 }, (_, index) => game(400 + index, `Parallel ${index}`));

    const enrichment = await fetchSyncArtworkEnrichment(db, games.map(prepare), {
      findArtwork: async title => {
        running++;
        peak = Math.max(peak, running);
        await new Promise(resolve => setTimeout(resolve, 10));
        running--;
        return [{ imageId: `sgdb-${title}`, source: "steamgriddb" as const, url: `https://cdn2.steamgriddb.com/${title}.jpg` }];
      }
    });

    expect(peak).toBe(4);
    expect(enrichment.artworksByIgdbId.size).toBe(10);
  });

  test("never looks up blocked games", async () => {
    const db = tempDb();
    db.prepare("insert into blocked_releases (id, igdb_id, normalized_title, title, reason) values ('b1', 301, 'blocked game', 'Blocked Game', 'Manual delete')").run();
    const calls: string[] = [];

    await fetchSyncArtworkEnrichment(db, [game(301, "Blocked Game"), game(302, "Wanted Game")].map(prepare), {
      findArtwork: async title => {
        calls.push(title);
        return [];
      }
    });

    expect(calls).toEqual(["Wanted Game"]);
  });

  test("skips existing local artwork and counts provider failures", async () => {
    const db = tempDb();
    db.prepare(`
      insert into releases (id, igdb_id, title, normalized_title, date_text, release_date, date_precision, category, eligible, effective_sort_date)
      values ('igdb-201', 201, 'Local Artwork Game', 'local artwork game', 'Feb 18, 2027', '2027-02-18', 'Exact', 'Main', 1, '2027-02-18')
    `).run();
    db.prepare("insert into release_artworks (release_id, image_id, source, url, sort_order) values (?, ?, ?, ?, ?)").run("igdb-201", "local.png", "local", "/api/artworks/local/local.png", 0);
    const calls: string[] = [];
    const enrichment = await fetchSyncArtworkEnrichment(db, [
      game(201, "Local Artwork Game"),
      game(202, "Provider Failure")
    ].map(prepare), {
      findArtwork: async title => {
        calls.push(title);
        throw new Error("SteamGridDB 500");
      }
    });

    expect(calls).toEqual(["Provider Failure"]);
    expect(enrichment.failed).toBe(1);
    expect(enrichment.artworksByIgdbId.size).toBe(0);
  });
});

function game(id: number, name: string, firstReleaseDate = 1802908800): IgdbGameLike {
  return {
    id,
    name,
    game_type: 0,
    first_release_date: firstReleaseDate,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [{ publisher: true, company: { id: 1, name: "Atlus" } }]
  };
}
