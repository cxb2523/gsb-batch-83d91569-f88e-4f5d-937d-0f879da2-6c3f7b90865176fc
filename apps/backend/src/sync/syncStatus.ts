import { sqliteUtcMs } from "../../../../shared/sqliteTime";
import type { TrackerDatabase } from "../database/db";
import type { SyncStatus } from "../../../../shared/types";
import { createSyncSettingsStore } from "./syncSettingsStore";

export function getSyncStatus(db: TrackerDatabase): SyncStatus {
  const row = db.prepare("select * from sync_runs order by id desc limit 1").get() as Record<string, unknown> | undefined;
  if (!row) return { status: "idle", added: 0, repaired: 0, skipped: 0, failed: 0 };
  return {
    status: row.status as SyncStatus["status"],
    added: Number(row.added),
    repaired: Number(row.repaired),
    skipped: Number(row.skipped),
    failed: Number(row.failed),
    lastSuccessfulSyncAt: row.status === "success" ? String(row.finished_at) : null,
    message: row.message ? String(row.message) : undefined
  };
}

// Called after a run finishes, in the same runWrite transaction as its status update.
export function trimSyncLog(db: TrackerDatabase) {
  db.prepare(`
    delete from sync_log
    where sync_run_id is null
       or sync_run_id not in (select id from sync_runs order by id desc limit 20)
  `).run();
}

// A run still marked running when the backend starts was cut off by the app closing mid-sync.
export function failInterruptedSyncRuns(db: TrackerDatabase) {
  db.prepare("update sync_runs set status = 'failed', message = 'interrupted', finished_at = current_timestamp where status = 'running'").run();
}

export function shouldAutoSync(db: TrackerDatabase, staleHours = 12) {
  if (!createSyncSettingsStore(db).read().autoSync) return false;
  const row = db.prepare("select finished_at from sync_runs where status = 'success' order by id desc limit 1").get() as { finished_at?: string } | undefined;
  if (!row?.finished_at) return true;
  return Date.now() - sqliteUtcMs(row.finished_at) > staleHours * 60 * 60 * 1000;
}
