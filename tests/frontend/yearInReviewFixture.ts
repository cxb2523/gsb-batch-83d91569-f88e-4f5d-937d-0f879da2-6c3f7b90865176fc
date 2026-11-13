import type { YearInReviewGame, YearInReviewSummary } from "../../shared/types";

export function reviewGame(overrides: Partial<YearInReviewGame> = {}): YearInReviewGame {
  return { id: "hades-pc", title: "Hades", coverImageId: "cohades", ratingScore: 9, userPlatform: "PC", finishLabel: "2 Mar 2026", month: 3, ...overrides };
}

// A summary with no cards; tests fill in what they check.
export function emptySummary(year: number, overrides: Partial<YearInReviewSummary> = {}): YearInReviewSummary {
  return {
    year,
    inProgress: false,
    count: 0,
    previousYearCount: null,
    coverage: { withMonth: 0, rated: 0, matched: 0 },
    overview: { months: Array(12).fill(0), busiestMonth: null, averageRating: null, nineOrHigher: 0, first: null, last: null },
    taste: { genres: [], themes: [], platforms: [], developer: null, publisher: null, playModes: null, somethingNew: null },
    ratings: { spread: null, hotTake: null, hiddenGem: null, criticsAgreed: null, playerType: null },
    timing: { dayOne: null, lateToTheParty: null, releaseRange: null, longestStreak: null },
    goty: null,
    games: [],
    ...overrides
  };
}

// A year with one game in every chapter.
export function fullSummary(year = 2026): YearInReviewSummary {
  const hades = reviewGame();
  const tunic = reviewGame({ id: "tunic-ps5", title: "Tunic", coverImageId: "cotunic", ratingScore: 7, userPlatform: "PS5", finishLabel: "Aug 2026", month: 8 });
  return emptySummary(year, {
    count: 2,
    previousYearCount: 1,
    coverage: { withMonth: 2, rated: 2, matched: 1 },
    overview: { months: [0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0], busiestMonth: { month: 3, count: 1 }, averageRating: 8, nineOrHigher: 1, first: hades, last: tunic },
    taste: {
      genres: [{ name: "RPG", count: 2, share: 1, ids: ["hades-pc", "tunic-ps5"] }, { name: "Roguelike", count: 1, share: 0.5, ids: ["hades-pc"] }],
      themes: [{ name: "Fantasy", count: 1, share: 1, ids: ["tunic-ps5"] }],
      platforms: [{ name: "PC", count: 1, share: 0.5, ids: ["hades-pc"] }, { name: "PS5", count: 1, share: 0.5, ids: ["tunic-ps5"] }],
      developer: { name: "Supergiant Games", count: 2 },
      publisher: null,
      playModes: { solo: 1, together: 0 },
      somethingNew: { genres: ["Roguelike"], platforms: [] }
    },
    ratings: {
      spread: [0, 0, 0, 0, 0, 0, 0, 1, 0, 1, 0],
      hotTake: { game: tunic, rating: 7, criticScore: 90 },
      hiddenGem: { game: hades, ratingCount: 12 },
      criticsAgreed: { agreed: 1, total: 2 },
      playerType: { key: "explorer", reason: "You played 8 different genres" }
    },
    timing: {
      dayOne: { games: [hades] },
      lateToTheParty: { game: tunic, years: 4, releaseYear: 2022 },
      releaseRange: { oldest: { game: tunic, year: 2022 }, newest: { game: hades, year: 2026 } },
      longestStreak: { months: 3, from: 5, to: 7 }
    },
    goty: { game: hades, isOverride: false, isLatestFinish: false, note: "Run 40 finally.", backdrop: { imageId: "shothades", kind: "screenshot" }, musicVideoId: null },
    games: [hades, tunic]
  });
}
