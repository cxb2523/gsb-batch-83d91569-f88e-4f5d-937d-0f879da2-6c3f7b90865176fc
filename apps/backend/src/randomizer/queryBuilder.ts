import type { RandomizerFilters, RandomizerOption, RandomizerOptions, RandomizerPreset } from "../../../../shared/types";
import { escapeIgdbSearch } from "../igdb/gateway";
import { JAPAN_COUNTRY_CODE, MAINSTREAM_PLATFORM_IDS, MAINSTREAM_PLATFORMS, POPULAR_TAGS, PRESET_KEYWORDS, PRESET_LABELS } from "./catalog";

// IGDB Game enum: 0 main_game, 8 remake, 9 remaster, 10 expanded_game, 11 port.
// DLC, bundles, mods, episodes, seasons, packs and updates are never picked.
const BASE_GAME_TYPES = [0, 10];
const REMAKE_GAME_TYPES = [8, 9, 11];

const DEFAULT_MIN_RATING_COUNT = 5;
// Keeps the IGDB request body small. Cooldown ids come first, so the newest picks always survive the cap.
export const MAX_EXCLUDED_IDS = 1000;
const MAX_IDS_PER_FILTER = 50;
const MIN_YEAR = 1950;
const MAX_YEAR = 2100;

export const PICK_FIELDS = "name,slug,url,first_release_date,cover.image_id,genres.name,themes.name,game_modes.name,platforms.abbreviation,platforms.name,total_rating,total_rating_count,summary,game_type";

type FilterValidation = { ok: true; filters: RandomizerFilters } | { ok: false; error: string };

const idListKeys = ["genreIds", "excludeGenreIds", "themeIds", "excludeThemeIds", "gameModeIds", "perspectiveIds", "platformIds", "tagIds", "excludeTagIds", "franchiseIds", "collectionIds"] as const;
const booleanKeys = ["madeInJapan", "includeUnrated", "includeRemakes", "hideCompleted", "hideUpcoming"] as const;
const MAX_TITLE_LENGTH = 200;
const presetKeys = Object.keys(PRESET_KEYWORDS) as RandomizerPreset[];

// Request bodies arrive as untyped JSON. Every value that reaches the IGDB query is a number or a
// boolean, so nothing user-typed is ever spliced into the query text.
export function parseRandomizerFilters(input: unknown): FilterValidation {
  if (input === undefined || input === null) return { ok: true, filters: {} };
  if (typeof input !== "object" || Array.isArray(input)) return { ok: false, error: "Filters must be an object" };
  const body = input as Record<string, unknown>;
  const filters: RandomizerFilters = {};

  for (const key of idListKeys) {
    const value = body[key];
    if (value === undefined || value === null) continue;
    if (!Array.isArray(value) || !value.every(id => Number.isSafeInteger(id) && (id as number) > 0)) {
      return { ok: false, error: `${key} must be a list of IGDB ids` };
    }
    if (value.length > MAX_IDS_PER_FILTER) return { ok: false, error: `${key} accepts at most ${MAX_IDS_PER_FILTER} ids` };
    if (value.length > 0) filters[key] = [...new Set(value as number[])];
  }

  // Only mainstream platforms can be chosen; ids saved before that rule are dropped rather than rejected.
  if (filters.platformIds) {
    const mainstream = filters.platformIds.filter(id => MAINSTREAM_PLATFORM_IDS.includes(id));
    if (mainstream.length) filters.platformIds = mainstream;
    else delete filters.platformIds;
  }

  if (body.presets !== undefined && body.presets !== null) {
    if (!Array.isArray(body.presets) || !body.presets.every(preset => presetKeys.includes(preset as RandomizerPreset))) {
      return { ok: false, error: `presets must be a list of ${presetKeys.join(", ")}` };
    }
    if (body.presets.length > 0) filters.presets = [...new Set(body.presets as RandomizerPreset[])];
  }

  if (body.similarToId !== undefined && body.similarToId !== null) {
    if (!Number.isSafeInteger(body.similarToId) || (body.similarToId as number) <= 0) return { ok: false, error: "similarToId must be an IGDB id" };
    filters.similarToId = body.similarToId as number;
    // Only used in the empty-pool message; it never reaches an IGDB query.
    if (typeof body.similarToTitle === "string" && body.similarToTitle.trim()) filters.similarToTitle = body.similarToTitle.trim().slice(0, MAX_TITLE_LENGTH);
  }

  for (const key of ["minRating", "maxRating"] as const) {
    const rating = optionalNumber(body[key]);
    if (rating === "invalid" || (rating !== undefined && (rating < 0 || rating > 100))) {
      return { ok: false, error: `${key} must be between 0 and 100` };
    }
    if (rating !== undefined) filters[key] = rating;
  }
  if (filters.minRating !== undefined && filters.maxRating !== undefined && filters.minRating > filters.maxRating) {
    return { ok: false, error: "The minimum rating must not be above the maximum rating" };
  }

  for (const key of ["minRatingCount", "maxRatingCount"] as const) {
    const count = optionalNumber(body[key]);
    if (count === "invalid" || (count !== undefined && (!Number.isSafeInteger(count) || count < 0))) {
      return { ok: false, error: `${key} must be a whole number of 0 or more` };
    }
    if (count !== undefined) filters[key] = count;
  }
  const floor = filters.minRatingCount ?? DEFAULT_MIN_RATING_COUNT;
  if (filters.maxRatingCount !== undefined && floor > filters.maxRatingCount) {
    return { ok: false, error: `The minimum ratings count (${floor}) must not be above the maximum ratings count` };
  }

  for (const key of ["releasedFromYear", "releasedToYear"] as const) {
    const year = optionalNumber(body[key]);
    if (year === "invalid" || (year !== undefined && (!Number.isSafeInteger(year) || year < MIN_YEAR || year > MAX_YEAR))) {
      return { ok: false, error: `${key} must be a year between ${MIN_YEAR} and ${MAX_YEAR}` };
    }
    if (year !== undefined) filters[key] = year;
  }
  if (filters.releasedFromYear !== undefined && filters.releasedToYear !== undefined && filters.releasedFromYear > filters.releasedToYear) {
    return { ok: false, error: "The from year must not be after the to year" };
  }

  for (const key of booleanKeys) {
    const value = body[key];
    if (value === undefined || value === null) continue;
    if (typeof value !== "boolean") return { ok: false, error: `${key} must be true or false` };
    filters[key] = value;
  }

  return { ok: true, filters };
}

