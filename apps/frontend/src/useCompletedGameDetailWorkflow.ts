import { useState } from "react";
import type {
  CompletedGameDetail,
  CompletedGameListItem,
  CompletedGameMatchCandidate
} from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell, AppView } from "./appShell";
import { useDetailSession } from "./detailSession";
import { confirmAndDelete } from "./collectionDeletion";

// Completed Game detail page: open, edit, delete, and the IGDB "fix match" flow.
export type CompletedGameDetailWorkflow = ReturnType<typeof useCompletedGameDetailWorkflow>;

export function useCompletedGameDetailWorkflow({
  api,
  shell,
  initialDetail,
  reload,
  setView,
  onDeleted
}: {
  api: ApiClient;
  shell: AppShell;
  initialDetail?: CompletedGameDetail;
  reload: () => Promise<void>;
  setView: (view: AppView) => void;
  onDeleted: (ids: string[]) => void;
}) {
  const session = useDetailSession<CompletedGameListItem, CompletedGameDetail>({
    initialDetail,
    load: item => api.getCompletedGame(item.id),
    fallback: item => ({ ...item, extra: {}, igdbGenres: item.igdbGenres ?? [], igdbPlatforms: [], igdbThemes: [], igdbGameModes: [], screenshots: [] }),
    reload,
    shell,
    action: "open-completed-game-detail"
  });
  const [matchCandidates, setMatchCandidates] = useState<CompletedGameMatchCandidate[]>([]);
  const [matchMessage, setMatchMessage] = useState("");
  const [appliedMatchIgdbId, setAppliedMatchIgdbId] = useState<number | null>(null);

  const resetMatch = () => {
    setMatchCandidates([]);
    setMatchMessage("");
    setAppliedMatchIgdbId(null);
  };

  const openDetail = (item: CompletedGameListItem) => {
    resetMatch();
    setView("completed-detail");
    return session.open(item);
  };

  // For pages that know only the game's id (Year in Review): the detail page shows "Loading" until it arrives.
  const openById = async (id: string) => {
    resetMatch();
    session.setDetail(null);
    setView("completed-detail");
    try {
      session.setDetail(await api.getCompletedGame(id));
    } catch (error) {
      shell.reportOperationError("open-completed-game-detail", error);
    }
  };

  const showDetail = (item: CompletedGameDetail) => {
    session.setDetail(item);
    resetMatch();
    setView("completed-detail");
  };

  const saveMatch = async (igdbId: number, options?: { keepCandidates?: boolean; confidence?: number }) => {
    setMatchMessage("Saving IGDB match...");
    const saved = await session.mutate("save-completed-match", async current => (await api.saveCompletedMatch(current.id, igdbId)).item);
    if (!saved) {
      setMatchMessage("Saving the IGDB match failed.");
      return;
    }
    setAppliedMatchIgdbId(igdbId);
    if (options?.keepCandidates) {
      setMatchMessage(typeof options.confidence === "number"
        ? `Auto-applied top match (${Math.round(options.confidence)}%) - review alternatives below.`
        : "IGDB match applied - review alternatives below.");
    } else {
      setMatchCandidates([]);
      setMatchMessage("");
    }
  };

  const loadMatchCandidates = async () => {
    const detail = session.detail;
    if (!detail) return;
    setMatchMessage("Loading IGDB matches...");
    setAppliedMatchIgdbId(null);
    try {
      const result = await api.getCompletedMatchCandidates(detail.id);
      setMatchCandidates(result.items);
      if (result.items.length === 0) {
        setMatchMessage("No IGDB candidates found.");
        return;
      }
      const top = result.items[0];
      await saveMatch(top.igdbId, { keepCandidates: true, confidence: top.confidence });
    } catch (error) {
      setMatchCandidates([]);
      setMatchMessage(shell.reportOperationError("load-completed-match-candidates", error));
    }
  };

  const deleteCurrent = async () => {
    const detail = session.detail;
    if (!detail) return;
    const result = await confirmAndDelete([detail], {
      scope: "single",
      action: "delete-completed",
      confirmMessage: `Delete "${detail.title}" from completed library?`,
      deleteOne: game => api.deleteCompletedGame(game.id),
      dialogs: shell.dialogs,
      log: shell.logUiEvent
    });
    if (result.status !== "deleted") return;
    session.close();
    resetMatch();
    setView("completed-library");
    onDeleted(result.deletedIds);
    await reload();
  };

  const renameCompletedGame = async (title: string) => {
    if (!title.trim()) return;
    await session.mutate("rename-completed-game", async current => (await api.patchCompletedGame(current.id, { title: title.trim() })).item);
  };

  const editCompletedDetails = async (patch: Record<string, unknown>) => {
    await session.mutate("edit-completed-game", async current => (await api.patchCompletedGame(current.id, patch)).item);
  };

  return {
    detail: session.detail,
    matchCandidates,
    matchMessage,
    appliedMatchIgdbId,
    actions: {
      openDetail,
      openById,
      showDetail,
      loadMatchCandidates,
      saveMatch,
      deleteCurrent,
      renameCompletedGame,
      editCompletedDetails
    }
  };
}
