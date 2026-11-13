import type { ReleaseListItem } from "../../../shared/types";
import { monthYearLabel } from "./monthLabel";

export function groupReleases(items: ReleaseListItem[]) {
  const groups = new Map<string, ReleaseListItem[]>();
  for (const item of [...items].sort((a, b) => `${a.effectiveSortDate ?? "9999-12-31"}${a.title}`.localeCompare(`${b.effectiveSortDate ?? "9999-12-31"}${b.title}`))) {
    const heading = headingFor(item);
    groups.set(heading, [...(groups.get(heading) ?? []), item]);
  }
  return [...groups.entries()].map(([heading, groupItems]) => ({ heading, items: groupItems }));
}

function headingFor(item: ReleaseListItem) {
  if (item.datePrecision === "Window") return item.releaseWindow || item.dateText;
  if (item.datePrecision === "Year") return item.dateText;
  const [year, month] = (item.releaseDate ?? "").split("-").map(Number);
  if (year && month) return monthYearLabel(year, month);
  return item.dateText;
}
