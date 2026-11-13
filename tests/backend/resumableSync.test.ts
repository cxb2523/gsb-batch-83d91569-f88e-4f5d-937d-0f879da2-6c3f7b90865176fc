import { afterEach, describe, expect, test } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { openDatabase, type TrackerDatabase } from "../../apps/backend/src/database/db";
import { runMigrations } from "../../apps/backend/src/database/migrations";
import { resetWriteQueueForTests } from "../../apps/backend/src/database/writeQueue";
import {
  collectIgdbCandidatesWithProgress,
  MAX_GAMES_PER_COMPANY_BATCH,
  PAGE_SIZE,
  PUBLISHER_BATCH_SIZE,
  buildPublisherGameQuery
} from "../../apps/backend/src/sync/igdbCandidateSource";
import { runSync } from "../../apps/backend/src/sync/syncRun";
import { createSyncSettingsStore } from "../../apps/backend/src/sync/syncSettingsStore";
import type { IgdbGameLike } from "../../shared/types";

let dirs: string[] = [];
let dbs: TrackerDatabase[] = [];

function tempDb(publishers: number[] = [100]) {
  const dir = mkdtempSync(join(tmpdir(), "grt-resumable-sync-"));
  dirs.push(dir);
  const db = openDatabase(join(dir, "tracker.db"));
  dbs.push(db);
  runMigrations(db);
  createSyncSettingsStore(db).addPublishers(publishers.map((id, index) => ({ id, name: `Publisher ${index}` })));
  return db;
}

afterEach(() => {
  for (const db of dbs) db.close();
  dbs = [];
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  resetWriteQueueForTests();
});

// Deterministic IGDB id for a (company batch, page offset): ids stay unique across batches and pages,
// except when repeatIds is on, where every page carries the same five ids.
function idFor(batchIndex: number, offset: number, indexOnPage: number, repeatIds: boolean) {
  if (repeatIds) return 9000 + (indexOnPage % 5);
  return batchIndex * 1_000_000 + offset + indexOnPage;
}

// A fake IGDB: pages are generated from (company batch, offset), so tests can assert the exact offsets
// requested — including after a mid-run failure and a resume.
class FakeIgdbClient {
  calls: Array<{ endpoint: string; body: string }> = [];
  // Total games each company batch holds; pages are slices of that, capped at PAGE_SIZE.
  totalForBatch: Record<number, number> = { 0: 10 };
  // Keys `${batchIndex}:${offset}` whose request throws, until cleared.
  failAt = new Set<string>();
  repeatIds = false;

  async query<T>(endpoint: string, body: string): Promise<T[]> {
    this.calls.push({ endpoint, body });
    const { batchIndex, offset } = parseCall(body);
    if (this.failAt.has(`${batchIndex}:${offset}`)) throw new Error(`IGDB games failed: 500 at offset ${offset}`);
    if (offset >= MAX_GAMES_PER_COMPANY_BATCH) throw new Error(`offset ${offset} crossed the per-batch cap`);
    const total = this.totalForBatch[batchIndex] ?? 0;
    const remaining = Math.max(0, total - offset);
    const count = Math.min(PAGE_SIZE, remaining);
    const games: IgdbGameLike[] = [];
    for (let index = 0; index < count; index += 1) {
      const id = idFor(batchIndex, offset, index, this.repeatIds);
      games.push({
        id,
        name: `Game ${id}`,
        game_type: 0,
        first_release_date: 1802908800,
        platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
        involved_companies: [{ publisher: true, company: { id: 100, name: "Publisher 0" } }]
      });
    }
    return games as T[];
  }
}

// Reads back the company ids and the offset a query was built with, then maps the first company id back
// to its batch index (test company ids start at 100 and step by PUBLISHER_BATCH_SIZE).
function parseCall(body: string): { batchIndex: number; offset: number; companyIds: number[] } {
  const offset = Number(/offset (\d+);/.exec(body)?.[1] ?? "NaN");
  const match = /involved_companies\.company = \(([^)]*)\)/.exec(body);
  const companyIds = match ? match[1].split(",").filter(Boolean).map(Number) : [];
  const batchIndex = Math.floor(((companyIds[0] ?? 100) - 100) / PUBLISHER_BATCH_SIZE);
  return { batchIndex, offset, companyIds };
}

function game(id: number): IgdbGameLike {
  return {
    id,
    name: `Game ${id}`,
    game_type: 0,
    first_release_date: 1802908800,
    platforms: [{ id: 6, abbreviation: "PC", slug: "win" }],
    involved_companies: [{ publisher: true, company: { id: 100, name: "Publisher 0" } }]
  };
}

