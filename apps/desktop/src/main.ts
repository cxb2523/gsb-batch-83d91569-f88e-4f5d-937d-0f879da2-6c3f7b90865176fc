import { randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, net, Notification, protocol, safeStorage, session, shell, Tray } from "electron";
import { APP_ORIGIN, handleAppProtocol, identifyAppToYouTube, registerAppScheme } from "./appProtocol";
import { type BackendChild, startBackendProcess, stopBackendProcess } from "./backendProcess";
import { handleStartupFailure, logBackendStoppedBeforeQuit, logDesktopFatalStartup, logDesktopProcessFailure, prepareDesktopRuntime } from "./desktopLifecycle";
import { registerWallpaperIpc } from "./wallpaperIpc";
import { registerSaveImageIpc } from "./saveImageIpc";
import { registerAppDataIpc } from "./appDataIpc";
import { decideNavigation, installWindowGuards } from "./windowGuards";
import { loadCredentialDataKey } from "./credentialKey";
import { type AppTray, bringWindowBack, installMinimizeToTray } from "./trayWindow";
import { createSystemNotifier, startReleaseAlerts } from "./releaseAlerts";
import { createStartAtLogin, registerStartAtLoginIpc, startsHidden } from "./startAtLogin";
import type { ReleaseAlert } from "../../../shared/types";
import { API_TOKEN_HEADER } from "../../../shared/constants";
import { createFileDiagnosticLogger } from "../../backend/src/diagnostics/logger";

let mainWindow: BrowserWindow | null = null;
// Held for the app's lifetime: a tray icon that is garbage-collected disappears.
let tray: AppTray | null = null;
let backend: BackendChild | null = null;
let apiBaseUrl = "";
let logPath = "";
let diagnosticsLogPath = "";
let dataDir = "";
let frontendDevUrl = "";
let backendShutdownStarted = false;
let fatalDialogShown = false;
// A fresh secret each launch: the backend refuses /api calls without it, so web pages and other local
// programs cannot use the local API. Only this app's renderer receives it, through the preload.
const apiToken = randomBytes(32).toString("hex");

// The data folder is named after the app (on Windows %APPDATA%\Game Release Tracker), not after the npm
// package, so the app never shares a folder with another build of the same package. Set before anything
// reads userData. An explicit --user-data-dir (a test profile) still wins.
// Windows shows notifications under this id (the installer's shortcut carries the same one).
if (process.platform === "win32") app.setAppUserModelId("io.github.hachi23.game-release-tracker");
if (!app.commandLine.hasSwitch("user-data-dir")) app.setPath("userData", join(app.getPath("appData"), "Game Release Tracker"));
registerAppScheme(protocol);

const gotLock = app.requestSingleInstanceLock();
if (!gotLock) app.quit();

// Starting the app again brings the running window back, even from the tray. This is also the way back
// on Linux desktops that do not show tray icons.
app.on("second-instance", () => bringWindowBack(mainWindow));

