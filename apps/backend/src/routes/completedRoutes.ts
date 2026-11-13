import { createCompletedGameStore } from "../completed/completedGameStore";
import { sendActionResult } from "./actionResult";
import { createManualCompletedGame, deleteCompletedGame, getMatchCandidates, matchCompletedGame, searchManualCompletedCandidates, updateCompletedGame } from "../actions/completedActions";
import type { BackendRouteContext } from "./context";

export function registerCompletedRoutes({ app, db, igdb }: BackendRouteContext) {
  const store = createCompletedGameStore(db);

  app.get("/api/completed-games", async request => {
    const query = request.query as Record<string, string | undefined>;
    return store.list({
      search: query.search,
      platform: query.platform,
      year: query.year,
      month: query.month,
      rating: query.rating,
      dateState: query.dateState as "" | "dated" | "undated" | undefined
    });
  });

  app.get("/api/completed-games/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    const item = store.getDetail(id);
    if (!item) return reply.code(404).send({ error: "Completed game not found" });
    return item;
  });

  app.post("/api/completed-games/manual", async (request, reply) => {
    const result = await createManualCompletedGame(db, igdb, request.body ?? {});
    return sendActionResult(reply, result);
  });

  app.get("/api/completed-games/manual/search", async (request, reply) => {
    const query = request.query as { q?: string; platform?: string; completionYear?: string };
    const year = query.completionYear ? Number(query.completionYear) : null;
    const result = await searchManualCompletedCandidates(igdb, {
      title: query.q,
      userPlatform: query.platform,
      completionYear: Number.isFinite(year) ? year : null
    });
    return sendActionResult(reply, result);
  });

  app.delete("/api/completed-games/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    return sendActionResult(reply, await deleteCompletedGame(db, id));
  });

  app.patch("/api/completed-games/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    return sendActionResult(reply, await updateCompletedGame(db, id, request.body as Record<string, unknown> | undefined));
  });

  app.get("/api/completed-games/:id/match-candidates", async (request, reply) => {
    const { id } = request.params as { id: string };
    const result = await getMatchCandidates(db, igdb, id);
    return sendActionResult(reply, result);
  });

  app.post("/api/completed-games/:id/match", async (request, reply) => {
    const { id } = request.params as { id: string };
    const body = request.body as { igdbId?: number } | undefined;
    const result = await matchCompletedGame(db, igdb, id, Number(body?.igdbId));
    return sendActionResult(reply, result);
  });
}
