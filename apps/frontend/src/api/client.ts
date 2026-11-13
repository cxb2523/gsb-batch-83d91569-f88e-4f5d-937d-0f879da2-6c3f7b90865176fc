import { API_TOKEN_HEADER } from "../../../../shared/constants";
import type {
  CompletedGameDetail,
  CompletedGameFilters,
  CompletedGameListResponse,
  CompletedGameMatchCandidate,
  ManualReleaseCandidate,
  RandomizerFilters,
  RandomizerGameOption,
  RandomizerHistoryItem,
  RandomizerOption,
  RandomizerOptions,
  RandomizerSeriesOption,
  RandomizerSpinResponse,
  ReleaseDetail,
  ReleaseListResponse,
  SettingsStatus,
  SyncSettings,
  SyncSettingsPatch,
  SyncStatus,
  TrackedPublisher,
  YearInReviewSettingsPatch,
  YearInReviewSummary,
  YearInReviewYear
} from "../../../../shared/types";

export interface ApiClient {
  listReleases(params?: Record<string, string | boolean | undefined>): Promise<ReleaseListResponse>;
  getRelease(id: string): Promise<ReleaseDetail>;
  searchManualReleaseCandidates(query: string): Promise<{ items: ManualReleaseCandidate[] }>;
  createManualRelease(payload: Record<string, unknown>): Promise<{ ok: boolean; item: ReleaseDetail }>;
  patchRelease(id: string, payload: Record<string, unknown>): Promise<{ ok: boolean; item: ReleaseDetail }>;
  deleteRelease(id: string, block?: boolean): Promise<{ ok: boolean }>;
  uploadLocalArtwork(id: string, payload: { fileName: string; mimeType: string; dataBase64: string }): Promise<{ ok: boolean; item: ReleaseDetail }>;
  deleteArtwork(id: string, artworkId: string): Promise<{ ok: boolean; item: ReleaseDetail }>;
  reorderArtworks(id: string, artworkIds: string[]): Promise<{ ok: boolean; item: ReleaseDetail }>;
  syncNow(): Promise<SyncStatus>;
  getSyncStatus(): Promise<SyncStatus>;
  getSettings(): Promise<SettingsStatus>;
  patchSettings(payload: Record<string, string>): Promise<{ ok: boolean; settings: SettingsStatus }>;
  clearCredentials(): Promise<{ ok: boolean; settings: SettingsStatus }>;
  testCredentials(): Promise<{ credentialStatus: SettingsStatus["credentialStatus"] }>;
  getDemo(): Promise<{ loaded: boolean }>;
  loadDemo(): Promise<{ loaded: boolean; releases: number; completedGames: number }>;
  removeDemo(): Promise<{ loaded: boolean }>;
  getSyncSettings(): Promise<SyncSettings>;
  updateSyncSettings(patch: SyncSettingsPatch): Promise<SyncSettings>;
  searchPublishers(text: string): Promise<{ items: TrackedPublisher[] }>;
  trackPublisher(publisher: TrackedPublisher): Promise<SyncSettings>;
  untrackPublisher(id: number): Promise<SyncSettings>;
  trackSuggestedPublishers(): Promise<SyncSettings & { notFound: string[] }>;
  getWallpaper(): Promise<{ hasWallpaper: boolean; url: string | null }>;
  clearWallpaper(): Promise<{ ok: boolean }>;
  listCompletedGames(params?: CompletedGameFilters): Promise<CompletedGameListResponse>;
  getCompletedGame(id: string): Promise<CompletedGameDetail>;
  searchManualCompletedCandidates(params: { title: string; userPlatform?: string; completionYear?: number }): Promise<{ items: CompletedGameMatchCandidate[] }>;
  createManualCompletedGame(payload: Record<string, unknown>): Promise<{ ok: boolean; item: CompletedGameDetail }>;
  deleteCompletedGame(id: string): Promise<{ ok: boolean }>;
  patchCompletedGame(id: string, payload: Record<string, unknown>): Promise<{ ok: boolean; item: CompletedGameDetail }>;
  getCompletedMatchCandidates(id: string): Promise<{ items: CompletedGameMatchCandidate[] }>;
  saveCompletedMatch(id: string, igdbId: number): Promise<{ ok: boolean; item: CompletedGameDetail }>;
  randomizerOptions(): Promise<RandomizerOptions>;
  spinRandomizer(filters: RandomizerFilters): Promise<RandomizerSpinResponse>;
  randomizerHistory(limit?: number): Promise<{ items: RandomizerHistoryItem[] }>;
  clearRandomizerHistory(): Promise<{ ok: boolean }>;
  searchRandomizerTags(search: string): Promise<{ items: RandomizerOption[] }>;
  searchRandomizerSeries(search: string): Promise<{ items: RandomizerSeriesOption[] }>;
  searchRandomizerGames(search: string): Promise<{ items: RandomizerGameOption[] }>;
  getYearInReviewYears(): Promise<{ years: YearInReviewYear[] }>;
  getYearInReview(year: number): Promise<YearInReviewSummary>;
  saveYearInReviewSettings(year: number, patch: YearInReviewSettingsPatch): Promise<YearInReviewSummary>;
  logEvent(event: string, details?: Record<string, unknown>): Promise<{ ok: boolean }>;
  getPreferences(): Promise<{ palette: string | null; themeAutoplay: boolean }>;
  savePalette(palette: string): Promise<{ palette: string }>;
  saveThemeAutoplay(themeAutoplay: boolean): Promise<{ themeAutoplay: boolean }>;
}

