import { useState } from "react";
import type { CompletedGameDetail, CompletedGameMatchCandidate } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell } from "./appShell";
import { useCandidateSearch, type ManualAddWorkflow } from "./candidateSearch";

export interface ManualCompletedGameForm {
  igdbId?: number;
  title: string;
  userPlatform: string;
  ratingRaw: string;
  completionDate: string;
  notes: string;
}

const emptyManualGame: ManualCompletedGameForm = {
  title: "",
  userPlatform: "",
  ratingRaw: "",
  completionDate: "",
  notes: ""
};

// The Add completed game form: IGDB search, picking a candidate, and saving.
export function useCompletedManualGameWorkflow({
  api,
  shell,
  reload,
  showDetail
}: {
  api: ApiClient;
  shell: AppShell;
  reload: () => Promise<void>;
  showDetail: (item: CompletedGameDetail) => void;
}) {
  const [manualGame, setManualGame] = useState<ManualCompletedGameForm>(emptyManualGame);
  const search = useCandidateSearch<CompletedGameMatchCandidate>({
    search: async title => {
      const completionYear = manualGame.completionDate.match(/(?:^|\D)(\d{4})(?:\D|$)/)?.[1];
      return (await api.searchManualCompletedCandidates({
        title,
        userPlatform: manualGame.userPlatform,
        completionYear: completionYear ? Number(completionYear) : undefined
      })).items;
    },
    shell,
    action: "search-completed-game-igdb",
    messages: { found: () => "Choose the correct IGDB game, then save your entry.", none: "No IGDB matches found. You can still save this game manually." }
  });

  const createManualGame = async (draft = manualGame) => {
    shell.clearOperationError();
    try {
      const result = await api.createManualCompletedGame({
        igdbId: draft.igdbId ?? null,
        title: draft.title,
        userPlatform: draft.userPlatform,
        ratingRaw: draft.ratingRaw || null,
        completionDate: draft.completionDate || null,
        notes: draft.notes || null
      });
      showDetail(result.item);
      setManualGame(emptyManualGame);
      search.reset();
      await reload();
    } catch (error) {
      shell.reportOperationError("create-completed-game", error);
    }
  };

  const useCandidate = (candidate: CompletedGameMatchCandidate) => {
    setManualGame(current => ({
      ...current,
      igdbId: candidate.igdbId,
      title: candidate.title,
      userPlatform: current.userPlatform || candidate.platforms[0] || ""
    }));
    search.setMessage(`Selected ${candidate.title}. Its IGDB artwork and details will be saved with the game.`);
  };

  return {
    form: manualGame,
    candidates: search.candidates,
    searchStatus: search.status,
    searchMessage: search.message,
    actions: {
      setForm: setManualGame,
      save: createManualGame,
      search: () => search.search(manualGame.title),
      useCandidate
    }
  } satisfies ManualAddWorkflow<ManualCompletedGameForm, CompletedGameMatchCandidate>;
}
