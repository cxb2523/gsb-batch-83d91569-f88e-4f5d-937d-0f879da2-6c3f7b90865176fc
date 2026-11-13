import type { IgdbGameLike, RandomizerGameOption, RandomizerHistoryItem, RandomizerOption, RandomizerOptions, RandomizerSeriesOption, RandomizerSpinResponse } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import { createReleaseStore } from "../database/releaseStore";
import { createCompletedGameStore } from "../completed/completedGameStore";
import type { IgdbGateway } from "../igdb/gateway";
import { COOLDOWN, drawRandomGame, toRandomizerPick, toReelItem, type DrawIo } from "../randomizer/draw";
import { createPickHistoryStore } from "../randomizer/pickHistoryStore";
import { MAINSTREAM_PLATFORMS, POPULAR_TAGS } from "../randomizer/catalog";
import { loadSampleCatalog, sampleUnsupportedReason } from "../randomizer/sampleCatalog";
import { isDemoLibraryLoaded } from "../demo/demoLibrary";
import {
  buildCountQuery,
  buildGameSearchQuery,
  buildGamesByIdQuery,
  buildJapanDeveloperWhere,
  buildJapanPageQuery,
  buildPageQuery,
  buildRandomizerWhere,
  buildSeriesSearchMultiquery,
  buildSimilarGamesQuery,
  buildTagSearchQuery,
  describeEmptyPool,
  OPTIONS_MULTIQUERY,
  parseRandomizerFilters
} from "../randomizer/queryBuilder";
import type { ActionResult } from "./actionResult";

const missingCredentials = { ok: false, statusCode: 409, error: "IGDB credentials are required for the randomizer" } as const;
const DEFAULT_HISTORY_LIMIT = 20;
const MAX_HISTORY_LIMIT = 100;

