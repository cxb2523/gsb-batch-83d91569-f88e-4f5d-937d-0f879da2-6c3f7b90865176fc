import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AppShell, type AppState } from "../../apps/frontend/src/App";
import type { CompletedGameDetail, ReleaseDetail } from "../../shared/types";
import { fakeApiClient } from "./fakeApiClient";

const idle = { status: "idle" as const, added: 0, repaired: 0, skipped: 0, failed: 0 };
let cleanup: (() => Promise<void>) | null = null;
afterEach(async () => {
  await cleanup?.();
  cleanup = null;
  vi.unstubAllGlobals();
});

async function open(initialState: AppState) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", { url: "http://127.0.0.1:4000" });
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  const root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(<AppShell apiBaseUrl="http://127.0.0.1:4000" api={fakeApiClient()} initialState={initialState} />));
  cleanup = async () => { await act(async () => root.unmount()); dom.window.close(); };
  return dom.window.document;
}

const completed: CompletedGameDetail = {
  id: "nier", title: "NieR Replicant", normalizedTitle: "nier replicant", userPlatform: "PC", completionPrecision: "exact", genres: [], igdbGenres: [], platforms: [],
  coverImageId: "co2vvt", matchStatus: "matched", extra: {}, igdbPlatforms: [], igdbThemes: [], igdbGameModes: [],
  screenshots: [{ imageId: "shot1", source: "artwork" }]
};

const release = {
  id: "p4", title: "Persona 4 Revival", dateText: "2027", releaseDate: "2027-01-01", datePrecision: "Year", effectiveSortDate: "2027-01-01", category: "Main",
  publishers: [], developers: [], platforms: ["PC"], genres: [], sourceConfidence: 80,
  artworks: [{ imageId: "sc9", source: "artwork" }, { imageId: "co9p4", source: "cover" }],
  sources: [], igdbUrl: null, screenshots: [], trailers: []
} as unknown as ReleaseDetail;

const backdropImage = (document: Document) => document.querySelector(".backdrop__img--current")?.getAttribute("src");

describe("detail pages sit in their game's cover", () => {
  test("a completed game's page is backed by its cover from the local cover cache, not its first screenshot", async () => {
    const document = await open({ status: "ready", releases: [], syncStatus: idle, initialView: "completed-detail", initialCompletedDetail: completed });
    expect(backdropImage(document)).toBe("http://127.0.0.1:4000/api/covers/co2vvt");
    expect(document.querySelector(".cover-scene .detail-view")).not.toBeNull();
  });

  test("an upcoming release's page is backed by its cover too", async () => {
    const document = await open({ status: "ready", releases: [], syncStatus: idle, initialView: "detail", initialDetail: release });
    expect(backdropImage(document)).toBe("http://127.0.0.1:4000/api/covers/co9p4");
    expect(document.querySelector(".backdrop")?.classList.contains("backdrop--blur-heavy")).toBe(true);
  });
});
