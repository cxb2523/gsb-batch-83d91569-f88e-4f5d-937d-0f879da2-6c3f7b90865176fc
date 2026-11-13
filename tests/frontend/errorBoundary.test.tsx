import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { afterEach, describe, expect, test, vi } from "vitest";
import { ErrorBoundary } from "../../apps/frontend/src/ErrorBoundary";
import { createApiClient } from "../../apps/frontend/src/api/client";

let dom: JSDOM | null = null;

afterEach(() => {
  dom?.window.close();
  dom = null;
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  delete (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT;
});

describe("frontend error boundary", () => {
  test("shows a reload state and reports render failures", async () => {
    dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://127.0.0.1" });
    vi.stubGlobal("window", dom.window);
    vi.stubGlobal("document", dom.window.document);
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const root = createRoot(dom.window.document.getElementById("root")!);

    function ThrowingView(): never {
      throw new Error("render failure");
    }

    await act(async () => {
      root.render(
        <ErrorBoundary api={createApiClient("http://127.0.0.1:3333")}>
          <ThrowingView />
        </ErrorBoundary>
      );
    });

    expect(dom.window.document.body.textContent).toContain("Something went wrong");
    expect(dom.window.document.body.textContent).toContain("render failure");
    expect(dom.window.document.body.textContent).toContain("Reload");
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:3333/api/diagnostics/log", expect.objectContaining({ method: "POST" }));

    await act(async () => root.unmount());
    consoleError.mockRestore();
  });
});
