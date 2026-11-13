import Fastify, { type FastifyRequest } from "fastify";
import type { TrackerDatabase } from "./database/db";
import { startSync } from "./sync/syncRun";
import { failInterruptedSyncRuns, shouldAutoSync } from "./sync/syncStatus";
import { runWrite } from "./database/writeQueue";
import { createFileDiagnosticLogger, type DiagnosticLogger } from "./diagnostics/logger";
import { createSettingsStore } from "./settings/settingsStore";
import { createIgdbGateway, type IgdbGateway } from "./igdb/gateway";
import { registerAdminRoutes } from "./routes/adminRoutes";
import { registerArtworkRoutes } from "./routes/artworkRoutes";
import { registerDiagnosticRoutes } from "./routes/diagnosticRoutes";
import { registerCompletedRoutes } from "./routes/completedRoutes";
import { registerRandomizerRoutes } from "./routes/randomizerRoutes";
import { registerYearInReviewRoutes } from "./routes/yearInReviewRoutes";
import { registerReleaseRoutes } from "./routes/releaseRoutes";
import { registerSettingsRoutes } from "./routes/settingsRoutes";
import { registerPreferencesRoutes } from "./routes/preferencesRoutes";
import { registerSyncRoutes } from "./routes/syncRoutes";
import { registerAlertRoutes } from "./routes/alertRoutes";
import { scheduleAutoSync } from "./sync/autoSyncSchedule";
import { registerWallpaperRoutes } from "./routes/wallpaperRoutes";
import { registerFrontendRoutes } from "./routes/frontendRoutes";
import { installRequestGuard } from "./requestGuard";
import type { CoverFetch } from "./artwork/coverCache";
import { registerDemoRoutes } from "./routes/demoRoutes";

interface BackendOptions {
  db: TrackerDatabase;
  autoSync?: boolean;
  logger?: DiagnosticLogger;
  igdb?: IgdbGateway;
  // The desktop app's per-launch secret; /api calls must send it. Omitted in development and tests.
  apiToken?: string;
  // The local date Year in Review treats as today. Tests pin it.
  today?: () => Date;
  // How the cover cache downloads an IGDB cover. Tests replace it; the app uses fetch.
  fetchCover?: CoverFetch;
}

const safeServerErrorMessage = "Something went wrong. Check the diagnostics log for details.";
const SLOW_REQUEST_MS = 1000;

const routeOf = (request: FastifyRequest) => request.routeOptions.url ?? request.url.split("?")[0];

export function createBackendApp({ db, autoSync = true, apiToken, logger = createFileDiagnosticLogger(), igdb = createIgdbGateway({ readConfig: () => createSettingsStore(db).igdbTokenConfig() }), today = () => new Date(), fetchCover = url => globalThis.fetch(url) }: BackendOptions) {
  const app = Fastify({ logger: false });
  installRequestGuard(app, { apiToken });
  const log = (event: string, details: Record<string, unknown>) => {
    try {
      logger.log(event, details);
    } catch {
      // Logging must not turn a recoverable request failure into a second failure.
    }
  };

  // Only what helps find a problem: failed and slow requests. Routes are logged by pattern
  // ("/api/releases/:id"), never the raw URL, so search text and ids stay out of the log.
  app.addHook("onResponse", async (request, reply) => {
    const ms = Math.round(reply.elapsedTime);
    if (reply.statusCode < 400 && ms < SLOW_REQUEST_MS) return;
    log(reply.statusCode >= 400 ? "http.response" : "http.slow", { method: request.method, route: routeOf(request), statusCode: reply.statusCode, ms });
  });

  app.setErrorHandler((error, request, reply) => {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorStack = error instanceof Error ? error.stack : undefined;
    const statusCode = typeof (error as { statusCode?: unknown }).statusCode === "number"
      && (error as { statusCode: number }).statusCode >= 400
      && (error as { statusCode: number }).statusCode < 500
      ? (error as { statusCode: number }).statusCode
      : 500;
    log("http.error", {
      method: request.method,
      url: routeOf(request),
      statusCode,
      message: errorMessage,
      stack: errorStack
    });
    if (reply.sent) return;
    reply.code(statusCode).send({ error: statusCode >= 500 ? safeServerErrorMessage : errorMessage });
  });

  const routeContext = { app, db, logger, igdb };
  registerReleaseRoutes(routeContext);
  registerCompletedRoutes(routeContext);
  registerRandomizerRoutes(routeContext);
  registerYearInReviewRoutes(routeContext, { today });
  registerDemoRoutes(routeContext, { today });
  registerArtworkRoutes(routeContext, { fetchCover });
  registerSyncRoutes(routeContext);
  registerAlertRoutes(routeContext, { today });
  registerSettingsRoutes(routeContext);
  registerPreferencesRoutes(routeContext);
  registerDiagnosticRoutes(routeContext);
  registerAdminRoutes(routeContext);
  registerWallpaperRoutes(routeContext);
  registerFrontendRoutes(routeContext);

  void runWrite(db, () => failInterruptedSyncRuns(db));
  if (autoSync) {
    const stop = scheduleAutoSync({ isDue: () => shouldAutoSync(db), sync: () => void startSync(db, undefined, igdb) });
    app.addHook("onClose", async () => stop());
  }

  return app;
}
