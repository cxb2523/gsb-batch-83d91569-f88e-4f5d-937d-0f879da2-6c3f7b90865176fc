interface StartAtLoginState {
  supported: boolean;
  platform: "windows" | "linux" | null;
  enabled: boolean;
}

interface ReleaseTrackerBridge {
  getApiBaseUrl?(): Promise<string>;
  getApiToken?(): Promise<string>;
  getDiagnosticsLogPath?(): Promise<string>;
  openDiagnosticsLog?(): Promise<{ ok?: boolean; error?: string }>;
  chooseWallpaper?(): Promise<string | null>;
  // Saves PNG bytes the page drew (the Year in Review poster) through a save dialog. Desktop only.
  saveImage?(png: Uint8Array, suggestedName: string): Promise<{ ok: boolean; canceled?: boolean; path?: string; error?: string }>;
  openLogFolder?(): Promise<{ ok: boolean; error?: string }>;
  // Asks the user to confirm, deletes everything the app stored on this computer and restarts. Desktop only.
  deleteAppData?(): Promise<{ ok: boolean; canceled?: boolean; error?: string }>;
  // Start with Windows (or the Linux session), straight into the tray. Packaged desktop app only.
  getStartAtLogin?(): Promise<StartAtLoginState>;
  setStartAtLogin?(on: boolean): Promise<StartAtLoginState>;
  // Calls back with a release id when the user clicks a release alert. Returns the unsubscribe function.
  onOpenRelease?(callback: (releaseId: string) => void): () => void;
}

interface Window {
  releaseTracker?: ReleaseTrackerBridge;
}
