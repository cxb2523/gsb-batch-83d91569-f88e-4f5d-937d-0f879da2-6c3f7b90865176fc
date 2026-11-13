import { readSyncSettings, searchPublishers, trackPublisher, trackSuggestedPublishers, untrackPublisher, updateSyncSettings } from "../actions/syncSettingsActions";
import { startSync } from "../sync/syncRun";
import { getSyncStatus } from "../sync/syncStatus";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerSyncRoutes({ app, db, igdb }: BackendRouteContext) {
  app.post("/api/sync/igdb", async () => startSync(db, undefined, igdb));
  app.get("/api/sync/status", async () => getSyncStatus(db));

  app.get("/api/sync/settings", async () => readSyncSettings(db));
  app.put("/api/sync/settings", async (request, reply) => sendActionResult(reply, await updateSyncSettings(db, request.body)));
  app.get("/api/sync/publishers/search", async (request, reply) => sendActionResult(reply, await searchPublishers(igdb, (request.query as { q?: unknown }).q)));
  app.post("/api/sync/publishers", async (request, reply) => sendActionResult(reply, await trackPublisher(db, request.body)));
  app.post("/api/sync/publishers/suggested", async (_request, reply) => sendActionResult(reply, await trackSuggestedPublishers(db, igdb)));
  app.delete("/api/sync/publishers/:id", async (request, reply) => sendActionResult(reply, await untrackPublisher(db, (request.params as { id: string }).id)));
}
