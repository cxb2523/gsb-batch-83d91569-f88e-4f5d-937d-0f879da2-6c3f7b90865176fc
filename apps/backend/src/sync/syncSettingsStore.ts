import { ALL_PLATFORM_FAMILIES, PLATFORM_FAMILIES } from "../../../../shared/constants";
import type { PlatformFamily, SyncSettings, SyncSettingsPatch, TrackedPublisher } from "../../../../shared/types";
import type { TrackerDatabase } from "../database/db";

const PLATFORMS_KEY = "SYNC_PLATFORMS";
const TRACK_FROM_KEY = "SYNC_TRACK_FROM";
const AUTO_SYNC_KEY = "SYNC_AUTO";
const ALERTS_KEY = "SYNC_ALERTS";

// The user's sync settings: tracked publishers (their own table) and the platform, date and auto-sync
// choices (rows of `settings`). Reads fill in the defaults for anything never saved.
export function createSyncSettingsStore(db: TrackerDatabase, today: () => Date = () => new Date()) {
  const readValue = (key: string) => (db.prepare("select value from settings where key = ?").get(key) as { value: string | null } | undefined)?.value ?? null;
  const writeValue = (key: string, value: string) => {
    db.prepare("insert or replace into settings (key, value, updated_at) values (?, ?, current_timestamp)").run(key, value);
  };

  return {
    read(): SyncSettings {
      const platforms = parsePlatforms(readValue(PLATFORMS_KEY));
      return {
        publishers: db.prepare("select company_id id, name from tracked_publishers order by name collate nocase").all() as TrackedPublisher[],
        platforms: platforms ?? [...ALL_PLATFORM_FAMILIES],
        trackFrom: readValue(TRACK_FROM_KEY) ?? `${today().getUTCFullYear()}-01-01`,
        autoSync: readValue(AUTO_SYNC_KEY) === "1",
        alerts: readValue(ALERTS_KEY) !== "0"
      };
    },

    update(patch: SyncSettingsPatch) {
      if (patch.platforms !== undefined) writeValue(PLATFORMS_KEY, JSON.stringify(patch.platforms));
      if (patch.trackFrom !== undefined) writeValue(TRACK_FROM_KEY, patch.trackFrom);
      if (patch.autoSync !== undefined) writeValue(AUTO_SYNC_KEY, patch.autoSync ? "1" : "0");
      if (patch.alerts !== undefined) writeValue(ALERTS_KEY, patch.alerts ? "1" : "0");
    },

    addPublishers(publishers: TrackedPublisher[]) {
      const insert = db.prepare("insert into tracked_publishers (company_id, name) values (?, ?) on conflict(company_id) do update set name = excluded.name");
      for (const publisher of publishers) insert.run(publisher.id, publisher.name);
    },

    removePublisher(id: number) {
      return db.prepare("delete from tracked_publishers where company_id = ?").run(id).changes > 0;
    }
  };
}

// The patch a request body describes, or an error message for the form.
export function parseSyncSettingsPatch(body: unknown): { ok: true; patch: SyncSettingsPatch } | { ok: false; error: string } {
  if (!body || typeof body !== "object") return { ok: false, error: "Expected a settings object" };
  const input = body as Record<string, unknown>;
  const patch: SyncSettingsPatch = {};
  if (input.platforms !== undefined) {
    const platforms = Array.isArray(input.platforms) ? input.platforms : null;
    if (!platforms || platforms.length === 0 || !platforms.every(isPlatformFamily)) return { ok: false, error: "Choose at least one platform" };
    patch.platforms = [...new Set(platforms)];
  }
  if (input.trackFrom !== undefined) {
    if (typeof input.trackFrom !== "string" || !isIsoDate(input.trackFrom)) return { ok: false, error: "Track-from must be a date like 2026-01-01" };
    patch.trackFrom = input.trackFrom;
  }
  if (input.autoSync !== undefined) {
    if (typeof input.autoSync !== "boolean") return { ok: false, error: "Auto-sync must be on or off" };
    patch.autoSync = input.autoSync;
  }
  if (input.alerts !== undefined) {
    if (typeof input.alerts !== "boolean") return { ok: false, error: "Alerts must be on or off" };
    patch.alerts = input.alerts;
  }
  return { ok: true, patch };
}

function parsePlatforms(value: string | null): PlatformFamily[] | null {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    return Array.isArray(parsed) && parsed.length > 0 && parsed.every(isPlatformFamily) ? parsed : null;
  } catch {
    return null;
  }
}

function isPlatformFamily(value: unknown): value is PlatformFamily {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(PLATFORM_FAMILIES, value);
}

function isIsoDate(value: string) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && !Number.isNaN(Date.parse(`${value}T00:00:00Z`)) && new Date(`${value}T00:00:00Z`).toISOString().startsWith(value);
}
