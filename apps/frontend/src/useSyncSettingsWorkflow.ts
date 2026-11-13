import { useState } from "react";
import type { PlatformFamily, SyncSettings, SyncSettingsPatch, TrackedPublisher } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import { useLoadOnFirstOpen } from "./useLoadOnFirstOpen";

// Settings → Sync: the tracked publishers (search, add, remove, add the suggested set) and the platform,
// track-from and auto-sync choices. Every change saves at once; the backend's answer is the new state.
export function useSyncSettingsWorkflow({ api, loadOnOpen, onError }: { api: ApiClient; loadOnOpen: boolean; onError?: (action: string, error: unknown) => void }) {
  const [settings, setSettings] = useState<SyncSettings | null>(null);
  const [searchText, setSearchText] = useState("");
  const [results, setResults] = useState<TrackedPublisher[] | null>(null);
  const [notFound, setNotFound] = useState<string[]>([]);

  useLoadOnFirstOpen(loadOnOpen, () => {
    api.getSyncSettings().then(setSettings, error => onError?.("load-sync-settings", error));
  });

  const apply = async (action: string, change: () => Promise<SyncSettings>) => {
    try {
      setSettings(await change());
    } catch (error) {
      onError?.(action, error);
    }
  };

  const update = (patch: SyncSettingsPatch) => apply("save-sync-settings", () => api.updateSyncSettings(patch));

  return {
    settings,
    searchText,
    results,
    notFound,
    actions: {
      setSearchText,
      async search() {
        try {
          setResults((await api.searchPublishers(searchText.trim())).items);
        } catch (error) {
          onError?.("search-publishers", error);
        }
      },
      track: (publisher: TrackedPublisher) => apply("track-publisher", () => api.trackPublisher(publisher)),
      untrack: (id: number) => apply("untrack-publisher", () => api.untrackPublisher(id)),
      trackSuggested: () => apply("track-suggested-publishers", async () => {
        const { notFound: missing, ...next } = await api.trackSuggestedPublishers();
        setNotFound(missing);
        return next;
      }),
      togglePlatform(platform: PlatformFamily) {
        if (!settings) return;
        const on = settings.platforms.includes(platform);
        if (on && settings.platforms.length === 1) return;
        return update({ platforms: on ? settings.platforms.filter(item => item !== platform) : [...settings.platforms, platform] });
      },
      setTrackFrom: (trackFrom: string) => (trackFrom ? update({ trackFrom }) : undefined),
      setAutoSync: (autoSync: boolean) => update({ autoSync }),
      setAlerts: (alerts: boolean) => update({ alerts })
    }
  };
}

export type SyncSettingsWorkflow = ReturnType<typeof useSyncSettingsWorkflow>;
