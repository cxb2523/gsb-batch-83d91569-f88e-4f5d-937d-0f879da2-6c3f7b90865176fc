import { MAX_RELEASE_ROWS } from "../../../../shared/constants";
import type { GameTrailer, ReleaseArtwork, ReleaseDetail, ReleaseListItem } from "../../../../shared/types";
import type { TrackerDatabase } from "./db";
import { normalizeText } from "../text/normalizeText";
import { localArtworkUrl } from "../artwork/localArtworkStorage";
import { latestDateChanges, listDateChanges } from "../releaseDates/dateChanges";

export interface ReleaseFilters {
  search?: string;
  publisher?: string;
  category?: string;
  platform?: string;
  datePrecision?: string;
  includeReleased?: boolean;
  includeHidden?: boolean;
  // Only releases the user is watching.
  watchedOnly?: boolean;
  // The earliest effective date to list (the user's "track from" setting).
  releasedFrom?: string;
}

export function listReleases(db: TrackerDatabase, filters: ReleaseFilters) {
  const params: Record<string, string | number> = {};
  const where: string[] = ["releases.eligible = 1"];
  if (filters.search) {
    const terms = normalizeText(filters.search).split(/\s+/).filter(Boolean);
    if (terms.length > 0) {
      params.search = terms.map(term => `${term}*`).join(" ");
      where.push("releases.rowid in (select rowid from releases_fts where releases_fts match @search)");
    }
  }
  if (filters.publisher) {
    params.publisher = filters.publisher;
    where.push("exists (select 1 from release_publishers rp where rp.release_id = releases.id and rp.publisher = @publisher)");
  }
  if (filters.category) {
    params.category = filters.category;
    where.push("releases.category = @category");
  }
  if (filters.platform) {
    params.platform = filters.platform;
    where.push("exists (select 1 from release_platforms pl where pl.release_id = releases.id and pl.platform = @platform)");
  }
  if (filters.datePrecision) {
    params.datePrecision = filters.datePrecision;
    where.push("releases.date_precision = @datePrecision");
  }
  if (filters.releasedFrom) {
    params.releasedFrom = filters.releasedFrom;
    where.push("releases.effective_sort_date >= @releasedFrom");
  }
  if (!filters.includeHidden) where.push("coalesce(state.hidden, 0) = 0");
  if (!filters.includeReleased) where.push("coalesce(state.released, 0) = 0");
  if (filters.watchedOnly) where.push("coalesce(state.watched, 0) = 1");

  const rows = db.prepare(`
    select releases.*, coalesce(state.hidden, 0) hidden, coalesce(state.watched, 0) watched, coalesce(state.released, 0) released
    from releases
    left join user_release_state state on state.release_id = releases.id
    where ${where.join(" and ")}
    order by releases.effective_sort_date, releases.title
    limit ${MAX_RELEASE_ROWS + 1}
  `).all(params) as Array<Record<string, unknown>>;

  const items = hydrateListItems(db, rows.slice(0, MAX_RELEASE_ROWS));
  return { items, total: items.length, truncated: rows.length > MAX_RELEASE_ROWS };
}

export function getRelease(db: TrackerDatabase, id: string): ReleaseDetail | null {
  const row = db.prepare("select * from releases where id = ? and eligible = 1").get(id) as Record<string, unknown> | undefined;
  if (!row) return null;
  const [item] = hydrateListItems(db, [row]);
  const state = db.prepare("select hidden, watched, released from user_release_state where release_id = ?").get(id) as { hidden?: number; watched?: number; released?: number } | undefined;
  return {
    ...item,
    hidden: Boolean(state?.hidden),
    watched: Boolean(state?.watched),
    released: Boolean(state?.released),
    igdbUrl: row.igdb_url ? String(row.igdb_url) : null,
    eligibilityReason: row.eligibility_reason ? String(row.eligibility_reason) : null,
    sources: db.prepare("select source_name sourceName, source_url sourceUrl, field from sources where release_id = ? order by created_at desc").all(id) as ReleaseDetail["sources"],
    screenshots: listScreenshots(db, id),
    trailers: listTrailers(db, id),
    dateChanges: listDateChanges(db, id)
  };
}

