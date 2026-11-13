import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, test, vi } from "vitest";
import { AppShell } from "../../apps/frontend/src/App";
import type { ApiClient } from "../../apps/frontend/src/api/client";
import { fakeApiClient } from "./fakeApiClient";

const readyState = { status: "ready" as const, releases: [], syncStatus: { status: "idle" as const, added: 0, repaired: 0, skipped: 0, failed: 0 } };

let cleanup: (() => Promise<void>) | null = null;
afterEach(async () => {
  await cleanup?.();
  cleanup = null;
  vi.unstubAllGlobals();
});

async function openApp(overrides: Partial<ApiClient>, stored?: string) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><div id=\"root\"></div>", { url: "http://127.0.0.1:51234" });
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  vi.stubGlobal("localStorage", dom.window.localStorage);
  if (stored) dom.window.localStorage.setItem("grt.palette", stored);
  const api = fakeApiClient(overrides);
  const root = createRoot(dom.window.document.getElementById("root")!);
  await act(async () => root.render(<AppShell apiBaseUrl="http://unused" api={api} initialState={readyState} />));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 0)); });
  cleanup = async () => { await act(async () => root.unmount()); dom.window.close(); };
  const trigger = () => dom.window.document.querySelector<HTMLButtonElement>(".theme-menu__trigger")!;
  return { api, dom, trigger };
}

describe("the chosen palette", () => {
  test("comes back from app data on launch, even when localStorage is empty", async () => {
    const { dom, trigger } = await openApp({ getPreferences: async () => ({ palette: "rose-noir", themeAutoplay: false }) });
    expect(trigger().getAttribute("aria-label")).toBe("Theme: Rose Noir");
    expect(dom.window.document.documentElement.dataset.theme).toBe("rose-noir");
  });

  test("is saved to app data when chosen", async () => {
    const { api, dom, trigger } = await openApp({});
    await act(async () => trigger().click());
    const nightshade = [...dom.window.document.querySelectorAll<HTMLButtonElement>("[role='menuitemradio']")].find(option => option.textContent?.startsWith("Nightshade"))!;
    await act(async () => nightshade.click());
    expect(api.savePalette).toHaveBeenCalledWith("nightshade");
    expect(trigger().getAttribute("aria-label")).toBe("Theme: Nightshade");
  });

  test("a palette only this browser remembered is carried into app data once", async () => {
    const { api, trigger } = await openApp({}, "black-pine");
    expect(trigger().getAttribute("aria-label")).toBe("Theme: Black Pine");
    expect(api.savePalette).toHaveBeenCalledWith("black-pine");
  });
});
