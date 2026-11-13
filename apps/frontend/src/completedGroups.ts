import type { CompletedGameListItem } from "../../../shared/types";
import { monthYearLabel } from "./monthLabel";

export interface CompletedGameGroup {
  heading: string;
  key: string;
  items: CompletedGameListItem[];
}

export function groupCompletedGames(items: CompletedGameListItem[]): CompletedGameGroup[] {
  const dated = new Map<string, CompletedGameListItem[]>();
  const undated: CompletedGameListItem[] = [];
  for (const item of items) {
    if (item.completionMonth && (item.completionPrecision === "exact" || item.completionPrecision === "month")) {
      const list = dated.get(item.completionMonth) ?? [];
      list.push(item);
      dated.set(item.completionMonth, list);
    } else {
      undated.push(item);
    }
  }
  const groups = [...dated.entries()]
    .sort(([left], [right]) => right.localeCompare(left))
    .map(([month, groupItems]) => ({ key: month, heading: formatMonth(month), items: groupItems }));
  if (undated.length > 0) groups.push({ key: "undated", heading: "Undated Completed Games", items: undated });
  return groups;
}

function formatMonth(month: string) {
  const [year, monthNumber] = month.split("-").map(Number);
  if (!year || !monthNumber) return month;
  return monthYearLabel(year, monthNumber);
}
