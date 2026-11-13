import type { TrackerDatabase } from "../database/db";
import type { CompletedGameFilters } from "../../../../shared/types";
import { normalizeText } from "../text/normalizeText";
import { completedGameId, completedIdentityKey } from "./completedIdentity";
import type { CompletedMetadataPatch } from "./completedIgdbMatcher";
import { normalizeCompletedPersonalPatch, normalizeManualCompletion, type ManualCompletedGamePayload } from "./completedPersonalFields";
import { parseRating } from "./completedRating";
import { createCompletedReadModel } from "./completedReadModel";

type CompletedEditResult = { ok: true } | { ok: false; reason: "not-found" | "conflict" };

interface IdentityRow {
  id: string;
  title: string;
  userPlatform: string;
  identityKey: string;
}

// Personal fields a user can edit. Title and platform are identity fields and are handled separately.
const personalColumns: Record<string, string> = {
  ratingRaw: "rating_raw",
  ratingScore: "rating_score",
  completionDate: "completion_date",
  completionMonth: "completion_month",
  completionYear: "completion_year",
  completionPrecision: "completion_precision",
  notes: "notes",
  developer: "developer",
  publisher: "publisher"
};

const identitySelect = `
  select id, title, user_platform userPlatform, identity_key identityKey
  from completed_games
`;

