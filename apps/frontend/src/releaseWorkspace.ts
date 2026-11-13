import { useEffect, useMemo, useRef, useState } from "react";
import type { ReleaseListItem, SyncStatus } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell, AppState } from "./appShell";
import { useCollectionWorkspace } from "./collectionWorkspace";
import { deleteManyReleases, type ReleaseDeletionMode } from "./releaseDeletion";
import { groupReleases } from "./releaseGroups";
import { useReleaseDetailWorkflow } from "./useReleaseDetailWorkflow";
import { useReleaseManualGameWorkflow } from "./useReleaseManualGameWorkflow";

export interface ReleaseFilters {
  search: string;
  publisher: string;
  category: string;
  platform: string;
  datePrecision: string;
  includeReleased: boolean;
  includeHidden: boolean;
  watchedOnly: boolean;
}

type ReleaseListState = Pick<AppState, "status" | "releases" | "error">;

const emptySync: SyncStatus = { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 };
// How often to check on a sync the app did not start itself (the startup auto-sync).
const SYNC_POLL_MS = 3000;
const initialReleaseFilters: ReleaseFilters = { search: "", publisher: "", category: "", platform: "", datePrecision: "", includeReleased: false, includeHidden: false, watchedOnly: false };

// The Upcoming workspace: the release list, sync, and navigation between the list and its detail and
// Add game pages. Detail editing and manual add live in their own workflows.
export function useReleaseWorkspace({ api, initialState, shell }: { api: ApiClient; initialState?: AppState; shell: AppShell }) {
  const { view, setView, reportOperationError, clearOperationError, logUiEvent, dialogs } = shell;
  const [listState, setListState] = useState<ReleaseListState>(initialState ?? { status: "starting", releases: [] });
  const [syncStatus, setSyncStatus] = useState<SyncStatus>(initialState?.syncStatus ?? emptySync);
  const ownSyncRunning = useRef(false);
  const state = { ...listState, syncStatus };

  const load = async (filters: ReleaseFilters) => {
    try {
      const releases = await api.listReleases({ ...filters });
      setListState({ status: "ready", releases: releases.items });
    } catch (error) {
      setListState(current => ({ ...current, status: "error", error: error instanceof Error ? error.message : String(error) }));
    }
  };

  const eligibleReleases = useMemo(() => state.releases.filter(item => item.eligible !== false), [state.releases]);
  const releases = useCollectionWorkspace({
    items: eligibleReleases,
    initialFilters: initialReleaseFilters,
    load,
    genresOf: item => item.genres ?? [],
    view,
    setView,
    listViews: ["gallery", "calendar"],
    detailView: "detail",
    itemAttribute: "data-release-id",
    log: logUiEvent
  });
  const visibleReleases = releases.visibleItems;
  const groups = useMemo(() => groupReleases(visibleReleases), [visibleReleases]);
  const reload = releases.reload;

  const detailWorkflow = useReleaseDetailWorkflow({
    api,
    shell,
    initialDetail: initialState?.initialDetail,
    reload,
    setView,
    onDeleted: releases.removeFromSelection
  });
  const manualWorkflow = useReleaseManualGameWorkflow({ api, shell, reload, showDetail: detailWorkflow.actions.showDetail });

  const refreshSyncStatus = async () => {
    try {
      setSyncStatus(await api.getSyncStatus());
    } catch {
      // The list load reports an unreachable backend; a missing sync status needs no second banner.
    }
  };

  useEffect(() => {
    if (!initialState) void Promise.all([reload(), refreshSyncStatus()]);
  }, [api]);

  // Coming back from the tray: a background sync may have changed the list while the window was hidden.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") void Promise.all([reload(), refreshSyncStatus()]);
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [api]);

  // A clicked release alert (desktop) opens that game's page.
  useEffect(() => window.releaseTracker?.onOpenRelease?.(releaseId => {
    logUiEvent("ui.click", { action: "open-release-alert", releaseId });
    void api.getRelease(releaseId).then(detailWorkflow.actions.showDetail, error => reportOperationError("open-release-alert", error));
  }), [api]);

  // A sync the app did not start (the startup auto-sync) is followed until it ends, then the list reloads.
  useEffect(() => {
    if (syncStatus.status !== "running" || ownSyncRunning.current) return;
    const timer = setTimeout(async () => {
      try {
        const next = await api.getSyncStatus();
        setSyncStatus(next);
        if (next.status !== "running") await reload();
      } catch {
        // Try again on the next status change; the list load reports an unreachable backend.
      }
    }, SYNC_POLL_MS);
    return () => clearTimeout(timer);
  }, [syncStatus, api]);

  const sync = async () => {
    logUiEvent("ui.click", { action: "sync" });
    clearOperationError();
    ownSyncRunning.current = true;
    setSyncStatus(current => ({ ...current, status: "running", message: "Sync running" }));
    try {
      const finished = await api.syncNow();
      ownSyncRunning.current = false;
      setSyncStatus(finished);
      // Like a followed sync: any finished run may have saved games, even a partial or failed one.
      await reload();
    } catch (error) {
      ownSyncRunning.current = false;
      reportOperationError("sync", error);
      setSyncStatus(current => ({ ...current, status: "failed", message: error instanceof Error ? error.message : String(error) }));
    }
  };

  const openDetail = (item: ReleaseListItem) => {
    logUiEvent("ui.click", { action: "open-detail", releaseId: item.id, title: item.title });
    releases.rememberReturnPosition(item.id);
    return detailWorkflow.actions.openDetail(item);
  };

  // Watch or stop watching a game from the list; its detail page has its own toggle.
  const setWatched = async (item: ReleaseListItem, watched: boolean) => {
    logUiEvent("ui.click", { action: watched ? "watch-release" : "unwatch-release", releaseId: item.id });
    clearOperationError();
    try {
      await api.patchRelease(item.id, { watched });
      await reload();
    } catch (error) {
      reportOperationError(watched ? "watch-release" : "unwatch-release", error);
    }
  };

  const deleteSelected = (mode: ReleaseDeletionMode) =>
    releases.deleteSelected(selected => deleteManyReleases(selected.map(({ id, title }) => ({ id, title })), mode, {
      confirm: dialogs.confirm,
      alert: dialogs.alert,
      deleteRelease: (id, block) => api.deleteRelease(id, block),
      log: logUiEvent
    }));

  return {
    state,
    releases,
    detail: detailWorkflow,
    manual: manualWorkflow,
    eligibleReleases,
    groups,
    actions: {
      setView,
      sync,
      openDetail,
      reload,
      returnToReleaseList: releases.returnToList,
      setWatched,
      deleteSelected
    }
  };
}
