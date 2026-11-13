import { ACCEPTED_GAME_TYPES } from "../../../../shared/constants";
import type { IgdbGameLike, TrackedPublisher } from "../../../../shared/types";
import { escapeIgdbSearch } from "../igdb/gateway";
import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import { createIgdbSyncProgressStore, type IgdbSyncProgress } from "./igdbSyncProgressStore";

interface IgdbQueryClient {
  query<T>(endpoint: string, body: string): Promise<T[]>;
}

export const PUBLISHER_BATCH_SIZE = 25;
export const PAGE_SIZE = 500;
export const MAX_GAMES_PER_COMPANY_BATCH = 2500;

const igdbGameFields = [
  "id",
  "name",
  "slug",
  "url",
  "game_type",
  "first_release_date",
  "updated_at",
  "hypes",
  "total_rating_count",
  "genres.name",
  "platforms.id",
  "platforms.slug",
  "platforms.name",
  "platforms.abbreviation",
  "release_dates.human",
  "release_dates.date",
  "release_dates.y",
  "release_dates.m",
  "release_dates.d",
  "release_dates.date_format",
  "release_dates.platform.id",
  "release_dates.platform.slug",
  "release_dates.platform.name",
  "release_dates.platform.abbreviation",
  "involved_companies.publisher",
  "involved_companies.developer",
  "involved_companies.company.id",
  "involved_companies.company.name",
  "artworks.image_id",
  "cover.image_id",
  "screenshots.image_id",
  "videos.video_id",
  "videos.name"
].join(",");

// Every game by a tracked company (as publisher or developer on IGDB) from the track-from year on.
// The in-memory crawl used by tests and by syncs handed an explicit candidate list: every company batch is
// walked from the first page and duplicate IGDB ids collapse into one game.
export async function discoverIgdbCandidates(client: IgdbQueryClient, { publisherIds, trackFrom }: { publisherIds: readonly number[]; trackFrom: string }): Promise<IgdbGameLike[]> {
  if (publisherIds.length === 0) throw new Error("No publishers are tracked yet. Add some in Settings → Sync, then sync again.");
  const seen = new Map<number, IgdbGameLike>();
  for (const ids of chunk([...publisherIds], PUBLISHER_BATCH_SIZE)) {
    for (let offset = 0; offset < MAX_GAMES_PER_COMPANY_BATCH; offset += PAGE_SIZE) {
      const batch = await client.query<IgdbGameLike>("games", buildPublisherGameQuery(ids, trackFrom, offset));
      for (const game of batch) seen.set(game.id, game);
      if (batch.length < PAGE_SIZE) break;
    }
  }
  return [...seen.values()];
}

export interface ResumableCollectionResult {
  ok: boolean;
  interrupted: boolean;
  games: IgdbGameLike[];
  progress: IgdbSyncProgress | null;
  error: string | null;
}

