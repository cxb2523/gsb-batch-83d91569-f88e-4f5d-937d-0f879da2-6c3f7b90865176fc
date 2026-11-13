import { describe, expect, test } from "vitest";
import type { CompletedReviewRow } from "../../apps/backend/src/completed/completedReadModel";
import { buildYearInReview, listReviewYears, type YearInReviewInput } from "../../apps/backend/src/yearInReview/buildYearInReview";

const TODAY = new Date(2027, 1, 10);
let serial = 0;

function game(overrides: Partial<CompletedReviewRow> & { date?: string } = {}): CompletedReviewRow {
  serial += 1;
  const { date, ...rest } = overrides;
  const dateParts = date === undefined ? { completionDate: "2026-06-15", completionMonth: "2026-06", completionYear: 2026, completionPrecision: "exact" as const }
    : /^\d{4}-\d{2}-\d{2}$/.test(date) ? { completionDate: date, completionMonth: date.slice(0, 7), completionYear: Number(date.slice(0, 4)), completionPrecision: "exact" as const }
    : /^\d{4}-\d{2}$/.test(date) ? { completionDate: null, completionMonth: date, completionYear: Number(date.slice(0, 4)), completionPrecision: "month" as const }
    : { completionDate: null, completionMonth: null, completionYear: Number(date), completionPrecision: "year" as const };
  return {
    id: `game-${serial}`,
    title: `Game ${serial}`,
    userPlatform: "PS5",
    ratingScore: null,
    ...dateParts,
    genres: [],
    igdbGenres: [],
    coverImageId: `cover${serial}`,
    igdbId: null,
    developer: null,
    publisher: null,
    notes: null,
    igdbReleaseDate: null,
    igdbDeveloper: null,
    igdbPublisher: null,
    igdbThemes: [],
    igdbGameModes: [],
    igdbAggregatedRating: null,
    igdbTotalRatingCount: null,
    screenshots: [],
    ...rest
  };
}

function build(games: CompletedReviewRow[], extra: Partial<YearInReviewInput> = {}) {
  return buildYearInReview({ year: 2026, today: TODAY, games, earlier: { genres: [], platforms: [] }, years: [], settings: { gotyCompletedId: null, musicVideoId: null }, ...extra });
}

