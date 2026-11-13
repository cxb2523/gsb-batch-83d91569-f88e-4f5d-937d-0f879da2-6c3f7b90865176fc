import type { IgdbGameLike } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";

// Where a publisher-game crawl parks each fetched page until the whole round is done. The progress row is
// the resume cursor: company batch index plus the next page offset inside that batch. Both tables are only
// ever written inside one transaction, so a game row and the cursor that says its page landed move together.

export interface IgdbSyncProgress {
  status: "running" | "interrupted" | "complete";
  companyBatchIndex: number;
  nextOffset: number;
  companyIdsJson: string;
  trackFrom: string;
  pagesFetched: number;
  lastError: string | null;
}

export function createIgdbSyncProgressStore(db: TrackerDatabase) {
  const read = (): IgdbSyncProgress | null => {
    const row = db.prepare("select * from igdb_sync_progress where id = 1").get() as Record<string, unknown> | undefined;
    if (!row) return null;
    return {
      status: row.status as IgdbSyncProgress["status"],
      companyBatchIndex: Number(row.company_batch_index),
      nextOffset: Number(row.next_offset),
      companyIdsJson: String(row.company_ids_json),
      trackFrom: String(row.track_from),
      pagesFetched: Number(row.pages_fetched),
      lastError: row.last_error === null ? null : String(row.last_error)
    };
  };

  // A brand-new round: everything parked by an earlier round is discarded and the cursor goes back to the
  // first page of the first company batch.
  const reset = (companyIds: readonly number[], trackFrom: string) => {
    db.prepare("delete from igdb_sync_candidates").run();
    db.prepare("delete from igdb_sync_progress").run();
    db.prepare(`
      insert into igdb_sync_progress (id, status, company_batch_index, next_offset, company_ids_json, track_from, pages_fetched, last_error)
      values (1, 'running', 0, 0, ?, ?, 0, null)
    `).run(JSON.stringify([...companyIds]), trackFrom);
  };

  const markRunning = () => {
    db.prepare("update igdb_sync_progress set status = 'running', last_error = null, updated_at = current_timestamp where id = 1").run();
  };

  // One fetched page and the cursor that points just past it, committed atomically. Games are keyed by
  // IGDB id, so re-fetched pages overwrite instead of duplicating.
  const savePage = (games: IgdbGameLike[], cursor: { companyBatchIndex: number; nextOffset: number; batchFinished: boolean }) => {
    const upsertGame = db.prepare(`
      insert into igdb_sync_candidates (igdb_id, game_json) values (?, ?)
      on conflict(igdb_id) do update set game_json = excluded.game_json, fetched_at = current_timestamp
    `);
    const advance = db.prepare(`
      update igdb_sync_progress
      set company_batch_index = ?, next_offset = ?, pages_fetched = pages_fetched + 1, updated_at = current_timestamp
      where id = 1
    `);
    const tx = db.transaction(() => {
      for (const game of games) upsertGame.run(game.id, JSON.stringify(game));
      advance.run(cursor.companyBatchIndex, cursor.nextOffset);
    });
    tx();
  };

  const markInterrupted = (error: string) => {
    db.prepare("update igdb_sync_progress set status = 'interrupted', last_error = ?, updated_at = current_timestamp where id = 1").run(error);
  };

  const markComplete = () => {
    db.prepare("update igdb_sync_progress set status = 'complete', updated_at = current_timestamp where id = 1").run();
  };

  const stagedGames = (): IgdbGameLike[] => {
    const rows = db.prepare("select game_json from igdb_sync_candidates order by igdb_id").all() as Array<{ game_json: string }>;
    return rows.map(row => JSON.parse(row.game_json) as IgdbGameLike);
  };

  return { read, reset, markRunning, savePage, markInterrupted, markComplete, stagedGames };
}
