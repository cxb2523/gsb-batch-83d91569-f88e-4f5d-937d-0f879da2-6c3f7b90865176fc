import { useState, type Dispatch, type SetStateAction } from "react";
import type { DetailErrorReporting } from "./detailSession";

export type CandidateSearchStatus = "idle" | "searching" | "success" | "error";
export type CandidateSearch<Candidate> = ReturnType<typeof useCandidateSearch<Candidate>>;

// The one shape of an add-game form workflow (Add game and Add completed game): the draft, the IGDB
// search step, and saving. Each add-game view takes this object whole.
export interface ManualAddWorkflow<Form, Candidate> {
  form: Form;
  candidates: Candidate[];
  searchStatus: CandidateSearchStatus;
  searchMessage: string | null;
  actions: {
    setForm: Dispatch<SetStateAction<Form>>;
    save: (draft?: Form) => Promise<void>;
    search: () => Promise<void>;
    useCandidate: (candidate: Candidate) => void;
  };
}

// The IGDB "search, then pick" step shared by the Add game and Add completed game forms.
export function useCandidateSearch<Candidate>({
  search: runSearch,
  shell,
  action,
  messages
}: {
  search: (title: string) => Promise<Candidate[]>;
  shell: DetailErrorReporting;
  action: string;
  messages: { found: (count: number) => string; none: string; searching?: string };
}) {
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [status, setStatus] = useState<CandidateSearchStatus>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const search = async (title: string) => {
    const query = title.trim();
    if (!query) {
      setCandidates([]);
      setStatus("error");
      setMessage("Enter a title before searching IGDB.");
      return;
    }
    shell.clearOperationError();
    setStatus("searching");
    setMessage(messages.searching ?? null);
    try {
      const found = await runSearch(query);
      setCandidates(found);
      setStatus("success");
      setMessage(found.length ? messages.found(found.length) : messages.none);
    } catch (error) {
      setCandidates([]);
      setStatus("error");
      setMessage(shell.reportOperationError(action, error));
    }
  };

  const reset = () => {
    setCandidates([]);
    setStatus("idle");
    setMessage(null);
  };

  return { candidates, status, message, setMessage, search, reset };
}
