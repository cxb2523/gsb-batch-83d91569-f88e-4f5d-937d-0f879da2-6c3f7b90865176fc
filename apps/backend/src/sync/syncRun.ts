import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import { createIgdbGateway, type IgdbGateway } from "../igdb/gateway";
import { createSettingsStore } from "../settings/settingsStore";
import type { IgdbGameLike, ReleaseArtwork, SyncStatus } from "../../../../shared/types";
import { discoverIgdbCandidates } from "./igdbCandidateSource";
import { createReleasePolicy } from "./releasePolicy";
import { createSyncSettingsStore } from "./syncSettingsStore";
import { planReleaseSync, prepareSyncCandidate, type SyncCandidate } from "./releaseSyncPlanner";
import { getSyncStatus, trimSyncLog } from "./syncStatus";
import { createReleaseStore } from "../database/releaseStore";
import { readDateSnapshot, recordDateChange } from "../releaseDates/dateChanges";
import { fetchSyncArtworkEnrichment, type SyncArtworkClient, type SyncArtworkEnrichment } from "./syncArtworkEnrichment";

interface SyncOptions {
  steamGridClient?: SyncArtworkClient;
}

interface SyncCounters {
  added: number;
  repaired: number;
  skipped: number;
  failed: number;
}

export function runSync(db: TrackerDatabase, candidates?: IgdbGameLike[], igdb?: IgdbGateway, options?: SyncOptions): Promise<SyncStatus> {
  return new SyncRun(db, candidates, igdb, options).execute();
}

let running: Promise<SyncStatus> | null = null;

export function startSync(db: TrackerDatabase, candidates?: IgdbGameLike[], igdb?: IgdbGateway, options?: SyncOptions) {
  if (running) return running;
  running = runSync(db, candidates, igdb, options).finally(() => {
    running = null;
  });
  return running;
}

class SyncRun {
  constructor(
    private readonly db: TrackerDatabase,
    private readonly candidates?: IgdbGameLike[],
    private readonly igdb?: IgdbGateway,
    private readonly options?: SyncOptions
  ) {}

  async execute(): Promise<SyncStatus> {
    const syncRunId = await this.startRun();
    try {
      const settings = createSyncSettingsStore(this.db).read();
      const rules = { publisherIds: settings.publishers.map(publisher => publisher.id), platforms: settings.platforms, trackFrom: settings.trackFrom };
      const candidates = await this.discoverCandidates(syncRunId, rules);
      if (!candidates.ok) return candidates.status;
      const policy = createReleasePolicy(rules);
      const prepared = candidates.items.map(game => prepareSyncCandidate(game, policy));
      const enrichment = await this.fetchSteamGridEnrichment(prepared);
      return await this.persistCandidates(syncRunId, prepared, enrichment);
    } catch (error) {
      // Whatever went wrong, the run must not stay marked as running.
      return runWrite(this.db, () => this.failRun(syncRunId, { added: 0, repaired: 0, skipped: 0, failed: 1 }, error));
    }
  }

  private startRun() {
    return runWrite(this.db, () => {
      const info = this.db.prepare("insert into sync_runs (status, message) values ('running', 'Sync started')").run();
      return Number(info.lastInsertRowid);
    });
  }

  private async discoverCandidates(syncRunId: number, rules: { publisherIds: number[]; trackFrom: string }): Promise<{ ok: true; items: IgdbGameLike[] } | { ok: false; status: SyncStatus }> {
    try {
      return { ok: true, items: this.candidates ?? await this.fetchIgdbCandidates(rules) };
    } catch (error) {
      const status = await runWrite(this.db, () => {
        this.db.prepare(`
          update sync_runs set status = 'failed', finished_at = current_timestamp, failed = 1, message = ?
          where id = ?
        `).run(error instanceof Error ? error.message : String(error), syncRunId);
        trimSyncLog(this.db);
        return getSyncStatus(this.db);
      });
      return { ok: false, status };
    }
  }

  private fetchIgdbCandidates(rules: { publisherIds: number[]; trackFrom: string }): Promise<IgdbGameLike[]> {
    const igdb = this.igdb ?? createIgdbGateway({ readConfig: () => createSettingsStore(this.db).igdbTokenConfig() });
    return discoverIgdbCandidates(igdb, rules);
  }