// The packaged renderer reaches the backend through its own app:// origin; the development renderer
// (the Vite server) calls the backend directly.
const rendererOrigin = () => (app.isPackaged ? APP_ORIGIN : frontendDevUrl);
ipcMain.handle("api-base-url", () => (app.isPackaged ? APP_ORIGIN : apiBaseUrl));
// A frame showing the app itself, the only kind that gets the token or can save an image.
const isAppFrame = (url: string) => decideNavigation(url, rendererOrigin()) === "allow";
ipcMain.handle("api-token", event => (isAppFrame(event.senderFrame?.url ?? "") ? apiToken : null));
registerSaveImageIpc({
  ipcMain,
  dialog: { showSaveDialog: options => (mainWindow ? dialog.showSaveDialog(mainWindow, options) : dialog.showSaveDialog(options)) },
  getDefaultDir: () => app.getPath("pictures"),
  isAppFrame
});
ipcMain.handle("diagnostics-log-path", () => diagnosticsLogPath);
ipcMain.handle("open-diagnostics-log", async () => {
  if (!diagnosticsLogPath) return { ok: false, error: "Diagnostics log path is not available yet" };
  const error = await shell.openPath(diagnosticsLogPath);
  return { ok: !error, path: diagnosticsLogPath, error: error || undefined };
});
registerAppDataIpc({
  ipcMain,
  isAppFrame,
  getDataDir: () => dataDir,
  openLogFolder: () => (diagnosticsLogPath ? shell.openPath(dirname(diagnosticsLogPath)) : Promise.resolve("The log folder is not available yet")),
  steps: {
    confirm: async () => {
      const options = {
        type: "warning" as const,
        buttons: ["Delete everything", "Cancel"],
        defaultId: 1,
        cancelId: 1,
        message: "Delete all app data?",
        detail: "This removes your library, covers, wallpaper, saved API keys, backups and logs from this computer, then restarts the app. It can't be undone."
      };
      const { response } = mainWindow ? await dialog.showMessageBox(mainWindow, options) : await dialog.showMessageBox(options);
      return response === 0;
    },
    stopBackend: async () => {
      backendShutdownStarted = true;
      const running = backend;
      backend = null;
      await stopBackendProcess(running, 3000);
    },
    clearBrowserStorage: () => session.defaultSession.clearStorageData(),
    relaunch: () => {
      app.relaunch();
      app.exit(0);
    }
  }
});
registerStartAtLoginIpc({
  ipcMain,
  isAppFrame,
  startAtLogin: createStartAtLogin({
    platform: process.platform,
    packaged: app.isPackaged,
    launchPath: process.env.APPIMAGE || process.execPath,
    autostartDir: join(app.getPath("appData"), "autostart"),
    getLoginItemSettings: options => app.getLoginItemSettings(options),
    setLoginItemSettings: settings => app.setLoginItemSettings(settings)
  })
});
registerWallpaperIpc({
  ipcMain,
  dialog,
  getWindow: () => mainWindow,
  getDataDir: () => dataDir
});

function handleDesktopProcessFailure(event: string, error: unknown) {
  const message = logDesktopProcessFailure(app, event, error);
  console.error(`[${event}] ${message}`);
  if (!fatalDialogShown) {
    fatalDialogShown = true;
    dialog.showErrorBox("Game Release Tracker stopped unexpectedly", message);
  }
  app.quit();
}

process.on("uncaughtException", error => handleDesktopProcessFailure("process.uncaught_exception", error));
process.on("unhandledRejection", reason => handleDesktopProcessFailure("process.unhandled_rejection", reason));

async function createWindow() {
  const { root, layout, logPath: startupLogPath } = prepareDesktopRuntime(app);
  logPath = startupLogPath;
  diagnosticsLogPath = layout.diagnosticLogPath;
  dataDir = layout.backendDataDir;
  frontendDevUrl = layout.frontendDevUrl;
  // Start the backend first, then build the hidden window while it boots so the renderer
  // process spin-up overlaps backend startup instead of waiting behind it.
  const diagnostics = createFileDiagnosticLogger(layout.logDir);
  const credentialKey = loadCredentialDataKey({ dir: layout.backendDataDir, safeStorage, log: (event, details) => diagnostics.log(event, details) });
  const backendStarting = startBackendProcess(root, { logPath, dataDir: layout.backendDataDir, apiToken, credentialKey, packaged: app.isPackaged });
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 920,
    minHeight: 620,
    show: false,
    webPreferences: {
      preload: layout.preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // Year in Review's theme music may start without a click once the user turns autoplay on in Settings;
      // until then it waits for one.
      autoplayPolicy: "no-user-gesture-required",
      devTools: !app.isPackaged
    }
  });
  const window = mainWindow;
  tray = installMinimizeToTray({
    window,
    createTray: () => createAppTray(root),
    quit: () => app.quit(),
    log: message => diagnostics.log("desktop.tray_unavailable", { message })
  });
  // Links open in the browser; the app window only ever shows the app.
  installWindowGuards(mainWindow.webContents, {
    appOrigin: rendererOrigin,
    openExternal: url => shell.openExternal(url)
  });
  const backendReady = await backendStarting;
  backend = backendReady.child;
  const runningBackend = backend;
  runningBackend.once?.("exit", code => {
    if (backend !== runningBackend || backendShutdownStarted) return;
    backend = null;
    handleDesktopProcessFailure("backend.child_exit", new Error(`Backend exited unexpectedly${code === undefined ? "" : ` with code ${String(code)}`}`));
  });
  runningBackend.once?.("error", error => {
    if (backend !== runningBackend || backendShutdownStarted) return;
    backend = null;
    handleDesktopProcessFailure("backend.child_error", error);
  });
  const port = backendReady.port;
  apiBaseUrl = `http://127.0.0.1:${port}`;
  if (app.isPackaged) {
    handleAppProtocol(protocol, net, () => apiBaseUrl);
    identifyAppToYouTube(session.defaultSession);
    await mainWindow.loadURL(`${APP_ORIGIN}/`);
  } else {
    await mainWindow.loadURL(layout.frontendDevUrl);
  }
  // Started at login: wait in the tray. Without a tray there would be no way back, so show the window.
  if (!(startsHidden(process.argv) && tray)) mainWindow.show();
  startReleaseAlerts({
    takeAlerts: takeBackendAlerts,
    notifier: createSystemNotifier({
      isSupported: () => Notification.isSupported(),
      create: alert => new Notification({ title: alert.title, body: alert.body, icon: appIconImage(root) }),
      fallback: (alert, onClick) => tray?.showBalloon?.(alert.title, alert.body, onClick)
    }),
    openRelease: releaseId => {
      bringWindowBack(mainWindow);
      mainWindow?.webContents.send("open-release", releaseId);
    },
    log: message => diagnostics.log("desktop.release_alerts", { message })
  });
}

