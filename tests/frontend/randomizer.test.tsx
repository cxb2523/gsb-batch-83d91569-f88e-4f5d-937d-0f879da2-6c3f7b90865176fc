import React, { act } from "react";
import { afterEach, describe, expect, test, vi } from "vitest";
import { renderToString } from "react-dom/server";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import type { RandomizerOptions, RandomizerSpinResponse } from "../../shared/types";
import { AppShell } from "../../apps/frontend/src/App";
import { RandomizerView } from "../../apps/frontend/src/views/RandomizerView";
import type { RandomizerWorkflow } from "../../apps/frontend/src/useRandomizerWorkflow";
import { fakeApiClient } from "./fakeApiClient";

const pickResponse: RandomizerSpinResponse = {
  pick: {
    igdbId: 1942,
    title: "The Witcher 3: Wild Hunt",
    url: "https://www.igdb.com/games/the-witcher-3-wild-hunt",
    coverImageId: "co1wyy",
    releaseYear: 2015,
    genres: ["RPG"],
    themes: ["Fantasy"],
    gameModes: ["Single player"],
    platforms: ["PC", "PS4"],
    totalRating: 93,
    totalRatingCount: 3000,
    summary: "Geralt hunts monsters."
  },
  reels: [{ title: "Hades", coverImageId: "hades" }],
  poolSize: 4200,
  repeatAllowed: false
};

const optionsFixture: RandomizerOptions = {
  genres: [{ id: 12, name: "RPG" }],
  themes: [],
  gameModes: [],
  perspectives: [],
  platforms: [
    { id: 6, name: "PC", family: "PC" },
    { id: 48, name: "PlayStation 4", family: "PlayStation" },
    { id: 167, name: "PlayStation 5", family: "PlayStation" },
    { id: 130, name: "Switch", family: "Nintendo" }
  ],
  tags: [{ id: 477, name: "Metroidvania" }]
};

function viewWorkflow(overrides: Partial<RandomizerWorkflow> = {}): RandomizerWorkflow {
  return {
    filters: {}, options: null, optionsStatus: "ready", missingCredentials: false,
    phase: "ready", result: null, reel: [], history: [], labels: {},
    actions: {
      setFilters: () => undefined,
      resetFilters: () => undefined,
      spin: async () => undefined,
      clearHistory: async () => undefined,
      searchTags: async () => [],
      searchSeries: async () => [],
      searchGames: async () => [],
      rememberLabel: () => undefined,
      moreLikeThis: () => undefined
    },
    ...overrides
  };
}

const renderView = (overrides: Partial<RandomizerWorkflow> = {}) =>
  <RandomizerView workflow={viewWorkflow(overrides)} onOpenSettings={() => undefined} />;

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
    values
  };
}

let cleanups: Array<() => Promise<void>> = [];

afterEach(async () => {
  for (const cleanup of cleanups) await cleanup();
  cleanups = [];
  vi.unstubAllGlobals();
});

let lastRoot: ReturnType<typeof createRoot> | null = null;
// Renders new props into the last rendered app, as a parent re-render would.
const rerender = (element: React.ReactElement) => lastRoot!.render(element);

async function renderApp(element: React.ReactElement) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", { url: "http://127.0.0.1" });
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  // Reduced motion skips the reel delay.
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
  // React loaded before this DOM existed, so it watches typing through its old IE fallback, which
  // calls attachEvent/detachEvent on the focused input. jsdom has neither.
  Object.assign(dom.window.HTMLElement.prototype, { attachEvent: () => undefined, detachEvent: () => undefined });
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  lastRoot = root;
  await act(async () => root.render(element));
  cleanups.push(async () => {
    await act(async () => root.unmount());
    dom.window.close();
  });
  return container;
}

// React loads under the node test environment, so it tracks typing through its focus/keyup fallback.
async function typeInto(input: HTMLInputElement, value: string) {
  await act(async () => {
    input.focus();
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
    input.dispatchEvent(new window.KeyboardEvent("keyup", { bubbles: true }));
  });
}

const button = (container: Element, text: string) => {
  const found = [...container.querySelectorAll("button")].find(item => item.textContent === text);
  if (!found) throw new Error(`Button not found: ${text}`);
  return found as HTMLButtonElement;
};

