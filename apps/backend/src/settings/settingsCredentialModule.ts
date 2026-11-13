import type { TrackerDatabase } from "../database/db";
import { getSyncStatus, shouldAutoSync } from "../sync/syncStatus";
import { getAppCredentialStatus } from "../igdb/token";
import { hasIgdbCredentials, type IgdbGateway } from "../igdb/gateway";
import { runWrite } from "../database/writeQueue";
import { createSettingsStore } from "./settingsStore";

export function updateSettingsCredentials(db: TrackerDatabase, payload: Record<string, string | undefined>) {
  return runWrite(db, () => {
    createSettingsStore(db).saveCredentials(payload ?? {});
    return { ok: true, settings: readSettingsStatus(db) };
  });
}

export function clearSettingsCredentials(db: TrackerDatabase) {
  return runWrite(db, () => {
    createSettingsStore(db).clearCredentials();
    return { ok: true, settings: readSettingsStatus(db) };
  });
}

// What the Settings page shows: credential readiness (never the values), which keys are saved, and
// whether an automatic sync is due.
export function readSettingsStatus(db: TrackerDatabase) {
  const settings = createSettingsStore(db);
  const syncStatus = getSyncStatus(db);
  return {
    credentialStatus: getAppCredentialStatus(settings.igdbTokenConfig(), syncStatus.status === "failed" ? syncStatus.message : null),
    autoSyncDue: shouldAutoSync(db),
    credentials: settings.savedCredentials()
  };
}

// Checks the saved credentials with a real IGDB request through the app's own gateway, so the test and
// the app share one client and one token.
export async function testSettingsCredentials(db: TrackerDatabase, igdb: Pick<IgdbGateway, "validateCredentials">) {
  const config = createSettingsStore(db).igdbTokenConfig();
  if (!hasIgdbCredentials(config)) return { credentialStatus: { status: "missing" } };
  try {
    await igdb.validateCredentials();
    return { credentialStatus: { status: "ready" } };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { credentialStatus: getAppCredentialStatus(config, message) };
  }
}
