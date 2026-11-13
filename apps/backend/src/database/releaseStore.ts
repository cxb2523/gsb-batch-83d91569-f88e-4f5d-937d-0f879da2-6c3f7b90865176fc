import { randomUUID } from "node:crypto";
import type { TrackerDatabase } from "./db";
import { getRelease, listReleases, type ReleaseFilters } from "./releaseReadModel";
import type { DatePrecision, GameTrailer, NormalizedRelease, ReleaseArtwork, ReleaseCategory, ReleaseEligibility, ReleaseOverride } from "../../../../shared/types";
import { computeSortDateAndEligibility, precisionOfDatedHuman } from "../sync/releasePolicy";
import { mergeArtworks, type ExistingReleaseMergeState } from "../sync/releaseMerge";
import { normalizeText } from "../text/normalizeText";

interface UserReleaseStatePatch {
  hidden?: boolean;
  watched?: boolean;
  released?: boolean;
}

interface DateOverridePatch {
  dateText: string;
  sourceUrl: string;
  sourceName: string;
}

// A user edit. Every field set here is also recorded as a user override, so the next Sync Run keeps it.
export interface ReleaseEdit {
  title?: string;
  publishers?: string[];
  developers?: string[];
  platforms?: string[];
  category?: ReleaseCategory;
  dateText?: string;
  releaseDate?: string | null;
  datePrecision?: DatePrecision;
  releaseWindow?: string | null;
}

// A curated correction from data/source-overrides.json. It lives on a seed-<title> release that sync
// merges into any release whose normalized title matches.
export interface OverrideSeed {
  title: string;
  aliases?: string[];
  fields: Record<string, string>;
  sourceName: string;
  sourceUrl: string;
}

interface DeletedRelease {
  igdbId: number | null;
  title: string;
  normalizedTitle: string;
  blocked: boolean;
}

type ReleaseDateFields = Pick<NormalizedRelease, "dateText" | "releaseDate" | "datePrecision" | "releaseWindow">;

// What save needs: eligibility is derived from the dates on save, and missing media lists mean none.
type ReleaseToSave = Omit<NormalizedRelease, keyof ReleaseEligibility | "screenshots" | "trailers">
  & Partial<Pick<NormalizedRelease, "screenshots" | "trailers">>;

const listFields = {
  publishers: { table: "release_publishers", column: "publisher" },
  developers: { table: "release_developers", column: "developer" },
  platforms: { table: "release_platforms", column: "platform" }
} as const;

const dateColumns = {
  dateText: "date_text",
  releaseDate: "release_date",
  datePrecision: "date_precision",
  releaseWindow: "release_window"
} as const;

const dateFieldsSql = "date_text dateText, release_date releaseDate, date_precision datePrecision, release_window releaseWindow";

// A user who changes a game's date to a vague one ("2028", "Q4 2027") without touching its day means the
// old day no longer holds; kept, it would still decide the sort and the countdown. So the day is cleared
// (and that is saved as their edit too, so sync keeps it cleared). When the edit names no precision (the
// form leaves it as it was), the words decide it, the way sync reads IGDB's. An Exact date keeps its day.
function withoutStaleDay(db: TrackerDatabase, releaseId: string, edit: ReleaseEdit): ReleaseEdit {
  if (edit.releaseDate !== undefined || (edit.dateText === undefined && edit.datePrecision === undefined)) return edit;
  const current = db.prepare("select date_precision datePrecision from releases where id = ?").get(releaseId) as { datePrecision: DatePrecision } | undefined;
  const fromWords = edit.dateText !== undefined ? precisionOfDatedHuman(edit.dateText) : undefined;
  const precision = edit.datePrecision ?? (fromWords && fromWords !== "Exact" ? fromWords : current?.datePrecision);
  if (precision === "Exact") return edit;
  return { ...edit, datePrecision: precision, releaseDate: null };
}

