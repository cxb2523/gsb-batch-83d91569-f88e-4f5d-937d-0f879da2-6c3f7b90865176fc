import { writeFile } from "node:fs/promises";
import { join } from "node:path";
import type { SaveDialogOptions } from "electron";

type SaveImageResult = { ok: true; path: string } | { ok: false; canceled: true } | { ok: false; error: string };

interface SaveDialog {
  showSaveDialog(options: SaveDialogOptions): Promise<{ canceled: boolean; filePath?: string }>;
}

export type SaveImageIpcEvent = { senderFrame?: { url?: string } | null };

const PNG_SIGNATURE = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a];
// A 1920×1920 poster is a few MB; anything past this is not one of ours.
const MAX_BYTES = 40 * 1024 * 1024;

// The bytes as a Buffer when they are a PNG of a sane size, otherwise null.
export function pngBytes(data: unknown): Buffer | null {
  if (!(data instanceof Uint8Array) || data.length < PNG_SIGNATURE.length || data.length > MAX_BYTES) return null;
  return PNG_SIGNATURE.every((byte, index) => data[index] === byte) ? Buffer.from(data) : null;
}

// A plain file name: no folders, no characters Windows refuses, always .png.
export function safeImageName(name: string) {
  const base = String(name ?? "")
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, " ")
    .replace(/\.{2,}/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\.+/, "")
    .slice(0, 120)
    .trim();
  return `${base || "Year in Review"}.png`;
}

// Saves a PNG the page drew (the Year in Review poster) where the user chooses.
export async function saveImage({ dialog, defaultDir, data, suggestedName }: {
  dialog: SaveDialog;
  defaultDir: string;
  data: unknown;
  suggestedName: string;
}): Promise<SaveImageResult> {
  const png = pngBytes(data);
  if (!png) return { ok: false, error: "That isn't a PNG image" };
  const choice = await dialog.showSaveDialog({
    defaultPath: join(defaultDir, safeImageName(suggestedName)),
    filters: [{ name: "PNG image", extensions: ["png"] }]
  });
  if (choice.canceled || !choice.filePath) return { ok: false, canceled: true };
  const path = /\.png$/i.test(choice.filePath) ? choice.filePath : `${choice.filePath}.png`;
  await writeFile(path, png);
  return { ok: true, path };
}

// "save-image" writes a PNG through a save dialog. Like the API token, it answers only a frame that is
// showing the app itself.
export function registerSaveImageIpc({ ipcMain, dialog, getDefaultDir, isAppFrame }: {
  ipcMain: { handle(channel: string, handler: (event: SaveImageIpcEvent, ...args: unknown[]) => unknown): void };
  dialog: SaveDialog;
  getDefaultDir(): string;
  isAppFrame(url: string): boolean;
}) {
  ipcMain.handle("save-image", async (event, data, suggestedName) => {
    if (!isAppFrame(event.senderFrame?.url ?? "")) return { ok: false, error: "Refused" };
    return saveImage({ dialog, defaultDir: getDefaultDir(), data, suggestedName: String(suggestedName ?? "") });
  });
}
