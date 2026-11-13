import { createRandomizerActions } from "../actions/randomizerActions";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerRandomizerRoutes({ app, db, igdb }: BackendRouteContext) {
  const randomizer = createRandomizerActions(db, igdb);

  app.get("/api/randomizer/options", async (_request, reply) => sendActionResult(reply, await randomizer.loadOptions()));

  app.post("/api/randomizer/spin", async (request, reply) => sendActionResult(reply, await randomizer.spin(request.body)));

  app.get("/api/randomizer/tags", async (request, reply) => sendActionResult(reply, await randomizer.searchTags((request.query as { search?: string }).search)));

  app.get("/api/randomizer/series", async (request, reply) => sendActionResult(reply, await randomizer.searchSeries((request.query as { search?: string }).search)));

  app.get("/api/randomizer/games", async (request, reply) => sendActionResult(reply, await randomizer.searchGames((request.query as { search?: string }).search)));

  app.get("/api/randomizer/history", async request => randomizer.history((request.query as { limit?: string }).limit));

  app.delete("/api/randomizer/history", async () => randomizer.clearHistory());
}
