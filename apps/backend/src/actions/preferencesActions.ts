import type { TrackerDatabase } from "../database/db";
import { runWrite } from "../database/writeQueue";
import { createSettingsStore } from "../settings/settingsStore";
import type { ActionResult } from "./actionResult";

// App-wide look-and-feel choices, kept in app data so they don't depend on the renderer's localStorage.
const PALETTE_ID = /^[a-z0-9][a-z0-9-]{0,39}$/;

export function readPreferences(db: TrackerDatabase) {
  const settings = createSettingsStore(db);
  return { palette: settings.palette(), themeAutoplay: settings.themeAutoplay() };
}

export async function saveThemeAutoplay(db: TrackerDatabase, body: unknown): Promise<ActionResult<{ themeAutoplay: boolean }>> {
  const themeAutoplay = (body as { themeAutoplay?: unknown } | null)?.themeAutoplay;
  if (typeof themeAutoplay !== "boolean") return { ok: false, statusCode: 400, error: "Theme autoplay must be on or off" };
  await runWrite(db, () => createSettingsStore(db).setThemeAutoplay(themeAutoplay));
  return { ok: true, value: { themeAutoplay } };
}

export async function savePalette(db: TrackerDatabase, body: unknown): Promise<ActionResult<{ palette: string }>> {
  const palette = (body as { palette?: unknown } | null)?.palette;
  if (typeof palette !== "string" || !PALETTE_ID.test(palette)) return { ok: false, statusCode: 400, error: "Palette must be a palette id" };
  await runWrite(db, () => createSettingsStore(db).setPalette(palette));
  return { ok: true, value: { palette } };
}