// The Release Store: the only module that writes the releases table family (lists, media, sources,
// search index, user state, overrides, blocks). Callers work in releases, not tables.
export function createReleaseStore(db: TrackerDatabase) {
  const store = {
    list(filters: ReleaseFilters) {
      return listReleases(db, filters);
    },
    getDetail(id: string) {
      return getRelease(db, id);
    },
    exists(id: string) {
      return Boolean(db.prepare("select 1 from releases where id = ?").get(id));
    },

    // One Release per IGDB game: a game added from IGDB search keeps its own id, and sync updates that
    // row instead of inserting igdb-<id> next to it.
    findByIgdbId(igdbId: number) {
      const row = db.prepare("select id from releases where igdb_id = ? order by id like 'igdb-%' desc limit 1").get(igdbId) as { id: string } | undefined;
      return row?.id ?? null;
    },
    idForIgdbGame(igdbId: number) {
      return store.findByIgdbId(igdbId) ?? `igdb-${igdbId}`;
    },

    // What sync merges an incoming IGDB release with: kept artwork order and every override that applies.
    loadMergeState(releaseId: string, normalizedTitle?: string): ExistingReleaseMergeState | null {
      const artworks = db.prepare("select image_id imageId, source, url from release_artworks where release_id = ? order by sort_order, image_id").all(releaseId) as ReleaseArtwork[];
      const overrides = [
        ...db.prepare("select field, value, source_type sourceType, source_url sourceUrl, source_name sourceName, updated_at updatedAt from manual_overrides where release_id = ?").all(releaseId) as ReleaseOverride[],
        ...loadSeededOverrides(db, normalizedTitle)
      ];
      if (!store.exists(releaseId) && overrides.length === 0) return null;
      return { releaseId, artworks, overrides };
    },

    save(release: ReleaseToSave) {
      upsertRelease(db, release);
    },
    addManualSourceUrl(releaseId: string, sourceUrl: string) {
      db.prepare("insert into sources (release_id, source_name, source_url, field) values (?, ?, ?, ?)").run(releaseId, "Manual", sourceUrl, "release");
      refreshSearchIndex(db, releaseId);
    },
    updateUserState(releaseId: string, patch: UserReleaseStatePatch) {
      if (typeof patch.hidden !== "boolean" && typeof patch.watched !== "boolean" && typeof patch.released !== "boolean") return;
      const current = db.prepare("select hidden, watched, released from user_release_state where release_id = ?").get(releaseId) as { hidden?: number; watched?: number; released?: number } | undefined;
      db.prepare(`
        insert into user_release_state (release_id, hidden, watched, released, updated_at)
        values (?, ?, ?, ?, current_timestamp)
        on conflict(release_id) do update set
          hidden = excluded.hidden,
          watched = excluded.watched,
          released = excluded.released,
          updated_at = current_timestamp
      `).run(
        releaseId,
        typeof patch.hidden === "boolean" ? (patch.hidden ? 1 : 0) : (current?.hidden ?? 0),
        typeof patch.watched === "boolean" ? (patch.watched ? 1 : 0) : (current?.watched ?? 0),
        typeof patch.released === "boolean" ? (patch.released ? 1 : 0) : (current?.released ?? 0)
      );
    },
    applyDateOverride(releaseId: string, patch: DateOverridePatch) {
      recordOverride(db, releaseId, "dateText", patch.dateText, "user", patch);
      db.prepare("update releases set date_text = ?, updated_at = current_timestamp where id = ?").run(patch.dateText, releaseId);
      recomputeEligibility(db, releaseId);
    },
    edit(releaseId: string, requested: ReleaseEdit) {
      const edit = withoutStaleDay(db, releaseId, requested);
      const apply = db.transaction(() => {
        if (edit.title !== undefined) {
          db.prepare("update releases set title = ?, normalized_title = ?, updated_at = current_timestamp where id = ?").run(edit.title, normalizeText(edit.title), releaseId);
          recordOverride(db, releaseId, "title", edit.title, "user");
        }
        for (const [field, { table, column }] of Object.entries(listFields)) {
          const values = edit[field as keyof typeof listFields];
          if (values === undefined) continue;
          replaceReleaseList(db, table, column, releaseId, values);
          recordOverride(db, releaseId, field, JSON.stringify(values), "user");
        }
        if (edit.category !== undefined) {
          db.prepare("update releases set category = ?, updated_at = current_timestamp where id = ?").run(edit.category, releaseId);
          db.prepare("update release_categories set category = ? where release_id = ?").run(edit.category, releaseId);
          recordOverride(db, releaseId, "category", edit.category, "user");
        }
        let datesChanged = false;
        for (const [field, column] of Object.entries(dateColumns)) {
          const value = edit[field as keyof typeof dateColumns];
          if (value === undefined) continue;
          db.prepare(`update releases set ${column} = ?, updated_at = current_timestamp where id = ?`).run(value, releaseId);
          if (field === "releaseDate") db.prepare("update release_categories set release_date = ? where release_id = ?").run(value, releaseId);
          recordOverride(db, releaseId, field, value ?? "", "user");
          datesChanged = true;
        }
        if (datesChanged) recomputeEligibility(db, releaseId);
        refreshSearchIndex(db, releaseId);
      });
      apply();
    },

    // Deletes a release; with block, future syncs skip the same IGDB game or title. Null when it does not exist.
    delete(releaseId: string, { block = false }: { block?: boolean } = {}): DeletedRelease | null {
      const row = db.prepare("select igdb_id igdbId, title, normalized_title normalizedTitle from releases where id = ?").get(releaseId) as { igdbId: number | null; title: string; normalizedTitle: string } | undefined;
      if (!row) return null;
      if (block) {
        db.prepare("insert or replace into blocked_releases (id, igdb_id, normalized_title, title, reason) values (?, ?, ?, ?, ?)").run(randomUUID(), row.igdbId ?? null, row.normalizedTitle, row.title, "Manual delete");
      }
      db.prepare("delete from releases where id = ?").run(releaseId);
      return { igdbId: row.igdbId ?? null, title: row.title, normalizedTitle: row.normalizedTitle, blocked: block };
    },
    listBlocked() {
      return db.prepare("select id, igdb_id igdbId, normalized_title normalizedTitle, title, reason, created_at createdAt from blocked_releases order by created_at desc").all();
    },
    // IGDB ids of tracked releases, newest first.
    ownedIgdbIds() {
      return (db.prepare("select igdb_id igdbId from releases where igdb_id is not null order by rowid desc").all() as Array<{ igdbId: number }>).map(row => row.igdbId);
    },
    unblock(blockedId: string) {
      db.prepare("delete from blocked_releases where id = ?").run(blockedId);
    },
    isBlocked(igdbId: number, title: string) {
      return Boolean(db.prepare(`
        select 1 from blocked_releases
        where (igdb_id is not null and igdb_id = ?)
           or normalized_title = ?
        limit 1
      `).get(igdbId, normalizeText(title)));
    },

    addArtwork(releaseId: string, artwork: ReleaseArtwork) {
      const row = db.prepare("select coalesce(max(sort_order), -1) + 1 nextOrder from release_artworks where release_id = ?").get(releaseId) as { nextOrder: number };
      db.prepare("insert or replace into release_artworks (release_id, image_id, source, url, sort_order) values (?, ?, ?, ?, ?)").run(releaseId, artwork.imageId, artwork.source ?? "artwork", artwork.url ?? null, row.nextOrder);
    },
    removeArtwork(releaseId: string, imageId: string) {
      const row = db.prepare("select source from release_artworks where release_id = ? and image_id = ?").get(releaseId, imageId) as { source?: string } | undefined;
      db.prepare("delete from release_artworks where release_id = ? and image_id = ?").run(releaseId, imageId);
      return { source: row?.source };
    },
    reorderArtworks(releaseId: string, imageIds: string[]) {
      const update = db.prepare("update release_artworks set sort_order = ? where release_id = ? and image_id = ?");
      imageIds.forEach((imageId, index) => update.run(index, releaseId, imageId));
    },

    // Writes one curated seed onto its seed-<title> release, never replacing a user's own edit. Returns the
    // number of override fields written.
    applySeed(seed: OverrideSeed) {
      const releaseId = `seed-${normalizeText(seed.title).replace(/\s+/g, "-")}`;
      db.prepare(`
        insert or ignore into releases (id, title, normalized_title, date_text, date_precision, category, source_confidence)
        values (?, ?, ?, 'TBA', 'TBA', 'Main', 50)
      `).run(releaseId, seed.title, normalizeText([seed.title, ...(seed.aliases ?? [])].join(" ")));
      let count = 0;
      for (const [field, value] of Object.entries(seed.fields)) {
        const hasUserEdit = db.prepare("select 1 from manual_overrides where release_id = ? and field = ? and source_type = 'user'").get(releaseId, field);
        if (hasUserEdit) continue;
        recordOverride(db, releaseId, field, value, "seeded", seed);
        count++;
      }
      db.prepare(`
        update releases
        set date_text = coalesce(?, date_text), release_date = coalesce(?, release_date),
            date_precision = coalesce(?, date_precision), release_window = coalesce(?, release_window),
            updated_at = current_timestamp
        where id = ?
      `).run(seed.fields.dateText ?? null, seed.fields.releaseDate ?? null, seed.fields.datePrecision ?? null, seed.fields.releaseWindow ?? null, releaseId);
      recomputeEligibility(db, releaseId);
      db.prepare("insert into sources (release_id, source_name, source_url, field) values (?, ?, ?, ?)").run(releaseId, seed.sourceName, seed.sourceUrl, "seed");
      refreshSearchIndex(db, releaseId);
      return count;
    },

    // Re-derives eligibility for every release in one transaction. Eligibility depends only on stored
    // dates (writes keep it current), so this repairs rows after a policy change.
    refreshAllEligibility() {
      const rows = db.prepare(`select id, ${dateFieldsSql} from releases`).all() as Array<ReleaseDateFields & { id: string }>;
      const update = eligibilityUpdate(db);
      db.transaction(() => {
        for (const row of rows) applyEligibility(update, row.id, row);
      })();
    }
  };
  return store;
}

