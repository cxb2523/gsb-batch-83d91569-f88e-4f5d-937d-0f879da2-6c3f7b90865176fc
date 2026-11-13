import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, test, vi } from "vitest";
import { JSDOM } from "jsdom";
import { useDetailSession, type DetailSession } from "../../apps/frontend/src/detailSession";
import { useCandidateSearch, type CandidateSearch } from "../../apps/frontend/src/candidateSearch";

let dom: JSDOM | null = null;

afterEach(() => {
  dom?.window.close();
  dom = null;
  vi.unstubAllGlobals();
});

function mountDom() {
  dom = new JSDOM("<!doctype html><div id=\"root\"></div>", { url: "http://127.0.0.1" });
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  return createRoot(dom.window.document.getElementById("root")!);
}

function renderHook<T>(useHook: () => T) {
  const root = mountDom();
  let current: T | null = null;
  function Probe() {
    current = useHook();
    return null;
  }
  act(() => root.render(<Probe />));
  return { get current() { return current as T; }, root };
}

const shell = () => ({ reportOperationError: vi.fn((_action: string, error: unknown) => (error instanceof Error ? error.message : String(error))), clearOperationError: vi.fn() });

describe("detail session", () => {
  test("opening falls back to the list item when the detail request fails", async () => {
    const errors = shell();
    const probe = renderHook(() => useDetailSession<{ id: string }, { id: string; full: boolean }>({
      load: async () => { throw new Error("offline"); },
      fallback: item => ({ ...item, full: false }),
      reload: async () => undefined,
      shell: errors,
      action: "open-detail"
    }));

    await act(async () => { await probe.current.open({ id: "a" }); });

    expect(probe.current.detail).toEqual({ id: "a", full: false });
    expect(errors.reportOperationError).toHaveBeenCalledWith("open-detail", expect.any(Error));
  });

  test("a mutation adopts the returned item, reloads the list and clears the old banner", async () => {
    const errors = shell();
    const reload = vi.fn(async () => undefined);
    let probe!: { current: DetailSession<{ id: string; title: string }> };
    probe = renderHook(() => useDetailSession<{ id: string }, { id: string; title: string }>({
      initialDetail: { id: "a", title: "Old" },
      load: async item => ({ ...item, title: "Old" }),
      fallback: item => ({ ...item, title: "" }),
      reload,
      shell: errors,
      action: "open-detail"
    }));

    await act(async () => { await probe.current.mutate("rename", async detail => ({ ...detail, title: "New" })); });

    expect(probe.current.detail?.title).toBe("New");
    expect(reload).toHaveBeenCalledTimes(1);
    expect(errors.clearOperationError).toHaveBeenCalled();
  });

  test("a failed mutation keeps the detail and reports once", async () => {
    const errors = shell();
    const reload = vi.fn(async () => undefined);
    const probe = renderHook(() => useDetailSession<{ id: string }, { id: string }>({
      initialDetail: { id: "a" },
      load: async item => item,
      fallback: item => item,
      reload,
      shell: errors,
      action: "open-detail"
    }));

    await act(async () => { await probe.current.mutate("rename", async () => { throw new Error("nope"); }); });

    expect(probe.current.detail).toEqual({ id: "a" });
    expect(errors.reportOperationError).toHaveBeenCalledTimes(1);
    expect(reload).not.toHaveBeenCalled();
  });
});

describe("candidate search", () => {
  test("an empty title is rejected without searching", async () => {
    const search = vi.fn(async () => []);
    const probe = renderHook(() => useCandidateSearch({ search, shell: shell(), action: "search", messages: { found: n => `${n} found`, none: "none" } }));

    await act(async () => { await probe.current.search("  "); });

    expect(search).not.toHaveBeenCalled();
    expect(probe.current).toMatchObject({ status: "error", message: "Enter a title before searching IGDB." });
  });

  test("results and failures set status, candidates and message", async () => {
    const errors = shell();
    let fail = false;
    const probe: { current: CandidateSearch<number> } = renderHook(() => useCandidateSearch<number>({
      search: async () => { if (fail) throw new Error("IGDB down"); return [1, 2]; },
      shell: errors,
      action: "search",
      messages: { found: n => `${n} found`, none: "none" }
    }));

    await act(async () => { await probe.current.search("Okami"); });
    expect(probe.current).toMatchObject({ status: "success", candidates: [1, 2], message: "2 found" });

    fail = true;
    await act(async () => { await probe.current.search("Okami"); });
    expect(probe.current).toMatchObject({ status: "error", candidates: [], message: "IGDB down" });
    expect(errors.reportOperationError).toHaveBeenCalledWith("search", expect.any(Error));
  });
});
