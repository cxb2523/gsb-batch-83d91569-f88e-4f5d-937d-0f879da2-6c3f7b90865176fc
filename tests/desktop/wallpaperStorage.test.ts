import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";
import { currentWallpaperPath, saveWallpaperFromFile } from "../../apps/runtime/src/wallpaperStorage";

let dirs: string[] = [];

function tempDir() {
  const dir = mkdtempSync(join(tmpdir(), "grt-wallpaper-"));
  dirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
});

describe("desktop wallpaper storage", () => {
  test("copies selected wallpaper into app data and replaces the previous wallpaper", () => {
    const dataDir = tempDir();
    const first = join(tempDir(), "first.png");
    const second = join(tempDir(), "second.jpg");
    writeFileSync(first, "first-wallpaper");
    writeFileSync(second, "second-wallpaper");

    expect(saveWallpaperFromFile(dataDir, first)).toEqual({ hasWallpaper: true, url: "/api/wallpaper/current" });
    const firstStored = currentWallpaperPath(dataDir);
    expect(firstStored?.endsWith(".png")).toBe(true);
    expect(readFileSync(firstStored!, "utf8")).toBe("first-wallpaper");

    expect(saveWallpaperFromFile(dataDir, second)).toEqual({ hasWallpaper: true, url: "/api/wallpaper/current" });
    const secondStored = currentWallpaperPath(dataDir);
    expect(secondStored?.endsWith(".jpg")).toBe(true);
    expect(readFileSync(secondStored!, "utf8")).toBe("second-wallpaper");
    expect(existsSync(firstStored!)).toBe(false);
  });
});
