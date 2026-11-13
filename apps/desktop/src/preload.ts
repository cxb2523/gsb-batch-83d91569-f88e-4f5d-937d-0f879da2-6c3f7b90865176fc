import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("releaseTracker", {
  getApiBaseUrl: () => ipcRenderer.invoke("api-base-url"),
  getApiToken: () => ipcRenderer.invoke("api-token"),
  getDiagnosticsLogPath: () => ipcRenderer.invoke("diagnostics-log-path"),
  openDiagnosticsLog: () => ipcRenderer.invoke("open-diagnostics-log"),
  chooseWallpaper: () => ipcRenderer.invoke("choose-wallpaper"),
  saveImage: (png: Uint8Array, suggestedName: string) => ipcRenderer.invoke("save-image", png, suggestedName),
  openLogFolder: () => ipcRenderer.invoke("open-log-folder"),
  deleteAppData: () => ipcRenderer.invoke("delete-app-data"),
  getStartAtLogin: () => ipcRenderer.invoke("start-at-login"),
  setStartAtLogin: (on: boolean) => ipcRenderer.invoke("set-start-at-login", on),
  // A clicked release alert asks the page to open that game. Returns the unsubscribe function.
  onOpenRelease: (callback: (releaseId: string) => void) => {
    const listener = (_event: unknown, releaseId: unknown) => {
      if (typeof releaseId === "string") callback(releaseId);
    };
    ipcRenderer.on("open-release", listener);
    return () => ipcRenderer.removeListener("open-release", listener);
  }
});
