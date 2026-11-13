// @vitest-environment jsdom
import { afterEach, describe, expect, test, vi } from "vitest";
import { AppShell } from "../../apps/frontend/src/App";
import { fakeApiClient } from "./fakeApiClient";
import { click, getButton, renderInteractive } from "./domHarness";

const cleanups: Array<() => Promise<void>> = [];
afterEach(async () => {
  while (cleanups.length) await cleanups.pop()!();
});

async function openDiagnostics(bridge?: Record<string, unknown>) {
  const view = await renderInteractive(<AppShell apiBaseUrl="http://unused" api={fakeApiClient()} />);
  cleanups.push(view.cleanup);
  if (bridge) (window as unknown as { releaseTracker: unknown }).releaseTracker = bridge;
  await click(getButton(view.container, "Settings"));
  await click(getButton(view.container, "Diagnostics"));
  return view;
}

describe("Settings → Diagnostics", () => {
  test("in the desktop app, opens the log folder and deletes all app data through the desktop bridge", async () => {
    const bridge = { openLogFolder: vi.fn(async () => ({ ok: true })), deleteAppData: vi.fn(async () => ({ ok: true })) };
    const { container } = await openDiagnostics(bridge);

    await click(getButton(container, "Open log folder"));
    await click(getButton(container, "Delete all app data"));

    expect(bridge.openLogFolder).toHaveBeenCalledTimes(1);
    expect(bridge.deleteAppData).toHaveBeenCalledTimes(1);
  });

  test("in a browser there is nothing to delete, so the buttons are not offered", async () => {
    const { container } = await openDiagnostics();

    expect(() => getButton(container, "Delete all app data")).toThrow();
    expect(() => getButton(container, "Open log folder")).toThrow();
  });
});
