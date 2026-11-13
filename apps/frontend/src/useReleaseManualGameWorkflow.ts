import { useState } from "react";
import type { ManualReleaseCandidate, ReleaseDetail } from "../../../shared/types";
import type { ApiClient } from "./api/client";
import type { AppShell } from "./appShell";
import { useCandidateSearch, type ManualAddWorkflow } from "./candidateSearch";
import type { ManualGameForm } from "./views/ManualReleaseView";

const emptyManualGame: ManualGameForm = {
  title: "",
  publishers: "NIS America",
  developers: "",
  platforms: "Windows PC, Xbox Series X|S",
  category: "Main",
  dateText: "",
  datePrecision: "Exact",
  releaseDate: "",
  releaseWindow: "",
  sourceUrl: ""
};

// The Add game form: IGDB search, picking a candidate, and saving.
export function useReleaseManualGameWorkflow({
  api,
  shell,
  reload,
  showDetail
}: {
  api: ApiClient;
  shell: AppShell;
  reload: () => Promise<void>;
  showDetail: (item: ReleaseDetail) => void;
}) {
  const [manualGame, setManualGame] = useState<ManualGameForm>(emptyManualGame);
  const search = useCandidateSearch<ManualReleaseCandidate>({
    search: async title => (await api.searchManualReleaseCandidates(title)).items,
    shell,
    action: "search-manual-release-igdb",
    messages: { searching: "Searching IGDB...", found: count => `${count} IGDB matches found.`, none: "No IGDB matches found." }
  });

  const createManualGame = async () => {
    shell.clearOperationError();
    try {
      const result = await api.createManualRelease({ ...manualGame });
      showDetail(result.item);
      setManualGame(emptyManualGame);
      search.reset();
      await reload();
      if (result.item.eligible === false) {
        shell.showOperationMessage(`Saved, but it is hidden from Upcoming because ${result.item.eligibilityReason ?? "it has no usable upcoming date"}. Add a release date or year to show it in Upcoming.`);
      }
    } catch (error) {
      shell.reportOperationError("create-manual-release", error);
    }
  };

  const useManualCandidate = (candidate: ManualReleaseCandidate) => {
    setManualGame(manualGameFromCandidate(candidate));
    search.setMessage(`Using IGDB #${candidate.igdbId}: ${candidate.title}`);
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
      useCandidate: useManualCandidate
    }
  } satisfies ManualAddWorkflow<ManualGameForm, ManualReleaseCandidate>;
}

export function manualGameFromCandidate(candidate: ManualReleaseCandidate): ManualGameForm {
  return {
    igdbId: candidate.igdbId,
    title: candidate.title,
    publishers: candidate.publishers.join(", "),
    developers: candidate.developers.join(", "),
    platforms: candidate.platforms.join(", "),
    category: candidate.category,
    dateText: candidate.dateText,
    datePrecision: candidate.datePrecision,
    releaseDate: candidate.releaseDate ?? "",
    releaseWindow: candidate.releaseWindow ?? "",
    sourceUrl: candidate.sourceUrl ?? "",
    artworks: candidate.artworks,
    screenshots: candidate.screenshots,
    trailers: candidate.trailers
  };
}
