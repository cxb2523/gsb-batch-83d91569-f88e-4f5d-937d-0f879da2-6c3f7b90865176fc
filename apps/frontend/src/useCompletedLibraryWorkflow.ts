import { useState } from "react";
import type {
  CompletedGameFilters,
  CompletedGameListItem,
  CompletedViewMode
} from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell, AppView } from "./appShell";
import { useCollectionWorkspace } from "./collectionWorkspace";
import { confirmAndDelete } from "./collectionDeletion";
import { groupCompletedGames } from "./completedGroups";
import { useLoadOnFirstOpen } from "./useLoadOnFirstOpen";
import { completedGenres } from "../../../shared/completedGenres";
import type { AppState } from "./appShell";
import { useCompletedGameDetailWorkflow } from "./useCompletedGameDetailWorkflow";
import { useCompletedManualGameWorkflow } from "./useCompletedManualGameWorkflow";

const initialCompletedFilters: CompletedGameFilters = { search: "", platform: "", year: "", month: "", rating: "", dateState: "" };

export function useCompletedLibraryWorkflow({
  api,
  shell,
  initialState
}: {
  api: ApiClient;
  shell: AppShell;
  initialState?: AppState;
}) {
  const { view: currentView, setView, reportOperationError: onError, dialogs } = shell;
  const [items, setItems] = useState<CompletedGameListItem[]>(initialState?.completedGames ?? []);
  const [viewMode, setViewMode] = useState<CompletedViewMode>("grouped");
  const [status, setStatus] = useState<"starting" | "ready" | "error">(initialState?.completedLibraryStatus ?? "starting");
  const [error, setError] = useState<string | undefined>();
  // Set while a game's detail page was opened from another view (Year in Review), so back goes there.
  const [openedFrom, setOpenedFrom] = useState<AppView | null>(null);

  const load = async (filters: CompletedGameFilters) => {
    try {
      const list = await api.listCompletedGames(filters);
      setItems(Array.isArray(list.items) ? list.items : []);
      setStatus("ready");
      setError(undefined);
    } catch (loadError) {
      setStatus("error");
      setError(loadError instanceof Error ? loadError.message : String(loadError));
      onError("load-completed-library", loadError);
    }
  };

  const games = useCollectionWorkspace({
    items,
    initialFilters: initialCompletedFilters,
    load,
    genresOf: completedGenres,
    view: currentView,
    setView,
    listViews: ["completed-library"],
    detailView: "completed-detail",
    itemAttribute: "data-completed-game-id",
    log: shell.logUiEvent
  });
  const reload = games.reload;

  useLoadOnFirstOpen(!initialState && currentView === "completed-library", () => void reload());

  const detailWorkflow = useCompletedGameDetailWorkflow({
    api,
    shell,
    initialDetail: initialState?.initialCompletedDetail,
    reload,
    setView,
    onDeleted: games.removeFromSelection
  });

  const manualWorkflow = useCompletedManualGameWorkflow({
    api,
    shell,
    reload,
    showDetail: detailWorkflow.actions.showDetail
  });

  const openDetail = (item: CompletedGameListItem) => {
    setOpenedFrom(null);
    games.rememberReturnPosition(item.id);
    void detailWorkflow.actions.openDetail(item);
  };

  const openGameFrom = (id: string, from: AppView) => {
    setOpenedFrom(from);
    void detailWorkflow.actions.openById(id);
  };

  const returnToLibrary = () => {
    if (!openedFrom) return games.returnToList();
    setOpenedFrom(null);
    setView(openedFrom);
  };

  const deleteSelected = () => games.deleteSelected(selected => confirmAndDelete(selected, {
    scope: "bulk",
    action: "bulk-delete-completed",
    confirmMessage: `Delete ${selected.length} selected completed ${selected.length === 1 ? "game" : "games"}?`,
    deleteOne: item => api.deleteCompletedGame(item.id),
    dialogs,
    log: shell.logUiEvent
  }));

  return {
    games,
    groups: groupCompletedGames(games.visibleItems),
    viewMode,
    status,
    error,
    openedFrom,
    detail: detailWorkflow,
    manual: manualWorkflow,
    actions: {
      setViewMode,
      openDetail,
      openGameFrom,
      returnToLibrary,
      deleteSelected
    }
  };
}
