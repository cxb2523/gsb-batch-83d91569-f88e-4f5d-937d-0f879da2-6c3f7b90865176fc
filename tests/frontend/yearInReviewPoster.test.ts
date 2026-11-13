import { afterEach, describe, expect, test, vi } from "vitest";
import type { YearInReviewGame, YearInReviewSummary } from "../../shared/types";
import { drawPoster, PHONE, phoneLayout, posterLayout } from "../../apps/frontend/src/views/yearInReview/poster";

describe("Year in Review poster: horizontal grid", () => {
  test("every game gets a tile, inside the poster, below the header, none overlapping", () => {
    for (const count of [1, 2, 7, 42, 120, 400]) {
      const layout = posterLayout(count);
      expect(layout.tiles).toHaveLength(count);
      for (const tile of layout.tiles) {
        expect(tile.x).toBeGreaterThanOrEqual(0);
        expect(tile.x + tile.width).toBeLessThanOrEqual(layout.width);
        expect(tile.y).toBeGreaterThanOrEqual(layout.header.top + layout.header.height);
        expect(tile.y + tile.coverHeight + tile.captionSize * 3.1).toBeLessThanOrEqual(layout.height);
        expect(tile.coverHeight).toBe(Math.round(tile.width * 4 / 3));
      }
      for (let index = 1; index < layout.tiles.length; index += 1) {
        const [previous, current] = [layout.tiles[index - 1], layout.tiles[index]];
        if (current.y === previous.y) expect(current.x).toBeGreaterThanOrEqual(previous.x + previous.width);
      }
    }
  });

  test("rows are centred, including a short last row", () => {
    const layout = posterLayout(5);
    const rows = new Map<number, number[]>();
    for (const tile of layout.tiles) rows.set(tile.y, [...(rows.get(tile.y) ?? []), tile.x]);
    for (const xs of rows.values()) {
      const left = Math.min(...xs);
      const right = Math.max(...xs) + layout.tiles[0].width;
      expect(Math.abs(left - (layout.width - right))).toBeLessThanOrEqual(2);
    }
  });
});

describe("Year in Review poster: vertical, for a phone's Reddit feed", () => {
  test("a typical year gets 6-7 covers a row and stays about a phone screen tall", () => {
    const layout = phoneLayout(42);
    expect(layout.columns).toBe(7);
    expect(layout.width).toBe(1080);
    expect(layout.height).toBeLessThanOrEqual(2100);
    expect(phoneLayout(20).columns).toBe(6);
  });

  test("names read at a glance when the feed shows the image at phone width", () => {
    // A phone feed shows the 1080-wide image about 390pt wide, so 24px reads as roughly 9pt.
    for (const count of [3, 12, 42, 90]) {
      const [tile] = phoneLayout(count).phoneTiles;
      expect(tile.titleSize).toBeGreaterThanOrEqual(PHONE.minTitle);
      expect(tile.platformSize).toBeGreaterThanOrEqual(20);
    }
  });

  test("every game gets a tile, inside the image, none overlapping, rows centred", () => {
    for (const count of [1, 5, 9, 42, 150]) {
      const layout = phoneLayout(count);
      expect(layout.phoneTiles).toHaveLength(count);
      for (const tile of layout.phoneTiles) {
        expect(tile.x).toBeGreaterThanOrEqual(0);
        expect(tile.x + tile.width).toBeLessThanOrEqual(layout.width);
        expect(tile.y).toBeGreaterThanOrEqual(layout.header.top + layout.header.height);
        expect(tile.y + tile.coverHeight + tile.titleSize * 2.3 + tile.platformSize).toBeLessThanOrEqual(layout.height);
      }
      const rows = new Map<number, number[]>();
      for (const tile of layout.phoneTiles) rows.set(tile.y, [...(rows.get(tile.y) ?? []), tile.x]);
      for (const xs of rows.values()) {
        const sorted = [...xs].sort((left, right) => left - right);
        for (let index = 1; index < sorted.length; index += 1) expect(sorted[index]).toBeGreaterThanOrEqual(sorted[index - 1] + layout.phoneTiles[0].width);
        expect(Math.abs(sorted[0] - (layout.width - (sorted[sorted.length - 1] + layout.phoneTiles[0].width)))).toBeLessThanOrEqual(2);
      }
    }
  });
});

describe("Year in Review poster: drawing", () => {
  afterEach(() => vi.unstubAllGlobals());

  // A canvas that records every font it is asked to draw with, and a font set that records what was loaded.
  function stubCanvas() {
    const drawn = new Set<string>();
    const loaded = new Set<string>();
    const context = new Proxy({} as Record<string, unknown>, {
      get: (_target, key) => (key === "measureText" ? () => ({ width: 10 }) : () => ({ addColorStop: () => undefined })),
      set: (_target, key, value) => {
        if (key === "font") drawn.add(weightAndFamily(String(value)));
        return true;
      }
    });
    const canvas = { getContext: () => context, toBlob: (resolve: (blob: Blob) => void) => resolve(new Blob(["png"])) };
    vi.stubGlobal("document", {
      createElement: () => canvas,
      fonts: { load: async (spec: string) => { loaded.add(weightAndFamily(spec)); } }
    });
    return { drawn, loaded };
  }

  const weightAndFamily = (font: string) => font.replace(/ \d+px /, " ").split(",")[0];

  test.each(["horizontal", "vertical"] as const)("the %s poster loads every font it draws with", async orientation => {
    const { drawn, loaded } = stubCanvas();
    const game = { id: "g1", title: "Hades", userPlatform: "PC", ratingScore: 9, coverImageId: null } as YearInReviewGame;
    const summary = { year: 2026, count: 1, inProgress: false, games: [game], goty: { game } } as unknown as YearInReviewSummary;

    await drawPoster({ summary, orientation, coverSrc: id => id });

    expect(drawn.size).toBeGreaterThan(0);
    expect([...drawn].filter(font => !loaded.has(font))).toEqual([]);
  });
});