function eligibilityUpdate(db: TrackerDatabase) {
  return db.prepare(`
    update releases
    set eligible = ?, eligibility_reason = ?, effective_sort_date = ?,
        archived_at = case when ? = 0 then coalesce(archived_at, current_timestamp) else null end
    where id = ?
  `);
}

function applyEligibility(update: ReturnType<typeof eligibilityUpdate>, releaseId: string, dateFields: ReleaseDateFields): ReleaseEligibility {
  const eligibility = computeSortDateAndEligibility(dateFields);
  update.run(eligibility.eligible ? 1 : 0, eligibility.eligibilityReason, eligibility.effectiveSortDate, eligibility.eligible ? 1 : 0, releaseId);
  return eligibility;
}

function recomputeEligibility(db: TrackerDatabase, releaseId: string) {
  const row = db.prepare(`select ${dateFieldsSql} from releases where id = ?`).get(releaseId) as ReleaseDateFields | undefined;
  if (row) applyEligibility(eligibilityUpdate(db), releaseId, row);
}

function recordOverride(db: TrackerDatabase, releaseId: string, field: string, value: string, sourceType: "user" | "seeded", source: { sourceUrl?: string; sourceName?: string } = {}) {
  db.prepare(`
    insert or replace into manual_overrides (release_id, field, value, source_type, source_url, source_name, updated_at)
    values (?, ?, ?, ?, ?, ?, current_timestamp)
  `).run(releaseId, field, value, sourceType, source.sourceUrl ?? null, source.sourceName ?? null);
}

