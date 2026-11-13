import type { IgdbGameLike, RandomizerFilters, RandomizerOptions } from "../../../../shared/types";
import type { DrawIo } from "./draw";

// The Randomizer's stand-in for IGDB while the sample library is loaded and no IGDB keys are saved:
// 267 released games (real IGDB data, gathered from Randomizer spins) with the filter lists they use.
// Spins draw from these through the same draw as IGDB, with the filters applied in memory.
type Ref = { id?: number; name?: string };
// IGDB returns ids with every genre, theme and mode; the sample keeps them for filtering.
type SampleGame = IgdbGameLike & { genres?: Ref[]; themes?: Ref[]; game_modes?: Ref[] };

export interface SampleCatalog {
  options: RandomizerOptions;
  drawIo(filters: RandomizerFilters): DrawIo;
}

// The catalogue (about 280 KB) loads on the first sample spin or filter list, not every time the
// backend starts.
let catalog: Promise<SampleCatalog> | null = null;
export function loadSampleCatalog(): Promise<SampleCatalog> {
  catalog ??= import("../demo/randomizerSample.json").then(({ default: sample }) => {
    const games = sample.games as SampleGame[];
    return {
      options: { ...sample.options, perspectives: [], tags: [], sample: true } as RandomizerOptions,
      drawIo: filters => sampleDrawIo(games, filters)
    };
  });
  return catalog;
}

// Filters that search IGDB for more than the sample holds (tags, series, similar games, studios, camera).
export function sampleUnsupportedReason(filters: RandomizerFilters) {
  const needsIgdb = filters.tagIds?.length || filters.excludeTagIds?.length || filters.presets?.length || filters.madeInJapan
    || filters.franchiseIds?.length || filters.collectionIds?.length || filters.similarToId || filters.perspectiveIds?.length;
  return needsIgdb ? "The sample Randomizer spins among 267 games. Tags, quick picks, series, similar games, Made in Japan and camera view search all of IGDB, so they need your own IGDB keys (Settings → API keys)." : null;
}

function sampleDrawIo(games: SampleGame[], filters: RandomizerFilters): DrawIo {
  const matching = games.filter(game => matches(game, filters));
  const without = (excludedIds: number[]) => {
    const excluded = new Set(excludedIds);
    return matching.filter(game => !excluded.has(game.id));
  };
  return {
    countGames: async excludedIds => without(excludedIds).length,
    fetchPage: async (excludedIds, limit, offset) => without(excludedIds).slice(offset, offset + limit)
  };
}

function matches(game: SampleGame, filters: RandomizerFilters) {
  const ids = (refs?: Ref[]) => new Set((refs ?? []).map(ref => ref.id));
  const genres = ids(game.genres);
  const themes = ids(game.themes);
  const anyOf = (wanted: number[] | undefined, has: Set<number | undefined>) => !wanted?.length || wanted.some(id => has.has(id));
  const noneOf = (unwanted: number[] | undefined, has: Set<number | undefined>) => !unwanted?.some(id => has.has(id));
  const year = game.first_release_date ? new Date(game.first_release_date * 1000).getUTCFullYear() : null;
  const rating = game.total_rating ?? null;
  const count = game.total_rating_count ?? 0;
  const ratingOk = rating !== null && count >= (filters.minRatingCount ?? 5) && count <= (filters.maxRatingCount ?? Infinity)
    && rating >= (filters.minRating ?? 0) && rating <= (filters.maxRating ?? 100);
  return anyOf(filters.genreIds, genres) && noneOf(filters.excludeGenreIds, genres)
    && anyOf(filters.themeIds, themes) && noneOf(filters.excludeThemeIds, themes)
    && anyOf(filters.gameModeIds, ids(game.game_modes)) && anyOf(filters.platformIds, ids(game.platforms))
    && (filters.releasedFromYear === undefined || (year !== null && year >= filters.releasedFromYear))
    && (filters.releasedToYear === undefined || (year !== null && year <= filters.releasedToYear))
    && (ratingOk || Boolean(filters.includeUnrated));
}