describe("Randomizer view", () => {
  test("renders the pick card", () => {
    const html = renderToString(renderView({ result: pickResponse }));

    expect(html).toContain("The Witcher 3: Wild Hunt");
    expect(html).toContain("https://images.igdb.com/igdb/image/upload/t_cover_big/co1wyy.jpg");
    expect(html).toContain("2015 · RPG · PC, PS4");
    expect(html.replace(/<!-- -->/g, "")).toContain("IGDB 93<small> from 3,000 ratings</small>");
    expect(html).toContain("Geralt hunts monsters.");
    expect(html).toContain("View on IGDB");
    expect(html).toContain("Spin again");
  });

  test("a landing spin slows the reel to a stop on the pick, then the card grows out of it", async () => {
    vi.useFakeTimers();
    const container = await renderApp(renderView({ phase: "spinning", reel: pickResponse.reels }));
    // Motion on: a frame loop and no reduced-motion preference.
    Object.assign(window, { requestAnimationFrame: (callback: () => void) => setTimeout(callback, 16), cancelAnimationFrame: (id: number) => clearTimeout(id) });
    vi.stubGlobal("matchMedia", () => ({ matches: false }));
    const reel = [...pickResponse.reels, { title: pickResponse.pick!.title, coverImageId: pickResponse.pick!.coverImageId }];
    await act(async () => rerender(renderView({ phase: "ready", result: pickResponse, reel })));

    const pickTile = container.querySelector(".randomizer-reel--landing .randomizer-reel__tile.is-pick img");
    expect(pickTile?.getAttribute("src")).toContain(pickResponse.pick!.coverImageId!);
    expect(container.querySelector(".randomizer-pick")).toBeNull();
    expect(container.querySelector(".randomizer-spin")?.textContent).toBe("Spinning...");

    await act(async () => { vi.advanceTimersByTime(2300); });
    expect(container.querySelector(".randomizer-reel__tile.is-landed")).not.toBeNull();
    await act(async () => { vi.advanceTimersByTime(700); });
    expect(container.querySelector(".randomizer-pick.randomizer-pick--landed h2")?.textContent).toBe(pickResponse.pick!.title);
  });

  test("renders the empty-pool reason instead of an error", () => {
    const html = renderToString(renderView({ result: { pick: null, reels: [], poolSize: 0, repeatAllowed: false, reason: "No released Horror games on PlayStation 5, rated 90+ with 50+ ratings." } }));

    expect(html).toContain("No released Horror games on PlayStation 5, rated 90+ with 50+ ratings.");
    expect(html).not.toContain("randomizer-pick__cover");
  });

  test("points to Settings when IGDB credentials are missing", () => {
    const html = renderToString(renderView({ result: null, missingCredentials: true }));

    expect(html).toContain("IGDB credentials are required for the randomizer.");
    expect(html).toContain("Open Settings");
  });
});

