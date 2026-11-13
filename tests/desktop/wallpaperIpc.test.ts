import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import { chooseWallpaperFromDesktop } from "../../apps/desktop/src/wallpaperIpc";
import { currentWallpaperPath } from "../../apps/runtime/src/wallpaperStorage";

let dirs: string[] = [];

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("desktop wallpaper IPC", () => {
  test("returns null when the native picker is canceled", async () => {
    const result = await chooseWallpaperFromDesktop({
      dataDir: tempDir(),
      window: null,
      dialog: { showOpenDialog: async () => ({ canceled: true, filePaths: [] }) }
    });

    expect(result).toBeNull();
  });

  test("copies the selected wallpaper into app data and returns the relative wallpaper URL", async () => {
    const dataDir = tempDir();
    const source = join(tempDir(), "wallpaper.png");
    writeFileSync(source, "selected-wallpaper");

    const result = await chooseWallpaperFromDesktop({
      dataDir,
      window: null,
      dialog: { showOpenDialog: async () => ({ canceled: false, filePaths: [source] }) }
    });

    const stored = currentWallpaperPath(dataDir);
    expect(result).toBe("/api/wallpaper/current");
    expect(stored?.endsWith(".png")).toBe(true);
    expect(existsSync(stored!)).toBe(true);
    expect(readFileSync(stored!, "utf8")).toBe("selected-wallpaper");
  });
});

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "grt-wallpaper-ipc-"));
  dirs.push(dir);
  return dir;
}
