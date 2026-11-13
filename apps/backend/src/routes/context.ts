import type { FastifyInstance } from "fastify";
import type { TrackerDatabase } from "../database/db";
import type { DiagnosticLogger } from "../diagnostics/logger";
import type { IgdbGateway } from "../igdb/gateway";

export interface BackendRouteContext {
  app: FastifyInstance;
  db: TrackerDatabase;
  logger: DiagnosticLogger;
  igdb: IgdbGateway;
}
