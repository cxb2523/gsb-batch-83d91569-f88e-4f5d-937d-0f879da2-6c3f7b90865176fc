import type { TrackerDatabase } from "../database/db";
import { SteamGridDbClient } from "../steamgriddb/client";
import type { ReleaseArtwork } from "../../../../shared/types";
import { needsArtworkEnrichment, type SyncCandidate } from "./releaseSyncPlanner";
import { createReleaseStore } from "../database/releaseStore";
import { createSettingsStore } from "../settings/settingsStore";

export interface SyncArtworkClient {
  findArtwork(title: string): Promise<ReleaseArtwork[]>;
}

// SteamGridDB lookups are independent network calls; a few at once shortens syncs with many new games
// without hammering the service.
const STEAMGRIDDB_CONCURRENCY = 4;

async function forEachWithConcurrency<T>(items: T[], limit: number, work: (item: T) => Promise<void>) {
  let next = 0;
  const lanes = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) await work(items[next++]);
  });
  await Promise.all(lanes);
}

export interface SyncArtworkEnrichment {
  artworksByIgdbId: Map<number, ReleaseArtwork[]>;
  failed: number;
}

export async function fetchSyncArtworkEnrichment(
  db: TrackerDatabase,
  candidates: SyncCandidate[],
  steamGridClient: SyncArtworkClient = new SteamGridDbClient(createSettingsStore(db).steamGridDbApiKey())
): Promise<SyncArtworkEnrichment> {
  const releaseStore = createReleaseStore(db);
  // Rejected and blocked games will not be saved, so they are never looked up on SteamGridDB.
  const wanted = candidates.filter((candidate): candidate is Extract<SyncCandidate, { accepted: true }> => {
    if (!candidate.accepted || releaseStore.isBlocked(candidate.igdbId, candidate.title)) return false;
    return needsArtworkEnrichment(candidate, releaseStore.loadMergeState(releaseStore.idForIgdbGame(candidate.igdbId), candidate.release.normalizedTitle));
  });
  const artworksByIgdbId = new Map<number, ReleaseArtwork[]>();
  let failed = 0;
  await forEachWithConcurrency(wanted, STEAMGRIDDB_CONCURRENCY, async candidate => {
    try {
      const artworks = await steamGridClient.findArtwork(candidate.release.title);
      if (artworks.length > 0) artworksByIgdbId.set(candidate.igdbId, artworks);
    } catch {
      failed++;
    }
  });
  return { artworksByIgdbId, failed };
}
