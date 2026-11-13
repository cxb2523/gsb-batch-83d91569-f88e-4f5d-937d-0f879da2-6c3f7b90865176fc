import { describe, expect, test } from "vitest";
import { MAINSTREAM_PLATFORM_IDS } from "../../apps/backend/src/randomizer/catalog";
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
  MAX_EXCLUDED_IDS,
  parseRandomizerFilters,
  PICK_FIELDS
} from "../../apps/backend/src/randomizer/queryBuilder";

const now = new Date(Date.UTC(2026, 8, 24));
const nowUnix = Math.floor(now.getTime() / 1000);
const mainstream = `platforms = (${MAINSTREAM_PLATFORM_IDS.join(",")})`;

describe("randomizer query builder", () => {
  test("always applies the base clauses and the default rating-count floor", () => {
    expect(buildRandomizerWhere({}, [], now)).toBe(
      `game_type = (0,10,8,9,11) & first_release_date != null & first_release_date < ${nowUnix} & cover != null & ${mainstream} & total_rating_count >= 5`
    );
  });

  test("turning remakes off keeps only main and expanded games", () => {
    expect(buildRandomizerWhere({ includeRemakes: false }, [], now)).toContain("game_type = (0,10) &");
  });

  test("maps each filter to its IGDB clause", () => {
    const where = buildRandomizerWhere({
      genreIds: [5, 12],
      themeIds: [1, 19],
      excludeThemeIds: [42],
      gameModeIds: [3],
      platformIds: [167, 6],
      minRating: 75,
      minRatingCount: 50,
      releasedFromYear: 2010,
      releasedToYear: 2015
    }, [], now);

    expect(where).toContain("genres = (5,12)");
    expect(where).toContain("themes = (1,19)");
    expect(where).toContain("themes != (42)");
    expect(where).toContain("game_modes = (3)");
    expect(where).toContain("platforms = (167,6)");
    expect(where).toContain("total_rating >= 75");
    expect(where).toContain("total_rating_count >= 50");
    expect(where).toContain(`first_release_date >= ${Date.UTC(2010, 0, 1) / 1000}`);
    expect(where).toContain(`first_release_date < ${Date.UTC(2016, 0, 1) / 1000}`);
  });

  test("maps the tag, perspective, preset and range filters", () => {
    const where = buildRandomizerWhere({
      excludeGenreIds: [14],
      perspectiveIds: [2, 3],
      tagIds: [477, 1705],
      excludeTagIds: [5],
      presets: ["jrpg", "anime"],
      maxRating: 90,
      maxRatingCount: 500
    }, [], now);

    expect(where).toContain("genres != (14)");
    expect(where).toContain("player_perspectives = (2,3)");
    expect(where).toContain("keywords = [477,1705]");
    expect(where).toContain("keywords != (5)");
    expect(where).toContain("keywords = (521,19521)");
    expect(where).toContain("keywords = (78,345)");
    expect(where).toContain("total_rating <= 90");
    expect(where).toContain("total_rating_count <= 500");
    expect(where).not.toContain("= !(");
  });

  test("a max rating of 100 adds no clause", () => {
    expect(buildRandomizerWhere({ maxRating: 100 }, [], now)).not.toContain("total_rating <=");
  });

  test("chosen platforms replace the mainstream default", () => {
    const where = buildRandomizerWhere({ platformIds: [167, 6] }, [], now);
    expect(where).toContain("platforms = (167,6)");
    expect(where).not.toContain(mainstream);
  });

  test("Made in Japan filters developer rows on involved_companies with game-prefixed clauses", () => {
    const where = buildJapanDeveloperWhere({ genreIds: [12], minRating: 80 }, [9, 4], now);

    expect(where.startsWith("developer = true & company.country = 392 & game.game_type = (0,10,8,9,11)")).toBe(true);
    expect(where).toContain(`game.platforms = (${MAINSTREAM_PLATFORM_IDS.join(",")})`);
    expect(where).toContain("game.genres = (12)");
    expect(where).toContain("game.total_rating >= 80");
    expect(where).toContain("game != (9,4)");
    expect(buildJapanPageQuery(where, 9, 30)).toBe(`fields game; where ${where}; sort id asc; limit 9; offset 30;`);
    expect(buildGamesByIdQuery([3, 1])).toBe(`fields ${PICK_FIELDS}; where id = (3,1); limit 2;`);
  });

  test("tag search is an escaped, length-checked name match", () => {
    expect(buildTagSearchQuery("  souls ")).toBe('fields id,name; where name ~ *"souls"*; sort name asc; limit 20;');
    expect(buildTagSearchQuery('a"b\\')).toBe('fields id,name; where name ~ *"a\\"b\\\\"*; sort name asc; limit 20;');
    expect(buildTagSearchQuery("x")).toBeNull();
  });

  test("include unrated turns the rating filters into 'matches them or has no rating'", () => {
    const where = buildRandomizerWhere({ minRating: 70, maxRating: 85, includeUnrated: true }, [], now);
    expect(where).toContain("((total_rating >= 70 & total_rating <= 85 & total_rating_count >= 5) | total_rating = null)");
    expect(where).not.toMatch(/& total_rating >= 70 &/);
    // With no rating filters at all there is nothing to widen.
    expect(buildRandomizerWhere({ minRatingCount: 0, includeUnrated: true }, [], now)).not.toContain("total_rating");
    expect(buildJapanDeveloperWhere({ includeUnrated: true }, [], now)).toContain("((game.total_rating_count >= 5) | game.total_rating = null)");
  });

  test("series match any chosen franchise or collection", () => {
    expect(buildRandomizerWhere({ franchiseIds: [4] }, [], now)).toContain("franchises = (4)");
    expect(buildRandomizerWhere({ franchiseIds: [4], collectionIds: [39, 67] }, [], now)).toContain("(franchises = (4) | collections = (39,67))");
    expect(buildJapanDeveloperWhere({ collectionIds: [39] }, [], now)).toContain("game.collections = (39)");
  });

  test("candidate ids limit the pool on either endpoint", () => {
    expect(buildRandomizerWhere({}, [5], now, [1, 2, 3])).toContain("id = (1,2,3) &");
    expect(buildJapanDeveloperWhere({}, [5], now, [1, 2])).toContain("game = (1,2)");
    expect(buildSimilarGamesQuery([119133])).toBe("fields similar_games; where id = (119133); limit 1;");
  });

  test("series and game searches are escaped and length-checked", () => {
    expect(buildSeriesSearchMultiquery("final fantasy")).toBe([
      'query franchises "franchises" { fields id,name; where name ~ *"final fantasy"*; sort name asc; limit 10; };',
      'query collections "collections" { fields id,name; where name ~ *"final fantasy"*; sort name asc; limit 10; };'
    ].join("\n"));
    expect(buildGameSearchQuery('elden "ring')).toBe('search "elden \\"ring"; fields name,first_release_date,cover.image_id; where game_type = (0,8,9,10,11); limit 10;');
    expect(buildSeriesSearchMultiquery(" x ")).toBeNull();
    expect(buildGameSearchQuery("")).toBeNull();
  });

  test("a rating-count floor of 0 disables the clause", () => {
    expect(buildRandomizerWhere({ minRatingCount: 0 }, [], now)).not.toContain("total_rating_count");
  });

  test("excluded ids become one none-of clause, deduplicated and capped with the newest first", () => {
    expect(buildRandomizerWhere({}, [7, 3, 7], now)).toContain("id != (7,3)");

    const many = Array.from({ length: MAX_EXCLUDED_IDS + 20 }, (_, index) => index + 1);
    const clause = buildRandomizerWhere({}, many, now).match(/id != \(([^)]*)\)/)?.[1].split(",") ?? [];
    expect(clause).toHaveLength(MAX_EXCLUDED_IDS);
    expect(clause[0]).toBe("1");
    expect(clause.at(-1)).toBe(String(MAX_EXCLUDED_IDS));
  });

  test("count and page bodies", () => {
    expect(buildCountQuery("cover != null")).toBe("where cover != null;");
    expect(buildPageQuery("cover != null", 9, 1200)).toBe(`fields ${PICK_FIELDS}; where cover != null; sort id asc; limit 9; offset 1200;`);
  });
});

