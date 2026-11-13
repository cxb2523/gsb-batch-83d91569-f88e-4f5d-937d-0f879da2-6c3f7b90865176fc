import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test, vi } from "vitest";
import { autostartEntry, createStartAtLogin, registerStartAtLoginIpc, startsHidden, type StartAtLoginPlatform } from "../../apps/desktop/src/startAtLogin";

let dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

function platform(overrides: Partial<StartAtLoginPlatform>): StartAtLoginPlatform {
  const dir = mkdtempSync(join(tmpdir(), "grt-autostart-"));
  dirs.push(dir);
  let openAtLogin = false;
  return {
    platform: "win32",
    packaged: true,
    launchPath: "C:\\Apps\\Game Release Tracker.exe",
    autostartDir: join(dir, "autostart"),
    getLoginItemSettings: () => ({ openAtLogin }),
    setLoginItemSettings: vi.fn(settings => { openAtLogin = settings.openAtLogin; }),
    ...overrides
  };
}

describe("start at login", () => {
  test("on Windows it is a login item that starts the app hidden in the tray", () => {
    const windows = platform({});
    const startAtLogin = createStartAtLogin(windows);

    expect(startAtLogin.supported).toBe(true);
    startAtLogin.setEnabled(true);
    expect(windows.setLoginItemSettings).toHaveBeenCalledWith({ openAtLogin: true, args: ["--hidden"] });
    expect(startAtLogin.isEnabled()).toBe(true);
    startAtLogin.setEnabled(false);
    expect(startAtLogin.isEnabled()).toBe(false);
  });

  test("on Linux it is an autostart file that runs the AppImage or executable hidden", () => {
    const linux = platform({ platform: "linux", launchPath: "/home/me/Apps/Game Release Tracker.AppImage" });
    const startAtLogin = createStartAtLogin(linux);
    const file = join(linux.autostartDir, "game-release-tracker.desktop");

    startAtLogin.setEnabled(true);
    expect(startAtLogin.isEnabled()).toBe(true);
    expect(readFileSync(file, "utf8")).toContain('Exec="/home/me/Apps/Game Release Tracker.AppImage" --hidden');

    startAtLogin.setEnabled(false);
    expect(existsSync(file)).toBe(false);
  });

  test("a development run never registers itself", () => {
    const dev = platform({ packaged: false });
    const startAtLogin = createStartAtLogin(dev);
    startAtLogin.setEnabled(true);
    expect(startAtLogin.supported).toBe(false);
    expect(dev.setLoginItemSettings).not.toHaveBeenCalled();
  });

  test("the autostart Exec line escapes characters the desktop-entry spec reserves", () => {
    expect(autostartEntry('/opt/my "odd" $app')).toContain('Exec="/opt/my \\"odd\\" \\$app" --hidden');
  });

  test("the app starts hidden only when asked", () => {
    expect(startsHidden(["/app", "--hidden"])).toBe(true);
    expect(startsHidden(["/app"])).toBe(false);
  });

  test("only the app's own frame can change it", async () => {
    const handlers: Record<string, (...args: never[]) => unknown> = {};
    const windows = platform({});
    registerStartAtLoginIpc({
      ipcMain: { handle: (channel: string, handler: (...args: never[]) => unknown) => { handlers[channel] = handler; } } as never,
      startAtLogin: createStartAtLogin(windows),
      isAppFrame: url => url.startsWith("app://renderer")
    });
    const set = handlers["set-start-at-login"] as (event: unknown, on: unknown) => { enabled: boolean };

    expect(set({ senderFrame: { url: "https://evil.example/" } }, true)).toMatchObject({ enabled: false });
    expect(set({ senderFrame: { url: "app://renderer/" } }, "yes")).toMatchObject({ enabled: false });
    expect(set({ senderFrame: { url: "app://renderer/" } }, true)).toMatchObject({ enabled: true });
    expect((handlers["start-at-login"] as () => unknown)()).toEqual({ supported: true, platform: "windows", enabled: true });
  });
});
