// @vitest-environment jsdom
import { afterEach, describe, expect, test } from "vitest";
import { AppShell } from "../../apps/frontend/src/App";
import type { ReleaseDetail, ReleaseListItem } from "../../shared/types";
import { fakeApiClient } from "./fakeApiClient";
import { click, getButton, renderInteractive } from "./domHarness";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  while (cleanups.length) await cleanups.pop()!();
});

const release = (id: string, title: string, watched = false) => ({
  id, title, normalizedTitle: title.toLowerCase(), dateText: "2027", releaseDate: "2027-01-01", datePrecision: "Year",
  releaseWindow: null, category: "Main", publishers: ["Sample Co"], developers: [], platforms: ["PC"], genres: [], artworks: [],
  eligible: true, eligibilityReason: null, effectiveSortDate: "2027-01-01", hidden: false, watched, released: false, sourceConfidence: 90
}) as unknown as ReleaseListItem;

async function openApp() {
  const items = [release("a", "Alpha Quest"), release("b", "Beta Saga")];
  const api = fakeApiClient({
    listReleases: async params => {
      const shown = params?.watchedOnly ? items.filter(item => item.watched) : items;
      return { items: shown.map(item => ({ ...item })), truncated: false, total: shown.length };
    },
    getDemo: async () => ({ loaded: true }),
    patchRelease: async (id, payload) => {
      const item = items.find(entry => entry.id === id)!;
      item.watched = Boolean(payload.watched);
      return { ok: true, item: { ...item, sources: [], igdbUrl: null, screenshots: [], trailers: [] } as unknown as ReleaseDetail };
    }
  });
  const view = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
  cleanups.push(view.cleanup);
  return { ...view, api };
}

const rowTitles = (container: Element) => [...container.querySelectorAll(".release-row strong")].map(node => node.textContent);

describe("watchlist", () => {
  test("Watch on the featured game saves it, stars its row, and Watched only lists just that game", async () => {
    const { container, api } = await openApp();
    expect(rowTitles(container)).toEqual(["Alpha Quest", "Beta Saga"]);

    await click(getButton(container, "☆ Watch"));
    expect(api.patchRelease).toHaveBeenCalledWith("a", { watched: true });
    expect(rowTitles(container)).toEqual(["★ Alpha Quest", "Beta Saga"]);
    expect(getButton(container, "★ Watching").getAttribute("aria-pressed")).toBe("true");

    await click(getButton(container, "More filters"));
    const watchedOnly = [...container.querySelectorAll("label")].find(label => label.textContent?.includes("Watched only"))!.querySelector("input")!;
    await click(watchedOnly);
    await new Promise(resolve => setTimeout(resolve, 0));
    expect(rowTitles(container)).toEqual(["★ Alpha Quest"]);

    await click(getButton(container, "★ Watching"));
    expect(api.patchRelease).toHaveBeenLastCalledWith("a", { watched: false });
  });
});

describe("date changes on the list", () => {
  test("a delayed game says so on its row and the featured panel; an announced date stays off the list", async () => {
    const delayed = { ...release("d", "Delta Run"), lastDateChange: { kind: "delayed", fromText: "Mar 14, 2027", toText: "Jun 2, 2027", changedAt: "2026-11-01 10:00:00" } } as ReleaseListItem;
    const announced = { ...release("e", "Echo Tale"), lastDateChange: { kind: "announced", fromText: "2027", toText: "Mar 3, 2027", changedAt: "2026-11-01 10:00:00" } } as ReleaseListItem;
    const api = fakeApiClient({ getDemo: async () => ({ loaded: true }), listReleases: async () => ({ items: [delayed, announced], truncated: false, total: 2 }) });
    const view = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
    cleanups.push(view.cleanup);

    const badges = [...view.container.querySelectorAll(".date-badge")].map(node => node.textContent);
    expect(badges).toEqual(["Delayed from Mar 14, 2027", "Delayed from Mar 14, 2027"]);
  });
});
