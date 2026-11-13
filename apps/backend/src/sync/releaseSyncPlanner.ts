import type { IgdbGameLike, NormalizedRelease, ReleaseArtwork } from "../../../../shared/types";
import type { ExistingReleaseMergeState } from "./releaseMerge";
import { mergeReleaseForPersistence } from "./releaseMerge";
import type { ReleasePolicy } from "./releasePolicy";

// An IGDB game after the sync rules, decided once per run and shared by artwork enrichment and saving.
export type SyncCandidate =
  | { igdbId: number; title: string; accepted: false; reason: string }
  | { igdbId: number; title: string; accepted: true; release: NormalizedRelease };

export function prepareSyncCandidate(game: IgdbGameLike, policy: ReleasePolicy): SyncCandidate {
  const decision = policy.evaluate(game);
  if (!decision.accepted) return { igdbId: game.id, title: game.name, accepted: false, reason: decision.reasons.join("; ") };
  return { igdbId: game.id, title: game.name, accepted: true, release: policy.normalize(game) };
}

type ReleaseSyncPlan =
  | { action: "skip"; title: string; reason: string }
  | { action: "save"; title: string; release: NormalizedRelease; outcome: "added" | "repaired" | "unchanged" };

interface ReleaseSyncPlanInput {
  candidate: SyncCandidate;
  blocked: boolean;
  existedBefore: boolean;
  existing: ExistingReleaseMergeState | null;
  enrichedArtworks: ReleaseArtwork[];
  // The Release row this IGDB game maps to; defaults to igdb-<id>.
  releaseId?: string;
}

export function planReleaseSync(input: ReleaseSyncPlanInput): ReleaseSyncPlan {
  const { candidate } = input;
  if (input.blocked) return { action: "skip", title: candidate.title, reason: "manually blocked" };
  if (!candidate.accepted) return { action: "skip", title: candidate.title, reason: candidate.reason };

  let release = candidate.release;
  if (input.releaseId) release = { ...release, id: input.releaseId };
  if (input.enrichedArtworks.length > 0 && shouldEnrichArtwork(release.artworks)) {
    release = { ...release, artworks: [...release.artworks, ...input.enrichedArtworks] };
  }
  const merged = mergeReleaseForPersistence(release, input.existing);
  const changedByMerge = JSON.stringify(merged) !== JSON.stringify(release);
  const enriched = input.enrichedArtworks.length > 0;

  if (!input.existedBefore) {
    return { action: "save", title: candidate.title, release: merged, outcome: enriched || changedByMerge ? "repaired" : "added" };
  }
  return {
    action: "save",
    title: candidate.title,
    release: merged,
    outcome: enriched || changedByMerge ? "repaired" : "unchanged"
  };
}

// True when an accepted candidate, merged with what is already stored, still has no provider artwork
// beyond IGDB's own.
export function needsArtworkEnrichment(candidate: SyncCandidate, existing: ExistingReleaseMergeState | null) {
  return candidate.accepted && shouldEnrichArtwork(mergeReleaseForPersistence(candidate.release, existing).artworks);
}

function shouldEnrichArtwork(artworks: ReleaseArtwork[]) {
  return artworks.length === 0 || artworks.every(artwork => artwork.source === "artwork" || !artwork.source);
}
