import { describe, expect, test } from "vitest";
import { computeSortDateAndEligibility, chooseBestReleaseDate, createReleasePolicy, normalizeIgdbGame } from "../../apps/backend/src/sync/releasePolicy";
import { applyFieldPrecedence } from "../../apps/backend/src/sync/releaseMerge";
import type { IgdbGameLike, ReleaseOverride } from "../../shared/types";

const baseGame: IgdbGameLike = {
  id: 1,
  name: "Persona 4 Revival",
  game_type: 8,
  first_release_date: 1802908800,
  release_dates: [
    { human: "Feb 18, 2027", date: 1802908800, platform: { id: 6, slug: "win", abbreviation: "PC", name: "PC" } }
  ],
  platforms: [{ id: 6, slug: "win", abbreviation: "PC", name: "PC" }, { id: 167, slug: "ps5", abbreviation: "PS5", name: "PlayStation 5" }],
  genres: [{ name: "Role-playing (RPG)" }],
  involved_companies: [{ company: { id: 1, name: "Atlus" }, developer: true, publisher: true }],
  hypes: 50,
  total_rating_count: 0,
  url: "https://www.igdb.com/games/persona-4-revival",
  slug: "persona-4-revival",
  updated_at: 1800000000
};

// Tracks Atlus (1) and Sega (2) on every platform from 2026; each test narrows what it needs.
const policy = (rules: Partial<Parameters<typeof createReleasePolicy>[0]> = {}) =>
  createReleasePolicy({ publisherIds: [1, 2], platforms: ["pc", "xbox", "playstation", "switch"], trackFrom: "2026-01-01", ...rules });
const evaluateCandidate = (game: IgdbGameLike) => policy().evaluate(game);

describe("release eligibility and sort dates", () => {
  test("computes eligibility and effective sort dates from exact, year, window, and TBA values", () => {
    expect(computeSortDateAndEligibility({ dateText: "Jan 1, 2026", releaseDate: "2026-01-01", datePrecision: "Exact", releaseWindow: null })).toMatchObject({
      eligible: true,
      effectiveSortDate: "2026-01-01"
    });
    expect(computeSortDateAndEligibility({ dateText: "2027", releaseDate: null, datePrecision: "Year", releaseWindow: "2027" })).toMatchObject({
      eligible: true,
      effectiveSortDate: "2027-01-01"
    });
    expect(computeSortDateAndEligibility({ dateText: "Early 2027", releaseDate: null, datePrecision: "Window", releaseWindow: "Early 2027" })).toMatchObject({
      eligible: true,
      effectiveSortDate: "2027-01-01"
    });
    expect(computeSortDateAndEligibility({ dateText: "TBA", releaseDate: null, datePrecision: "TBA", releaseWindow: null })).toMatchObject({
      eligible: false,
      effectiveSortDate: null
    });
  });

  test("a stored release is eligible whenever it has a date; the track-from date is not part of it", () => {
    expect(computeSortDateAndEligibility({ dateText: "Dec 31, 2019", releaseDate: "2019-12-31", datePrecision: "Exact", releaseWindow: null }).eligible).toBe(true);
  });
});

