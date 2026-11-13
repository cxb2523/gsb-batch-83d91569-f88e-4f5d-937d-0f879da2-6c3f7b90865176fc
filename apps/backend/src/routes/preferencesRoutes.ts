import { readPreferences, savePalette, saveThemeAutoplay } from "../actions/preferencesActions";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerPreferencesRoutes({ app, db }: BackendRouteContext) {
  app.get("/api/preferences", async () => readPreferences(db));

  app.put("/api/preferences/palette", async (request, reply) => sendActionResult(reply, await savePalette(db, request.body)));
  app.put("/api/preferences/theme-autoplay", async (request, reply) => sendActionResult(reply, await saveThemeAutoplay(db, request.body)));
}
