import { describe, expect, it } from "vitest";
import type { ReleaseListItem } from "../../shared/types";
import { bannerLabel, daysUntil, rowSubLine, rowWhenLabel, stripCurrentYear } from "../../apps/frontend/src/ui/countdown";

const today = new Date(2026, 8, 23, 17, 40);
function item(date: string, precision: ReleaseListItem["datePrecision"] = "Exact"): ReleaseListItem {
  return { id: date, title: "Game", dateText: "Autumn 2026", releaseDate: date, datePrecision: precision, category: "Main", publishers: [], developers: [], platforms: [], genres: [], sourceConfidence: 1, artworks: [] };
}
describe("calendar day labels", () => {
  it.each([
    ["2026-09-22", "released", "Released", "Tue 22"],
    ["2026-09-23", "today", "Out today", "Wed 23"],
    ["2026-09-24", "tomorrow", "Arrives tomorrow", "Thu 24"],
    ["2026-09-29", "6 days", "Arrives in 6 days", "Tue 29"]
  ])("%s", (date, row, banner, sub) => {
    expect(rowWhenLabel(item(date), today)).toBe(row);
    expect(bannerLabel(item(date), today)).toBe(banner);
    expect(rowSubLine(item(date))).toBe(sub);
  });
  it("uses date text and category for non-exact releases", () => {
    const release = item("2026-10-01", "Window");
    expect(rowWhenLabel(release, today)).toBe("Autumn 2026");
    expect(rowSubLine(release)).toBe("Main");
    expect(bannerLabel(release, today)).toBe("Arrives Autumn 2026");
  });
  it("compares calendar days and trims only current year", () => {
    expect(daysUntil("2026-09-24", today)).toBe(1);
    expect(stripCurrentYear("September 2026", today)).toBe("September");
    expect(stripCurrentYear("January 2027", today)).toBe("January 2027");
  });
});