const progressRow = (db: TrackerDatabase) => db.prepare("select * from igdb_sync_progress where id = 1").get() as
  | { status: string; company_batch_index: number; next_offset: number; pages_fetched: number; last_error: string | null; track_from: string }
  | undefined;

const stagedCount = (db: TrackerDatabase) => Number((db.prepare("select count(*) n from igdb_sync_candidates").get() as { n: number }).n);
const offsetsRequested = (client: FakeIgdbClient) => client.calls.map(call => parseCall(call.body).offset);
const batchesRequested = (client: FakeIgdbClient) => client.calls.map(call => parseCall(call.body).batchIndex);

const RULES = { publisherIds: [100], trackFrom: "2026-01-01" } as const;
// 26 tracked companies: ids 100..124 form the first 25-id batch, 125 the second.
const TWO_BATCH_PUBLISHERS = Array.from({ length: PUBLISHER_BATCH_SIZE + 1 }, (_, index) => 100 + index);
const TWO_BATCH_RULES = { publisherIds: TWO_BATCH_PUBLISHERS, trackFrom: "2026-01-01" } as const;

describe("resumable IGDB candidate collection", () => {
  test("walks every company batch page by page and parks every fetched page", async () => {
    const db = tempDb(TWO_BATCH_PUBLISHERS);
    const client = new FakeIgdbClient();
    client.totalForBatch = { 0: 10, 1: 7 };

    const result = await collectIgdbCandidatesWithProgress(db, client, TWO_BATCH_RULES);

    expect(result).toMatchObject({ ok: true, interrupted: false, error: null });
    expect(result.games).toHaveLength(17);
    expect(new Set(result.games.map(item => item.id)).size).toBe(17);
    expect(batchesRequested(client)).toEqual([0, 1]);
    expect(offsetsRequested(client)).toEqual([0, 0]);
    expect(progressRow(db)).toMatchObject({ status: "complete", company_batch_index: 2, next_offset: 0, pages_fetched: 2, last_error: null });
    expect(stagedCount(db)).toBe(17);
  });

  test("a full 500-game page keeps paging until the short final page", async () => {
    const db = tempDb();
    const client = new FakeIgdbClient();
    client.totalForBatch = { 0: 600 };

    const result = await collectIgdbCandidatesWithProgress(db, client, RULES);

    expect(result.ok).toBe(true);
    expect(offsetsRequested(client)).toEqual([0, 500]);
    expect(result.games).toHaveLength(600);
    expect(progressRow(db)).toMatchObject({ status: "complete", pages_fetched: 2 });
  });

  test("stops at the 2500-game cap without ever requesting offset 2500, then moves to the next batch", async () => {
    const db = tempDb(TWO_BATCH_PUBLISHERS);
    const client = new FakeIgdbClient();
    client.totalForBatch = { 0: 10_000, 1: 0 };

    const result = await collectIgdbCandidatesWithProgress(db, client, TWO_BATCH_RULES);

    expect(result.ok).toBe(true);
    const firstBatchOffsets = client.calls.filter(call => parseCall(call.body).batchIndex === 0).map(call => parseCall(call.body).offset);
    expect(firstBatchOffsets).toEqual([0, 500, 1000, 1500, 2000]);
    expect(offsetsRequested(client).some(offset => offset >= MAX_GAMES_PER_COMPANY_BATCH)).toBe(false);
    const secondBatchOffsets = client.calls.filter(call => parseCall(call.body).batchIndex === 1).map(call => parseCall(call.body).offset);
    expect(secondBatchOffsets).toEqual([0]);
    expect(result.games).toHaveLength(2500);
  });

  test("a failed page interrupts the round and keeps every earlier page and its cursor", async () => {
    const db = tempDb();
    const client = new FakeIgdbClient();
    client.totalForBatch = { 0: 10_000 };
    client.failAt.add("0:1000");

    const result = await collectIgdbCandidatesWithProgress(db, client, RULES);

    expect(result).toMatchObject({ ok: false, interrupted: true });
    expect(result.error).toContain("500 at offset 1000");
    expect(offsetsRequested(client)).toEqual([0, 500, 1000]);
    // Two pages of 500 landed before the failure; the failed page stored nothing.
    expect(stagedCount(db)).toBe(1000);
    expect(progressRow(db)).toMatchObject({
      status: "interrupted",
      company_batch_index: 0,
      next_offset: 1000,
      pages_fetched: 2,
      last_error: expect.stringContaining("500 at offset 1000")
    });
  });

  test("the next run resumes at the failed offset instead of refetching earlier pages", async () => {
    const db = tempDb();
    const first = new FakeIgdbClient();
    first.totalForBatch = { 0: 10_000 };
    first.failAt.add("0:1000");
    const firstResult = await collectIgdbCandidatesWithProgress(db, first, RULES);
    expect(firstResult.interrupted).toBe(true);
    expect(stagedCount(db)).toBe(1000);

    // Second run: the failure is gone, paging continues to the 2500 cap.
    const second = new FakeIgdbClient();
    second.totalForBatch = { 0: 10_000 };
    const secondResult = await collectIgdbCandidatesWithProgress(db, second, RULES);

    expect(secondResult).toMatchObject({ ok: true, interrupted: false });
    expect(offsetsRequested(second)).toEqual([1000, 1500, 2000]);
    expect(progressRow(db)).toMatchObject({ status: "complete", company_batch_index: 1, next_offset: 0, last_error: null });
    // 1000 parked before the interruption plus the 1500 fetched after: no id lost, none duplicated.
    expect(stagedCount(db)).toBe(2500);
    expect(new Set(secondResult.games.map(item => item.id)).size).toBe(secondResult.games.length);
  });

  test("resuming after a finished batch continues the next company batch from offset zero", async () => {
    const db = tempDb(TWO_BATCH_PUBLISHERS);
    const first = new FakeIgdbClient();
    first.totalForBatch = { 0: 10, 1: 10_000 };
    first.failAt.add("1:500");
    const firstResult = await collectIgdbCandidatesWithProgress(db, first, TWO_BATCH_RULES);
    expect(firstResult.interrupted).toBe(true);
    expect(progressRow(db)).toMatchObject({ status: "interrupted", company_batch_index: 1, next_offset: 500 });

    const second = new FakeIgdbClient();
    second.totalForBatch = { 1: 10_000 };
    const secondResult = await collectIgdbCandidatesWithProgress(db, second, TWO_BATCH_RULES);

    expect(secondResult.ok).toBe(true);
    expect(offsetsRequested(second)).toEqual([500, 1000, 1500, 2000]);
    expect(secondResult.games).toHaveLength(10 + 2500);
  });

  test("a completed round starts the next round over from the first page with an empty staging table", async () => {
    const db = tempDb();
    const first = new FakeIgdbClient();
    first.totalForBatch = { 0: 30 };
    const firstResult = await collectIgdbCandidatesWithProgress(db, first, RULES);
    expect(firstResult.ok).toBe(true);
    expect(stagedCount(db)).toBe(30);

    const second = new FakeIgdbClient();
    second.totalForBatch = { 0: 12 };
    const secondResult = await collectIgdbCandidatesWithProgress(db, second, RULES);

    expect(secondResult.ok).toBe(true);
    expect(offsetsRequested(second)).toEqual([0]);
    expect(secondResult.games).toHaveLength(12);
    expect(stagedCount(db)).toBe(12);
    expect(progressRow(db)).toMatchObject({ status: "complete", pages_fetched: 1 });
  });

  test("changed tracked publishers or track-from date discard the old cursor and restart", async () => {
    const db = tempDb();
    const first = new FakeIgdbClient();
    first.totalForBatch = { 0: 10_000 };
    first.failAt.add("0:500");
    await collectIgdbCandidatesWithProgress(db, first, RULES);
    expect(stagedCount(db)).toBe(500);

    // Same company but a different track-from year: the parked cursor no longer describes this round.
    const second = new FakeIgdbClient();
    second.totalForBatch = { 0: 5 };
    const result = await collectIgdbCandidatesWithProgress(db, second, { publisherIds: [100], trackFrom: "2027-01-01" });

    expect(result.ok).toBe(true);
    expect(offsetsRequested(second)).toEqual([0]);
    expect(stagedCount(db)).toBe(5);
    expect(progressRow(db)).toMatchObject({ track_from: "2027-01-01", pages_fetched: 1 });
  });

  test("games repeated across pages are deduplicated by IGDB id", async () => {
    const db = tempDb();
    const client = new FakeIgdbClient();
    client.repeatIds = true;
    client.totalForBatch = { 0: 600 };

    const result = await collectIgdbCandidatesWithProgress(db, client, RULES);

    expect(offsetsRequested(client)).toEqual([0, 500]);
    expect(stagedCount(db)).toBe(5);
    expect(result.games.map(item => item.id).sort((a, b) => a - b)).toEqual([9000, 9001, 9002, 9003, 9004]);
  });

  test("no publishers tracked fails before touching IGDB", async () => {
    const db = tempDb([]);
    const client = new FakeIgdbClient();

    await expect(collectIgdbCandidatesWithProgress(db, client, { publisherIds: [], trackFrom: "2026-01-01" })).rejects.toThrow("No publishers are tracked yet");
    expect(client.calls).toEqual([]);
    expect(progressRow(db)).toBeUndefined();
  });

  test("page games and the progress cursor commit in one transaction", async () => {
    const db = tempDb();
    // Any insert into the staging table aborts: the cursor update in the same transaction must roll back too.
    db.exec("create trigger igdb_candidates_boom before insert on igdb_sync_candidates begin select raise(abort, 'staging locked'); end");
    const client = new FakeIgdbClient();

    const result = await collectIgdbCandidatesWithProgress(db, client, RULES);

    expect(result.interrupted).toBe(true);
    expect(result.error).toContain("staging locked");
    expect(stagedCount(db)).toBe(0);
    // The round was just created and never advanced: no "games stored but cursor unmoved" state.
    expect(progressRow(db)).toMatchObject({ status: "interrupted", company_batch_index: 0, next_offset: 0, pages_fetched: 0 });
  });

  test("a cursor left running by a closed app is marked interrupted on the next backend start", async () => {
    const db = tempDb();
    const client = new FakeIgdbClient();
    client.totalForBatch = { 0: 10_000 };
    client.failAt.add("0:1000");
    await collectIgdbCandidatesWithProgress(db, client, RULES);
    // Simulate the app dying between committing a page and recording the interruption.
    db.prepare("update igdb_sync_progress set status = 'running' where id = 1").run();

    const { failInterruptedSyncRuns } = await import("../../apps/backend/src/sync/syncStatus");
    failInterruptedSyncRuns(db);

    expect(progressRow(db)).toMatchObject({ status: "interrupted", next_offset: 1000 });
    expect(stagedCount(db)).toBe(1000);

    // The next run still resumes at the failed page rather than starting over.
    const second = new FakeIgdbClient();
    second.totalForBatch = { 0: 10_000 };
    const resumed = await collectIgdbCandidatesWithProgress(db, second, RULES);
    expect(resumed.ok).toBe(true);
    expect(offsetsRequested(second)).toEqual([1000, 1500, 2000]);
  });
});

