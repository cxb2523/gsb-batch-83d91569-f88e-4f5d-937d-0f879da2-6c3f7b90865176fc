import { app, BrowserWindow, Menu, Tray, nativeImage, shell, dialog } from "electron";
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRemoteDashboard } from "./remote.mjs";
import { desktopAddress, miniPreferences } from "../src/desktop-options.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const address = desktopAddress(process.env, process.argv.slice(1));
const miniFile = path.join(root, "dist", "dashboard", "mini.html");
let remoteDashboard;
let serverProcess, miniWindow, tray;
let quitting = false;
let ready = false;
let preferences = {};
let sources = [];

function openMiniWindow(input = preferences) {
  preferences = miniPreferences(input);
  const width = preferences.fiveHour === "1" && preferences.weekly === "1" ? 480 : 280;
  if (!miniWindow || miniWindow.isDestroyed()) {
    miniWindow = new BrowserWindow({
      width, height: 250, useContentSize: true, minWidth: 260, minHeight: 200,
      maximizable: false, alwaysOnTop: true, backgroundColor: "#0e110f",
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true,
        ...(address.external ? { preload: path.join(root, "desktop", "preload.cjs") } : {}),
      },
    });
    miniWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
    miniWindow.webContents.on("will-navigate", (event, url) => {
      if (address.external || new URL(url).origin !== address.url) event.preventDefault();
    });
    miniWindow.on("closed", () => { miniWindow = null; });
  } else miniWindow.setContentSize(width, 250);
  const window = miniWindow;
  const navigation = address.external
    ? window.loadFile(miniFile, { query: preferences })
    : window.loadURL(`${address.url}/mini.html?${new URLSearchParams(preferences)}`);
  void navigation.catch((error) => {
    // Closing/reopening while a navigation is pending aborts that navigation.
    // A synchronous error box here would interrupt shutdown and orphan the app.
    if (quitting || window.isDestroyed() || error.code === "ERR_ABORTED") return;
    void dialog.showMessageBox(window, { type: "error", title: "Codex Usage", message: "Unable to open the quota window", detail: error.message });
  });
  miniWindow.show();
  miniWindow.focus();
}

async function capabilities() {
  const response = await fetch(`${address.url}/api/capabilities`, { signal: AbortSignal.timeout(1500) });
  if (!response.ok) throw new Error(`Dashboard returned HTTP ${response.status}`);
  const result = await response.json();
  if (result.apiVersion !== 1 || !Array.isArray(result.sources) || !result.sources.includes(result.defaultSource)) {
    throw new Error("The configured address does not serve a compatible Codex Usage dashboard.");
  }
  return result;
}

async function startOrReuseServer() {
  try {
    await capabilities();
    console.log(`Using existing dashboard at ${address.url}; it will remain running on exit.`);
    return;
  } catch (error) {
    // An occupied or unresponsive address must not start another server.
    if (error.cause?.code !== "ECONNREFUSED") throw error;
  }
  serverProcess = spawn(process.execPath, [path.join(root, "server.mjs")], {
    cwd: root,
    env: { ...process.env, ELECTRON_RUN_AS_NODE: "1", CODEX_DESKTOP_HELPER: "1" },
    stdio: ["ignore", "inherit", "inherit", "ipc"], windowsHide: true,
  });
  serverProcess.on("message", (message) => {
    if (message?.type === "open-mini-quota" && ready) openMiniWindow(message.preferences);
  });
  serverProcess.on("error", (error) => {
    if (!quitting) { dialog.showErrorBox("Codex Usage", error.message); app.quit(); }
  });
  serverProcess.on("exit", (code) => {
    if (!quitting && ready) {
      dialog.showErrorBox("Codex Usage", `Dashboard server stopped (${code}).`);
      app.quit();
    }
  });
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (serverProcess.exitCode !== null) throw new Error("Dashboard server exited during startup.");
    try { await capabilities(); return; }
    catch { await new Promise((resolve) => setTimeout(resolve, 200)); }
  }
  throw new Error("Dashboard did not become ready within 30 seconds.");
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => { if (ready) openMiniWindow(); });
  app.whenReady().then(async () => {
    if (address.external) {
      remoteDashboard = await createRemoteDashboard({ baseUrl: address.baseUrl, miniFile, getMiniWindow: () => miniWindow });
      sources = ["local", "centralized"];
    } else {
      await startOrReuseServer();
      sources = (await capabilities()).sources;
    }
    ready = true;
    tray = new Tray(nativeImage.createFromPath(path.join(root, "public", "icon-192.png")).resize({ width: 16, height: 16 }));
    tray.setToolTip("Codex Usage");
    const menu = [
      { label: "Open mini quota window", click: () => openMiniWindow() },
      { label: "Open dashboard", click: () => { if (remoteDashboard) void remoteDashboard.openDashboard(); else void shell.openExternal(address.url); } },
      { label: "Data source", submenu: sources.map((source) => ({
        label: source === "centralized" ? "Centralized" : "Local",
        click: () => openMiniWindow({ ...preferences, source }),
      })) },
      { label: "Visible quotas", submenu: [
        { label: "Both quotas", click: () => openMiniWindow({ ...preferences, fiveHour: "1", weekly: "1" }) },
        { label: "5 hours", click: () => openMiniWindow({ ...preferences, fiveHour: "1", weekly: "0" }) },
        { label: "Weekly", click: () => openMiniWindow({ ...preferences, fiveHour: "0", weekly: "1" }) },
      ] },
      { type: "separator" },
      { label: "Quit Codex Usage desktop", click: () => app.quit() },
    ];
    tray.setContextMenu(Menu.buildFromTemplate(menu));
    tray.on("double-click", () => openMiniWindow());
    Menu.setApplicationMenu(Menu.buildFromTemplate([{ label: "Codex Usage", submenu: menu }]));
    openMiniWindow();
  }).catch((error) => {
    dialog.showErrorBox("Codex Usage", error.message);
    app.quit();
  });
}

app.on("window-all-closed", () => { /* The tray keeps reopen and quit accessible. */ });
app.on("activate", () => { if (ready && !quitting) openMiniWindow(); });
app.on("before-quit", () => {
  quitting = true;
  remoteDashboard?.close();
  serverProcess?.kill();
  tray?.destroy();
});