// The resumable crawl. Each fetched page and the resume cursor land in one transaction; a request that
// throws after retries are exhausted ends the round with status `interrupted` and every earlier page kept.
// The next call resumes at the failed page (same company batch, same offset), unless the previous round
// finished, the settings changed, or nothing is parked yet — then a fresh round starts on page one.
export async function collectIgdbCandidatesWithProgress(
  db: TrackerDatabase,
  client: IgdbQueryClient,
  { publisherIds, trackFrom }: { publisherIds: readonly number[]; trackFrom: string }
): Promise<ResumableCollectionResult> {
  if (publisherIds.length === 0) throw new Error("No publishers are tracked yet. Add some in Settings → Sync, then sync again.");

  const batches = chunk([...publisherIds], PUBLISHER_BATCH_SIZE);
  const store = createIgdbSyncProgressStore(db);
  const stored = await runWrite(db, () => prepareRound(store, batches, trackFrom));

  let batchIndex = stored.companyBatchIndex;
  let offset = stored.nextOffset;
  try {
    while (batchIndex < batches.length) {
      const page = await client.query<IgdbGameLike>("games", buildPublisherGameQuery(batches[batchIndex], trackFrom, offset));
      // A short page ends the batch. A full page keeps paging until the 2500-game cap, where the next
      // request would start at the cap itself and must never be sent.
      const atCap = offset + PAGE_SIZE >= MAX_GAMES_PER_COMPANY_BATCH;
      const batchFinished = page.length < PAGE_SIZE || atCap;
      const nextBatchIndex = batchFinished ? batchIndex + 1 : batchIndex;
      const nextOffset = batchFinished ? 0 : offset + PAGE_SIZE;
      // Games and cursor in one transaction: the page is never stored without the cursor moving past it.
      await runWrite(db, () => store.savePage(page, { companyBatchIndex: nextBatchIndex, nextOffset, batchFinished }));
      batchIndex = nextBatchIndex;
      offset = nextOffset;
    }
    const progress = await runWrite(db, () => {
      store.markComplete();
      return store.read();
    });
    return { ok: true, interrupted: false, games: store.stagedGames(), progress, error: null };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const progress = await runWrite(db, () => {
      store.markInterrupted(message);
      return store.read();
    });
    return { ok: false, interrupted: true, games: store.stagedGames(), progress, error: message };
  }
}

// Decide whether the parked cursor still describes this round. A completed round, changed publishers or
// track-from date, or a cursor that points past the current batches all start the crawl over from page one.
function prepareRound(store: ReturnType<typeof createIgdbSyncProgressStore>, batches: number[][], trackFrom: string): IgdbSyncProgress {
  const stored = store.read();
  const sameRules = stored
    && stored.companyIdsJson === JSON.stringify(batches.flat())
    && stored.trackFrom === trackFrom;
  const cursorInRange = stored && stored.companyBatchIndex < batches.length && stored.nextOffset < MAX_GAMES_PER_COMPANY_BATCH;
  if (stored && stored.status !== "complete" && sameRules && cursorInRange) {
    store.markRunning();
    return store.read()!;
  }
  store.reset(batches.flat(), trackFrom);
  return store.read()!;
}

export function buildPublisherGameQuery(companyIds: number[], trackFrom: string, offset: number) {
  const fromUnix = Math.floor(new Date(`${trackFrom}T00:00:00Z`).getTime() / 1000);
  const fromYear = Number(trackFrom.slice(0, 4));
  return `
    fields ${igdbGameFields};
    where game_type = (${ACCEPTED_GAME_TYPES.join(",")})
      & involved_companies.company = (${companyIds.join(",")})
      & (first_release_date >= ${fromUnix} | release_dates.y >= ${fromYear});
    sort first_release_date asc;
    limit ${PAGE_SIZE};
    offset ${offset};
  `;
}

interface IgdbCompany {
  id: number;
  name: string;
  published?: number[];
}

// Companies whose name contains the text, those that published the most games first.
export async function searchCompanies(client: IgdbQueryClient, text: string): Promise<TrackedPublisher[]> {
  const companies = await client.query<IgdbCompany>("companies", `
    fields id,name,published;
    where name ~ *"${escapeIgdbSearch(text)}"* & published != null;
    limit 50;
  `);
  return byGamesPublished(companies).slice(0, 10).map(({ id, name }) => ({ id, name }));
}

// The company with exactly this name that published the most games, or null.
export async function findCompanyByName(client: IgdbQueryClient, name: string): Promise<TrackedPublisher | null> {
  const companies = await client.query<IgdbCompany>("companies", `fields id,name,published; where name = "${escapeIgdbSearch(name)}"; limit 10;`);
  const best = byGamesPublished(companies)[0];
  return best ? { id: best.id, name: best.name } : null;
}

function byGamesPublished(companies: IgdbCompany[]) {
  return [...companies].sort((left, right) => (right.published?.length ?? 0) - (left.published?.length ?? 0));
}

function chunk<T>(items: T[], size: number) {
  const chunks: T[][] = [];
  for (let index = 0; index < items.length; index += size) chunks.push(items.slice(index, index + size));
  return chunks;
}
