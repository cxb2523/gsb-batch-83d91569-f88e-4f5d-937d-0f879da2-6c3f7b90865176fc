import { ACCEPTED_GAME_TYPES } from "../../../../shared/constants";
import type { IgdbGameLike, TrackedPublisher } from "../../../../shared/types";
import { escapeIgdbSearch } from "../igdb/gateway";

interface IgdbQueryClient {
  query<T>(endpoint: string, body: string): Promise<T[]>;
}

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
export async function discoverIgdbCandidates(client: IgdbQueryClient, { publisherIds, trackFrom }: { publisherIds: readonly number[]; trackFrom: string }): Promise<IgdbGameLike[]> {
  if (publisherIds.length === 0) throw new Error("No publishers are tracked yet. Add some in Settings → Sync, then sync again.");
  const seen = new Map<number, IgdbGameLike>();
  for (const ids of chunk([...publisherIds], 25)) {
    for (let offset = 0; offset < 2500; offset += 500) {
      const batch = await client.query<IgdbGameLike>("games", buildPublisherGameQuery(ids, trackFrom, offset));
      for (const game of batch) seen.set(game.id, game);
      if (batch.length < 500) break;
    }
  }
  return [...seen.values()];
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
    limit 500;
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
