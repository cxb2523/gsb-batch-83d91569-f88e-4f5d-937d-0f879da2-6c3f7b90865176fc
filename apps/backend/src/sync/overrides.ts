import { readFileSync } from "node:fs";
import type { TrackerDatabase } from "../database/db";
import { createReleaseStore, type OverrideSeed } from "../database/releaseStore";
import { enqueueWrite } from "../database/writeQueue";
import { createSettingsStore } from "../settings/settingsStore";

export async function seedOverrides(db: TrackerDatabase, path: string) {
  const releaseStore = createReleaseStore(db);
  const parsed = JSON.parse(readFileSync(path, "utf8")) as { version: number; overrides: OverrideSeed[] };
  return enqueueWrite(() => {
    const settings = createSettingsStore(db);
    if (settings.sourceOverrideVersion() === String(parsed.version)) return 0;
    const tx = db.transaction(() => {
      let count = 0;
      for (const seed of parsed.overrides) count += releaseStore.applySeed(seed);
      settings.setSourceOverrideVersion(String(parsed.version));
      return count;
    });
    return tx();
  });
}