describe("resumable sync through the full sync run", () => {
  const noArtwork = { steamGridClient: { findArtwork: async () => [] } };

  test("an interrupted run saves nothing to the library yet, then a resume completes it without duplicates", async () => {
    const db = tempDb();
    const first = new FakeIgdbClient();
    first.totalForBatch = { 0: 10_000 };
    first.failAt.add("0:500");

    const firstStatus = await runSync(db, undefined, first as never, noArtwork);

    expect(firstStatus).toMatchObject({ status: "interrupted" });
    expect(db.prepare("select count(*) n from releases").get()).toEqual({ n: 0 });
    expect(stagedCount(db)).toBe(500);

    const second = new FakeIgdbClient();
    second.totalForBatch = { 0: 10_000 };
    const secondStatus = await runSync(db, undefined, second as never, noArtwork);

    expect(secondStatus).toMatchObject({ status: "success", failed: 0 });
    expect(offsetsRequested(second)).toEqual([500, 1000, 1500, 2000]);
    expect(db.prepare("select count(*) n from releases").get()).toEqual({ n: 2500 });
    expect(db.prepare("select count(distinct igdb_id) n from releases").get()).toEqual({ n: 2500 });
    expect(progressRow(db)).toMatchObject({ status: "complete" });
  });

  test("a run handed an explicit candidate list bypasses the resumable crawl", async () => {
    const db = tempDb();
    const status = await runSync(db, [game(42)], undefined, noArtwork);

    expect(status).toMatchObject({ status: "success", added: 1 });
    expect(progressRow(db)).toBeUndefined();
    expect(db.prepare("select count(*) n from releases where igdb_id = 42").get()).toEqual({ n: 1 });
  });
});

describe("publisher query pagination shape", () => {
  test("the query requests exactly the given page size and offset", () => {
    const query = buildPublisherGameQuery([17, 42], "2025-06-01", 1500);
    expect(query).toContain("limit 500;");
    expect(query).toContain("offset 1500;");
    expect(query).toContain("involved_companies.company = (17,42)");
  });

  test("the pagination constants match the IGDB crawl contract", () => {
    expect(PUBLISHER_BATCH_SIZE).toBe(25);
    expect(PAGE_SIZE).toBe(500);
    expect(MAX_GAMES_PER_COMPANY_BATCH).toBe(2500);
  });

  test("every crawl request goes to the games endpoint", async () => {
    const db = tempDb();
    const client = new FakeIgdbClient();
    await collectIgdbCandidatesWithProgress(db, client, RULES);
    expect(client.calls.every(call => call.endpoint === "games")).toBe(true);
  });
});
