import { describe, expect, test, vi } from "vitest";
import { replaceBlobUrl, resolveApiUrl, resolveWallpaperDisplayUrl, setResolvedWallpaperUrl } from "../../apps/frontend/src/wallpaperWorkflow";

describe("wallpaper workflow", () => {
  test("resolves backend wallpaper paths against the current API base", () => {
    expect(resolveApiUrl("http://127.0.0.1:1234", "/api/wallpaper/current")).toBe("http://127.0.0.1:1234/api/wallpaper/current");
    expect(resolveApiUrl("http://127.0.0.1:1234", "https://example.test/wallpaper.png")).toBe("https://example.test/wallpaper.png");
  });

  test("replaces blob wallpaper URLs and revokes the old object URL", () => {
    const revoke = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);

    expect(replaceBlobUrl("blob:http://127.0.0.1/old", "blob:http://127.0.0.1/new")).toBe("blob:http://127.0.0.1/new");
    expect(revoke).toHaveBeenCalledWith("blob:http://127.0.0.1/old");

    revoke.mockRestore();
  });

  test("sets a resolved wallpaper URL through one interface", () => {
    let next = "";

    setResolvedWallpaperUrl(updater => {
      next = updater("blob:http://127.0.0.1/old");
    }, "http://127.0.0.1:1234", "/api/wallpaper/current");

    expect(next).toContain("http://127.0.0.1:1234/api/wallpaper/current?v=");
  });

  test("backend wallpaper display URLs change between selections so the browser reloads the image", () => {
    const first = resolveWallpaperDisplayUrl("http://127.0.0.1:1234", "/api/wallpaper/current");
    const second = resolveWallpaperDisplayUrl("http://127.0.0.1:1234", "/api/wallpaper/current");

    expect(first).toContain("http://127.0.0.1:1234/api/wallpaper/current?v=");
    expect(second).toContain("http://127.0.0.1:1234/api/wallpaper/current?v=");
    expect(second).not.toBe(first);
  });
});
