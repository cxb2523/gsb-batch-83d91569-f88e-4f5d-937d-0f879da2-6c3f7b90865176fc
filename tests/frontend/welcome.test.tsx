// @vitest-environment jsdom
import { afterEach, describe, expect, test } from "vitest";
import { AppShell } from "../../apps/frontend/src/App";
import type { ReleaseListItem } from "../../shared/types";
import { fakeApiClient } from "./fakeApiClient";
import { click, getButton, renderInteractive } from "./domHarness";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  while (cleanups.length) await cleanups.pop()!();
});

const sampleRelease = {
  id: "demo-1", title: "Sample Quest", normalizedTitle: "sample quest", dateText: "2027", releaseDate: "2027-01-01", datePrecision: "Year",
  releaseWindow: null, category: "Main", publishers: ["Sample Co"], developers: [], platforms: ["PC"], genres: [], artworks: [],
  eligible: true, eligibilityReason: null, effectiveSortDate: "2027-01-01", hidden: false, watched: false, released: false, sourceConfidence: 90
} as unknown as ReleaseListItem;

async function openApp() {
  let loaded = false;
  const api = fakeApiClient({
    getDemo: async () => ({ loaded }),
    loadDemo: async () => { loaded = true; return { loaded, releases: 1, completedGames: 0 }; },
    removeDemo: async () => { loaded = false; return { loaded }; },
    listReleases: async () => (loaded ? { items: [sampleRelease], truncated: false, total: 1 } : { items: [], truncated: false, total: 0 })
  });
  const view = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={api} />);
  cleanups.push(view.cleanup);
  return { ...view, api };
}

describe("first run", () => {
  test("an empty library offers the sample library, which fills Upcoming and can be removed again", async () => {
    const { container, api } = await openApp();
    expect(container.querySelector(".welcome")?.textContent).toContain("Try it with sample data");

    await click(getButton(container, "Try it with sample data"));
    expect(api.loadDemo).toHaveBeenCalledTimes(1);
    expect(container.textContent).toContain("Sample Quest");
    expect(container.querySelector(".welcome")).toBeNull();
    expect(container.querySelector(".sample-banner")?.textContent).toContain("sample library");

    await click(getButton(container, "Remove sample data"));
    expect(api.removeDemo).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain("Sample Quest");
    expect(container.querySelector(".sample-banner")).toBeNull();
  });

  test("setting up your own library opens Settings on the API keys", async () => {
    const { container } = await openApp();

    await click(getButton(container, "Set up my own"));

    expect(container.querySelector(".settings-view")).not.toBeNull();
    expect(container.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe("API keys");
  });
});