describe("Year in Review summary", () => {
  test("an empty year is a summary with no cards", () => {
    const summary = build([]);
    expect(summary.count).toBe(0);
    expect(summary.goty).toBeNull();
    expect(summary.overview.busiestMonth).toBeNull();
    expect(summary.ratings.playerType).toBeNull();
    expect(summary.games).toEqual([]);
  });

  test("the current year is in progress; a past one is not", () => {
    expect(build([], { year: 2027 }).inProgress).toBe(true);
    expect(build([]).inProgress).toBe(false);
  });

  test("the count is compared with last year only when last year had games", () => {
    expect(build([game()], { years: [{ year: 2025, count: 3 }, { year: 2026, count: 1 }] }).previousYearCount).toBe(3);
    expect(build([game()], { years: [{ year: 2024, count: 3 }] }).previousYearCount).toBeNull();
  });

  describe("overview", () => {
    test("year-only games count in totals but not in the month chart, and the coverage says so", () => {
      const summary = build([game({ date: "2026-03-02" }), game({ date: "2026-03" }), game({ date: "2026-07-09" }), game({ date: "2026" })]);
      expect(summary.count).toBe(4);
      expect(summary.overview.months).toEqual([0, 0, 2, 0, 0, 0, 1, 0, 0, 0, 0, 0]);
      expect(summary.overview.busiestMonth).toEqual({ month: 3, count: 2 });
      expect(summary.coverage.withMonth).toBe(3);
    });

    test("a tie for busiest month goes to the earlier month", () => {
      expect(build([game({ date: "2026-09-01" }), game({ date: "2026-02-01" })]).overview.busiestMonth).toEqual({ month: 2, count: 1 });
    });

    test("average rating is over rated games, with the 9+ count", () => {
      const summary = build([game({ ratingScore: 9.5 }), game({ ratingScore: 7 }), game({ ratingScore: 9 }), game()]);
      expect(summary.overview.averageRating).toBeCloseTo(8.5);
      expect(summary.overview.nineOrHigher).toBe(2);
      expect(summary.coverage.rated).toBe(3);
    });

    test("first and last use finish order: exact dates before month-only entries in the same month, year-only left out", () => {
      const monthOnly = game({ title: "Month only", date: "2026-01" });
      const exact = game({ title: "Exact", date: "2026-01-31" });
      const last = game({ title: "Last", date: "2026-11-02" });
      const yearOnly = game({ title: "Year only", date: "2026" });
      const summary = build([yearOnly, last, monthOnly, exact]);
      expect(summary.overview.first?.title).toBe("Exact");
      expect(summary.overview.last?.title).toBe("Last");
      expect(summary.games.map(item => item.title)).toEqual(["Exact", "Month only", "Last", "Year only"]);
      expect(summary.games.map(item => item.finishLabel)).toEqual(["31 Jan 2026", "Jan 2026", "2 Nov 2026", "2026"]);
      expect(summary.games.map(item => item.month)).toEqual([1, 1, 11, null]);
    });
  });

  describe("taste", () => {
    test("genres are Excel plus IGDB genres, case-insensitive, once per game, as a share of games", () => {
      const summary = build([
        game({ id: "a", title: "A", genres: ["RPG"], igdbGenres: ["Role-playing (RPG)", "rpg"] }),
        game({ id: "b", title: "B", genres: ["rpg", "Action"] }),
        game({ id: "c", title: "C", genres: ["Puzzle"] }),
        game({ id: "d", title: "D", genres: [] })
      ]);
      expect(summary.taste.genres.slice(0, 2)).toEqual([
        { name: "RPG", count: 2, share: 0.5, ids: ["a", "b"] },
        { name: "Action", count: 1, share: 0.25, ids: ["b"] }
      ]);
    });

    test("top genres stop at five; top themes at three and only from matched games", () => {
      const summary = build([
        game({ genres: ["A", "B", "C", "D", "E", "F"], igdbId: 1, igdbThemes: ["Horror", "Fantasy", "Sci-fi", "Drama"] }),
        game({ igdbThemes: ["Comedy"] })
      ]);
      expect(summary.taste.genres).toHaveLength(5);
      expect(summary.taste.themes.map(theme => theme.name)).toEqual(["Drama", "Fantasy", "Horror"]);
      expect(summary.taste.themes[0].share).toBe(1);
      expect(summary.coverage.matched).toBe(1);
    });

    test("platforms are split exactly as entered, with an empty platform as Unknown platform", () => {
      const summary = build([game({ id: "a", title: "A", userPlatform: "PS5" }), game({ id: "b", title: "B", userPlatform: "PlayStation 5" }), game({ id: "c", title: "C", userPlatform: "PS5" }), game({ id: "d", title: "D", userPlatform: "" })]);
      expect(summary.taste.platforms).toEqual([
        { name: "PS5", count: 2, share: 0.5, ids: ["a", "c"] },
        { name: "PlayStation 5", count: 1, share: 0.25, ids: ["b"] },
        { name: "Unknown platform", count: 1, share: 0.25, ids: ["d"] }
      ]);
    });

    test("platform spellings that differ only in case stay separate, as in the Completed Library filter", () => {
      const summary = build([game({ userPlatform: "PS5" }), game({ userPlatform: "ps5" }), game({ userPlatform: "PS5" })]);
      expect(summary.taste.platforms.map(entry => entry.name)).toEqual(["PS5", "ps5"]);
    });

    test("a favourite developer needs two games; IGDB developer wins over the typed one", () => {
      expect(build([game({ developer: "From", igdbDeveloper: "FromSoftware" }), game({ developer: "FromSoftware" }), game({ developer: "Other" })]).taste.developer)
        .toEqual({ name: "FromSoftware", count: 2 });
      expect(build([game({ developer: "A" }), game({ developer: "B" })]).taste.developer).toBeNull();
    });

    test("solo or together comes from IGDB game modes", () => {
      const summary = build([
        game({ igdbId: 1, igdbGameModes: ["Single player"] }),
        game({ igdbId: 2, igdbGameModes: ["Single player", "Co-operative"] }),
        game({ igdbId: 3, igdbGameModes: ["Multiplayer"] }),
        game()
      ]);
      expect(summary.taste.playModes).toEqual({ solo: 1, together: 2 });
      expect(build([game()]).taste.playModes).toBeNull();
    });

    test("something new lists genres and platforms not seen in any earlier year", () => {
      const summary = build([game({ genres: ["RPG", "Horror"], userPlatform: "Switch 2" }), game({ genres: ["rpg"], userPlatform: "PC" })], {
        earlier: { genres: ["rpg", "action"], platforms: ["PC"] },
        years: [{ year: 2020, count: 4 }]
      });
      expect(summary.taste.somethingNew).toEqual({ genres: ["Horror"], platforms: ["Switch 2"] });
    });

    test("there is nothing new in the first recorded year, or when everything was seen before", () => {
      expect(build([game({ genres: ["RPG"] })]).taste.somethingNew).toBeNull();
      expect(build([game({ genres: ["RPG"] })], { earlier: { genres: ["rpg"], platforms: ["PS5"] }, years: [{ year: 2020, count: 1 }] }).taste.somethingNew).toBeNull();
    });
  });

  describe("ratings", () => {
    test("the spread rounds half up for the chart only", () => {
      const summary = build([game({ ratingScore: 9.5 }), game({ ratingScore: 8 }), game({ ratingScore: 8.4 }), game({ ratingScore: 0 })]);
      expect(summary.ratings.spread).toEqual([1, 0, 0, 0, 0, 0, 0, 0, 2, 0, 1]);
      expect(summary.overview.averageRating).toBeCloseTo(6.475);
      expect(build([game()]).ratings.spread).toBeNull();
    });

    test("the hot take is the largest gap with critics, and only from 15 points", () => {
      const summary = build([
        game({ title: "Mild", ratingScore: 8, igdbAggregatedRating: 70 }),
        game({ title: "Hot", ratingScore: 9, igdbAggregatedRating: 71 }),
        game({ title: "Cold", ratingScore: 4, igdbAggregatedRating: 58 })
      ]);
      expect(summary.ratings.hotTake).toMatchObject({ game: { title: "Hot" }, rating: 9, criticScore: 71 });
      expect(build([game({ ratingScore: 8, igdbAggregatedRating: 66 })]).ratings.hotTake).toBeNull();
    });

    test("the hidden gem is the best-rated matched game, rated 8+, with fewer than 50 IGDB ratings", () => {
      const summary = build([
        game({ title: "Popular", igdbId: 1, ratingScore: 10, igdbTotalRatingCount: 900 }),
        game({ title: "Gem", igdbId: 2, ratingScore: 9, igdbTotalRatingCount: 12 }),
        game({ title: "Unmatched", ratingScore: 10 }),
        game({ title: "Unknown count", igdbId: 3, ratingScore: 8 })
      ]);
      expect(summary.ratings.hiddenGem).toMatchObject({ game: { title: "Gem" }, ratingCount: 12 });
      expect(build([game({ igdbId: 3, ratingScore: 8 })]).ratings.hiddenGem).toMatchObject({ ratingCount: 0 });
      expect(build([game({ igdbId: 3, ratingScore: 7.5, igdbTotalRatingCount: 3 })]).ratings.hiddenGem).toBeNull();
    });

    test("critics agreed counts rated games within 10 points of the critic score", () => {
      const summary = build([
        game({ ratingScore: 8, igdbAggregatedRating: 90 }),
        game({ ratingScore: 8, igdbAggregatedRating: 91 }),
        game({ ratingScore: 6, igdbAggregatedRating: 60 }),
        game({ ratingScore: 6 })
      ]);
      expect(summary.ratings.criticsAgreed).toEqual({ agreed: 2, total: 3 });
    });
  });

  describe("player type", () => {
    const many = (count: number, overrides: Partial<CompletedReviewRow> = {}) => Array.from({ length: count }, () => game(overrides));

    test.each([
      ["critic", () => many(5, { ratingScore: 5 }), "Your average was 5.0 across 5 rated games"],
      ["loyalist", () => [...many(4, { userPlatform: "PS5" }), game({ userPlatform: "PS5" })], "100% of your games were on PS5"],
      ["explorer", () => ["A", "B", "C", "D", "E", "F", "G", "H"].map(genre => game({ genres: [genre], userPlatform: genre })), "You played 8 different genres"],
      ["time-traveller", () => [game({ igdbReleaseDate: "2014-11-16" }), game({ igdbReleaseDate: "2016-01-01" }), game({ igdbReleaseDate: "2010-01-01" })], "Your median game was 12 years old"],
      ["day-one-hero", () => [game({ date: "2026-03-10", igdbReleaseDate: "2026-03-01" }), game({ date: "2026-04", igdbReleaseDate: "2026-03-20" }), game({ date: "2026-05-30", igdbReleaseDate: "2026-05-01" })], "3 games finished within a month of release"],
      ["completionist", () => ["A", "B", "C", "D"].flatMap(platform => many(6, { userPlatform: platform })), "24 games finished"],
      ["adventurer", () => [game()], "A bit of everything"]
    ])("%s", (key, games, reason) => {
      expect(build(games()).ratings.playerType).toEqual({ key, reason });
    });

    test("the first rule that fits wins", () => {
      expect(build(many(6, { ratingScore: 4, userPlatform: "PC" })).ratings.playerType?.key).toBe("critic");
    });

    test("a loyalist needs one platform spelled the same way", () => {
      const games = [...many(3, { userPlatform: "PS5" }), ...many(2, { userPlatform: "ps5" })];
      expect(build(games).ratings.playerType?.key).not.toBe("loyalist");
    });

    test("an unknown platform never makes a loyalist", () => {
      expect(build(many(5, { userPlatform: "" })).ratings.playerType?.key).toBe("adventurer");
    });
  });

  describe("timing", () => {
    test("day-one: within 30 days of release, or a month-only finish in the release month or the next", () => {
      const summary = build([
        game({ title: "Exact", date: "2026-03-31", igdbReleaseDate: "2026-03-01" }),
        game({ title: "Too late", date: "2026-04-01", igdbReleaseDate: "2026-03-01" }),
        game({ title: "Next month", date: "2026-04", igdbReleaseDate: "2026-03-28" }),
        game({ title: "Two months", date: "2026-05", igdbReleaseDate: "2026-03-28" }),
        game({ title: "Year only", date: "2026", igdbReleaseDate: "2026-01-01" }),
        game({ title: "Before release", date: "2026-02-20", igdbReleaseDate: "2026-03-01" })
      ]);
      expect(summary.timing.dayOne?.games.map(item => item.title)).toEqual(["Exact", "Next month"]);
    });

    test("a day-one finish in December counts a January release month-only finish", () => {
      expect(build([game({ date: "2026-01", igdbReleaseDate: "2025-12-20" })]).timing.dayOne?.games).toHaveLength(1);
    });

    test("late to the party is the biggest release-to-finish gap, from 2 years", () => {
      const summary = build([
        game({ title: "Half-Life 2", date: "2026-12-01", igdbReleaseDate: "2004-11-16" }),
        game({ title: "Newer", date: "2026-01-01", igdbReleaseDate: "2020-01-01" })
      ]);
      expect(summary.timing.lateToTheParty).toMatchObject({ game: { title: "Half-Life 2" }, years: 22, releaseYear: 2004 });
      expect(build([game({ date: "2026-06-01", igdbReleaseDate: "2024-07-01" })]).timing.lateToTheParty).toBeNull();
    });

    test("oldest and newest release years played", () => {
      const summary = build([game({ title: "Old", igdbReleaseDate: "1998-11-19" }), game({ title: "New", igdbReleaseDate: "2026-02-01" }), game()]);
      expect(summary.timing.releaseRange).toMatchObject({ oldest: { game: { title: "Old" }, year: 1998 }, newest: { game: { title: "New" }, year: 2026 } });
    });

    test("the longest streak of consecutive months, ignoring year-only games", () => {
      const summary = build([
        game({ date: "2026-01" }), game({ date: "2026-02-03" }),
        game({ date: "2026-05-01" }), game({ date: "2026-06-01" }), game({ date: "2026-07" }),
        game({ date: "2026" })
      ]);
      expect(summary.timing.longestStreak).toEqual({ months: 3, from: 5, to: 7 });
      expect(build([game({ date: "2026-01" }), game({ date: "2026-03" })]).timing.longestStreak).toBeNull();
    });
  });

  describe("Game of the Year", () => {
    test("the automatic pick is the highest rating; ties go to the later finish", () => {
      const summary = build([
        game({ title: "Early ten", date: "2026-02-01", ratingScore: 10 }),
        game({ title: "Late ten", date: "2026-09-01", ratingScore: 10, notes: "Wow.", screenshots: [{ imageId: "shot1" }], coverImageId: "c1" }),
        game({ title: "Nine", date: "2026-12-01", ratingScore: 9 })
      ]);
      expect(summary.goty).toMatchObject({ game: { title: "Late ten" }, isOverride: false, isLatestFinish: false, note: "Wow.", backdrop: { imageId: "shot1", kind: "screenshot" } });
    });

    test("with no rated games it is the last finish of the year, backed by its cover", () => {
      const summary = build([game({ title: "Last", date: "2026-10-01", coverImageId: "c9" }), game({ title: "First", date: "2026-01-01" })]);
      expect(summary.goty).toMatchObject({ game: { title: "Last" }, isLatestFinish: true, backdrop: { imageId: "c9", kind: "cover" } });
    });

    test("a saved override wins while the game is in the year, and the music id rides along", () => {
      const pick = game({ title: "My pick", ratingScore: 6 });
      const games = [game({ ratingScore: 10 }), pick];
      expect(build(games, { settings: { gotyCompletedId: pick.id, musicVideoId: "dQw4w9WgXcQ" } }).goty)
        .toMatchObject({ game: { title: "My pick" }, isOverride: true, musicVideoId: "dQw4w9WgXcQ" });
      expect(build(games, { settings: { gotyCompletedId: "moved-to-another-year", musicVideoId: null } }).goty)
        .toMatchObject({ game: { ratingScore: 10 }, isOverride: false });
    });
  });
});

describe("Year in Review years", () => {
  test("years with games, newest first, plus the current year in progress", () => {
    expect(listReviewYears([{ year: 2024, count: 3 }, { year: 2026, count: 12 }, { year: 2025, count: 0 }], TODAY)).toEqual([
      { year: 2027, count: 0, inProgress: true },
      { year: 2026, count: 12, inProgress: false },
      { year: 2024, count: 3, inProgress: false }
    ]);
  });
});