function optionalNumber(value: unknown): number | undefined | "invalid" {
  if (value === undefined || value === null || value === "") return undefined;
  return typeof value === "number" && Number.isFinite(value) ? value : "invalid";
}

const idList = (ids: number[]) => ids.map(id => Math.trunc(id)).join(",");
const unixSeconds = (date: Date) => Math.floor(date.getTime() / 1000);
const startOfYear = (year: number) => unixSeconds(new Date(Date.UTC(year, 0, 1)));

// The newest ids first, deduplicated and capped.
function capExcludedIds(ids: number[]) {
  return [...new Set(ids.filter(id => Number.isSafeInteger(id) && id > 0))].slice(0, MAX_EXCLUDED_IDS);
}

// The clauses about the game itself. `prefix` is "game." when they are applied through
// another endpoint (involved_companies for Made in Japan).
function gameClauses(filters: RandomizerFilters, excludedIds: number[], now: Date, prefix: string, candidateIds?: number[]) {
  const gameTypes = filters.includeRemakes === false ? BASE_GAME_TYPES : [...BASE_GAME_TYPES, ...REMAKE_GAME_TYPES];
  const field = (name: string) => `${prefix}${name}`;
  const idField = prefix ? "game" : "id";
  const clauses = [
    `${field("game_type")} = (${idList(gameTypes)})`,
    `${field("first_release_date")} != null`,
    `${field("first_release_date")} < ${unixSeconds(now)}`,
    `${field("cover")} != null`,
    `${field("platforms")} = (${idList(filters.platformIds?.length ? filters.platformIds : MAINSTREAM_PLATFORM_IDS)})`
  ];
  if (filters.genreIds?.length) clauses.push(`${field("genres")} = (${idList(filters.genreIds)})`);
  if (filters.excludeGenreIds?.length) clauses.push(`${field("genres")} != (${idList(filters.excludeGenreIds)})`);
  if (filters.themeIds?.length) clauses.push(`${field("themes")} = (${idList(filters.themeIds)})`);
  if (filters.excludeThemeIds?.length) clauses.push(`${field("themes")} != (${idList(filters.excludeThemeIds)})`);
  if (filters.gameModeIds?.length) clauses.push(`${field("game_modes")} = (${idList(filters.gameModeIds)})`);
  if (filters.perspectiveIds?.length) clauses.push(`${field("player_perspectives")} = (${idList(filters.perspectiveIds)})`);
  for (const preset of filters.presets ?? []) clauses.push(`${field("keywords")} = (${idList(PRESET_KEYWORDS[preset])})`);
  if (filters.tagIds?.length) clauses.push(`${field("keywords")} = [${idList(filters.tagIds)}]`);
  if (filters.excludeTagIds?.length) clauses.push(`${field("keywords")} != (${idList(filters.excludeTagIds)})`);
  const series = [
    filters.franchiseIds?.length ? `${field("franchises")} = (${idList(filters.franchiseIds)})` : "",
    filters.collectionIds?.length ? `${field("collections")} = (${idList(filters.collectionIds)})` : ""
  ].filter(Boolean);
  if (series.length) clauses.push(series.length > 1 ? `(${series.join(" | ")})` : series[0]);
  if (candidateIds) clauses.push(`${idField} = (${idList(candidateIds)})`);

  const rated: string[] = [];
  if (filters.minRating !== undefined && filters.minRating > 0) rated.push(`${field("total_rating")} >= ${Number(filters.minRating)}`);
  if (filters.maxRating !== undefined && filters.maxRating < 100) rated.push(`${field("total_rating")} <= ${Number(filters.maxRating)}`);
  const minRatingCount = filters.minRatingCount ?? DEFAULT_MIN_RATING_COUNT;
  if (minRatingCount > 0) rated.push(`${field("total_rating_count")} >= ${Math.trunc(minRatingCount)}`);
  if (filters.maxRatingCount !== undefined) rated.push(`${field("total_rating_count")} <= ${Math.trunc(filters.maxRatingCount)}`);
  // Unrated games have no score to compare, so "include unrated" turns the rating filters into
  // "matches them, or has no rating yet".
  if (filters.includeUnrated && rated.length) clauses.push(`((${rated.join(" & ")}) | ${field("total_rating")} = null)`);
  else clauses.push(...rated);
  if (filters.releasedFromYear !== undefined) clauses.push(`${field("first_release_date")} >= ${startOfYear(filters.releasedFromYear)}`);
  if (filters.releasedToYear !== undefined) clauses.push(`${field("first_release_date")} < ${startOfYear(filters.releasedToYear + 1)}`);
  // IGDB only accepts none-of as `field != (...)`; `field = !(...)` is a syntax error.
  const excluded = capExcludedIds(excludedIds);
  if (excluded.length) clauses.push(`${idField} != (${idList(excluded)})`);
  return clauses;
}

