import { confirmAndDelete, type DeletionResult } from "./collectionDeletion";
import type { Dialogs } from "./appShell";

export type ReleaseDeletionMode = "delete" | "delete-block";

interface DeletableRelease {
  id: string;
  title: string;
}

interface ReleaseDeletionDeps extends Pick<Dialogs, "confirm" | "alert"> {
  deleteRelease(id: string, block: boolean): Promise<unknown>;
  log(event: string, details: Record<string, unknown>): void;
}

// Upcoming's delete modes on top of the shared collection deletion: plain delete, or delete and block
// the game from future syncs.
export function deleteOneRelease(release: DeletableRelease, mode: ReleaseDeletionMode, deps: ReleaseDeletionDeps): Promise<DeletionResult> {
  return confirmAndDelete([release], {
    scope: "single",
    action: mode,
    confirmMessage: mode === "delete-block"
      ? `Delete "${release.title}" and block it from future syncs?`
      : `Delete "${release.title}"?`,
    ...transport(mode, deps)
  });
}

export function deleteManyReleases(releases: DeletableRelease[], mode: ReleaseDeletionMode, deps: ReleaseDeletionDeps): Promise<DeletionResult> {
  return confirmAndDelete(releases, {
    scope: "bulk",
    action: mode === "delete-block" ? "bulk-delete-block" : "bulk-delete",
    confirmMessage: mode === "delete-block"
      ? `Delete and block ${releases.length} selected releases?`
      : `Delete ${releases.length} selected releases?`,
    ...transport(mode, deps)
  });
}

function transport(mode: ReleaseDeletionMode, deps: ReleaseDeletionDeps) {
  return {
    deleteOne: (release: DeletableRelease) => deps.deleteRelease(release.id, mode === "delete-block"),
    dialogs: deps,
    log: deps.log
  };
}