// One query per child table for the whole page, grouped in memory, instead of one query per row.
function hydrateListItems(db: TrackerDatabase, rows: Array<Record<string, unknown>>): ReleaseListItem[] {
  if (rows.length === 0) return [];
  const ids = JSON.stringify(rows.map(row => String(row.id)));
  const publishers = groupValues(db, "release_publishers", "publisher", ids);
  const developers = groupValues(db, "release_developers", "developer", ids);
  const platforms = groupValues(db, "release_platforms", "platform", ids);
  const genres = groupValues(db, "release_genres", "genre", ids);
  const artworks = groupArtworks(db, ids);
  const dateChanges = latestDateChanges(db, ids);
  return rows.map(row => {
    const id = String(row.id);
    return {
      id,
      title: String(row.title),
      dateText: String(row.date_text),
      releaseDate: row.release_date ? String(row.release_date) : null,
      datePrecision: row.date_precision as ReleaseListItem["datePrecision"],
      releaseWindow: row.release_window ? String(row.release_window) : null,
      effectiveSortDate: row.effective_sort_date ? String(row.effective_sort_date) : null,
      category: row.category as ReleaseListItem["category"],
      publishers: publishers.get(id) ?? [],
      developers: developers.get(id) ?? [],
      platforms: platforms.get(id) ?? [],
      genres: genres.get(id) ?? [],
      sourceConfidence: Number(row.source_confidence ?? 0),
      artworks: artworks.get(id) ?? [],
      eligible: Boolean(row.eligible),
      hidden: Boolean(row.hidden),
      watched: Boolean(row.watched),
      released: Boolean(row.released),
      lastDateChange: dateChanges.get(id) ?? null
    };
  });
}

function groupValues(db: TrackerDatabase, table: string, column: string, ids: string) {
  const rows = db.prepare(`
    select release_id releaseId, ${column} value from ${table}
    where release_id in (select value from json_each(?))
    order by release_id, ${column}
  `).all(ids) as Array<{ releaseId: string; value: string }>;
  const grouped = new Map<string, string[]>();
  for (const row of rows) {
    const list = grouped.get(row.releaseId) ?? [];
    list.push(row.value);
    grouped.set(row.releaseId, list);
  }
  return grouped;
}

function groupArtworks(db: TrackerDatabase, ids: string) {
  const rows = db.prepare(`
    select release_id releaseId, image_id imageId, source, url from release_artworks
    where release_id in (select value from json_each(?))
    order by release_id, sort_order, image_id
  `).all(ids) as Array<{ releaseId: string; imageId: string; source?: string; url?: string | null }>;
  const grouped = new Map<string, ReleaseArtwork[]>();
  for (const row of rows) {
    const list = grouped.get(row.releaseId) ?? [];
    list.push(toArtwork(row));
    grouped.set(row.releaseId, list);
  }
  return grouped;
}

function toArtwork(artwork: { imageId: string; source?: string; url?: string | null }): ReleaseArtwork {
  if (artwork.source === "local") return { imageId: artwork.imageId, source: "local", url: artwork.url || localArtworkUrl(artwork.imageId) };
  if (artwork.source === "steamgriddb" && artwork.url) return { imageId: artwork.imageId, source: "steamgriddb", url: artwork.url };
  if (artwork.source === "cover") return { imageId: artwork.imageId, source: "cover" };
  if (artwork.source === "artwork") return { imageId: artwork.imageId, source: "artwork" };
  return { imageId: artwork.imageId };
}

function listScreenshots(db: TrackerDatabase, releaseId: unknown) {
  return db.prepare(`select image_id imageId, source from release_screenshots where release_id = ? order by sort_order, image_id`).all(releaseId).map(row => {
    const screenshot = row as { imageId: string; source?: string };
    return { imageId: screenshot.imageId, source: "artwork" as const };
  }) satisfies ReleaseArtwork[];
}

function listTrailers(db: TrackerDatabase, releaseId: unknown) {
  return db.prepare(`select video_id videoId, name from release_trailers where release_id = ? order by sort_order, video_id`).all(releaseId).map(row => {
    const trailer = row as { videoId: string; name?: string | null };
    return { videoId: trailer.videoId, name: trailer.name ?? null, provider: "youtube" as const };
  }) satisfies GameTrailer[];
}
