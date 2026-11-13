import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, test, vi } from "vitest";
import type { AppView } from "../../apps/frontend/src/appShell";
import { JSDOM } from "jsdom";
import { useCollectionWorkspace, type CollectionWorkspace } from "../../apps/frontend/src/collectionWorkspace";
import { confirmAndDelete } from "../../apps/frontend/src/collectionDeletion";

interface Game { id: string; title: string; genres: string[] }
interface Filters { search: string; platform: string }

let dom: JSDOM | null = null;

afterEach(() => {
  dom?.window.close();
  dom = null;
  delete (globalThis as { window?: Window }).window;
  delete (globalThis as { document?: Document }).document;
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
});

const games: Game[] = [
  { id: "a", title: "Alpha", genres: ["RPG"] },
  { id: "b", title: "Beta", genres: ["Shooter"] },
  { id: "c", title: "Gamma", genres: ["RPG", "Adventure"] }
];

describe("collection workspace", () => {
  test("setting a filter reloads with the merged filters", async () => {
    const load = vi.fn(async () => undefined);
    const probe = renderWorkspace({ load });

    await act(async () => probe.current.setFilter("platform", "PC"));

    expect(load).toHaveBeenCalledWith({ search: "", platform: "PC" });
    expect(probe.current.filters).toEqual({ search: "", platform: "PC" });
  });

  test("genre narrows visible items and select-all only picks visible ones", () => {
    const probe = renderWorkspace({});

    act(() => probe.current.setGenre("RPG"));
    expect(probe.current.genres).toEqual(["Adventure", "RPG", "Shooter"]);
    expect(probe.current.visibleItems.map(item => item.id)).toEqual(["a", "c"]);

    act(() => probe.current.selectAllVisible());
    expect([...probe.current.selectedIds]).toEqual(["a", "c"]);
    expect(probe.current.selectedVisibleCount).toBe(2);
  });

  test("Ctrl+A selects all visible items only while the collection is active", () => {
    const probe = renderWorkspace({ view: "settings" });
    const pressCtrlA = () => act(() => {
      dom!.window.document.dispatchEvent(new dom!.window.KeyboardEvent("keydown", { key: "a", ctrlKey: true, bubbles: true }));
    });

    pressCtrlA();
    expect(probe.current.selectedVisibleCount).toBe(0);

    act(() => probe.current.navigate("gallery"));
    pressCtrlA();
    expect(probe.current.selectedVisibleCount).toBe(3);
  });

  test("a partial bulk delete keeps the failed items selected and reloads", async () => {
    const load = vi.fn(async () => undefined);
    const probe = renderWorkspace({ load });
    act(() => probe.current.selectAllVisible());
    load.mockClear();

    const alert = vi.fn();
    const deleteOne = vi.fn(async (game: Game) => {
      if (game.id === "b") throw new Error("locked");
    });
    await act(async () => {
      await probe.current.deleteSelected(selected => confirmAndDelete(selected, { scope: "bulk", action: "bulk-delete", confirmMessage: "Delete?", deleteOne, dialogs: { confirm: () => true, alert } }));
    });

    expect(alert).toHaveBeenCalledWith("Bulk delete failed: locked");
    expect([...probe.current.selectedIds].sort()).toEqual(["b", "c"]);
    expect(load).toHaveBeenCalledTimes(1);
  });

  test("returning from a detail page goes back to the list view it was opened from", () => {
    const probe = renderWorkspace({ view: "calendar" });

    act(() => {
      probe.current.rememberReturnPosition("b");
      probe.current.navigate("detail");
    });
    act(() => probe.current.returnToList());

    expect(probe.current.view).toBe("calendar");
  });

  test("leaving the detail page for another view forgets the return position", () => {
    const probe = renderWorkspace({ view: "calendar" });

    act(() => {
      probe.current.rememberReturnPosition("b");
      probe.current.navigate("detail");
    });
    act(() => probe.current.navigate("settings"));
    act(() => probe.current.navigate("detail"));
    act(() => probe.current.returnToList());

    expect(probe.current.view).toBe("gallery");
  });

  test("a cancelled bulk delete changes nothing", async () => {
    const load = vi.fn(async () => undefined);
    const probe = renderWorkspace({ load });
    act(() => probe.current.selectAllVisible());
    load.mockClear();
    const deleteOne = vi.fn(async () => undefined);

    await act(async () => {
      await probe.current.deleteSelected(selected => confirmAndDelete(selected, { scope: "bulk", action: "bulk-delete", confirmMessage: "Delete?", deleteOne, dialogs: { confirm: () => false, alert: vi.fn() } }));
    });

    expect(deleteOne).not.toHaveBeenCalled();
    expect(probe.current.selectedVisibleCount).toBe(3);
    expect(load).not.toHaveBeenCalled();
  });
});

function renderWorkspace(initial: { load?: (filters: Filters) => Promise<void>; view?: AppView }) {
  dom = new JSDOM("<!doctype html><div id=\"root\"></div>");
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.window = dom.window as unknown as Window & typeof globalThis;
  globalThis.document = dom.window.document;
  const root = createRoot(dom.window.document.getElementById("root")!);
  const load = initial.load ?? (async () => undefined);
  let current: (CollectionWorkspace<Game, Filters> & { view: AppView; navigate: (view: AppView) => void }) | null = null;

  function Probe() {
    const [view, setView] = React.useState<AppView>(initial.view ?? "gallery");
    const workspace = useCollectionWorkspace<Game, Filters>({
      items: games,
      initialFilters: { search: "", platform: "" },
      load,
      genresOf: game => game.genres,
      view,
      setView,
      listViews: ["gallery", "calendar"],
      detailView: "detail",
      itemAttribute: "data-game-id"
    });
    current = { ...workspace, view, navigate: setView };
    return null;
  }

  act(() => root.render(<Probe />));

  return {
    get current() {
      if (!current) throw new Error("Workspace hook did not render");
      return current;
    }
  };
}
