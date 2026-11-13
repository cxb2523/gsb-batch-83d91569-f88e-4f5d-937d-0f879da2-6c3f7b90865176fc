import { createReleaseStore } from "../database/releaseStore";
import { createSyncSettingsStore } from "../sync/syncSettingsStore";
import { createManualRelease, deleteReleaseWithOptionalBlock, searchManualReleaseCandidates, updateRelease } from "../actions/releaseActions";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerReleaseRoutes({ app, db, logger, igdb }: BackendRouteContext) {
  const releaseStore = createReleaseStore(db);

  app.get("/api/releases", async request => {
    const query = request.query as Record<string, string | undefined>;
    return releaseStore.list({
      search: query.search,
      publisher: query.publisher,
      category: query.category,
      platform: query.platform,
      datePrecision: query.datePrecision,
      includeHidden: query.includeHidden === "true",
      includeReleased: query.includeReleased === "true",
      watchedOnly: query.watchedOnly === "true",
      releasedFrom: createSyncSettingsStore(db).read().trackFrom
    });
  });

  app.get("/api/releases/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    const release = releaseStore.getDetail(id);
    if (!release) return reply.code(404).send({ error: "Release not found" });
    return release;
  });

  app.post("/api/releases/manual", async (request, reply) => {
    return sendActionResult(reply, await createManualRelease(db, request.body ?? {}));
  });

  app.get("/api/releases/manual/search", async (request, reply) => {
    const query = request.query as { q?: string };
    const q = query.q?.trim();
    if (!q) return reply.code(400).send({ error: "Search title is required" });
    const result = await searchManualReleaseCandidates(igdb, q);
    if (result.ok) logger.log("release.manual_search.completed", { query: q, count: result.value.items.length });
    return sendActionResult(reply, result);
  });

  app.patch("/api/releases/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    return sendActionResult(reply, await updateRelease(db, id, request.body ?? {}));
  });

  app.delete("/api/releases/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    const query = request.query as { block?: string };
    return sendActionResult(reply, await deleteReleaseWithOptionalBlock(db, id, query.block === "true", logger));
  });

}
