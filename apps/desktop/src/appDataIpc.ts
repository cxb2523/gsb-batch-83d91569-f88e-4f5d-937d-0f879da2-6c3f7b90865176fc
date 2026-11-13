import { readdirSync, rmSync } from "node:fs";
import { join } from "node:path";
import type { IpcMain } from "electron";

// What the app itself keeps in its data folder. Chromium's own profile folders (Cache, Local Storage, ...)
// can sit beside them and are cleared through the session instead, since the running browser holds them.
const APP_ENTRIES = ["game-release-tracker.db", "game-release-tracker.db-wal", "game-release-tracker.db-shm", "artworks", "covers", "wallpaper", "backups", "logs"];
const isCredentialKeyFile = (name: string) => name.startsWith("credential-key.bin");

// Settings → Diagnostics → Delete all app data: the library, covers, wallpaper, saved keys, backups and
// logs, after the user confirms. The backend is stopped first so the database is closed, and the app
// restarts as a new install.
export async function deleteAppData({ dataDir, confirm, stopBackend, clearBrowserStorage, relaunch }: {
  dataDir: string;
  confirm: () => Promise<boolean>;
  stopBackend: () => Promise<void>;
  clearBrowserStorage: () => Promise<void>;
  relaunch: () => void;
}): Promise<{ ok: true } | { ok: false; canceled: true }> {
  if (!(await confirm())) return { ok: false, canceled: true };
  await stopBackend();
  for (const name of readdirSync(dataDir)) {
    if (APP_ENTRIES.includes(name) || isCredentialKeyFile(name)) rmSync(join(dataDir, name), { recursive: true, force: true });
  }
  await clearBrowserStorage();
  relaunch();
  return { ok: true };
}

export type AppDataIpcEvent = { senderFrame?: { url?: string } | null };

type DeleteSteps = Omit<Parameters<typeof deleteAppData>[0], "dataDir">;

export function registerAppDataIpc({ ipcMain, isAppFrame, getDataDir, openLogFolder, steps }: {
  ipcMain: Pick<IpcMain, "handle">;
  isAppFrame: (url: string) => boolean;
  getDataDir: () => string;
  // Resolves to an error message, or "" when the folder opened.
  openLogFolder: () => Promise<string>;
  steps: DeleteSteps;
}) {
  // Only the app's own page may ask; anything else gets a refusal, never a deletion.
  ipcMain.handle("delete-app-data", (event: AppDataIpcEvent) => {
    if (!isAppFrame(event.senderFrame?.url ?? "")) return { ok: false, error: "Not allowed" };
    return deleteAppData({ dataDir: getDataDir(), ...steps });
  });
  ipcMain.handle("open-log-folder", async () => {
    const error = await openLogFolder();
    return { ok: !error, error: error || undefined };
  });
}
