import type React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { vi } from "vitest";

// Renders into a fresh JSDOM window installed as the global window/document for the test.
export async function renderInteractive(element: React.ReactElement) {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  const dom = new JSDOM("<!doctype html><html><body><div id=\"root\"></div></body></html>", { url: "http://127.0.0.1" });
  const previous = { window: globalThis.window, document: globalThis.document, navigator: globalThis.navigator };
  vi.stubGlobal("window", dom.window);
  vi.stubGlobal("document", dom.window.document);
  vi.stubGlobal("navigator", dom.window.navigator);
  const container = dom.window.document.getElementById("root")!;
  const root = createRoot(container);
  await act(async () => root.render(element));
  return {
    container,
    async cleanup() {
      await act(async () => root.unmount());
      dom.window.close();
      vi.stubGlobal("window", previous.window);
      vi.stubGlobal("document", previous.document);
      vi.stubGlobal("navigator", previous.navigator);
    }
  };
}

// A button by its accessible name: its aria-label, or its text.
export function getButton(container: Element, text: string) {
  const button = [...container.querySelectorAll("button")].find(item => (item.getAttribute("aria-label") ?? item.textContent) === text);
  if (!button) throw new Error(`Button not found: ${text}`);
  return button as HTMLButtonElement;
}

export const click = (element: HTMLElement) => act(async () => element.click());

// Types into an input the way React notices: through the native value setter, then an input event.
// Needs React DOM to have loaded with a window present (the jsdom test environment); otherwise React
// falls back to an old-browser polyfill that ignores synthetic input events.
export async function typeInto(element: Element, value: string) {
  const field = element as HTMLInputElement;
  const view = field.ownerDocument.defaultView!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(view.HTMLInputElement.prototype, "value")!.set!.call(field, value);
    field.dispatchEvent(new view.Event("input", { bubbles: true }));
  });
}
