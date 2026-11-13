// Minimize to the system tray: minimizing the app window hides it to a tray icon, and the icon (a click,
// or "Open" in its menu) brings it back. Closing the window still quits the app; "Quit" in the tray menu
// does the same while the window is hidden.

export interface TrayableWindow {
  isDestroyed(): boolean;
  isVisible(): boolean;
  isMinimized(): boolean;
  show(): void;
  hide(): void;
  restore(): void;
  focus(): void;
  on(event: "minimize", listener: () => void): unknown;
}

export interface TrayMenuItem {
  label?: string;
  type?: "separator";
  click?: () => void;
}

export interface AppTray {
  setToolTip(text: string): void;
  // A notification balloon from the tray icon (Windows), for when a system notification can't be shown.
  showBalloon?(title: string, body: string, onClick: () => void): void;
  setContextMenu(items: TrayMenuItem[]): void;
  on(event: "click" | "double-click", listener: () => void): unknown;
  destroy(): void;
}

export const TRAY_TOOLTIP = "Game Release Tracker";

// Shows the window wherever it is: hidden in the tray, minimized, or behind other windows.
export function bringWindowBack(window: TrayableWindow | null) {
  if (!window || window.isDestroyed()) return;
  if (!window.isVisible()) window.show();
  if (window.isMinimized()) window.restore();
  window.focus();
}

// Creates the tray icon and hides the window to it on minimize. When the tray cannot be created the
// window minimizes normally, so it can never be hidden with no way back.
export function installMinimizeToTray({
  window,
  createTray,
  quit,
  log
}: {
  window: TrayableWindow;
  createTray: () => AppTray;
  quit: () => void;
  log?: (message: string) => void;
}): AppTray | null {
  let tray: AppTray;
  try {
    tray = createTray();
  } catch (error) {
    log?.(`tray unavailable, minimize stays normal: ${error instanceof Error ? error.message : String(error)}`);
    return null;
  }
  const open = () => bringWindowBack(window);
  tray.setToolTip(TRAY_TOOLTIP);
  tray.setContextMenu([
    { label: "Open Game Release Tracker", click: open },
    { type: "separator" },
    { label: "Quit", click: quit }
  ]);
  tray.on("click", open);
  tray.on("double-click", open);
  window.on("minimize", () => {
    if (!window.isDestroyed()) window.hide();
  });
  return tray;
}
