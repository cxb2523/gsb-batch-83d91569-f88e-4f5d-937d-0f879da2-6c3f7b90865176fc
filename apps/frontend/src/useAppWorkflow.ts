import { useMemo } from "react";
import { createApiClient, type ApiClient } from "./api/client";
import { useAppShell, type AppState } from "./appShell";
import { useReleaseWorkspace } from "./releaseWorkspace";
import { useCompletedLibraryWorkflow } from "./useCompletedLibraryWorkflow";
import { useRandomizerWorkflow } from "./useRandomizerWorkflow";
import { useSettingsWorkflow } from "./useSettingsWorkflow";
import { useSyncSettingsWorkflow } from "./useSyncSettingsWorkflow";
import { useDemoWorkflow } from "./useDemoWorkflow";
import { usePreferences } from "./theme/usePreferences";
import { useWallpaperWorkflow } from "./wallpaperWorkflow";
import { useYearInReviewWorkflow } from "./useYearInReviewWorkflow";

export type { AppState };

// `api` replaces the HTTP client, e.g. with an in-memory fake in tests.
export function useAppWorkflow({ apiBaseUrl, initialState, api: injectedApi }: { apiBaseUrl: string; initialState?: AppState; api?: ApiClient }) {
  const api = useMemo(() => injectedApi ?? createApiClient(apiBaseUrl), [apiBaseUrl, injectedApi]);
  const shell = useAppShell({ api, initialView: initialState?.initialView, initialOperationError: initialState?.operationError });
  const releaseWorkspace = useReleaseWorkspace({ api, initialState, shell });
  const completedLibrary = useCompletedLibraryWorkflow({ api, shell, initialState });
  const randomizer = useRandomizerWorkflow({ api, shell, active: shell.view === "randomizer" });
  const preferences = usePreferences(api);
  const yearInReview = useYearInReviewWorkflow({ api, shell, active: shell.view === "year-in-review", themeAutoplay: preferences.themeAutoplay });
  const wallpaper = useWallpaperWorkflow({ api, apiBaseUrl, onError: shell.reportOperationError });
  const settings = useSettingsWorkflow({
    api,
    initialStatus: initialState?.settingsStatus,
    loadOnOpen: !initialState && shell.view === "settings",
    onError: shell.reportOperationError
  });
  const demo = useDemoWorkflow({
    api,
    enabled: !initialState,
    onChanged: () => Promise.all([releaseWorkspace.actions.reload(), completedLibrary.games.reload()]),
    onError: shell.reportOperationError
  });
  const syncSettings = useSyncSettingsWorkflow({ api, loadOnOpen: !initialState && shell.view === "settings", onError: shell.reportOperationError });

  return {
    ...releaseWorkspace,
    view: shell.view,
    operationError: shell.operationError,
    completedLibrary,
    randomizer,
    yearInReview,
    preferences,
    hasNativeWallpaperPicker: wallpaper.hasNativeWallpaperPicker,
    wallpaperUrl: wallpaper.wallpaperUrl,
    settings,
    syncSettings,
    demo,
    actions: {
      ...releaseWorkspace.actions,
      chooseWallpaper: wallpaper.actions.chooseWallpaper,
      clearWallpaper: wallpaper.actions.clearWallpaper,
      // The first-run choice to use your own data: IGDB keys come first.
      setUpOwnLibrary() {
        settings.actions.setTab("API keys");
        releaseWorkspace.actions.setView("settings");
      }
    }
  };
}
