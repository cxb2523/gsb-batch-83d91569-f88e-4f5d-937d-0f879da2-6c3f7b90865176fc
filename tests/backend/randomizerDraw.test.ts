import { describe, expect, test } from "vitest";
import type { IgdbGameLike } from "../../shared/types";
import { cooldownWindows, drawRandomGame, REEL_SIZE, toRandomizerPick, type DrawIo } from "../../apps/backend/src/randomizer/draw";

// mulberry32: a tiny seeded rng so draws are repeatable.
function seededRng(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// An in-memory catalogue that answers count and page calls like IGDB with `sort id asc`.
function fakeCatalogue(ids: number[]) {
  const calls: Array<{ kind: "count" | "page"; excluded: number[]; limit?: number; offset?: number }> = [];
  const pool = (excluded: number[]) => ids.filter(id => !excluded.includes(id)).sort((a, b) => a - b);
  const io: DrawIo = {
    async countGames(excluded) {
      calls.push({ kind: "count", excluded });
      return pool(excluded).length;
    },
    async fetchPage(excluded, limit, offset) {
      calls.push({ kind: "page", excluded, limit, offset });
      return pool(excluded).slice(offset, offset + limit).map(id => ({ id, name: `Game ${id}` }));
    }
  };
  return { io, calls };
}

const range = (from: number, to: number) => Array.from({ length: to - from + 1 }, (_, index) => from + index);

describe("randomizer draw", () => {
  test("cooldown windows halve down to 1", () => {
    expect(cooldownWindows(0)).toEqual([]);
    expect(cooldownWindows(1)).toEqual([1]);
    expect(cooldownWindows(7)).toEqual([7, 3, 1]);
    expect(cooldownWindows(200)).toEqual([50, 25, 12, 6, 3, 1]);
  });

  test("small pools fetch every game and use two requests", async () => {
    const catalogue = fakeCatalogue(range(1, 40));

    const result = await drawRandomGame({ recentIds: [], fixedExcludedIds: [], rng: seededRng(1), io: catalogue.io });

    expect(result.poolSize).toBe(40);
    expect(result.game?.id).toBeGreaterThanOrEqual(1);
    expect(result.reels).toHaveLength(REEL_SIZE - 1);
    expect(result.reels.map(game => game.id)).not.toContain(result.game?.id);
    expect(result.repeatAllowed).toBe(false);
    expect(catalogue.calls.map(call => [call.kind, call.limit, call.offset])).toEqual([["count", undefined, undefined], ["page", 500, 0]]);
  });

  test("large pools fetch one reel-sized window at a random offset", async () => {
    const catalogue = fakeCatalogue(range(1, 5000));

    const result = await drawRandomGame({ recentIds: [], fixedExcludedIds: [], rng: seededRng(7), io: catalogue.io });

    const page = catalogue.calls[1];
    expect(page).toMatchObject({ kind: "page", limit: REEL_SIZE });
    expect(page.offset).toBeGreaterThanOrEqual(0);
    expect(page.offset).toBeLessThanOrEqual(5000 - REEL_SIZE);
    expect(result.game!.id).toBeGreaterThan(page.offset!);
    expect(result.game!.id).toBeLessThanOrEqual(page.offset! + REEL_SIZE);
    expect(catalogue.calls).toHaveLength(2);
  });

  test("retries once from offset 0 when the pool shrank after counting", async () => {
    const calls: number[] = [];
    const io: DrawIo = {
      countGames: async () => 5000,
      fetchPage: async (_excluded, limit, offset) => {
        calls.push(offset);
        return offset === 0 ? [{ id: 1, name: "Only" }] : [];
      }
    };

    const result = await drawRandomGame({ recentIds: [], fixedExcludedIds: [], rng: () => 0.5, io });

    expect(calls).toEqual([2496, 0]);
    expect(result.game?.id).toBe(1);
  });

  test("excludes the cooldown window first, then completed and upcoming ids", async () => {
    const catalogue = fakeCatalogue(range(1, 100));

    await drawRandomGame({ recentIds: range(1, 60), fixedExcludedIds: [99], rng: seededRng(3), io: catalogue.io });

    expect(catalogue.calls[0].excluded).toEqual([...range(1, 50), 99]);
  });

  test("shrinks the cooldown window when it would empty the pool", async () => {
    const catalogue = fakeCatalogue(range(1, 10));
    const recent = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1];

    const result = await drawRandomGame({ recentIds: recent, fixedExcludedIds: [], rng: seededRng(5), io: catalogue.io });

    // 10 in the window -> 0; no window -> 10; then 5 -> 5 games left.
    expect(catalogue.calls.filter(call => call.kind === "count").map(call => call.excluded.length)).toEqual([10, 0, 5]);
    expect(result.repeatAllowed).toBe(true);
    expect(recent.slice(0, 5)).not.toContain(result.game?.id);
  });

  test("never repeats the previous pick while the pool has two or more games", async () => {
    const catalogue = fakeCatalogue([1, 2]);
    const rng = seededRng(11);
    const history: number[] = [];

    for (let spin = 0; spin < 30; spin++) {
      const result = await drawRandomGame({ recentIds: [...history].reverse(), fixedExcludedIds: [], rng, io: catalogue.io });
      if (history.length) expect(result.game?.id).not.toBe(history.at(-1));
      history.push(result.game!.id);
    }
  });

  test("a single-game pool may repeat that game", async () => {
    const catalogue = fakeCatalogue([42]);

    const result = await drawRandomGame({ recentIds: [42], fixedExcludedIds: [], rng: seededRng(2), io: catalogue.io });

    expect(result.game?.id).toBe(42);
    expect(result.repeatAllowed).toBe(true);
  });

  test("an empty pool returns no pick after one count, or two with history", async () => {
    const none = fakeCatalogue([]);
    expect(await drawRandomGame({ recentIds: [], fixedExcludedIds: [], rng: seededRng(1), io: none.io })).toEqual({ game: null, reels: [], poolSize: 0, repeatAllowed: false });
    expect(none.calls).toHaveLength(1);

    const withHistory = fakeCatalogue([]);
    await drawRandomGame({ recentIds: [1, 2, 3], fixedExcludedIds: [], rng: seededRng(1), io: withHistory.io });
    expect(withHistory.calls).toHaveLength(2);
  });
});

