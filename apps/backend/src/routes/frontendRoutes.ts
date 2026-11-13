import { existsSync, readFileSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { resolveBackendRuntimeLayout } from "../../../runtime/src/layout";
import type { BackendRouteContext } from "./context";

const contentTypes: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff2": "font/woff2"
};

export function registerFrontendRoutes({ app }: BackendRouteContext) {
  const frontendRoot = join(resolveBackendRuntimeLayout().assetRoot, "dist", "frontend");

  app.get("/", async (_request, reply) => {
    return sendFrontendFile(reply, join(frontendRoot, "index.html"));
  });

  app.get("/assets/*", async (request, reply) => {
    const params = request.params as { "*": string };
    const assetPath = safeAssetPath(frontendRoot, params["*"]);
    if (!assetPath) return reply.code(404).send({ error: "Asset not found" });
    // Vite puts a content hash in every asset name, so an asset never changes under the same URL.
    reply.header("cache-control", "public, max-age=31536000, immutable");
    return sendFrontendFile(reply, assetPath);
  });
}

function safeAssetPath(frontendRoot: string, value: string) {
  const relative = normalize(value || "");
  if (!relative || relative.startsWith("..") || relative.includes("..\\")) return null;
  return join(frontendRoot, "assets", relative);
}

function sendFrontendFile(reply: { code(statusCode: number): { send(payload: unknown): unknown }; header(name: string, value: string): unknown; send(payload: unknown): unknown }, filePath: string) {
  if (!existsSync(filePath)) return reply.code(404).send({ error: "Asset not found" });
  reply.header("content-type", contentTypes[extname(filePath).toLowerCase()] ?? "application/octet-stream");
  return reply.send(readFileSync(filePath));
}
