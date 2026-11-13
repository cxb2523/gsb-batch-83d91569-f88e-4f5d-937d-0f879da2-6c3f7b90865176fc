import { sqliteUtcMs } from "../../../../shared/sqliteTime";
import type { ReleaseDateChange } from "../../../../shared/types";

// Words for a date change a sync recorded. A delay or a move up is news on the list; a date being
// announced (a vague date made exact) only shows in the game's date history.
export function dateChangeLabel(change: ReleaseDateChange) {
  if (change.kind === "delayed") return `Delayed from ${change.fromText}`;
  if (change.kind === "earlier") return `Moved up from ${change.fromText}`;
  return `Date announced (was ${change.fromText})`;
}

export function listDateBadge(change: ReleaseDateChange | null | undefined) {
  if (!change || change.kind === "announced") return null;
  return { label: dateChangeLabel(change), kind: change.kind };
}

// "2026-11-06 20:21:10" (SQLite, UTC) as "Nov 6, 2026".
export function changeDay(changedAt: string) {
  const date = new Date(sqliteUtcMs(changedAt));
  return Number.isNaN(date.getTime()) ? changedAt : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}