describe("Randomizer workflow in the app", () => {
  test("the nav opens the Randomizer, a spin shows the pick and refreshes recent picks", async () => {
    vi.stubGlobal("localStorage", memoryStorage());
    const api = fakeApiClient({
      randomizerOptions: async () => optionsFixture,
      spinRandomizer: async () => pickResponse
    });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} />);

    await act(async () => button(container, "Randomizer").click());
    expect(api.randomizerOptions).toHaveBeenCalledTimes(1);
    expect(api.randomizerHistory).toHaveBeenCalledTimes(1);

    api.randomizerHistory.mockResolvedValue({ items: [{ id: 1, igdbId: 1942, title: "The Witcher 3: Wild Hunt", coverImageId: "co1wyy", pickedAt: "2026-09-24 12:00:00" }] });
    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith({ includeRemakes: true, hideCompleted: true, hideUpcoming: false, minRatingCount: 5 });
    expect(container.querySelector(".randomizer-pick h2")?.textContent).toBe("The Witcher 3: Wild Hunt");
    expect(container.querySelector(".randomizer-recent")?.textContent).toContain("The Witcher 3: Wild Hunt");
  });

  test("chosen filters are sent with the spin and remembered", async () => {
    const storage = memoryStorage();
    vi.stubGlobal("localStorage", storage);
    const api = fakeApiClient({
      randomizerOptions: async () => optionsFixture
    });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    const select = container.querySelector("select[aria-label='Add genres']") as HTMLSelectElement;
    await act(async () => {
      select.value = "12";
      select.dispatchEvent(new window.Event("change", { bubbles: true }));
    });
    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith(expect.objectContaining({ genreIds: [12] }));
    expect(JSON.parse(storage.values.get("grt.randomizer.filters")!)).toMatchObject({ genreIds: [12] });
    expect(container.textContent).toContain("No released games.");
  });

  test("quick picks and platform families are sent with the spin", async () => {
    vi.stubGlobal("localStorage", memoryStorage());
    const api = fakeApiClient({ randomizerOptions: async () => optionsFixture });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    await act(async () => button(container, "JRPG").click());
    await act(async () => button(container, "Made in Japan").click());
    await act(async () => button(container, "All PlayStation").click());
    await act(async () => button(container, "Switch").click());
    expect(button(container, "JRPG").getAttribute("aria-pressed")).toBe("true");
    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith(expect.objectContaining({ presets: ["jrpg"], madeInJapan: true, platformIds: [48, 167, 130] }));

    await act(async () => button(container, "All PlayStation").click());
    await act(async () => button(container, "Made in Japan").click());
    await act(async () => button(container, "Spin").click());
    expect(api.spinRandomizer).toHaveBeenLastCalledWith(expect.objectContaining({ platformIds: [130], madeInJapan: undefined }));
  });

  test("a searched tag is added, sent as all-of tags and keeps its name after a restart", async () => {
    const storage = memoryStorage();
    vi.stubGlobal("localStorage", storage);
    const api = fakeApiClient({
      randomizerOptions: async () => optionsFixture,
      searchRandomizerTags: async () => ({ items: [{ id: 17326, name: "soulslike" }] })
    });
    const initialState = { status: "ready" as const, releases: [], syncStatus: { status: "idle" as const, added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" as const };
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={initialState} />);

    const input = container.querySelector("input[aria-label='Search tags']") as HTMLInputElement;
    await typeInto(input, "souls");
    await act(async () => input.form!.requestSubmit());
    expect(api.searchRandomizerTags).toHaveBeenCalledWith("souls");
    await act(async () => button(container, "+ soulslike").click());
    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith(expect.objectContaining({ tagIds: [17326] }));
    expect(JSON.parse(storage.values.get("grt.randomizer.labels")!)).toEqual({ "tag:17326": "soulslike" });

    const again = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={initialState} />);
    expect(again.querySelector("button[aria-label='Remove soulslike']")).not.toBeNull();
  });

  test("saved platforms that are no longer offered are dropped", async () => {
    const storage = memoryStorage({ "grt.randomizer.filters": JSON.stringify({ platformIds: [34, 167] }) });
    vi.stubGlobal("localStorage", storage);
    const api = fakeApiClient({ randomizerOptions: async () => optionsFixture });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith(expect.objectContaining({ platformIds: [167] }));
    expect(JSON.parse(storage.values.get("grt.randomizer.filters")!).platformIds).toEqual([167]);
  });

  test("More like this spins among similar games and shows the seed in the filters", async () => {
    vi.stubGlobal("localStorage", memoryStorage());
    const api = fakeApiClient({ randomizerOptions: async () => optionsFixture, spinRandomizer: async () => pickResponse });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    await act(async () => button(container, "Spin").click());
    await act(async () => button(container, "More like this").click());

    expect(api.spinRandomizer).toHaveBeenLastCalledWith(expect.objectContaining({ similarToId: 1942, similarToTitle: "The Witcher 3: Wild Hunt" }));
    expect(container.querySelector("button[aria-label='Remove The Witcher 3: Wild Hunt']")).not.toBeNull();

    await act(async () => (container.querySelector("button[aria-label='Remove The Witcher 3: Wild Hunt']") as HTMLButtonElement).click());
    await act(async () => button(container, "Spin again").click());
    expect(api.spinRandomizer).toHaveBeenLastCalledWith(expect.objectContaining({ similarToId: undefined }));
  });

  test("a series found by search and include unrated are sent with the spin", async () => {
    vi.stubGlobal("localStorage", memoryStorage());
    const api = fakeApiClient({
      randomizerOptions: async () => optionsFixture,
      searchRandomizerSeries: async () => ({ items: [{ kind: "franchise", id: 4, name: "Final Fantasy" }, { kind: "collection", id: 67, name: "Final Fantasy Crystal Chronicles" }] })
    });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    const input = container.querySelector("input[aria-label='Search series']") as HTMLInputElement;
    await typeInto(input, "final");
    await act(async () => input.form!.requestSubmit());
    await act(async () => button(container, "+ Final Fantasy · franchise").click());
    await act(async () => button(container, "+ Final Fantasy Crystal Chronicles · series").click());
    const unrated = [...container.querySelectorAll("label")].find(label => label.textContent?.includes("Include unrated games"))!.querySelector("input")!;
    await act(async () => unrated.click());
    await act(async () => button(container, "Spin").click());

    expect(api.spinRandomizer).toHaveBeenCalledWith(expect.objectContaining({ franchiseIds: [4], collectionIds: [67], includeUnrated: true }));
    expect(container.querySelector("button[aria-label='Remove Final Fantasy']")).not.toBeNull();
  });

  test("missing credentials show the Settings hint instead of an error banner", async () => {
    const api = fakeApiClient({
      randomizerOptions: async () => { throw new Error("409 Conflict: IGDB credentials are required for the randomizer"); }
    });
    const container = await renderApp(<AppShell apiBaseUrl="http://unused" api={api} initialState={{ status: "ready", releases: [], syncStatus: { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 }, initialView: "randomizer" }} />);

    expect(container.textContent).toContain("IGDB credentials are required for the randomizer.");
    expect(container.querySelector(".operation-error")).toBeNull();
    expect(button(container, "Spin").disabled).toBe(true);

    await act(async () => button(container, "Open Settings").click());
    expect(button(container, "Settings").className).toBe("active");
  });
});