// The Randomizer only reads the library tables to hide games the user already has, and only ever
// writes its own pick history. IGDB failures throw and surface as the safe server error.
export function createRandomizerActions(db: TrackerDatabase, igdb: IgdbGateway, { rng = Math.random, now = () => new Date() }: { rng?: () => number; now?: () => Date } = {}) {
  const history = createPickHistoryStore(db);
  // With the sample library loaded and no IGDB keys, spins draw from the sample's games instead of IGDB.
  const sampleMode = () => !igdb.hasCredentials() && isDemoLibraryLoaded(db);
  // Filter option lists hardly change, so they are fetched once per backend process.
  let options: RandomizerOptions | null = null;
  let loadingOptions: Promise<RandomizerOptions> | null = null;

  const fetchOptions = async () => {
    const results = await igdb.multiquery<RandomizerOption>(OPTIONS_MULTIQUERY);
    const list = (name: string) => (results.find(entry => entry.name === name)?.result ?? [])
      .filter(option => Number.isSafeInteger(option.id) && typeof option.name === "string")
      .map(option => ({ id: option.id, name: option.name }));
    return {
      genres: list("genres"),
      themes: list("themes"),
      gameModes: list("gameModes"),
      perspectives: list("perspectives"),
      platforms: MAINSTREAM_PLATFORMS,
      tags: POPULAR_TAGS
    };
  };

  // IGDB's similar-games lists hardly change, so each seed is looked up once per backend process.
  type SimilarEntry = { direct: number[]; widened?: number[] };
  const similarCache = new Map<number, SimilarEntry>();
  const similarLists = async (ids: number[]) => {
    const rows = await igdb.query<{ similar_games?: number[] }>("games", buildSimilarGamesQuery(ids));
    return rows.map(row => [...new Set((row.similar_games ?? []).filter(id => Number.isSafeInteger(id)))]);
  };
  const directSimilar = async (seed: number) => {
    const cached = similarCache.get(seed);
    if (cached) return cached;
    const entry: SimilarEntry = { direct: (await similarLists([seed])).flat().filter(id => id !== seed) };
    similarCache.set(seed, entry);
    return entry;
  };
  // One step further: the direct matches plus games that at least two of them list as similar.
  // Games listed by only one drift off topic (Elden Ring -> Witcher 3 -> a cozy puzzle game).
  const widenedSimilar = async (seed: number) => {
    const entry = await directSimilar(seed);
    if (!entry.widened) {
      const lists = entry.direct.length ? await similarLists(entry.direct) : [];
      const votes = new Map<number, number>();
      for (const id of lists.flat()) votes.set(id, (votes.get(id) ?? 0) + 1);
      const needed = Math.min(2, entry.direct.length);
      const further = [...votes].filter(([id, count]) => count >= needed && id !== seed).map(([id]) => id);
      entry.widened = [...new Set([...entry.direct, ...further])];
    }
    return entry.widened;
  };


  return {
    async loadOptions(): Promise<ActionResult<RandomizerOptions>> {
      if (sampleMode()) return { ok: true, value: (await loadSampleCatalog()).options };
      if (options) return { ok: true, value: options };
      if (!igdb.hasCredentials()) return missingCredentials;
      loadingOptions ??= fetchOptions().finally(() => { loadingOptions = null; });
      const loaded = await loadingOptions;
      options = loaded;
      return { ok: true, value: loaded };
    },

    async spin(body: unknown): Promise<ActionResult<RandomizerSpinResponse>> {
      const parsed = parseRandomizerFilters(body);
      if (!parsed.ok) return { ok: false, statusCode: 400, error: parsed.error };
      const filters = parsed.filters;
      if (sampleMode()) {
        const unsupported = sampleUnsupportedReason(filters);
        if (unsupported) return { ok: true, value: { pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: unsupported } };
      } else if (!igdb.hasCredentials()) return missingCredentials;
      // Newest first, so they survive the exclusion-list cap. Duplicates are dropped by the query builder.
      const fixedExcludedIds = [
        ...(filters.hideCompleted === false ? [] : createCompletedGameStore(db).ownedIgdbIds()),
        ...(filters.hideUpcoming ? createReleaseStore(db).ownedIgdbIds() : [])
      ];
      const at = now();
      // Made in Japan draws over involved-company rows, then fetches those games: one extra request.
      // A game with two Japanese developers appears twice in the pool, a negligible bias.
      const ioFor = (candidateIds?: number[]): DrawIo => {
        if (filters.madeInJapan) {
          const where = (excluded: number[]) => buildJapanDeveloperWhere(filters, excluded, at, candidateIds);
          return {
            countGames: excluded => igdb.count("involved_companies", buildCountQuery(where(excluded))),
            fetchPage: async (excluded, limit, offset) => {
              const rows = await igdb.query<{ game?: number }>("involved_companies", buildJapanPageQuery(where(excluded), limit, offset));
              const ids = [...new Set(rows.map(row => row.game).filter((id): id is number => Number.isSafeInteger(id)))];
              if (!ids.length) return [];
              const games = await igdb.query<IgdbGameLike>("games", buildGamesByIdQuery(ids));
              return ids.map(id => games.find(game => game.id === id)).filter((game): game is IgdbGameLike => Boolean(game));
            }
          };
        }
        const where = (excluded: number[]) => buildRandomizerWhere(filters, excluded, at, candidateIds);
        return {
          countGames: excluded => igdb.count("games", buildCountQuery(where(excluded))),
          fetchPage: (excluded, limit, offset) => igdb.query<IgdbGameLike>("games", buildPageQuery(where(excluded), limit, offset))
        };
      };

      const recentIds = history.recentIgdbIds(COOLDOWN);
      let candidateIds: number[] | undefined;
      let similarWidened = false;
      if (filters.similarToId) {
        // Direct matches first. Only when none of them is left after the filters and the full
        // cooldown does the pool widen, so widening comes before repeating a recent pick.
        const { direct } = await directSimilar(filters.similarToId);
        const directLeft = direct.length ? await ioFor(direct).countGames([...recentIds, ...fixedExcludedIds]) : 0;
        const similar = directLeft > 0 ? direct : await widenedSimilar(filters.similarToId);
        similarWidened = similar.length > direct.length;
        candidateIds = similar;
        if (!similar.length) {
          const title = filters.similarToTitle ?? "this game";
          return { ok: true, value: { pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: `IGDB lists no similar games for ${title}.` } };
        }
      }

      const result = await drawRandomGame({
        recentIds,
        fixedExcludedIds,
        rng,
        io: sampleMode() ? (await loadSampleCatalog()).drawIo(filters) : ioFor(candidateIds)
      });

      if (!result.game) {
        const reason = result.poolSize > 0 ? "IGDB returned no games for these filters. Try spinning again." : describeEmptyPool(filters, options);
        return { ok: true, value: { pick: null, reels: [], poolSize: result.poolSize, repeatAllowed: false, reason } };
      }
      const pick = toRandomizerPick(result.game);
      await runWrite(db, () => history.record(pick, filters));
      return { ok: true, value: { pick, reels: result.reels.map(toReelItem), poolSize: result.poolSize, repeatAllowed: result.repeatAllowed, ...(similarWidened ? { similarWidened } : {}) } };
    },

    // Any IGDB keyword by name, for tags beyond the popular list.
    async searchTags(text: unknown): Promise<ActionResult<{ items: RandomizerOption[] }>> {
      const query = typeof text === "string" ? buildTagSearchQuery(text) : null;
      if (!query) return { ok: false, statusCode: 400, error: "Type at least 2 characters to search tags" };
      if (!igdb.hasCredentials()) return missingCredentials;
      const rows = await igdb.query<RandomizerOption>("keywords", query);
      return { ok: true, value: { items: rows.filter(row => Number.isSafeInteger(row.id) && typeof row.name === "string").map(row => ({ id: row.id, name: row.name })) } };
    },

    // Franchises and collections by name, for the series filter.
    async searchSeries(text: unknown): Promise<ActionResult<{ items: RandomizerSeriesOption[] }>> {
      const query = typeof text === "string" ? buildSeriesSearchMultiquery(text) : null;
      if (!query) return { ok: false, statusCode: 400, error: "Type at least 2 characters to search series" };
      if (!igdb.hasCredentials()) return missingCredentials;
      const results = await igdb.multiquery<RandomizerOption>(query);
      const list = (name: string, kind: RandomizerSeriesOption["kind"]) => (results.find(entry => entry.name === name)?.result ?? [])
        .filter(row => Number.isSafeInteger(row.id) && typeof row.name === "string")
        .map(row => ({ kind, id: row.id, name: row.name }));
      return { ok: true, value: { items: [...list("franchises", "franchise"), ...list("collections", "collection")] } };
    },

    // Full games by name, for choosing the "similar to" game.
    async searchGames(text: unknown): Promise<ActionResult<{ items: RandomizerGameOption[] }>> {
      const query = typeof text === "string" ? buildGameSearchQuery(text) : null;
      if (!query) return { ok: false, statusCode: 400, error: "Type at least 2 characters to search games" };
      if (!igdb.hasCredentials()) return missingCredentials;
      const rows = await igdb.query<IgdbGameLike>("games", query);
      return {
        ok: true,
        value: {
          items: rows.filter(row => Number.isSafeInteger(row.id) && typeof row.name === "string").map(row => ({
            id: row.id,
            name: row.name,
            year: row.first_release_date ? new Date(row.first_release_date * 1000).getUTCFullYear() : null,
            coverImageId: row.cover?.image_id ?? null
          }))
        }
      };
    },

    history(limit?: unknown): { items: RandomizerHistoryItem[] } {
      const requested = Number(limit);
      const size = Number.isSafeInteger(requested) && requested > 0 ? Math.min(requested, MAX_HISTORY_LIMIT) : DEFAULT_HISTORY_LIMIT;
      return { items: history.list(size) };
    },

    async clearHistory(): Promise<{ ok: true }> {
      await runWrite(db, () => history.clear());
      return { ok: true };
    }
  };
}
