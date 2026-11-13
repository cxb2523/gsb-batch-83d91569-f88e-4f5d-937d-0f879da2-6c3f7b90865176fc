import type { TrackerDatabase } from "../database/db";
import { createReleaseStore } from "../database/releaseStore";
import { runWrite } from "../database/writeQueue";
import type { ActionResult } from "../actions/actionResult";
import { ArtworkValidationError, prepareLocalArtwork, removeLocalArtwork, type LocalArtworkPayload, type PreparedLocalArtwork } from "./localArtworkStorage";
import type { ReleaseArtwork, ReleaseDetail } from "../../../../shared/types";

interface ReleaseArtworkStorage {
  prepareLocalArtwork(payload: LocalArtworkPayload): PreparedLocalArtwork;
  removeLocalArtwork(imageId: string): void;
}

const notFound = { ok: false, statusCode: 404, error: "Release not found" } as const;

// Release artwork actions: each is queued and atomic. An uploaded file is written only after its
// database row is in, inside the same transaction, so a failed insert never leaves a stray file.
export function createReleaseArtworkWorkflow(
  db: TrackerDatabase,
  storage: ReleaseArtworkStorage = { prepareLocalArtwork, removeLocalArtwork }
) {
  const releaseStore = createReleaseStore(db);
  return {
    async saveLocalArtworkForRelease(releaseId: string, payload: LocalArtworkPayload): Promise<ActionResult<{ ok: true; artwork: ReleaseArtwork; item: ReleaseDetail }>> {
      let prepared: PreparedLocalArtwork;
      try {
        prepared = storage.prepareLocalArtwork(payload);
      } catch (error) {
        if (error instanceof ArtworkValidationError) return { ok: false, statusCode: 400, error: error.message };
        throw error;
      }
      return runWrite(db, () => {
        if (!releaseStore.exists(releaseId)) return notFound;
        releaseStore.addArtwork(releaseId, prepared.artwork);
        prepared.write();
        return { ok: true, value: { ok: true, artwork: prepared.artwork, item: releaseStore.getDetail(releaseId)! } };
      });
    },

    removeArtworkFromRelease(releaseId: string, artworkId: string): Promise<ActionResult<{ ok: true; item: ReleaseDetail | null }>> {
      return runWrite(db, () => {
        if (!releaseStore.exists(releaseId)) return notFound;
        const removed = releaseStore.removeArtwork(releaseId, artworkId);
        if (removed.source === "local") storage.removeLocalArtwork(artworkId);
        return { ok: true, value: { ok: true, item: releaseStore.getDetail(releaseId) } };
      });
    },

    reorderReleaseArtworks(releaseId: string, artworkIds: string[]): Promise<ActionResult<{ ok: true; item: ReleaseDetail | null }>> {
      return runWrite(db, () => {
        if (!releaseStore.exists(releaseId)) return notFound;
        releaseStore.reorderArtworks(releaseId, artworkIds);
        return { ok: true, value: { ok: true, item: releaseStore.getDetail(releaseId) } };
      });
    }
  };
}
