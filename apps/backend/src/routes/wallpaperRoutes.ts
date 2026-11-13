import { resolveBackendRuntimeLayout } from "../../../runtime/src/layout";
import { clearWallpaper, readCurrentWallpaper, wallpaperStatus } from "../../../runtime/src/wallpaperStorage";
import type { BackendRouteContext } from "./context";

export function registerWallpaperRoutes({ app }: BackendRouteContext) {
  app.get("/api/wallpaper", async () => wallpaperStatus(resolveBackendRuntimeLayout().dataDir));

  app.get("/api/wallpaper/current", async (_request, reply) => {
    const wallpaper = readCurrentWallpaper(resolveBackendRuntimeLayout().dataDir);
    if (!wallpaper) return reply.code(404).send({ error: "Wallpaper not found" });
    return reply.header("Cache-Control", "no-store").header("Content-Type", wallpaper.contentType).send(wallpaper.bytes);
  });

  app.delete("/api/wallpaper", async () => {
    clearWallpaper(resolveBackendRuntimeLayout().dataDir);
    return { ok: true };
  });
}