// Filters plus excluded ids -> the IGDB `where` expression for the games endpoint, without the `where` keyword or trailing `;`.
// `candidateIds` limits the pool to those games (the "similar to" list).
export function buildRandomizerWhere(filters: RandomizerFilters, excludedIds: number[] = [], now = new Date(), candidateIds?: number[]) {
  return gameClauses(filters, excludedIds, now, "", candidateIds).join(" & ");
}

// Made in Japan: the developer flag and the company country must sit on the same involved-company
// row, which only the involved_companies endpoint can express. Filtering games by
// `involved_companies.company.country` would also match Japanese publishers and localizers.
export function buildJapanDeveloperWhere(filters: RandomizerFilters, excludedIds: number[] = [], now = new Date(), candidateIds?: number[]) {
  return [`developer = true`, `company.country = ${JAPAN_COUNTRY_CODE}`, ...gameClauses(filters, excludedIds, now, "game.", candidateIds)].join(" & ");
}

export const buildCountQuery = (where: string) => `where ${where};`;

// `sort id asc` keeps offsets stable between the count and the page request.
export const buildPageQuery = (where: string, limit: number, offset: number) =>
  `fields ${PICK_FIELDS}; where ${where}; sort id asc; limit ${Math.trunc(limit)}; offset ${Math.max(0, Math.trunc(offset))};`;

// Made in Japan pages list involved-company rows; the game ids are then fetched with buildGamesByIdQuery.
export const buildJapanPageQuery = (where: string, limit: number, offset: number) =>
  `fields game; where ${where}; sort id asc; limit ${Math.trunc(limit)}; offset ${Math.max(0, Math.trunc(offset))};`;

export const buildGamesByIdQuery = (ids: number[]) =>
  `fields ${PICK_FIELDS}; where id = (${idList(ids)}); limit ${Math.min(500, Math.max(1, ids.length))};`;

const MIN_SEARCH = 2;
const MAX_SEARCH = 60;

// Name lookups are the only Randomizer queries that carry typed text, so it is always escaped and length-capped.
function searchTerm(text: string) {
  const term = text.trim().slice(0, MAX_SEARCH);
  return term.length < MIN_SEARCH ? null : escapeIgdbSearch(term);
}

// The IGDB keywords endpoint cannot `search`, so tag lookup is a case-insensitive name match.
export function buildTagSearchQuery(text: string) {
  const term = searchTerm(text);
  return term ? `fields id,name; where name ~ *"${term}"*; sort name asc; limit 20;` : null;
}

// Franchises and collections by name in one request.
export function buildSeriesSearchMultiquery(text: string) {
  const term = searchTerm(text);
  if (!term) return null;
  return [
    `query franchises "franchises" { fields id,name; where name ~ *"${term}"*; sort name asc; limit 10; };`,
    `query collections "collections" { fields id,name; where name ~ *"${term}"*; sort name asc; limit 10; };`
  ].join("\n");
}