  private fetchSteamGridEnrichment(candidates: SyncCandidate[]) {
    return fetchSyncArtworkEnrichment(this.db, candidates, this.options?.steamGridClient);
  }

  private persistCandidates(syncRunId: number, candidates: SyncCandidate[], enrichment: SyncArtworkEnrichment) {
    // Each game saves in its own savepoint: one that fails is rolled back and counted, the rest are kept.
    return runWrite(this.db, () => {
      const counters: SyncCounters = { added: 0, repaired: 0, skipped: 0, failed: enrichment.failed };
      const saveOne = this.db.transaction((candidate: SyncCandidate) => this.persistCandidate(syncRunId, candidate, enrichment.artworksByIgdbId, counters));
      for (const candidate of candidates) {
        try {
          saveOne(candidate);
        } catch (error) {
          counters.failed++;
          log(this.db, syncRunId, candidate.title ?? `IGDB #${candidate.igdbId}`, "error", error instanceof Error ? error.message : String(error));
        }
      }
      return this.finishRun(syncRunId, counters);
    });
  }

  // Reads the stored state again inside the write queue: the user may have edited the release while
  // artwork enrichment was running.
  private persistCandidate(syncRunId: number, candidate: SyncCandidate, artworksByIgdbId: Map<number, ReleaseArtwork[]>, counters: SyncCounters) {
    const releaseStore = createReleaseStore(this.db);
    const releaseId = releaseStore.idForIgdbGame(candidate.igdbId);
    const existedBefore = releaseStore.exists(releaseId);
    const plan = planReleaseSync({
      candidate,
      releaseId,
      blocked: releaseStore.isBlocked(candidate.igdbId, candidate.title),
      existedBefore,
      existing: candidate.accepted ? releaseStore.loadMergeState(releaseId, candidate.release.normalizedTitle) : null,
      enrichedArtworks: artworksByIgdbId.get(candidate.igdbId) ?? []
    });

    if (plan.action === "skip") {
      counters.skipped++;
      log(this.db, syncRunId, plan.title, "reject", plan.reason);
      return;
    }
    const dateBefore = existedBefore ? readDateSnapshot(this.db, releaseId) : null;
    releaseStore.save(plan.release);
    const dateAfter = dateBefore ? readDateSnapshot(this.db, releaseId) : null;
    if (dateBefore && dateAfter) recordDateChange(this.db, releaseId, dateBefore, dateAfter, syncRunId);
    log(this.db, syncRunId, plan.title, "accept", "matched sync rules");
    if (plan.outcome === "added") {
      counters.added++;
    } else if (plan.outcome === "repaired") {
      if (!existedBefore) counters.added++;
      counters.repaired++;
    } else {
      counters.skipped++;
    }
  }

  private finishRun(syncRunId: number, counters: SyncCounters) {
    const status = counters.failed > 0 ? "partial" : "success";
    const message = counters.failed > 0 ? `Sync complete with ${counters.failed} ${counters.failed === 1 ? "failure" : "failures"}; see the sync log` : "Sync complete";
    this.db.prepare("update sync_runs set status = ?, finished_at = current_timestamp, added = ?, repaired = ?, skipped = ?, failed = ?, message = ? where id = ?").run(status, counters.added, counters.repaired, counters.skipped, counters.failed, message, syncRunId);
    trimSyncLog(this.db);
    return getSyncStatus(this.db);
  }

  private failRun(syncRunId: number, counters: SyncCounters, error: unknown) {
    this.db.prepare("update sync_runs set status = 'failed', finished_at = current_timestamp, added = ?, repaired = ?, skipped = ?, failed = ?, message = ? where id = ?").run(counters.added, counters.repaired, counters.skipped, counters.failed, error instanceof Error ? error.message : String(error), syncRunId);
    trimSyncLog(this.db);
    return getSyncStatus(this.db);
  }
}

function log(db: TrackerDatabase, syncRunId: number, title: string, action: string, reason: string) {
  db.prepare("insert into sync_log (sync_run_id, title, action, reason) values (?, ?, ?, ?)").run(syncRunId, title, action, reason);
}