async function takeBackendAlerts(): Promise<ReleaseAlert[]> {
  const response = await fetch(`${apiBaseUrl}/api/alerts/take`, { method: "POST", headers: { [API_TOKEN_HEADER]: apiToken } });
  if (!response.ok) throw new Error(`backend answered ${response.status}`);
  return ((await response.json()) as { items: ReleaseAlert[] }).items;
}

// The app icon for the tray and notifications: the multi-size .ico on Windows, the PNG scaled down elsewhere.
function appIconImage(root: string) {
  return process.platform === "win32"
    ? nativeImage.createFromPath(join(root, "build", "icon.ico"))
    : nativeImage.createFromPath(join(root, "build", "icon.png")).resize({ width: 32, height: 32, quality: "best" });
}

function createAppTray(root: string): AppTray {
  const image = appIconImage(root);
  if (image.isEmpty()) throw new Error("tray icon image is missing");
  const electronTray = new Tray(image);
  return {
    setToolTip: text => electronTray.setToolTip(text),
    setContextMenu: items => electronTray.setContextMenu(Menu.buildFromTemplate(items)),
    on: (event, listener) => (event === "click" ? electronTray.on("click", listener) : electronTray.on("double-click", listener)),
    showBalloon: process.platform === "win32"
      ? (title, body, onClick) => {
          electronTray.removeAllListeners("balloon-click");
          electronTray.once("balloon-click", onClick);
          electronTray.displayBalloon({ title, content: body, icon: image });
        }
      : undefined,
    destroy: () => electronTray.destroy()
  };
}

app.whenReady().then(() => {
  // Camera, microphone, notifications, location and the rest are refused; trailers may go fullscreen.
  session.defaultSession.setPermissionRequestHandler((_contents, permission, callback) => callback(permission === "fullscreen"));
}).then(() => void createWindow().catch(error => handleStartupFailure(error, {
  logFatal: startupError => logDesktopFatalStartup(app, startupError),
  showError: message => dialog.showErrorBox("Game Release Tracker startup failed", message),
  stopBackend: async () => {
    backendShutdownStarted = true;
    const running = backend;
    backend = null;
    await stopBackendProcess(running, 3000);
  },
  quit: () => app.quit()
})));

app.on("before-quit", event => {
  if (!backend || backend.killed || backendShutdownStarted) return;
  event.preventDefault();
  backendShutdownStarted = true;
  void stopBackendProcess(backend, 3000).finally(() => {
    logBackendStoppedBeforeQuit(app, logPath);
    backend = null;
    app.quit();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
