import type { BackendRouteContext } from "./context";

export function registerDiagnosticRoutes({ app, logger }: BackendRouteContext) {
  app.post("/api/diagnostics/log", async request => {
    const payload = request.body as Partial<{ event: string; details: Record<string, unknown> }>;
    logger.log(payload.event || "frontend.event", payload.details ?? {});
    return { ok: true };
  });
}
