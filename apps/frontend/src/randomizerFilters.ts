import type { RandomizerFilters, RandomizerPreset, RandomizerSeriesOption } from "../../../shared/types";

// Every edit the Randomizer view makes to its filters. Pure functions of the current filters, so the
// rules hold everywhere: id lists never repeat an id, and an empty list, false flag or blank number is
// stored as absent (undefined), which is how "no filter" reaches the backend.

export type IdListKey =
  | "genreIds" | "excludeGenreIds" | "themeIds" | "excludeThemeIds" | "gameModeIds" | "perspectiveIds"
  | "platformIds" | "tagIds" | "excludeTagIds" | "franchiseIds" | "collectionIds";
export type NumberKey = "minRating" | "maxRating" | "minRatingCount" | "maxRatingCount" | "releasedFromYear" | "releasedToYear";
type LabelKind = "tag" | RandomizerSeriesOption["kind"];

// Names found by search are remembered under these keys so their chips read correctly after a restart.
export const labelKey = (kind: LabelKind, id: number) => `${kind}:${id}`;

export const seriesKey = (kind: RandomizerSeriesOption["kind"]): IdListKey => (kind === "franchise" ? "franchiseIds" : "collectionIds");

function setIds(filters: RandomizerFilters, key: IdListKey, ids: number[]): RandomizerFilters {
  const unique = [...new Set(ids)];
  return { ...filters, [key]: unique.length ? unique : undefined };
}

export const addIds = (filters: RandomizerFilters, key: IdListKey, ids: number[]) => setIds(filters, key, [...(filters[key] ?? []), ...ids]);

export const removeIds = (filters: RandomizerFilters, key: IdListKey, ids: number[]) =>
  setIds(filters, key, (filters[key] ?? []).filter(id => !ids.includes(id)));

export const toggleId = (filters: RandomizerFilters, key: IdListKey, id: number) =>
  (filters[key] ?? []).includes(id) ? removeIds(filters, key, [id]) : addIds(filters, key, [id]);

// Selects every id of a group, or clears the group when all of it is already selected.
export const toggleGroup = (filters: RandomizerFilters, key: IdListKey, ids: number[]) =>
  ids.every(id => (filters[key] ?? []).includes(id)) ? removeIds(filters, key, ids) : addIds(filters, key, ids);

export function togglePreset(filters: RandomizerFilters, preset: RandomizerPreset): RandomizerFilters {
  const current = filters.presets ?? [];
  const next = current.includes(preset) ? current.filter(value => value !== preset) : [...current, preset];
  return { ...filters, presets: next.length ? next : undefined };
}

export const setFlag = (filters: RandomizerFilters, key: "madeInJapan" | "includeUnrated", on: boolean): RandomizerFilters =>
  ({ ...filters, [key]: on || undefined });

// Options whose "off" is meaningful and therefore stored as false.
export const setOption = (filters: RandomizerFilters, key: "includeRemakes" | "hideCompleted" | "hideUpcoming", on: boolean): RandomizerFilters =>
  ({ ...filters, [key]: on });

// A number field's text: blank or not a number clears the filter.
export function setNumber(filters: RandomizerFilters, key: NumberKey, text: string): RandomizerFilters {
  const trimmed = text.trim();
  const value = trimmed === "" ? undefined : Number(trimmed);
  return { ...filters, [key]: value !== undefined && Number.isFinite(value) ? value : undefined };
}

export const setSimilarTo = (filters: RandomizerFilters, game: { id: number; name: string } | null): RandomizerFilters =>
  ({ ...filters, similarToId: game?.id, similarToTitle: game?.name });

// Drops saved platform ids the server no longer offers (e.g. from before the mainstream-only list).
export function keepOfferedPlatforms(filters: RandomizerFilters, offeredIds: Set<number>): RandomizerFilters {
  if (!filters.platformIds?.some(id => !offeredIds.has(id))) return filters;
  return setIds(filters, "platformIds", filters.platformIds.filter(id => offeredIds.has(id)));
}
