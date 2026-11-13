import { useState } from "react";

export interface DetailErrorReporting {
  reportOperationError(action: string, error: unknown): string;
  clearOperationError(): void;
}

export type DetailSession<Detail> = ReturnType<typeof useDetailSession<unknown, Detail>>;

// The open detail page for one item: loading it (falling back to the list item if that fails),
// applying edits that return the updated item, refreshing the list, and one error policy.
// Release detail and Completed Game detail both use it; they only supply their API calls.
export function useDetailSession<Item, Detail>({
  initialDetail,
  load,
  fallback,
  reload,
  shell,
  action
}: {
  initialDetail?: Detail | null;
  load: (item: Item) => Promise<Detail>;
  fallback: (item: Item) => Detail;
  reload: () => Promise<void>;
  shell: DetailErrorReporting;
  action: string;
}) {
  const [detail, setDetail] = useState<Detail | null>(initialDetail ?? null);

  const open = async (item: Item) => {
    setDetail(null);
    try {
      setDetail(await load(item));
    } catch (error) {
      shell.reportOperationError(action, error);
      setDetail(fallback(item));
    }
  };

  // `run` returns the updated item from the server; undefined keeps the current one.
  const mutate = async (mutationAction: string, run: (current: Detail) => Promise<Detail | undefined>) => {
    if (!detail) return false;
    shell.clearOperationError();
    try {
      const next = await run(detail);
      if (next !== undefined) setDetail(next);
      await reload();
      return true;
    } catch (error) {
      shell.reportOperationError(mutationAction, error);
      return false;
    }
  };

  return { detail, setDetail, open, mutate, close: () => setDetail(null) };
}