// Appends the non-empty params as a query string; undefined and "" mean "not filtered".
function withQuery(path: string, params: Record<string, string | number | boolean | undefined | null>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  const search = query.toString();
  return search ? `${path}?${search}` : path;
}

// apiToken is the desktop app's per-launch secret; the backend refuses /api calls without it.
export function createApiClient(baseUrl: string, apiToken?: string): ApiClient {
  const request = async <T>(path: string, init?: RequestInit): Promise<T> => {
    const headers = {
      ...(init?.body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(apiToken ? { [API_TOKEN_HEADER]: apiToken } : {}),
      ...init?.headers as Record<string, string> | undefined
    };
    const response = await fetch(`${baseUrl}${path}`, {
      ...init,
      headers: Object.keys(headers).length ? headers : undefined
    });
    if (!response.ok) throw new Error(await responseErrorMessage(response));
    return await response.json() as T;
  };

  return {
    listReleases(params = {}) {
      return request<ReleaseListResponse>(withQuery("/api/releases", params));
    },
    getRelease(id) {
      return request<ReleaseDetail>(`/api/releases/${encodeURIComponent(id)}`);
    },
    searchManualReleaseCandidates(query) {
      return request<{ items: ManualReleaseCandidate[] }>(withQuery("/api/releases/manual/search", { q: query }));
    },
    createManualRelease(payload) {
      return request("/api/releases/manual", { method: "POST", body: JSON.stringify(payload) });
    },
    patchRelease(id, payload) {
      return request(`/api/releases/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });
    },
    deleteRelease(id, block = false) {
      return request(`/api/releases/${encodeURIComponent(id)}?block=${block ? "true" : "false"}`, { method: "DELETE" });
    },
    uploadLocalArtwork(id, payload) {
      return request(`/api/releases/${encodeURIComponent(id)}/artworks/local`, { method: "POST", body: JSON.stringify(payload) });
    },
    deleteArtwork(id, artworkId) {
      return request(`/api/releases/${encodeURIComponent(id)}/artworks/${encodeURIComponent(artworkId)}`, { method: "DELETE" });
    },
    reorderArtworks(id, artworkIds) {
      return request(`/api/releases/${encodeURIComponent(id)}/artworks/order`, { method: "PATCH", body: JSON.stringify({ artworkIds }) });
    },
    syncNow() {
      return request<SyncStatus>("/api/sync/igdb", { method: "POST", body: "{}" });
    },
    getSyncStatus() {
      return request<SyncStatus>("/api/sync/status");
    },
    getSettings() {
      return request("/api/settings");
    },
    patchSettings(payload) {
      return request("/api/settings", { method: "PATCH", body: JSON.stringify(payload) });
    },
    clearCredentials() {
      return request("/api/settings/credentials", { method: "DELETE" });
    },
    testCredentials() {
      return request("/api/settings/test-credentials", { method: "POST", body: "{}" });
    },
    getDemo() {
      return request<{ loaded: boolean }>("/api/demo");
    },
    loadDemo() {
      return request<{ loaded: boolean; releases: number; completedGames: number }>("/api/demo", { method: "POST", body: "{}" });
    },
    removeDemo() {
      return request<{ loaded: boolean }>("/api/demo", { method: "DELETE" });
    },
    getSyncSettings() {
      return request<SyncSettings>("/api/sync/settings");
    },
    updateSyncSettings(patch) {
      return request<SyncSettings>("/api/sync/settings", { method: "PUT", body: JSON.stringify(patch) });
    },
    searchPublishers(text) {
      return request<{ items: TrackedPublisher[] }>(`/api/sync/publishers/search?q=${encodeURIComponent(text)}`);
    },
    trackPublisher(publisher) {
      return request<SyncSettings>("/api/sync/publishers", { method: "POST", body: JSON.stringify(publisher) });
    },
    untrackPublisher(id) {
      return request<SyncSettings>(`/api/sync/publishers/${encodeURIComponent(String(id))}`, { method: "DELETE" });
    },
    trackSuggestedPublishers() {
      return request<SyncSettings & { notFound: string[] }>("/api/sync/publishers/suggested", { method: "POST", body: "{}" });
    },
    getWallpaper() {
      return request("/api/wallpaper");
    },
    clearWallpaper() {
      return request("/api/wallpaper", { method: "DELETE" });
    },
    listCompletedGames(params = {}) {
      return request<CompletedGameListResponse>(withQuery("/api/completed-games", { ...params }));
    },
    getCompletedGame(id) {
      return request<CompletedGameDetail>(`/api/completed-games/${encodeURIComponent(id)}`);
    },
    searchManualCompletedCandidates({ title, userPlatform, completionYear }) {
      return request<{ items: CompletedGameMatchCandidate[] }>(withQuery("/api/completed-games/manual/search", { q: title, platform: userPlatform, completionYear: completionYear || undefined }));
    },
    createManualCompletedGame(payload) {
      return request("/api/completed-games/manual", { method: "POST", body: JSON.stringify(payload) });
    },
    deleteCompletedGame(id) {
      return request(`/api/completed-games/${encodeURIComponent(id)}`, { method: "DELETE" });
    },
    patchCompletedGame(id, payload) {
      return request(`/api/completed-games/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(payload) });
    },
    getCompletedMatchCandidates(id) {
      return request(`/api/completed-games/${encodeURIComponent(id)}/match-candidates`);
    },
    saveCompletedMatch(id, igdbId) {
      return request(`/api/completed-games/${encodeURIComponent(id)}/match`, { method: "POST", body: JSON.stringify({ igdbId }) });
    },
    randomizerOptions() {
      return request<RandomizerOptions>("/api/randomizer/options");
    },
    spinRandomizer(filters) {
      return request<RandomizerSpinResponse>("/api/randomizer/spin", { method: "POST", body: JSON.stringify(filters) });
    },
    randomizerHistory(limit = 20) {
      return request<{ items: RandomizerHistoryItem[] }>(`/api/randomizer/history?limit=${encodeURIComponent(String(limit))}`);
    },
    clearRandomizerHistory() {
      return request("/api/randomizer/history", { method: "DELETE" });
    },
    searchRandomizerTags(search) {
      return request<{ items: RandomizerOption[] }>(withQuery("/api/randomizer/tags", { search }));
    },
    searchRandomizerSeries(search) {
      return request<{ items: RandomizerSeriesOption[] }>(withQuery("/api/randomizer/series", { search }));
    },
    searchRandomizerGames(search) {
      return request<{ items: RandomizerGameOption[] }>(withQuery("/api/randomizer/games", { search }));
    },
    getYearInReviewYears() {
      return request<{ years: YearInReviewYear[] }>("/api/year-in-review/years");
    },
    getYearInReview(year) {
      return request<YearInReviewSummary>(`/api/year-in-review/${encodeURIComponent(String(year))}`);
    },
    getPreferences() {
      return request("/api/preferences");
    },
    savePalette(palette) {
      return request("/api/preferences/palette", { method: "PUT", body: JSON.stringify({ palette }) });
    },
    saveThemeAutoplay(themeAutoplay) {
      return request("/api/preferences/theme-autoplay", { method: "PUT", body: JSON.stringify({ themeAutoplay }) });
    },
    saveYearInReviewSettings(year, patch) {
      return request<YearInReviewSummary>(`/api/year-in-review/${encodeURIComponent(String(year))}/settings`, { method: "PUT", body: JSON.stringify(patch) });
    },
    logEvent(event, details = {}) {
      return request("/api/diagnostics/log", { method: "POST", body: JSON.stringify({ event, details }) });
    }
  };
}

async function responseErrorMessage(response: Response) {
  const fallback = `${response.status} ${response.statusText}`.trim();
  const text = await response.text().catch(() => "");
  if (!text) return fallback;
  try {
    const parsed = JSON.parse(text) as { error?: unknown; message?: unknown };
    const message = typeof parsed.error === "string" ? parsed.error : typeof parsed.message === "string" ? parsed.message : "";
    return message ? `${fallback}: ${message}` : fallback;
  } catch {
    return `${fallback}: ${text}`;
  }
}