// The Completed Library store. It owns the Identity Key: every write that creates a game,
// changes its title or platform, or applies an IGDB match goes through here.
// Reads (list, getDetail) are here too, so callers have one module for completed games.
export function createCompletedGameStore(db: TrackerDatabase) {
  const readModel = createCompletedReadModel(db);

  const findById = (id: string) => db.prepare(`${identitySelect} where id = ?`).get(id) as IdentityRow | undefined;
  const findByIdentity = (identityKey: string) => db.prepare(`${identitySelect} where identity_key = ?`).get(identityKey) as IdentityRow | undefined;

  // Ids are derived from the first title and platform but never change afterwards,
  // so a later game with the same title needs a free id.
  const allocateId = (title: string, userPlatform: string) => {
    const base = completedGameId(title, userPlatform);
    const taken = db.prepare("select 1 from completed_games where id = ?");
    if (!taken.get(base)) return base;
    for (let suffix = 2; ; suffix++) {
      const candidate = `${base}-${suffix}`;
      if (!taken.get(candidate)) return candidate;
    }
  };

  const saveMatchOverride = (title: string, userPlatform: string, igdbId: number) => {
    db.prepare(`
      insert into completed_match_overrides (identity_key, normalized_title, user_platform, igdb_id, updated_at)
      values (?, ?, ?, ?, current_timestamp)
      on conflict(identity_key) do update set igdb_id = excluded.igdb_id, updated_at = current_timestamp
    `).run(completedIdentityKey(title, userPlatform), normalizeText(title), userPlatform, igdbId);
  };

  const saveMetadata = (identityKey: string, metadata: CompletedMetadataPatch) => {
    db.prepare(`
      update completed_games set
        igdb_id = @igdbId,
        cover_image_id = @coverImageId,
        igdb_release_date = @igdbReleaseDate,
        igdb_developer = @igdbDeveloper,
        igdb_publisher = @igdbPublisher,
        igdb_genres_json = @igdbGenresJson,
        igdb_platforms_json = @igdbPlatformsJson,
        igdb_themes_json = @igdbThemesJson,
        igdb_game_modes_json = @igdbGameModesJson,
        igdb_rating = @igdbRating,
        igdb_aggregated_rating = @igdbAggregatedRating,
        igdb_total_rating = @igdbTotalRating,
        igdb_total_rating_count = @igdbTotalRatingCount,
        summary = @summary,
        screenshots_json = @screenshotsJson,
        match_status = @matchStatus,
        updated_at = current_timestamp
      where identity_key = @identityKey
    `).run({
      identityKey,
      ...metadata,
      igdbGenresJson: JSON.stringify(metadata.igdbGenres),
      igdbPlatformsJson: JSON.stringify(metadata.igdbPlatforms),
      igdbThemesJson: JSON.stringify(metadata.igdbThemes),
      igdbGameModesJson: JSON.stringify(metadata.igdbGameModes),
      screenshotsJson: JSON.stringify(metadata.screenshots)
    });
  };

  const changeIdentity = (row: IdentityRow, title: string, userPlatform: string) => {
    const identityKey = completedIdentityKey(title, userPlatform);
    db.prepare("update completed_match_overrides set identity_key = ?, normalized_title = ?, user_platform = ? where identity_key = ?")
      .run(identityKey, normalizeText(title), userPlatform, row.identityKey);
    const platformChanged = normalizeText(userPlatform) !== normalizeText(row.userPlatform);
    db.prepare(`
      update completed_games
      set title = ?, normalized_title = ?, user_platform = ?, identity_key = ?,
          platforms_json = case when ? then ? else platforms_json end,
          updated_at = current_timestamp
      where id = ?
    `).run(title, normalizeText(title), userPlatform, identityKey, platformChanged ? 1 : 0, JSON.stringify(userPlatform ? [userPlatform] : []), row.id);
  };

  const updatePersonalFields = (id: string, patch: Record<string, unknown>) => {
    const normalizedPatch = normalizeCompletedPersonalPatch(patch);
    const sets: string[] = [];
    const params: unknown[] = [];
    for (const [key, column] of Object.entries(personalColumns)) {
      if (normalizedPatch[key] === undefined) continue;
      sets.push(`${column} = ?`);
      params.push(normalizedPatch[key] === null ? null : String(normalizedPatch[key]));
    }
    if (normalizedPatch.genres !== undefined) {
      sets.push("genres_json = ?");
      params.push(JSON.stringify(normalizedPatch.genres));
    }
    if (normalizedPatch.platforms !== undefined) {
      sets.push("platforms_json = ?");
      params.push(JSON.stringify(normalizedPatch.platforms));
    }
    if (sets.length === 0) return;
    sets.push("updated_at = current_timestamp");
    db.prepare(`update completed_games set ${sets.join(", ")} where id = ?`).run(...params, id);
  };

  return {
    createManual(payload: ManualCompletedGamePayload) {
      const title = payload.title?.trim();
      if (!title) throw new Error("Title is required");
      const userPlatform = payload.userPlatform?.trim() ?? "";
      const identityKey = completedIdentityKey(title, userPlatform);
      const id = findByIdentity(identityKey)?.id ?? allocateId(title, userPlatform);
      const completion = normalizeManualCompletion(payload);
      db.prepare(`
        insert into completed_games (
          id, title, normalized_title, user_platform, identity_key, platforms_json, rating_raw, rating_score,
          completion_date, completion_month, completion_year, completion_precision, notes, source_type, source_row_hash
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'manual', '')
        on conflict(identity_key) do update set
          title = excluded.title,
          rating_raw = coalesce(excluded.rating_raw, completed_games.rating_raw),
          rating_score = coalesce(excluded.rating_score, completed_games.rating_score),
          completion_date = coalesce(excluded.completion_date, completed_games.completion_date),
          completion_month = coalesce(excluded.completion_month, completed_games.completion_month),
          completion_year = coalesce(excluded.completion_year, completed_games.completion_year),
          completion_precision = case when excluded.completion_precision != 'none' then excluded.completion_precision else completed_games.completion_precision end,
          notes = coalesce(excluded.notes, completed_games.notes),
          updated_at = current_timestamp
      `).run(
        id,
        title,
        normalizeText(title),
        userPlatform,
        identityKey,
        JSON.stringify(userPlatform ? [userPlatform] : []),
        payload.ratingRaw ?? null,
        parseRating(payload.ratingRaw),
        completion.completionDate,
        completion.completionMonth,
        completion.completionYear,
        completion.completionPrecision,
        payload.notes ?? null
      );
      return readModel.getByIdentity(identityKey)!;
    },

    // Title and platform changes rebuild the Identity Key and carry the match override along.
    edit(id: string, patch: Record<string, unknown>): CompletedEditResult {
      const row = findById(id);
      if (!row) return { ok: false, reason: "not-found" };
      const title = typeof patch.title === "string" && patch.title.trim() ? patch.title.trim() : row.title;
      const userPlatform = typeof patch.userPlatform === "string" ? patch.userPlatform.trim() : row.userPlatform;
      const identityKey = completedIdentityKey(title, userPlatform);
      if (identityKey !== row.identityKey) {
        const clash = findByIdentity(identityKey);
        if (clash && clash.id !== id) return { ok: false, reason: "conflict" };
      }
      db.transaction(() => {
        if (title !== row.title || userPlatform !== row.userPlatform) changeIdentity(row, title, userPlatform);
        updatePersonalFields(id, patch);
      })();
      return { ok: true };
    },

    // Saves the manual match override and the IGDB metadata together, under the game's current Identity Key.
    applyMatch(id: string, igdbId: number, metadata: CompletedMetadataPatch) {
      const row = findById(id);
      if (!row) return false;
      db.transaction(() => {
        saveMatchOverride(row.title, row.userPlatform, igdbId);
        saveMetadata(row.identityKey, metadata);
      })();
      return true;
    },

    deleteById(id: string) {
      const row = findById(id);
      if (!row) return false;
      db.transaction(() => {
        db.prepare("delete from completed_match_overrides where identity_key = ?").run(row.identityKey);
        db.prepare("delete from completed_games where id = ?").run(id);
      })();
      return true;
    },

    list(filters: CompletedGameFilters) {
      return readModel.list(filters);
    },

    getDetail(id: string) {
      return readModel.getDetail(id);
    },

    // Year in Review's read: the year's finishes, earlier years' genres and platforms, and finishes per year.
    yearInReviewRows(year: number) {
      return readModel.yearInReviewRows(year);
    },

    // Finishes per completion year.
    completionYearCounts() {
      return readModel.completionYearCounts();
    },

    // IGDB ids of completed games, newest first.
    ownedIgdbIds() {
      return (db.prepare("select igdb_id igdbId from completed_games where igdb_id is not null order by rowid desc").all() as Array<{ igdbId: number }>).map(row => row.igdbId);
    }
  };
}