describe("randomizer pick mapping", () => {
  test("maps IGDB fields to the pick card shape", () => {
    const game: IgdbGameLike = {
      id: 1942,
      name: "The Witcher 3: Wild Hunt",
      url: "https://www.igdb.com/games/the-witcher-3-wild-hunt",
      first_release_date: Date.UTC(2015, 4, 19) / 1000,
      cover: { image_id: "co1wyy" },
      genres: [{ name: "RPG" }],
      themes: [{ name: "Fantasy" }],
      game_modes: [{ name: "Single player" }],
      platforms: [{ id: 6, abbreviation: "PC", name: "PC (Microsoft Windows)" }, { id: 34, abbreviation: "Android" }, { id: 48, abbreviation: "PS4", name: "PlayStation 4" }],
      total_rating: 92.6,
      total_rating_count: 3000,
      summary: "Geralt."
    };

    expect(toRandomizerPick(game)).toEqual({
      igdbId: 1942,
      title: "The Witcher 3: Wild Hunt",
      url: "https://www.igdb.com/games/the-witcher-3-wild-hunt",
      coverImageId: "co1wyy",
      releaseYear: 2015,
      genres: ["RPG"],
      themes: ["Fantasy"],
      gameModes: ["Single player"],
      platforms: ["PC", "PlayStation 4"],
      totalRating: 93,
      totalRatingCount: 3000,
      summary: "Geralt."
    });
  });
});
