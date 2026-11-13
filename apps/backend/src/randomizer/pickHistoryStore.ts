import type { TrackerDatabase } from "../database/db";
import type { RandomizerFilters, RandomizerHistoryItem, RandomizerPick } from "../../../../shared/types";

export const PICK_HISTORY_LIMIT = 500;

// Randomizer pick history. Rows are ordered by insert id, which is finer than `picked_at` seconds.
// Callers write through `runWrite`; the store itself is synchronous.
export function createPickHistoryStore(db: TrackerDatabase) {
  return {
    // The newest distinct IGDB ids, most recent first.
    recentIgdbIds(limit: number): number[] {
      if (limit <= 0) return [];
      const rows = db.prepare("select igdb_id igdbId from randomizer_picks order by id desc limit ?").all(limit) as Array<{ igdbId: number }>;
      return [...new Set(rows.map(row => row.igdbId))];
    },

    record(pick: Pick<RandomizerPick, "igdbId" | "title" | "coverImageId">, filters: RandomizerFilters = {}) {
      db.prepare("insert into randomizer_picks (igdb_id, title, cover_image_id, filters_json) values (?, ?, ?, ?)")
        .run(pick.igdbId, pick.title, pick.coverImageId ?? null, JSON.stringify(filters));
      db.prepare("delete from randomizer_picks where id not in (select id from randomizer_picks order by id desc limit ?)").run(PICK_HISTORY_LIMIT);
    },

    list(limit: number): RandomizerHistoryItem[] {
      return db.prepare(`
        select id, igdb_id igdbId, title, cover_image_id coverImageId, picked_at pickedAt
        from randomizer_picks
        order by id desc
        limit ?
      `).all(Math.max(0, limit)) as RandomizerHistoryItem[];
    },

    clear() {
      db.prepare("delete from randomizer_picks").run();
    }
  };
}
