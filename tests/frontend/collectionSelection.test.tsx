import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, test } from "vitest";
import { JSDOM } from "jsdom";
import { useCollectionSelection, type CollectionSelection } from "../../apps/frontend/src/collectionSelection";

let dom: JSDOM | null = null;

afterEach(() => {
  dom?.window.close();
  dom = null;
  delete (globalThis as { window?: Window }).window;
  delete (globalThis as { document?: Document }).document;
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
});

describe("collection selection hook", () => {
  test("selects all visible items and counts only still-visible selections", () => {
    const probe = renderSelection(["a", "b"]);

    act(() => probe.current.selectAllVisible());
    expect([...probe.current.selectedIds]).toEqual(["a", "b"]);
    expect(probe.current.selectedVisibleCount).toBe(2);

    act(() => probe.rerender(["b"]));
    expect([...probe.current.selectedIds]).toEqual(["a", "b"]);
    expect(probe.current.selectedVisibleCount).toBe(1);
  });

  test("toggles, clears, and removes selected items", () => {
    const probe = renderSelection(["a", "b", "c"]);

    act(() => {
      probe.current.toggle("a", true);
      probe.current.toggle("b", true);
      probe.current.toggle("b", false);
      probe.current.removeIds(["a"]);
      probe.current.toggle("c", true);
    });
    expect([...probe.current.selectedIds]).toEqual(["c"]);

    act(() => probe.current.clearSelection());
    expect([...probe.current.selectedIds]).toEqual([]);
  });
});

function renderSelection(initialVisibleIds: string[]) {
  dom = new JSDOM("<!doctype html><div id=\"root\"></div>");
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  globalThis.window = dom.window as unknown as Window & typeof globalThis;
  globalThis.document = dom.window.document;
  const root = createRoot(dom.window.document.getElementById("root")!);
  let current: CollectionSelection | null = null;

  function Probe({ visibleIds }: { visibleIds: string[] }) {
    current = useCollectionSelection(visibleIds);
    return null;
  }

  act(() => root.render(<Probe visibleIds={initialVisibleIds} />));

  return {
    get current() {
      if (!current) throw new Error("Selection hook did not render");
      return current;
    },
    rerender(visibleIds: string[]) {
      root.render(<Probe visibleIds={visibleIds} />);
    }
  };
}
