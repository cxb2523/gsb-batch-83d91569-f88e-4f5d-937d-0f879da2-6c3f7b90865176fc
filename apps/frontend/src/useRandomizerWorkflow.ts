import { useCallback, useEffect, useRef, useState } from "react";
import type { RandomizerFilters, RandomizerGameOption, RandomizerHistoryItem, RandomizerOption, RandomizerOptions, RandomizerPick, RandomizerSeriesOption, RandomizerSpinResponse } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell } from "./appShell";
import { keepOfferedPlatforms, setSimilarTo } from "./randomizerFilters";
import { prefersReducedMotion } from "./motion";

const FILTERS_STORAGE_KEY = "grt.randomizer.filters";
const LABELS_STORAGE_KEY = "grt.randomizer.labels";
const REEL_MS = 1500;
const HISTORY_LIMIT = 12;

const defaultRandomizerFilters: RandomizerFilters = { includeRemakes: true, hideCompleted: true, hideUpcoming: false, minRatingCount: 5 };

export type RandomizerPhase = "idle" | "spinning" | "ready";

// Storage can be unavailable, so every preference read and write is guarded.
function readStoredObject<T extends object>(key: string, fallback: T): T {
  try {
    const saved = JSON.parse(localStorage.getItem(key) ?? "null") as unknown;
    if (saved && typeof saved === "object" && !Array.isArray(saved)) return { ...fallback, ...saved as T };
  } catch { /* Keep the in-session defaults. */ }
  return fallback;
}

function saveStored(key: string, value: object) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* Keep the value for this session. */ }
}

const needsCredentials = (error: unknown) => error instanceof Error && /IGDB credentials/i.test(error.message);

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

export type RandomizerWorkflow = ReturnType<typeof useRandomizerWorkflow>;

// The Randomizer view: IGDB option lists, filters, spinning and recent picks.
// Nothing loads until the view is first opened, so other views never wait on IGDB for it.
export function useRandomizerWorkflow({ api, shell, active, reelMs = REEL_MS }: {
  api: ApiClient;
  shell: Pick<AppShell, "reportOperationError" | "clearOperationError">;
  active: boolean;
  reelMs?: number;
}) {
  const [filters, setFiltersState] = useState<RandomizerFilters>(() => readStoredObject(FILTERS_STORAGE_KEY, defaultRandomizerFilters));
  const [options, setOptions] = useState<RandomizerOptions | null>(null);
  const [optionsStatus, setOptionsStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [missingCredentials, setMissingCredentials] = useState(false);
  const [phase, setPhase] = useState<RandomizerPhase>("idle");
  const [result, setResult] = useState<RandomizerSpinResponse | null>(null);
  const [reel, setReel] = useState<RandomizerSpinResponse["reels"]>([]);
  const [history, setHistory] = useState<RandomizerHistoryItem[]>([]);
  const [labels, setLabels] = useState<Record<string, string>>(() => readStoredObject(LABELS_STORAGE_KEY, {}));
  const spinning = useRef(false);

  const loadHistory = useCallback(async () => {
    try {
      setHistory((await api.randomizerHistory(HISTORY_LIMIT)).items);
    } catch (error) {
      shell.reportOperationError("load-randomizer-history", error);
    }
  }, [api]);

  const loadOptions = useCallback(async () => {
    setOptionsStatus("loading");
    try {
      const loaded = await api.randomizerOptions();
      setOptions(loaded);
      setMissingCredentials(false);
      // Platforms saved before the mainstream-only list would otherwise show as unknown chips.
      const offered = new Set(loaded.platforms.map(platform => platform.id));
      setFiltersState(current => {
        const next = keepOfferedPlatforms(current, offered);
        if (next !== current) saveStored(FILTERS_STORAGE_KEY, next);
        return next;
      });
      setOptionsStatus("ready");
    } catch (error) {
      setOptionsStatus("error");
      if (needsCredentials(error)) setMissingCredentials(true);
      else shell.reportOperationError("load-randomizer-options", error);
    }
  }, [api]);

  useEffect(() => {
    if (!active) return;
    // Sample options are asked again each visit: keys saved since, or the sample removed, change the answer.
    if (optionsStatus === "idle" || (optionsStatus === "error" && missingCredentials) || options?.sample) void loadOptions();
    void loadHistory();
  }, [active]);

  const setFilters = (update: RandomizerFilters | ((current: RandomizerFilters) => RandomizerFilters)) => {
    setFiltersState(current => {
      const next = typeof update === "function" ? update(current) : update;
      saveStored(FILTERS_STORAGE_KEY, next);
      return next;
    });
  };

  // `override` spins with filters that were just set, before the state update lands.
  const spin = async (override?: RandomizerFilters) => {
    if (spinning.current) return;
    spinning.current = true;
    shell.clearOperationError();
    setPhase("spinning");
    const started = Date.now();
    try {
      const response = await api.spinRandomizer(override ?? filters);
      setMissingCredentials(false);
      if (response.pick) setReel([...response.reels, { title: response.pick.title, coverImageId: response.pick.coverImageId }]);
      const remaining = prefersReducedMotion() || !response.pick ? 0 : reelMs - (Date.now() - started);
      if (remaining > 0) await wait(remaining);
      setResult(response);
      if (response.pick) void loadHistory();
    } catch (error) {
      if (needsCredentials(error)) setMissingCredentials(true);
      else shell.reportOperationError("spin-randomizer", error);
    } finally {
      spinning.current = false;
      setPhase("ready");
    }
  };

  // Search failures are shown inside each picker, not as the app-wide error banner.
  const searchTags = async (text: string): Promise<RandomizerOption[]> => (await api.searchRandomizerTags(text)).items;
  const searchSeries = async (text: string): Promise<RandomizerSeriesOption[]> => (await api.searchRandomizerSeries(text)).items;
  const searchGames = async (text: string): Promise<RandomizerGameOption[]> => (await api.searchRandomizerGames(text)).items;

  const rememberLabel = (key: string, name: string) => {
    setLabels(current => {
      if (current[key] === name) return current;
      const next = { ...current, [key]: name };
      saveStored(LABELS_STORAGE_KEY, next);
      return next;
    });
  };

  // Keeps every other filter and spins among games IGDB lists as similar to the pick.
  const moreLikeThis = (pick: Pick<RandomizerPick, "igdbId" | "title">) => {
    const next = setSimilarTo(filters, { id: pick.igdbId, name: pick.title });
    setFilters(next);
    void spin(next);
  };

  const clearHistory = async () => {
    try {
      await api.clearRandomizerHistory();
      setHistory([]);
    } catch (error) {
      shell.reportOperationError("clear-randomizer-history", error);
    }
  };

  return {
    filters,
    options,
    optionsStatus,
    missingCredentials,
    phase,
    result,
    reel,
    history,
    labels,
    actions: {
      setFilters,
      resetFilters: () => setFilters(defaultRandomizerFilters),
      spin,
      clearHistory,
      searchTags,
      searchSeries,
      searchGames,
      rememberLabel,
      moreLikeThis
    }
  };
}
