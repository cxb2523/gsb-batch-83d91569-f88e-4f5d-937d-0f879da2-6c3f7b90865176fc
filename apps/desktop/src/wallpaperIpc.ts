import type { BrowserWindow, Dialog, IpcMain, OpenDialogOptions } from "electron";
import { saveWallpaperFromFile } from "../../runtime/src/wallpaperStorage";

interface WallpaperIpcOptions {
  ipcMain: IpcMain;
  dialog: Pick<Dialog, "showOpenDialog">;
  getWindow(): BrowserWindow | null;
  getDataDir(): string;
}

export function registerWallpaperIpc({ ipcMain, dialog, getWindow, getDataDir }: WallpaperIpcOptions) {
  ipcMain.handle("choose-wallpaper", async () => chooseWallpaperFromDesktop({
    dialog,
    window: getWindow(),
    dataDir: getDataDir()
  }));
}

export async function chooseWallpaperFromDesktop({
  dialog,
  window,
  dataDir
}: {
  dialog: Pick<Dialog, "showOpenDialog">;
  window: BrowserWindow | null;
  dataDir: string;
}) {
  const options: OpenDialogOptions = {
    properties: ["openFile"],
    filters: [{ name: "Images", extensions: ["jpg", "jpeg", "png", "webp", "bmp", "gif"] }]
  };
  const result = window
    ? await dialog.showOpenDialog(window, options)
    : await dialog.showOpenDialog(options);
  if (result.canceled || result.filePaths.length === 0) return null;
  return saveWallpaperFromFile(dataDir, result.filePaths[0]).url;
}
