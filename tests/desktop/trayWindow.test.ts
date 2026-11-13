import { describe, expect, test, vi } from "vitest";
import { type AppTray, type TrayMenuItem, type TrayableWindow, bringWindowBack, installMinimizeToTray } from "../../apps/desktop/src/trayWindow";

function fakeWindow() {
  const state = { visible: true, minimized: false, destroyed: false, focused: false };
  const listeners: Record<string, () => void> = {};
  const window: TrayableWindow = {
    isDestroyed: () => state.destroyed,
    isVisible: () => state.visible,
    isMinimized: () => state.minimized,
    show: () => { state.visible = true; },
    hide: () => { state.visible = false; },
    restore: () => { state.minimized = false; },
    focus: () => { state.focused = true; },
    on: (event, listener) => { listeners[event] = listener; }
  };
  const minimize = () => {
    state.minimized = true;
    listeners.minimize?.();
  };
  return { window, state, minimize };
}

function fakeTray() {
  const listeners: Record<string, () => void> = {};
  let menu: TrayMenuItem[] = [];
  const tray: AppTray = {
    setToolTip: vi.fn(),
    setContextMenu: items => { menu = items; },
    on: (event, listener) => { listeners[event] = listener; },
    destroy: vi.fn()
  };
  return { tray, listeners, menu: () => menu };
}

describe("minimize to tray", () => {
  test("minimizing hides the window; clicking the tray icon brings it back restored and focused", () => {
    const { window, state, minimize } = fakeWindow();
    const { tray, listeners } = fakeTray();
    installMinimizeToTray({ window, createTray: () => tray, quit: vi.fn() });

    minimize();
    expect(state.visible).toBe(false);

    listeners.click();
    expect(state).toMatchObject({ visible: true, minimized: false, focused: true });
  });

  test("the tray menu opens the window or quits the app", () => {
    const { window, state, minimize } = fakeWindow();
    const { tray, menu } = fakeTray();
    const quit = vi.fn();
    installMinimizeToTray({ window, createTray: () => tray, quit });
    const item = (label: string) => menu().find(entry => entry.label === label)!;

    minimize();
    item("Open Game Release Tracker").click!();
    expect(state.visible).toBe(true);

    item("Quit").click!();
    expect(quit).toHaveBeenCalledOnce();
  });

  test("without a tray the window minimizes normally instead of disappearing", () => {
    const { window, state, minimize } = fakeWindow();
    const log = vi.fn();
    const tray = installMinimizeToTray({ window, createTray: () => { throw new Error("no tray"); }, quit: vi.fn(), log });

    minimize();
    expect(tray).toBeNull();
    expect(state).toMatchObject({ visible: true, minimized: true });
    expect(log).toHaveBeenCalledWith(expect.stringContaining("no tray"));
  });

  test("bringing back a missing or destroyed window does nothing", () => {
    expect(() => bringWindowBack(null)).not.toThrow();
    const { window, state } = fakeWindow();
    state.destroyed = true;
    state.visible = false;
    bringWindowBack(window);
    expect(state.visible).toBe(false);
  });
});