function loadSeededOverrides(db: TrackerDatabase, normalizedTitle?: string) {
  if (!normalizedTitle) return [];
  return db.prepare(`
    select mo.field, mo.value, mo.source_type sourceType, mo.source_url sourceUrl, mo.source_name sourceName, mo.updated_at updatedAt
    from manual_overrides mo
    join releases seeded on seeded.id = mo.release_id
    where mo.source_type = 'seeded'
      and seeded.id like 'seed-%'
      and (
        seeded.normalized_title = @normalizedTitle
        or instr(' ' || seeded.normalized_title || ' ', ' ' || @normalizedTitle || ' ') > 0
      )
  `).all({ normalizedTitle }) as ReleaseOverride[];
}

function upsertRelease(db: TrackerDatabase, release: ReleaseToSave) {
  const eligibility = computeSortDateAndEligibility(release);
  db.prepare(`
    insert into releases (
      id, igdb_id, title, normalized_title, date_text, release_date, date_precision,
      release_window, category, source_confidence, igdb_url, updated_at,
      eligible, eligibility_reason, effective_sort_date, archived_at
    )
    values (
      @id, @igdbId, @title, @normalizedTitle, @dateText, @releaseDate, @datePrecision,
      @releaseWindow, @category, @sourceConfidence, @igdbUrl, @updatedAt,
      @eligible, @eligibilityReason, @effectiveSortDate,
      case when @eligible = 0 then current_timestamp else null end
    )
    on conflict(id) do update set
      title = excluded.title,
      normalized_title = excluded.normalized_title,
      date_text = excluded.date_text,
      release_date = excluded.release_date,
      date_precision = excluded.date_precision,
      release_window = excluded.release_window,
      category = excluded.category,
      source_confidence = excluded.source_confidence,
      igdb_url = excluded.igdb_url,
      updated_at = excluded.updated_at,
      eligible = excluded.eligible,
      eligibility_reason = excluded.eligibility_reason,
      effective_sort_date = excluded.effective_sort_date,
      archived_at = case when excluded.eligible = 0 then coalesce(releases.archived_at, current_timestamp) else null end
  `).run({
    ...release,
    igdbId: release.igdbId ?? null,
    releaseDate: release.releaseDate,
    releaseWindow: release.releaseWindow,
    igdbUrl: release.igdbUrl ?? null,
    updatedAt: release.updatedAt ?? null,
    eligible: eligibility.eligible ? 1 : 0,
    eligibilityReason: eligibility.eligibilityReason,
    effectiveSortDate: eligibility.effectiveSortDate
  });

  replaceReleaseList(db, "release_publishers", "publisher", release.id, release.publishers);
  replaceReleaseList(db, "release_developers", "developer", release.id, release.developers);
  replaceReleaseList(db, "release_platforms", "platform", release.id, release.platforms);
  replaceReleaseList(db, "release_genres", "genre", release.id, release.genres);
  replaceArtworks(db, release.id, release.artworks);
  replaceScreenshots(db, release.id, release.screenshots);
  replaceTrailers(db, release.id, release.trailers);
  db.prepare("insert or replace into release_categories (release_id, category, release_date) values (?, ?, ?)").run(release.id, release.category, release.releaseDate);
  persistSourceUrls(db, release.id, release.sourceUrls ?? []);
  refreshSearchIndex(db, release.id);
}

