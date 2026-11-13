import { createReadStream, existsSync } from "node:fs";
import { resolveBackendRuntimeLayout } from "../../../runtime/src/layout";
import { createCoverCache, isIgdbImageId, type CoverFetch } from "../artwork/coverCache";
import { localArtworkPath } from "../artwork/localArtworkStorage";
import { createReleaseArtworkWorkflow } from "../artwork/releaseArtworkWorkflow";
import { sendActionResult } from "./actionResult";
import type { BackendRouteContext } from "./context";

// Uploads arrive as base64 JSON: a 10 MB image is about 13.4 MB on the wire. The artwork module still
// refuses anything over 10 MB with a clear message; this only lifts Fastify's 1 MiB default.
const artworkUploadBodyLimit = 16 * 1024 * 1024;

export function registerArtworkRoutes({ app, db }: BackendRouteContext, { fetchCover }: { fetchCover: CoverFetch }) {
  const releaseArtworkWorkflow = createReleaseArtworkWorkflow(db);
  const covers = createCoverCache({ dir: resolveBackendRuntimeLayout().coversDir, fetchCover });

  app.post("/api/releases/:id/artworks/local", { bodyLimit: artworkUploadBodyLimit }, async (request, reply) => {
    const { id } = request.params as { id: string };
    return sendActionResult(reply, await releaseArtworkWorkflow.saveLocalArtworkForRelease(id, request.body ?? {}));
  });

  app.delete("/api/releases/:id/artworks/:artworkId", async (request, reply) => {
    const { id, artworkId } = request.params as { id: string; artworkId: string };
    return sendActionResult(reply, await releaseArtworkWorkflow.removeArtworkFromRelease(id, artworkId));
  });

  app.patch("/api/releases/:id/artworks/order", async (request, reply) => {
    const { id } = request.params as { id: string };
    const payload = request.body as { artworkIds?: string[] } | undefined;
    return sendActionResult(reply, await releaseArtworkWorkflow.reorderReleaseArtworks(id, payload?.artworkIds ?? []));
  });

  app.get("/api/artworks/local/:fileName", async (request, reply) => {
    const { fileName } = request.params as { fileName: string };
    const file = localArtworkPath(fileName);
    if (!existsSync(file)) return reply.code(404).send({ error: "Artwork not found" });
    return reply.send(createReadStream(file));
  });

  // Covers never change for an image id, so the browser may keep them for good.
  app.get("/api/covers/:imageId", async (request, reply) => {
    const { imageId } = request.params as { imageId: string };
    if (!isIgdbImageId(imageId)) return reply.code(400).send({ error: "Not an IGDB image id" });
    const file = await covers.file(imageId);
    if (!file) return reply.code(404).send({ error: "Cover not available" });
    return reply.header("content-type", "image/jpeg").header("cache-control", "public, max-age=31536000, immutable").send(createReadStream(file));
  });
}