// Full games (no DLC or bundles) by IGDB's relevance search, for picking a "similar to" seed.
export function buildGameSearchQuery(text: string) {
  const term = searchTerm(text);
  return term ? `search "${term}"; fields name,first_release_date,cover.image_id; where game_type = (0,8,9,10,11); limit 10;` : null;
}

export const buildSimilarGamesQuery = (ids: number[]) => `fields similar_games; where id = (${idList(ids)}); limit ${Math.min(500, Math.max(1, ids.length))};`;

// Platforms and popular tags are static (catalog.ts), so only these four lists come from IGDB.
export const OPTIONS_MULTIQUERY = [
  'query genres "genres" { fields id,name; sort name asc; limit 500; };',
  'query themes "themes" { fields id,name; sort name asc; limit 500; };',
  'query game_modes "gameModes" { fields id,name; sort name asc; limit 500; };',
  'query player_perspectives "perspectives" { fields id,name; sort name asc; limit 500; };'
].join("\n");

// "No released Horror RPG games made in Japan on PlayStation 5, rated 90+ with 50+ ratings".
export function describeEmptyPool(filters: RandomizerFilters, options?: Partial<RandomizerOptions> | null) {
  const names = (ids: number[] | undefined, list: RandomizerOption[] | undefined, noun: string, separator = "/") => {
    if (!ids?.length) return "";
    const found = ids.map(id => list?.find(option => option.id === id)?.name).filter((name): name is string => Boolean(name));
    return found.length === ids.length ? found.join(separator) : `${ids.length} ${noun}${ids.length === 1 ? "" : "s"}`;
  };
  const tags = [...(options?.tags ?? []), ...POPULAR_TAGS];
  const presets = (filters.presets ?? []).map(preset => PRESET_LABELS[preset]).join(" ");
  const kinds = [names(filters.themeIds, options?.themes, "theme"), names(filters.genreIds, options?.genres, "genre"), presets].filter(Boolean).join(" ");
  const parts = [`No released ${kinds ? `${kinds} ` : ""}games`];
  if (filters.similarToId) parts.push(`similar to ${filters.similarToTitle ?? "the chosen game"}`);
  if (filters.madeInJapan) parts.push("made in Japan");
  const seriesCount = (filters.franchiseIds?.length ?? 0) + (filters.collectionIds?.length ?? 0);
  if (seriesCount) parts.push(`in the chosen series`);
  const platforms = names(filters.platformIds, MAINSTREAM_PLATFORMS, "platform");
  if (platforms) parts.push(`on ${platforms}`);
  const withAny = [names(filters.gameModeIds, options?.gameModes, "game mode"), names(filters.perspectiveIds, options?.perspectives, "perspective")].filter(Boolean).join(", ");
  if (withAny) parts.push(`with ${withAny}`);
  const tagged = names(filters.tagIds, tags, "tag", " + ");
  if (tagged) parts.push(`tagged ${tagged}`);
  const without = [
    names(filters.excludeGenreIds, options?.genres, "genre"),
    names(filters.excludeThemeIds, options?.themes, "theme"),
    names(filters.excludeTagIds, tags, "tag")
  ].filter(Boolean).join("/");
  if (without) parts.push(`without ${without}`);

  const qualifiers: string[] = [];
  const range = (min: number | undefined, max: number | undefined, unit: string) => {
    if (min !== undefined && max !== undefined) return min === max ? `${unit} ${min}` : `${unit} ${min}–${max}`;
    if (min !== undefined) return `${unit} ${min}+`;
    return max !== undefined ? `${unit} up to ${max}` : "";
  };
  const rating = range(filters.minRating || undefined, filters.maxRating !== undefined && filters.maxRating < 100 ? filters.maxRating : undefined, "rated");
  if (rating) qualifiers.push(rating);
  const minRatingCount = filters.minRatingCount ?? DEFAULT_MIN_RATING_COUNT;
  const count = range(minRatingCount > 0 ? minRatingCount : undefined, filters.maxRatingCount, "with");
  if (count) qualifiers.push(`${count} ratings`);
  if (filters.includeUnrated && (rating || count)) qualifiers.push("or unrated");
  const from = filters.releasedFromYear;
  const to = filters.releasedToYear;
  if (from !== undefined && to !== undefined) qualifiers.push(from === to ? `released in ${from}` : `released ${from}–${to}`);
  else if (from !== undefined) qualifiers.push(`released since ${from}`);
  else if (to !== undefined) qualifiers.push(`released by ${to}`);
  let reason = parts.join(" ");
  if (qualifiers.length) reason += `, ${qualifiers.join(" ")}`;
  return `${reason}.`;
}
