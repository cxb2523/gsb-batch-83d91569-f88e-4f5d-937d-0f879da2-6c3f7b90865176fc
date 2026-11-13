import type { Dialogs } from "./appShell";

export type DeletionResult =
  | { status: "deleted"; deletedIds: string[] }
  | { status: "cancelled"; deletedIds: string[] }
  | { status: "failed"; deletedIds: string[]; error: string };

interface DeletionRequest<Item extends { id: string; title: string }> {
  // "single" is a detail-page delete; "bulk" is a delete of the selected list items.
  scope: "single" | "bulk";
  // The diagnostics action name, e.g. "delete", "delete-block", "bulk-delete".
  action: string;
  confirmMessage: string;
  deleteOne: (item: Item) => Promise<unknown>;
  dialogs: Pick<Dialogs, "confirm" | "alert">;
  log?: (event: string, details: Record<string, unknown>) => void;
}

// Every delete in both collections: confirm once, delete one item at a time, log each step, and report
// a failure through an alert. The result says which items are gone, so a partial failure can be pruned.
export async function confirmAndDelete<Item extends { id: string; title: string }>(
  items: Item[],
  { scope, action, confirmMessage, deleteOne, dialogs, log = () => undefined }: DeletionRequest<Item>
): Promise<DeletionResult> {
  if (items.length === 0) return { status: "cancelled", deletedIds: [] };
  const details = scope === "single"
    ? { action, id: items[0].id, title: items[0].title }
    : { action, count: items.length, ids: items.map(item => item.id) };
  const outcomeEvent = scope === "single" ? "ui.delete" : "ui.bulk-delete";

  log("ui.click", details);
  if (!dialogs.confirm(confirmMessage)) {
    log("ui.confirm.cancelled", details);
    return { status: "cancelled", deletedIds: [] };
  }
  log("ui.confirm.accepted", details);

  const deletedIds: string[] = [];
  try {
    for (const item of items) {
      await deleteOne(item);
      deletedIds.push(item.id);
    }
    log(`${outcomeEvent}.succeeded`, details);
    return { status: "deleted", deletedIds };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    log(`${outcomeEvent}.failed`, { ...details, error: message });
    dialogs.alert(`${scope === "single" ? "Delete" : "Bulk delete"} failed: ${message}`);
    return { status: "failed", deletedIds, error: message };
  }
}
