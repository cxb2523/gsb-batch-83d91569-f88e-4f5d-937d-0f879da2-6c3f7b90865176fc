import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { IpcMain } from "electron";

// Start with Windows (or with the Linux desktop session): the app starts at login, straight into the
// tray, with this argument. Windows keeps the choice as a login item; Linux as an XDG autostart file.
// Only a packaged app (installer, zip or AppImage) can register itself, so a development run never lands
// in the user's login items. It registers the program where it is now; a moved zip or AppImage needs the
// switch turned off and on again.
export const START_HIDDEN_ARG = "--hidden";
const AUTOSTART_FILE = "game-release-tracker.desktop";

export interface StartAtLogin {
  supported: boolean;
  // Names the switch: "Start with Windows" or "Start when I log in".
  platform: "windows" | "linux" | null;
  isEnabled(): boolean;
  setEnabled(on: boolean): void;
}

export interface StartAtLoginPlatform {
  platform: NodeJS.Platform;
  packaged: boolean;
  // The program to start: the AppImage itself when running from one, else the executable.
  launchPath: string;
  // ~/.config/autostart on Linux.
  autostartDir: string;
  getLoginItemSettings(options: { args: string[] }): { openAtLogin: boolean };
  setLoginItemSettings(settings: { openAtLogin: boolean; args: string[] }): void;
}

export function createStartAtLogin(platform: StartAtLoginPlatform): StartAtLogin {
  if (!platform.packaged) return unsupported;
  if (platform.platform === "win32") {
    const args = [START_HIDDEN_ARG];
    return {
      supported: true,
      platform: "windows",
      isEnabled: () => platform.getLoginItemSettings({ args }).openAtLogin,
      setEnabled: on => platform.setLoginItemSettings({ openAtLogin: on, args })
    };
  }
  if (platform.platform === "linux") {
    const file = join(platform.autostartDir, AUTOSTART_FILE);
    return {
      supported: true,
      platform: "linux",
      isEnabled: () => existsSync(file),
      setEnabled: on => {
        if (!on) return rmSync(file, { force: true });
        mkdirSync(platform.autostartDir, { recursive: true });
        writeFileSync(file, autostartEntry(platform.launchPath));
      }
    };
  }
  return unsupported;
}

const unsupported: StartAtLogin = { supported: false, platform: null, isEnabled: () => false, setEnabled: () => undefined };

export function autostartEntry(launchPath: string) {
  // Exec quotes the path (it may contain spaces) and escapes what the desktop-entry spec reserves.
  const quoted = `"${launchPath.replace(/(["`$\\])/g, "\\$1")}"`;
  return [
    "[Desktop Entry]",
    "Type=Application",
    "Name=Game Release Tracker",
    "Comment=Start Game Release Tracker in the tray",
    `Exec=${quoted} ${START_HIDDEN_ARG}`,
    "Icon=game-release-tracker",
    "Terminal=false",
    "X-GNOME-Autostart-enabled=true",
    ""
  ].join("\n");
}

export function startsHidden(argv: string[]) {
  return argv.includes(START_HIDDEN_ARG);
}

// Settings asks whether starting at login is available and on, and turns it on or off. Only the app's
// own frame may change it.
export function registerStartAtLoginIpc({ ipcMain, startAtLogin, isAppFrame }: {
  ipcMain: Pick<IpcMain, "handle">;
  startAtLogin: StartAtLogin;
  isAppFrame: (url: string) => boolean;
}) {
  const state = () => ({ supported: startAtLogin.supported, platform: startAtLogin.platform, enabled: startAtLogin.supported && startAtLogin.isEnabled() });
  ipcMain.handle("start-at-login", () => state());
  ipcMain.handle("set-start-at-login", (event: { senderFrame?: { url?: string } | null }, on: unknown) => {
    if (!isAppFrame(event.senderFrame?.url ?? "") || typeof on !== "boolean" || !startAtLogin.supported) return state();
    startAtLogin.setEnabled(on);
    return state();
  });
}
