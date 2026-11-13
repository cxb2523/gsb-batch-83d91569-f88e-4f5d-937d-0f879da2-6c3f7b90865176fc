import type { IgdbGameLike, RandomizerPick, RandomizerReelItem } from "../../../../shared/types";
import { MAINSTREAM_PLATFORMS } from "./catalog";

export const REEL_SIZE = 9;
export const COOLDOWN = 50;
// Pools up to this size are fetched whole (IGDB's max `limit`) and picked from exactly.
const SMALL_POOL = 500;

export interface DrawIo {
  countGames(excludedIds: number[]): Promise<number>;
  fetchPage(excludedIds: number[], limit: number, offset: number): Promise<IgdbGameLike[]>;
}

interface DrawInput {
  // Newest pick first. The first COOLDOWN of these form the cooldown window.
  recentIds: number[];
  // Always excluded (completed/upcoming games), placed after the cooldown ids.
  fixedExcludedIds: number[];
  rng: () => number;
  io: DrawIo;
}

interface DrawResult {
  game: IgdbGameLike | null;
  reels: IgdbGameLike[];
  poolSize: number;
  repeatAllowed: boolean;
}

// 50 -> 25 -> 12 -> 6 -> 3 -> 1. Never below 1 while there is a previous pick.
export function cooldownWindows(historyLength: number) {
  const windows: number[] = [];
  for (let size = Math.min(COOLDOWN, historyLength); size >= 1; size = Math.floor(size / 2)) {
    if (windows.at(-1) !== size) windows.push(size);
  }
  if (historyLength > 0 && windows.at(-1) !== 1) windows.push(1);
  return windows;
}

// Picks one game uniformly from the filtered pool. IGDB I/O is injected; the caller owns the query text.
export async function drawRandomGame({ recentIds, fixedExcludedIds, rng, io }: DrawInput): Promise<DrawResult> {
  const excludedFor = (window: number) => [...recentIds.slice(0, window), ...fixedExcludedIds];
  const windows = cooldownWindows(recentIds.length);
  const fullWindow = windows[0] ?? 0;

  let window = fullWindow;
  let poolSize = await io.countGames(excludedFor(window));
  if (poolSize === 0) {
    if (fullWindow === 0) return empty();
    // One check without any cooldown first, so an impossible filter set costs one call, not six.
    const withoutCooldown = await io.countGames(excludedFor(0));
    if (withoutCooldown === 0) return empty();
    window = 0;
    poolSize = withoutCooldown;
    for (const smaller of windows.slice(1)) {
      const count = await io.countGames(excludedFor(smaller));
      if (count > 0) {
        window = smaller;
        poolSize = count;
        break;
      }
    }
    // window 0 here means the pool is exactly the previous pick, the one case a repeat is allowed.
  }

  const excluded = excludedFor(window);
  const repeatAllowed = window < fullWindow;
  const page = await fetchWindow(io, excluded, poolSize, rng);
  if (page.length === 0) return { ...empty(), poolSize, repeatAllowed };

  const pickIndex = Math.floor(rng() * page.length);
  const game = page[pickIndex];
  const others = page.filter((_, index) => index !== pickIndex);
  return { game, reels: sample(others, REEL_SIZE - 1, rng), poolSize, repeatAllowed };
}

async function fetchWindow(io: DrawIo, excluded: number[], poolSize: number, rng: () => number) {
  if (poolSize <= SMALL_POOL) return io.fetchPage(excluded, SMALL_POOL, 0);
  // Uniform window placement slightly under-weights the first and last REEL_SIZE - 1 games of the
  // ordering, which is negligible for pools in the thousands.
  const start = Math.floor(rng() * (poolSize - REEL_SIZE + 1));
  const page = await io.fetchPage(excluded, REEL_SIZE, start);
  // The pool can shrink between the count and the page request.
  return page.length > 0 ? page : io.fetchPage(excluded, REEL_SIZE, 0);
}

function sample<T>(items: T[], size: number, rng: () => number) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index--) {
    const swap = Math.floor(rng() * (index + 1));
    [copy[index], copy[swap]] = [copy[swap], copy[index]];
  }
  return copy.slice(0, size);
}

function empty(): DrawResult {
  return { game: null, reels: [], poolSize: 0, repeatAllowed: false };
}

const names = (items: Array<{ name?: string }> | undefined) => (items ?? []).map(item => item.name).filter((name): name is string => Boolean(name));

export function toRandomizerPick(game: IgdbGameLike): RandomizerPick {
  return {
    igdbId: game.id,
    title: game.name,
    url: game.url ?? null,
    coverImageId: game.cover?.image_id ?? null,
    releaseYear: game.first_release_date ? new Date(game.first_release_date * 1000).getUTCFullYear() : null,
    genres: names(game.genres),
    themes: names(game.themes),
    gameModes: names(game.game_modes),
    platforms: pickPlatforms(game.platforms),
    totalRating: typeof game.total_rating === "number" ? Math.round(game.total_rating) : null,
    totalRatingCount: game.total_rating_count ?? null,
    summary: game.summary ?? null
  };
}

// The card lists only the mainstream platforms the Randomizer covers, by their catalog names,
// so a PS4 game does not also read "Android, iOS, Mac".
function pickPlatforms(platforms: IgdbGameLike["platforms"]) {
  const names = (platforms ?? []).map(platform => {
    if (platform.id === undefined) return platform.abbreviation || platform.name;
    return MAINSTREAM_PLATFORMS.find(mainstream => mainstream.id === platform.id)?.name;
  });
  return [...new Set(names.filter((name): name is string => Boolean(name)))];
}

export function toReelItem(game: IgdbGameLike): RandomizerReelItem {
  return { title: game.name, coverImageId: game.cover?.image_id ?? null };
}
