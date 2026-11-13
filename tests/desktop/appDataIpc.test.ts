import { afterEach, describe, expect, test, vi } from "vitest";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { deleteAppData } from "../../apps/desktop/src/appDataIpc";

const dirs: string[] = [];
afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs.length = 0;
});

// A data folder as the packaged app leaves it: the app's own files beside Chromium's profile folders.
function dataFolder() {
  const dir = mkdtempSync(join(tmpdir(), "grt-app-data-"));
  dirs.push(dir);
  for (const file of ["game-release-tracker.db", "game-release-tracker.db-wal", "credential-key.bin", "credential-key.bin.unreadable"]) writeFileSync(join(dir, file), "x");
  for (const folder of ["covers", "artworks", "wallpaper", "backups", "logs", "Local Storage", "Cache"]) {
    mkdirSync(join(dir, folder));
    writeFileSync(join(dir, folder, "file"), "x");
  }
  return dir;
}

function hooks(confirmed: boolean) {
  const calls: string[] = [];
  return {
    calls,
    confirm: vi.fn(async () => { calls.push("confirm"); return confirmed; }),
    stopBackend: vi.fn(async () => { calls.push("stop-backend"); }),
    clearBrowserStorage: vi.fn(async () => { calls.push("clear-browser-storage"); }),
    relaunch: vi.fn(() => { calls.push("relaunch"); })
  };
}

describe("delete all app data", () => {
  test("after the user confirms, stops the backend, removes the app's own files, clears the page's storage and restarts", async () => {
    const dataDir = dataFolder();
    const steps = hooks(true);

    expect(await deleteAppData({ dataDir, ...steps })).toEqual({ ok: true });

    expect(steps.calls).toEqual(["confirm", "stop-backend", "clear-browser-storage", "relaunch"]);
    expect(readdirSync(dataDir).sort()).toEqual(["Cache", "Local Storage"]);
  });

  test("nothing is touched when the user cancels", async () => {
    const dataDir = dataFolder();
    const steps = hooks(false);

    expect(await deleteAppData({ dataDir, ...steps })).toEqual({ ok: false, canceled: true });

    expect(steps.calls).toEqual(["confirm"]);
    expect(existsSync(join(dataDir, "game-release-tracker.db"))).toBe(true);
  });
});
