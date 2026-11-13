import type { IgdbGameLike } from "../../../../shared/types";
import type { CompletedIgdbClient } from "../completed/completedIgdbMatcher";
import { IgdbClient } from "./client";
import type { TokenConfig } from "./token";

// The one way the backend talks to IGDB. A single client per credential set means one token,
// one rate limit shared by sync and user searches, and one place that knows the query text.
export interface IgdbGateway {
  hasCredentials(): boolean;
  query<T>(endpoint: string, body: string): Promise<T[]>;
  // `<endpoint>/count` for a where clause, e.g. count("games", "where ...;").
  count(endpoint: string, body: string): Promise<number>;
  // Up to 10 named sub-queries in one request.
  multiquery<T>(body: string): Promise<Array<IgdbMultiqueryResult<T>>>;
  searchReleaseCandidates(title: string): Promise<IgdbGameLike[]>;
  completed: CompletedIgdbClient;
  validateCredentials(): Promise<void>;
}

export interface IgdbMultiqueryResult<T> {
  name: string;
  result?: T[];
  count?: number;
}

const releaseCandidateFields = "id,name,url,game_type,first_release_date,release_dates.human,release_dates.date,release_dates.platform.id,release_dates.platform.abbreviation,release_dates.platform.name,release_dates.platform.slug,cover.image_id,artworks.image_id,screenshots.image_id,videos.video_id,videos.name,platforms.abbreviation,platforms.name,platforms.slug,platforms.id,involved_companies.developer,involved_companies.publisher,involved_companies.company.name";
const completedGameFields = "name,summary,first_release_date,cover.image_id,screenshots.image_id,platforms.abbreviation,platforms.name,genres.name,themes.name,game_modes.name,rating,rating_count,aggregated_rating,total_rating,total_rating_count,involved_companies.developer,involved_companies.publisher,involved_companies.company.name";

export function hasIgdbCredentials(config: TokenConfig) {
  return Boolean(config.clientId && (config.clientSecret || config.accessToken));
}

export function escapeIgdbSearch(title: string) {
  return title.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

export function createIgdbGateway({ readConfig, fetcher }: { readConfig: () => TokenConfig; fetcher?: typeof fetch }): IgdbGateway {
  let current: { key: string; client: IgdbClient } | null = null;

  // Rebuilt only when the saved credentials change, which also drops the old token.
  const client = () => {
    const config = readConfig();
    const key = JSON.stringify([config.clientId ?? "", config.clientSecret ?? "", config.accessToken ?? ""]);
    if (!current || current.key !== key) current = { key, client: new IgdbClient(config, fetcher) };
    return current.client;
  };

  const query = <T>(endpoint: string, body: string) => client().query<T>(endpoint, body);

  return {
    hasCredentials: () => hasIgdbCredentials(readConfig()),
    query,
    async count(endpoint, body) {
      const response = await client().request<{ count?: unknown }>(`${endpoint}/count`, body);
      const count = Number(response?.count);
      if (!Number.isFinite(count)) throw new Error(`IGDB ${endpoint}/count returned no count`);
      return count;
    },
    multiquery<T>(body: string) {
      return client().request<Array<IgdbMultiqueryResult<T>>>("multiquery", body);
    },
    searchReleaseCandidates(title) {
      return query<IgdbGameLike>("games", `search "${escapeIgdbSearch(title)}"; fields ${releaseCandidateFields}; limit 8;`);
    },
    completed: {
      searchGames(title) {
        return query<IgdbGameLike>("games", `search "${escapeIgdbSearch(title)}"; fields ${completedGameFields}; limit 8;`);
      },
      async getGameDetails(id) {
        const rows = await query<IgdbGameLike>("games", `where id = ${Math.trunc(id)}; fields ${completedGameFields}; limit 1;`);
        return rows[0] ?? null;
      }
    },
    async validateCredentials() {
      await query("companies", 'search "Atlus"; fields id,name; limit 1;');
    }
  };
}
