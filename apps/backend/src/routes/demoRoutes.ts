import { createDemoLibrary } from "../demo/demoLibrary";
import type { BackendRouteContext } from "./context";

export function registerDemoRoutes({ app, db }: BackendRouteContext, { today }: { today: () => Date }) {
  const demo = createDemoLibrary(db, today);

  app.get("/api/demo", async () => ({ loaded: demo.isLoaded() }));

  app.post("/api/demo", async (_request, reply) => {
    const counts = await demo.load();
    if (!counts) return reply.code(409).send({ error: "The sample library is already loaded" });
    return { loaded: true, ...counts };
  });

  app.delete("/api/demo", async () => {
    await demo.remove();
    return { loaded: false };
  });
}
