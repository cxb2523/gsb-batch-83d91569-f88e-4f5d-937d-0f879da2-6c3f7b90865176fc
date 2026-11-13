import { vi } from "vitest";
import type { ApiClient } from "../../apps/frontend/src/api/client";
import { emptySummary } from "./yearInReviewFixture";

const idleSync = { status: "idle" as const, added: 0, repaired: 0, skipped: 0, failed: 0 };

// An in-memory ApiClient: every method is a vi.fn with a harmless default, overridable per test.
export function fakeApiClient(overrides: Partial<ApiClient> = {}): ApiClient & Record<keyof ApiClient, ReturnType<typeof vi.fn>> {
  const defaults: ApiClient = {
    listReleases: async () => ({ items: [], truncated: false, total: 0 }),
    getRelease: async id => { throw new Error(`no release ${id}`); },
    searchManualReleaseCandidates: async () => ({ items: [] }),
    createManualRelease: async () => { throw new Error("not stubbed"); },
    patchRelease: async () => { throw new Error("not stubbed"); },
    deleteRelease: async () => ({ ok: true }),
    uploadLocalArtwork: async () => { throw new Error("not stubbed"); },
    deleteArtwork: async () => { throw new Error("not stubbed"); },
    reorderArtworks: async () => { throw new Error("not stubbed"); },
    syncNow: async () => idleSync,
    getSyncStatus: async () => idleSync,
    getSettings: async () => ({ credentialStatus: { status: "missing" }, autoSyncDue: false, credentials: { IGDB_CLIENT_ID: { saved: false }, IGDB_CLIENT_SECRET: { saved: false }, IGDB_ACCESS_TOKEN: { saved: false }, STEAMGRIDDB_API_KEY: { saved: false } } }),
    patchSettings: async () => { throw new Error("not stubbed"); },
    clearCredentials: async () => { throw new Error("not stubbed"); },
    testCredentials: async () => ({ credentialStatus: { status: "missing" } }),
    getDemo: async () => ({ loaded: false }),
    loadDemo: async () => { throw new Error("not stubbed"); },
    removeDemo: async () => { throw new Error("not stubbed"); },
    getSyncSettings: async () => ({ publishers: [], platforms: ["pc", "xbox", "playstation", "switch"], trackFrom: "2026-01-01", autoSync: false, alerts: true }),
    updateSyncSettings: async () => { throw new Error("not stubbed"); },
    searchPublishers: async () => ({ items: [] }),
    trackPublisher: async () => { throw new Error("not stubbed"); },
    untrackPublisher: async () => { throw new Error("not stubbed"); },
    trackSuggestedPublishers: async () => { throw new Error("not stubbed"); },
    getWallpaper: async () => ({ hasWallpaper: false, url: null }),
    clearWallpaper: async () => ({ ok: true }),
    listCompletedGames: async () => ({ items: [], total: 0 }),
    getCompletedGame: async id => { throw new Error(`no completed game ${id}`); },
    searchManualCompletedCandidates: async () => ({ items: [] }),
    createManualCompletedGame: async () => { throw new Error("not stubbed"); },
    deleteCompletedGame: async () => ({ ok: true }),
    patchCompletedGame: async () => { throw new Error("not stubbed"); },
    getCompletedMatchCandidates: async () => ({ items: [] }),
    saveCompletedMatch: async () => { throw new Error("not stubbed"); },
    randomizerOptions: async () => ({ genres: [], themes: [], gameModes: [], perspectives: [], platforms: [], tags: [] }),
    spinRandomizer: async () => ({ pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: "No released games." }),
    randomizerHistory: async () => ({ items: [] }),
    clearRandomizerHistory: async () => ({ ok: true }),
    searchRandomizerTags: async () => ({ items: [] }),
    searchRandomizerSeries: async () => ({ items: [] }),
    searchRandomizerGames: async () => ({ items: [] }),
    getYearInReviewYears: async () => ({ years: [{ year: 2026, count: 0, inProgress: true }] }),
    getYearInReview: async year => emptySummary(year),
    saveYearInReviewSettings: async year => emptySummary(year),
    getPreferences: async () => ({ palette: null, themeAutoplay: false }),
    savePalette: async palette => ({ palette }),
    saveThemeAutoplay: async themeAutoplay => ({ themeAutoplay }),
    logEvent: async () => ({ ok: true })
  };
  const merged = { ...defaults, ...overrides } as ApiClient;
  return Object.fromEntries(Object.entries(merged).map(([key, fn]) => [key, vi.fn(fn as (...args: unknown[]) => unknown)])) as never;
}
