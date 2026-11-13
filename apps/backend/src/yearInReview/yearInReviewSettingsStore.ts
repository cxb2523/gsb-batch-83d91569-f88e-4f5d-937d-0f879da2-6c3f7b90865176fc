import type { TrackerDatabase } from "../database/db";

export interface YearInReviewSettings {
  gotyCompletedId: string | null;
  musicVideoId: string | null;
}

// The only reader and writer of `year_in_review_settings`. It never touches completed_games.
// Callers write through `runWrite`; the store itself is synchronous.
export function createYearInReviewSettingsStore(db: TrackerDatabase) {
  const read = (year: number): YearInReviewSettings =>
    (db.prepare("select goty_completed_id gotyCompletedId, music_video_id musicVideoId from year_in_review_settings where year = ?").get(year) as YearInReviewSettings | undefined)
    ?? { gotyCompletedId: null, musicVideoId: null };

  return {
    read,

    // Absent fields stay as they are; null clears.
    save(year: number, patch: Partial<YearInReviewSettings>) {
      const next = { ...read(year), ...patch };
      db.prepare(`
        insert into year_in_review_settings (year, goty_completed_id, music_video_id, updated_at)
        values (@year, @gotyCompletedId, @musicVideoId, current_timestamp)
        on conflict(year) do update set
          goty_completed_id = excluded.goty_completed_id,
          music_video_id = excluded.music_video_id,
          updated_at = current_timestamp
      `).run({ year, ...next });
    }
  };
}
