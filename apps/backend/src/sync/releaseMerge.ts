import { computeSortDateAndEligibility } from "./releasePolicy";
import { normalizeText } from "../text/normalizeText";
import type { DatePrecision, NormalizedRelease, ReleaseArtwork, ReleaseCategory, ReleaseOverride } from "../../../../shared/types";

// Pure merge rules for sync. The Release Store loads the existing state; this module decides the result.
export interface ExistingReleaseMergeState {
  releaseId: string;
  artworks: ReleaseArtwork[];
  overrides: ReleaseOverride[];
}

export function mergeReleaseForPersistence(incoming: NormalizedRelease, existing: ExistingReleaseMergeState | null): NormalizedRelease {
  const withOverrides = applyOverrides(incoming, existing?.overrides ?? []);
  return {
    ...withOverrides,
    artworks: mergeArtworks(withOverrides.artworks, existing?.artworks ?? [])
  };
}

export function mergeArtworks(incoming: ReleaseArtwork[], existing: ReleaseArtwork[]) {
  if (existing.length === 0) return incoming;
  const incomingById = new Map(incoming.map(artwork => [artwork.imageId, artwork]));
  const merged: ReleaseArtwork[] = [];
  for (const artwork of existing) {
    const next = incomingById.get(artwork.imageId);
    if (artwork.source === "local") merged.push(artwork);
    else if (next) {
      merged.push(next);
      incomingById.delete(artwork.imageId);
    }
  }
  for (const artwork of incoming) {
    if (incomingById.has(artwork.imageId)) merged.push(artwork);
  }
  return merged;
}

function applyOverrides(incoming: NormalizedRelease, overrides: ReleaseOverride[]) {
  if (overrides.length === 0) return incoming;
  const next = { ...incoming };
  const title = valueFor("title", overrides);
  if (title) {
    next.title = title;
    next.normalizedTitle = normalizeText(title);
  }
  for (const field of ["publishers", "developers", "platforms"] as const) {
    const value = parseList(valueFor(field, overrides));
    if (value) next[field] = value;
  }
  const category = valueFor("category", overrides);
  if (category) next.category = category as ReleaseCategory;
  const dateFields = new Set(["dateText", "releaseDate", "datePrecision", "releaseWindow"]);
  for (const field of dateFields) {
    const value = valueFor(field, overrides);
    if (value === undefined) continue;
    if (field === "datePrecision") next.datePrecision = value as DatePrecision;
    else if (field === "releaseDate") next.releaseDate = value || null;
    else if (field === "releaseWindow") next.releaseWindow = value || null;
    else if (field === "dateText") next.dateText = value;
  }
  if (valueFor("datePrecision", overrides) && next.datePrecision !== "Exact" && valueFor("releaseDate", overrides) === undefined) {
    next.releaseDate = null;
  }
  const eligibility = computeSortDateAndEligibility(next);
  return { ...next, ...eligibility };
}

function parseList(value: string | undefined) {
  if (value === undefined) return undefined;
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map(String) : undefined;
  } catch {
    return undefined;
  }
}

// user > seeded > igdb
export function applyFieldPrecedence(overrides: ReleaseOverride[]) {
  const rank = { igdb: 0, seeded: 1, user: 2 };
  return [...overrides].sort((a, b) => rank[b.sourceType] - rank[a.sourceType])[0]?.value;
}

function valueFor(field: string, overrides: ReleaseOverride[]) {
  return applyFieldPrecedence(overrides.filter(override => override.field === field));
}