describe("randomizer filter validation", () => {
  test("accepts an empty or missing body", () => {
    expect(parseRandomizerFilters(undefined)).toEqual({ ok: true, filters: {} });
    expect(parseRandomizerFilters({})).toEqual({ ok: true, filters: {} });
  });

  test("keeps valid values and deduplicates ids", () => {
    expect(parseRandomizerFilters({ genreIds: [12, 12, 5], minRating: 80, minRatingCount: 0, releasedFromYear: 2000, releasedToYear: 2000, hideCompleted: false })).toEqual({
      ok: true,
      filters: { genreIds: [12, 5], minRating: 80, minRatingCount: 0, releasedFromYear: 2000, releasedToYear: 2000, hideCompleted: false }
    });
  });

  test.each([
    [{ genreIds: [1.5] }, "genreIds"],
    [{ platformIds: ["6"] }, "platformIds"],
    [{ themeIds: "1,2" }, "themeIds"],
    [{ minRating: 101 }, "minRating"],
    [{ minRating: "90" }, "minRating"],
    [{ minRatingCount: -1 }, "minRatingCount"],
    [{ releasedFromYear: 2020, releasedToYear: 2010 }, "from year"],
    [{ releasedToYear: 20000 }, "releasedToYear"],
    [{ hideUpcoming: "yes" }, "hideUpcoming"],
    [{ maxRating: -1 }, "maxRating"],
    [{ minRating: 90, maxRating: 80 }, "minimum rating"],
    [{ maxRatingCount: 2.5 }, "maxRatingCount"],
    [{ maxRatingCount: 3 }, "minimum ratings count (5)"],
    [{ minRatingCount: 100, maxRatingCount: 50 }, "minimum ratings count (100)"],
    [{ presets: ["jrpg", "rpg"] }, "presets"],
    [{ madeInJapan: 1 }, "madeInJapan"],
    [{ similarToId: "119133" }, "similarToId"],
    [{ franchiseIds: [0] }, "franchiseIds"],
    [{ includeUnrated: "true" }, "includeUnrated"]
  ])("rejects %j", (body, message) => {
    const result = parseRandomizerFilters(body);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toContain(message);
  });

  test("keeps the new filters and drops platforms outside the mainstream list", () => {
    expect(parseRandomizerFilters({
      presets: ["anime", "anime", "jrpg"],
      madeInJapan: true,
      tagIds: [477],
      excludeGenreIds: [14],
      perspectiveIds: [1],
      platformIds: [34, 167],
      minRating: 70,
      maxRating: 85,
      minRatingCount: 10,
      maxRatingCount: 10
    })).toEqual({
      ok: true,
      filters: { presets: ["anime", "jrpg"], madeInJapan: true, tagIds: [477], excludeGenreIds: [14], perspectiveIds: [1], platformIds: [167], minRating: 70, maxRating: 85, minRatingCount: 10, maxRatingCount: 10 }
    });
    expect(parseRandomizerFilters({ platformIds: [34, 39] })).toEqual({ ok: true, filters: {} });
  });

  test("keeps the similar-to seed and a trimmed display title", () => {
    expect(parseRandomizerFilters({ similarToId: 119133, similarToTitle: "  Elden Ring ", includeUnrated: true, franchiseIds: [4], collectionIds: [39] })).toEqual({
      ok: true,
      filters: { similarToId: 119133, similarToTitle: "Elden Ring", includeUnrated: true, franchiseIds: [4], collectionIds: [39] }
    });
    expect(parseRandomizerFilters({ similarToTitle: "orphan title" })).toEqual({ ok: true, filters: {} });
  });

  test("rejects a non-object body", () => {
    expect(parseRandomizerFilters([1]).ok).toBe(false);
  });
});