describe("IGDB candidate rules", () => {
  test("includes DLC, expansions, remakes, remasters, expanded games, and ports", () => {
    for (const gameType of [0, 1, 2, 4, 8, 9, 10, 11]) {
      const result = evaluateCandidate({ ...baseGame, game_type: gameType });
      expect(result.accepted, `game_type ${gameType}`).toBe(true);
    }
  });

  test("rejects demos, deluxe editions and season passes; sports games are welcome", () => {
    expect(evaluateCandidate({ ...baseGame, genres: [{ name: "Sports" }] }).accepted).toBe(true);
    expect(evaluateCandidate({ ...baseGame, name: "Exodus Demo" }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, name: "Persona 4 Revival Digital Deluxe" }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, name: "Persona 4 Revival Guidebook Edition" }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, name: "Persona 4 Revival Complete Launch Edition" }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, name: "Persona 4 Revival Season Pass" }).accepted).toBe(false);
  });

  test("keeps only games on a tracked platform family", () => {
    const ps5Only = { ...baseGame, platforms: [{ id: 167, slug: "ps5", abbreviation: "PS5", name: "PlayStation 5" }] };
    const switch2Only = { ...baseGame, platforms: [{ slug: "switch-2", name: "Nintendo Switch 2" }] };

    expect(policy().evaluate(ps5Only).accepted).toBe(true);
    expect(policy({ platforms: ["pc", "xbox"] }).evaluate(ps5Only)).toMatchObject({ accepted: false, reasons: ["not on a tracked platform"] });
    expect(policy({ platforms: ["switch"] }).evaluate(switch2Only).accepted).toBe(true);
  });

  test("keeps only games by a tracked publisher, and releases from the track-from date on", () => {
    expect(policy({ publisherIds: [2] }).evaluate(baseGame)).toMatchObject({ accepted: false, reasons: ["not by a tracked publisher"] });
    expect(policy({ trackFrom: "2027-03-01" }).evaluate(baseGame)).toMatchObject({ accepted: false, reasons: ["before 2027-03-01"] });
    expect(policy({ trackFrom: "2027-02-18" }).evaluate(baseGame).accepted).toBe(true);
  });

  test("does not accept incidental involved companies outside developer or publisher roles", () => {
    const result = evaluateCandidate({
      ...baseGame,
      involved_companies: [
        { company: { id: 1, name: "Atlus" }, developer: false, publisher: false },
        { company: { id: 90, name: "Small Port Studio" }, developer: true },
        { company: { id: 91, name: "Unknown Publisher" }, publisher: true }
      ]
    });

    expect(result.accepted).toBe(false);
  });

  test("prefers a tracked platform's date over an earlier date on an untracked one", () => {
    const date = chooseBestReleaseDate({
      ...baseGame,
      release_dates: [
        { human: "Jan 1, 2027", date: 1798761600, platform: { id: 167, slug: "ps5", abbreviation: "PS5", name: "PlayStation 5" } },
        { human: "Mar 3, 2027", date: 1804032000, platform: { id: 169, slug: "series-x-s", abbreviation: "Series X|S", name: "Xbox Series X|S" } }
      ]
    }, ["pc", "xbox"]);

    expect(date.dateText).toBe("Mar 3, 2027");
    expect(date.releaseDate).toBe("2027-03-03");
    expect(date.datePrecision).toBe("Exact");
  });

  // IGDB gives a vague date a timestamp at the end of its period (Dec 31 for "2027" or "Q4 2026"), so the
  // human text, not the timestamp, says how precise it is.
  test.each([
    ["2027", 1830211200, "Year", "2027"],
    ["Q4 2026", 1798675200, "Window", "Q4 2026"],
    ["Dec 2026", 1798675200, "Month", null],
    ["Feb 18, 2027", 1802908800, "Exact", null]
  ] as const)("a dated IGDB release shown as %s (timestamp %i) has %s precision", (human, date, precision, releaseWindow) => {
    const choice = chooseBestReleaseDate({ ...baseGame, release_dates: [{ human, date }] });

    expect(choice.dateText).toBe(human);
    expect(choice.datePrecision).toBe(precision);
    expect(choice.releaseWindow).toBe(releaseWindow);
  });

  test("the track-from date applies to the tracked platform's date", () => {
    const result = policy({ platforms: ["pc"] }).evaluate({
      ...baseGame,
      release_dates: [
        { human: "Dec 15, 2025", date: 1765756800, platform: { id: 167, slug: "ps5", abbreviation: "PS5", name: "PlayStation 5" } },
        { human: "Jan 20, 2026", date: 1768867200, platform: { id: 6, slug: "win", abbreviation: "WIN", name: "Windows PC" } }
      ]
    });

    expect(result.accepted).toBe(true);
  });

  test("rejects platforms outside the four families", () => {
    expect(evaluateCandidate({ ...baseGame, platforms: [{ id: 86, slug: "turbografx16--1", abbreviation: "TG16", name: "PC Engine" }] }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, platforms: [{ id: 12, slug: "xbox360", abbreviation: "X360", name: "Xbox 360" }] }).accepted).toBe(false);
    expect(evaluateCandidate({ ...baseGame, platforms: [{ abbreviation: "PC", name: "PC" }] }).accepted).toBe(false);
  });

  test("a tracked developer counts as well as a tracked publisher", () => {
    const result = evaluateCandidate({
      ...baseGame,
      involved_companies: [{ company: { id: 2, name: "Sega" }, developer: true, publisher: false }, { company: { id: 90, name: "Other Publisher" }, publisher: true }],
      platforms: [{ id: 169, slug: "series-x-s", abbreviation: "Series X|S", name: "Xbox Series X|S" }],
      release_dates: [{ human: "Apr 2, 2027", date: 1806624000, platform: { id: 169, slug: "series-x-s", abbreviation: "Series X|S", name: "Xbox Series X|S" } }]
    });

    expect(result.accepted).toBe(true);
  });

  test("normalizes a repair seed with stale TBA into sourced release data", () => {
    const release = normalizeIgdbGame(baseGame);
    expect(release.title).toBe("Persona 4 Revival");
    expect(release.releaseDate).toBe("2027-02-18");
    expect(release.category).toBe("Remake");
  });

  test("normalizes IGDB artworks and keeps cover available for gallery capsules", () => {
    const release = normalizeIgdbGame({
      ...baseGame,
      cover: { image_id: "cover-only" },
      artworks: [{ image_id: "art-a" }, { image_id: "art-b" }]
    });

    expect(release.artworks).toEqual([
      { imageId: "art-a", source: "artwork" },
      { imageId: "art-b", source: "artwork" },
      { imageId: "cover-only", source: "cover" }
    ]);
  });

  test("normalizes one primary YouTube trailer using gameplay, announcement, then generic trailer priority", () => {
    const release = normalizeIgdbGame({
      ...baseGame,
      videos: [
        { video_id: "", name: "Broken Gameplay" },
        { video_id: "generic12345", name: "Overview Trailer" },
        { video_id: "announce123", name: "Announcement Trailer" },
        { video_id: "gameplay123", name: "Gameplay Trailer" }
      ]
    });

    expect(release.trailers).toEqual([{ videoId: "gameplay123", name: "Gameplay Trailer", provider: "youtube" }]);

    expect(normalizeIgdbGame({
      ...baseGame,
      videos: [
        { video_id: "overview123", name: "Overview Trailer" },
        { video_id: "announce123", name: "Announcement Trailer" }
      ]
    }).trailers).toEqual([{ videoId: "announce123", name: "Announcement Trailer", provider: "youtube" }]);

    expect(normalizeIgdbGame({
      ...baseGame,
      videos: [{ video_id: "overview123", name: "Overview Trailer" }]
    }).trailers).toEqual([{ videoId: "overview123", name: "Overview Trailer", provider: "youtube" }]);
  });

  test("uses cover image as fallback when artworks are missing", () => {
    const release = normalizeIgdbGame({
      ...baseGame,
      cover: { image_id: "cover-only" },
      artworks: []
    });

    expect(release.artworks).toEqual([{ imageId: "cover-only", source: "cover" }]);
  });

});

describe("override precedence", () => {
  test("applies user PATCH over seeded override over IGDB sync", () => {
    const igdb = { field: "dateText", value: "TBA", sourceType: "igdb" } satisfies ReleaseOverride;
    const seeded = { field: "dateText", value: "Jul 9, 2026", sourceType: "seeded", sourceUrl: "https://source.test", sourceName: "Source" } satisfies ReleaseOverride;
    const user = { field: "dateText", value: "Jul 10, 2026", sourceType: "user", sourceUrl: "https://user.test", sourceName: "Manual" } satisfies ReleaseOverride;

    expect(applyFieldPrecedence([igdb, seeded, user])).toBe("Jul 10, 2026");
    expect(applyFieldPrecedence([igdb, seeded])).toBe("Jul 9, 2026");
    expect(applyFieldPrecedence([igdb])).toBe("TBA");
  });
});
