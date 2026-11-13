import type { CompletedGameMatchCandidate, IgdbGameLike, ReleaseArtwork } from "../../../../shared/types";
import { getCompanyNames, getPlatformNames } from "../igdb/igdbGame";
import { scoreNameMatch, scorePlatformMatch } from "../matching/titleMatch";
import { normalizeText } from "../text/normalizeText";

// IGDB metadata saved onto a completed game when it is matched.
export interface CompletedMetadataPatch {
  igdbId: number | null;
  coverImageId: string | null;
  igdbReleaseDate: string | null;
  igdbDeveloper: string | null;
  igdbPublisher: string | null;
  igdbGenres: string[];
  igdbPlatforms: string[];
  igdbThemes: string[];
  igdbGameModes: string[];
  igdbRating: number | null;
  igdbAggregatedRating: number | null;
  igdbTotalRating: number | null;
  igdbTotalRatingCount: number | null;
  summary: string | null;
  screenshots: ReleaseArtwork[];
  matchStatus: "matched" | "needsReview" | "unmatched";
}

export interface CompletedIgdbClient {
  searchGames(title: string): Promise<IgdbGameLike[]>;
  getGameDetails(id: number): Promise<IgdbGameLike | null>;
}

interface CompletedMatchQuery {
  normalizedTitle: string;
  userPlatform: string;
  completionYear?: number | null;
}

// What a completed game is matched by: its title and platform, plus the completion year as a tie-breaker.
interface CompletedMatchRequest {
  title: string;
  userPlatform: string;
  completionYear?: number | null;
}

export type CompletedMatchLookup<T> = { ok: true; value: T } | { ok: false; reason: "no-credentials" | "not-found" };

const noCredentials = { ok: false, reason: "no-credentials" } as const;

// The Completed IGDB matcher: every IGDB search, ranking and details fetch for completed games goes
// through here (manual search, fix match, adding a game from IGDB). Searches are cached per matcher.
export function createCompletedMatcher(igdb: { hasCredentials(): boolean; completed: CompletedIgdbClient }) {
  const searchCache = new Map<string, Promise<IgdbGameLike[]>>();
  const search = (title: string) => {
    const key = normalizeText(title);
    let result = searchCache.get(key);
    if (!result) {
      result = igdb.completed.searchGames(title);
      searchCache.set(key, result);
      result.catch(() => searchCache.delete(key));
    }
    return result;
  };
  const rank = async (request: CompletedMatchRequest) =>
    chooseCompletedMatch({ ...request, normalizedTitle: normalizeText(request.title) }, await search(request.title));

  return {
    hasCredentials: () => igdb.hasCredentials(),

    // Ranked IGDB candidates for the user to pick from.
    async candidates(request: CompletedMatchRequest): Promise<CompletedMatchLookup<CompletedGameMatchCandidate[]>> {
      if (!igdb.hasCredentials()) return noCredentials;
      return { ok: true, value: (await rank(request)).candidates };
    },

    // Full metadata for an IGDB game the user chose.
    async metadataFor(igdbId: number): Promise<CompletedMatchLookup<CompletedMetadataPatch>> {
      if (!igdb.hasCredentials()) return noCredentials;
      const game = await igdb.completed.getGameDetails(igdbId);
      return game ? { ok: true, value: toCompletedMetadata(game) } : { ok: false, reason: "not-found" };
    }
  };
}

function chooseCompletedMatch(query: CompletedMatchQuery, candidates: IgdbGameLike[]) {
  const ranked = candidates
    .map(candidate => toMatchCandidate(query, candidate))
    .sort((a, b) => b.confidence - a.confidence);
  const best = ranked[0];
  const second = ranked[1];
  if (!best || best.confidence < 85 || (second && best.confidence - second.confidence < 12)) {
    return { status: "needsReview" as const, candidates: ranked };
  }
  return { status: "matched" as const, match: best, candidates: ranked };
}

function toCompletedMetadata(game: IgdbGameLike, matchStatus: CompletedMetadataPatch["matchStatus"] = "matched"): CompletedMetadataPatch {
  const releaseDate = game.first_release_date ? new Date(game.first_release_date * 1000).toISOString().slice(0, 10) : null;
  return {
    igdbId: game.id,
    coverImageId: game.cover?.image_id ?? null,
    igdbReleaseDate: releaseDate,
    igdbDeveloper: getCompanyNames(game, "developer")[0] ?? null,
    igdbPublisher: getCompanyNames(game, "publisher")[0] ?? null,
    igdbGenres: (game.genres ?? []).map(genre => genre.name ?? "").filter(Boolean),
    igdbPlatforms: getPlatformNames(game),
    igdbThemes: (game.themes ?? []).map(theme => theme.name ?? "").filter(Boolean),
    igdbGameModes: (game.game_modes ?? []).map(mode => mode.name ?? "").filter(Boolean),
    igdbRating: game.rating ?? null,
    igdbAggregatedRating: game.aggregated_rating ?? null,
    igdbTotalRating: game.total_rating ?? null,
    igdbTotalRatingCount: game.total_rating_count ?? null,
    summary: game.summary ?? null,
    screenshots: (game.screenshots ?? []).map(screen => screen.image_id).filter((imageId): imageId is string => Boolean(imageId)).slice(0, 6).map(imageId => ({ imageId, source: "artwork" as const })) satisfies ReleaseArtwork[],
    matchStatus
  };
}

function toMatchCandidate(query: CompletedMatchQuery, game: IgdbGameLike): CompletedGameMatchCandidate {
  let confidence = scoreNameMatch(query.normalizedTitle, game.name ?? "");
  const platforms = getPlatformNames(game);
  confidence += scorePlatformMatch(query.userPlatform, platforms);
  if (query.completionYear && game.first_release_date) {
    const releaseYear = new Date(game.first_release_date * 1000).getUTCFullYear();
    if (releaseYear <= query.completionYear) confidence += 5;
  }
  return {
    igdbId: game.id,
    title: game.name,
    releaseDate: game.first_release_date ? new Date(game.first_release_date * 1000).toISOString().slice(0, 10) : null,
    platforms,
    summary: game.summary ?? null,
    coverImageId: game.cover?.image_id ?? null,
    confidence
  };
}