function replaceReleaseList(db: TrackerDatabase, table: string, column: string, releaseId: string, values: string[]) {
  db.prepare(`delete from ${table} where release_id = ?`).run(releaseId);
  const insert = db.prepare(`insert or ignore into ${table} (release_id, ${column}) values (?, ?)`);
  for (const value of values) insert.run(releaseId, value);
}

// Local uploads keep their place; provider artwork follows the incoming list.
function replaceArtworks(db: TrackerDatabase, releaseId: string, artworks: ReleaseArtwork[]) {
  const existing = db.prepare("select image_id imageId, source, url from release_artworks where release_id = ? order by sort_order, image_id").all(releaseId) as ReleaseArtwork[];
  const merged = mergeArtworks(artworks, existing);
  db.prepare("delete from release_artworks where release_id = ?").run(releaseId);
  const insert = db.prepare("insert or ignore into release_artworks (release_id, image_id, source, url, sort_order) values (?, ?, ?, ?, ?)");
  merged.forEach((artwork, index) => insert.run(releaseId, artwork.imageId, artwork.source ?? "artwork", artwork.url ?? null, index));
}

function replaceScreenshots(db: TrackerDatabase, releaseId: string, screenshots: ReleaseArtwork[] | undefined) {
  db.prepare("delete from release_screenshots where release_id = ?").run(releaseId);
  const insert = db.prepare("insert or replace into release_screenshots (release_id, image_id, source, sort_order) values (?, ?, ?, ?)");
  (screenshots ?? []).forEach((screenshot, index) => insert.run(releaseId, screenshot.imageId, screenshot.source ?? "artwork", index));
}

function replaceTrailers(db: TrackerDatabase, releaseId: string, trailers: GameTrailer[] | undefined) {
  db.prepare("delete from release_trailers where release_id = ?").run(releaseId);
  const insert = db.prepare("insert or replace into release_trailers (release_id, video_id, name, provider, sort_order) values (?, ?, ?, ?, ?)");
  (trailers ?? []).forEach((trailer, index) => insert.run(releaseId, trailer.videoId, trailer.name ?? null, trailer.provider, index));
}

function persistSourceUrls(db: TrackerDatabase, releaseId: string, sourceUrls: string[]) {
  const insert = db.prepare(`
    insert into sources (release_id, source_name, source_url, field)
    select ?, 'Release', ?, 'release'
    where not exists (
      select 1 from sources where release_id = ? and source_url = ? and field = 'release'
    )
  `);
  for (const url of sourceUrls.filter(Boolean)) insert.run(releaseId, url, releaseId, url);
}

// The publishers, developers and sources columns of a releases_fts row, as SQL over a release id
// expression. Used by the historical v1 migration, full rebuild and single-release refreshes.
export function releaseFtsValues(idSql: string) {
  return `coalesce((select group_concat(publisher, ' ') from release_publishers where release_id = ${idSql}), ''),
      coalesce((select group_concat(developer, ' ') from release_developers where release_id = ${idSql}), ''),
      coalesce((select group_concat(source_name || ' ' || source_url, ' ') from sources where release_id = ${idSql}), '')`;
}

function refreshSearchIndex(db: TrackerDatabase, releaseId: string) {
  const row = db.prepare("select rowid, id, title, normalized_title normalizedTitle from releases where id = ?").get(releaseId) as { rowid: number; id: string; title: string; normalizedTitle: string } | undefined;
  if (!row) return;
  db.prepare("delete from releases_fts where rowid = ?").run(row.rowid);
  db.prepare(`
    insert into releases_fts(rowid, title, normalized_title, publishers, developers, sources)
    values (@rowid, @title, @normalizedTitle, ${releaseFtsValues("@id")})
  `).run(row);
}
