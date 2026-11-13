import type { PlatformFamily, ReleaseCategory } from "./types";

export const ACCEPTED_GAME_TYPES = [0, 1, 2, 4, 8, 9, 10, 11] as const;

export const GAME_TYPE_LABELS: Record<number, ReleaseCategory> = {
  0: "Main",
  1: "DLC",
  2: "Expansion",
  4: "Standalone Expansion",
  8: "Remake",
  9: "Remaster",
  10: "Expanded Game",
  11: "Port"
};

export const EXCLUDED_TITLE_TERMS = [
  "Digital Deluxe",
  "Ultimate Edition",
  "Collector",
  "Collector's Edition",
  "Complete Launch Edition",
  "Guidebook Edition",
  "Launch Edition",
  "Limited Edition",
  "Gold Edition",
  "Premium Edition",
  "Season Pass",
  "Demo",
  "Beta"
] as const;
// The API keys the app stores (encrypted) in Settings.
export const CREDENTIAL_KEYS = ["IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET", "IGDB_ACCESS_TOKEN", "STEAMGRIDDB_API_KEY"] as const;

export const MAX_RELEASE_ROWS = 5000;
// The header that carries the per-launch API token: the backend requires it on /api calls, and the
// renderer and the desktop app's own calls (release alerts) send it.
export const API_TOKEN_HEADER = "x-grt-token";
export const IGDB_REQUESTS_PER_SECOND = 4;

// IGDB platforms per family, by id and by slug (IGDB lists some ports without an id).
export const PLATFORM_FAMILIES: Record<PlatformFamily, { label: string; ids: readonly number[]; slugs: readonly string[] }> = {
  pc: { label: "PC", ids: [6], slugs: ["win"] },
  xbox: { label: "Xbox", ids: [49, 169], slugs: ["xboxone", "series-x-s"] },
  playstation: { label: "PlayStation", ids: [48, 167], slugs: ["ps4--1", "ps5"] },
  switch: { label: "Nintendo Switch", ids: [130, 508], slugs: ["switch", "switch-2"] }
};

export const ALL_PLATFORM_FAMILIES = Object.keys(PLATFORM_FAMILIES) as PlatformFamily[];

// Offered by "Add suggested publishers": large publishers most players know. Resolved to IGDB companies
// by exact name when the user asks.
export const SUGGESTED_PUBLISHERS = [
  "Activision",
  "Bandai Namco Entertainment",
  "Bethesda Softworks",
  "Capcom",
  "CD Projekt",
  "Devolver Digital",
  "Electronic Arts",
  "Konami",
  "Nintendo",
  "Sega",
  "Sony Interactive Entertainment",
  "Square Enix",
  "Ubisoft Entertainment",
  "Xbox Game Studios"
] as const;