describe("empty pool reason", () => {
  const options = {
    genres: [{ id: 12, name: "RPG" }],
    themes: [{ id: 19, name: "Horror" }],
    gameModes: []
  };

  test("names the filters when the option lists are known", () => {
    expect(describeEmptyPool({ themeIds: [19], genreIds: [12], platformIds: [167], minRating: 90, minRatingCount: 50 }, options))
      .toBe("No released Horror RPG games on PlayStation 5, rated 90+ with 50+ ratings.");
  });

  test("describes presets, Made in Japan, tags and ranges", () => {
    expect(describeEmptyPool({ presets: ["jrpg"], madeInJapan: true, platformIds: [130], tagIds: [477, 999], excludeTagIds: [5], minRating: 70, maxRating: 80, minRatingCount: 10, maxRatingCount: 200 }, null))
      .toBe("No released JRPG games made in Japan on Switch tagged 2 tags without Zombies, rated 70–80 with 10–200 ratings.");
    expect(describeEmptyPool({ maxRating: 60, minRatingCount: 0, maxRatingCount: 40 }, null))
      .toBe("No released games, rated up to 60 with up to 40 ratings.");
  });

  test("describes similar-to, series and unrated", () => {
    expect(describeEmptyPool({ similarToId: 1, similarToTitle: "Elden Ring", franchiseIds: [4], minRating: 90, includeUnrated: true }, null))
      .toBe("No released games similar to Elden Ring in the chosen series, rated 90+ with 5+ ratings or unrated.");
  });

  test("falls back to counts when the option lists are not loaded", () => {
    expect(describeEmptyPool({ genreIds: [12, 5], releasedFromYear: 1990, releasedToYear: 1990, minRatingCount: 0 }, null))
      .toBe("No released 2 genres games, released in 1990.");
  });
});
