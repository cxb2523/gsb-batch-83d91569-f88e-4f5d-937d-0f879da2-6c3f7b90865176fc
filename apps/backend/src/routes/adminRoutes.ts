import { unblockRelease } from "../actions/releaseActions";
import { createReleaseStore } from "../database/releaseStore";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

export function registerAdminRoutes({ app, db }: BackendRouteContext) {
  const releaseStore = createReleaseStore(db);
  app.get("/api/blocked-releases", async () => ({ items: releaseStore.listBlocked() }));

  app.delete("/api/blocked-releases/:id", async (request, reply) => {
    const { id } = request.params as { id: string };
    return sendActionResult(reply, await unblockRelease(db, id));
  });
}
