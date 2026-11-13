import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, test, vi } from "vitest";
import { getPalette } from "../../apps/frontend/src/theme/palettes";
import { ThemeMenu } from "../../apps/frontend/src/ui/ThemeMenu";

let dom: JSDOM | null = null;

afterEach(() => {
  dom?.window.close();
  dom = null;
  vi.unstubAllGlobals();
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
});

describe("topbar theme menu", () => {
  test("opens a grouped list, marks the active theme, and closes after choosing", async () => {
    dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://127.0.0.1" });
    vi.stubGlobal("window", dom.window);
    vi.stubGlobal("document", dom.window.document);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const setPaletteId = vi.fn();
    const root = createRoot(dom.window.document.getElementById("root")!);
    await act(async () => root.render(<ThemeMenu palette={getPalette("abyss-gold")} setPaletteId={setPaletteId} />));

    const trigger = dom.window.document.querySelector<HTMLButtonElement>(".theme-menu__trigger")!;
    expect(trigger.getAttribute("aria-label")).toBe("Theme: Abyss Gold");
    await act(async () => trigger.click());

    const options = [...dom.window.document.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')];
    expect(options).toHaveLength(12);
    expect(options.filter(o => o.getAttribute("aria-checked") === "true").map(o => o.textContent)).toEqual(["Abyss Gold◆"]);

    await act(async () => options.find(o => o.textContent?.startsWith("Rose Noir"))!.click());
    expect(setPaletteId).toHaveBeenCalledWith("rose-noir");
    expect(dom.window.document.querySelector('[role="menu"]')).toBeNull();
    await act(async () => root.unmount());
  });
});
