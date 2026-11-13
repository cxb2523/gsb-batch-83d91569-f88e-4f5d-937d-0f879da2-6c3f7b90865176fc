import { copyFileSync, existsSync, mkdirSync, readdirSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";

interface BackendRuntimeLayoutOptions {
  env?: NodeJS.ProcessEnv;
  cwd?: string;
  homeDir?: string;
}

interface DesktopRuntimeLayoutOptions {
  env?: NodeJS.ProcessEnv;
  root: string;
  userData: string;
}

export function resolveBackendRuntimeLayout(options: BackendRuntimeLayoutOptions = {}) {
  const env = options.env ?? process.env;
  const cwd = options.cwd ?? process.cwd();
  const homeDir = options.homeDir ?? homedir();

  let defaultDataDir: string;
  if (process.platform === "win32") {
    defaultDataDir = join(homeDir, "AppData", "Roaming", "Game Release Tracker");
  } else if (process.platform === "darwin") {
    defaultDataDir = join(homeDir, "Library", "Application Support", "Game Release Tracker");
  } else {
    defaultDataDir = join(homeDir, ".config", "Game Release Tracker");
  }

  const dataDir = env.GRT_DATA_DIR || defaultDataDir;
  const assetRoot = env.GRT_ASSET_ROOT || cwd;
  const logDir = env.GRT_LOG_DIR || join(dataDir, "logs");

  return {
    dataDir,
    dbPath: join(dataDir, "game-release-tracker.db"),
    assetRoot,
    seedOverridesPath: join(assetRoot, "data", "source-overrides.json"),
    logDir,
    diagnosticLogPath: join(logDir, "game-release-tracker.log"),
    artworkDir: join(dataDir, "artworks"),
    coversDir: join(dataDir, "covers")
  };
}

export function resolveDesktopRuntimeLayout({ env = process.env, root, userData }: DesktopRuntimeLayoutOptions) {
  const dataDir = env.GRT_DATA_DIR || userData;
  const logDir = env.GRT_LOG_DIR || join(dataDir, "logs");
  const legacyDataDirs = env.GRT_DATA_DIR && env.GRT_DATA_DIR !== userData ? [userData] : [];
  const restoreDataDirs = findRestoreDataDirs(env, root, dataDir);
  return {
    root,
    backendChildPath: join(root, "dist", "apps", "backend", "src", "child.js"),
    backendCwd: root.endsWith("app.asar") ? dirname(root) : root,
    backendDataDir: dataDir,
    backendEnv: {
      GRT_ASSET_ROOT: env.GRT_ASSET_ROOT || root,
      GRT_DATA_DIR: dataDir,
      GRT_LOG_DIR: logDir
    },
    legacyDataDirs: [...legacyDataDirs, ...restoreDataDirs.filter(dir => !legacyDataDirs.includes(dir))],
    logDir,
    startupLogPath: join(logDir, "startup.log"),
    diagnosticLogPath: join(logDir, "game-release-tracker.log"),
    preloadPath: join(root, "dist", "apps", "desktop", "src", "preload.js"),
    frontendIndexPath: join(root, "dist", "frontend", "index.html"),
    frontendDevUrl: env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173"
  };
}

export function backfillRuntimeData(layout: ReturnType<typeof resolveDesktopRuntimeLayout>) {
  const copied: string[] = [];
  const skipped: string[] = [];
  for (const legacyDir of layout.legacyDataDirs) {
    copyIfMissing(join(legacyDir, "game-release-tracker.db"), join(layout.backendDataDir, "game-release-tracker.db"), copied, skipped);
    copyIfMissing(join(legacyDir, "game-release-tracker.db-wal"), join(layout.backendDataDir, "game-release-tracker.db-wal"), copied, skipped);
    copyIfMissing(join(legacyDir, "game-release-tracker.db-shm"), join(layout.backendDataDir, "game-release-tracker.db-shm"), copied, skipped);
    copyTreeIfMissing(join(legacyDir, "artworks"), join(layout.backendDataDir, "artworks"), copied, skipped);
    copyIfMissing(join(legacyDir, "startup.log"), layout.startupLogPath, copied, skipped);
    copyIfMissing(join(legacyDir, "logs", "game-release-tracker.log"), join(layout.logDir, "game-release-tracker.log"), copied, skipped);
    copyTreeIfMissing(join(legacyDir, "wallpaper"), join(layout.backendDataDir, "wallpaper"), copied, skipped);
  }
  // The copy of the retired Completed Library Excel workbook; the app's database holds the library now.
  const retiredExcel = join(layout.backendDataDir, "completed-library");
  if (existsSync(retiredExcel)) rmSync(retiredExcel, { recursive: true, force: true });
  return { copied, skipped };
}

function findRestoreDataDirs(env: NodeJS.ProcessEnv, root: string, dataDir: string) {
  const explicitDir = env.GRT_RESTORE_DIR?.trim();
  const candidates = explicitDir
    ? [explicitDir]
    : [join(root, "game-release-tracker")];

  return [...new Set(candidates)].filter(candidate => {
    return candidate !== dataDir && existsSync(candidate) && existsSync(join(candidate, "game-release-tracker.db"));
  });
}

function copyIfMissing(source: string, target: string, copied: string[], skipped: string[]) {
  if (!existsSync(source)) return;
  if (existsSync(target)) {
    skipped.push(target);
    return;
  }
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(source, target);
  copied.push(target);
}

function copyTreeIfMissing(source: string, target: string, copied: string[], skipped: string[]) {
  if (!existsSync(source)) return;
  const stack = [{ source, target }];
  while (stack.length > 0) {
    const current = stack.pop()!;
    const entries = readdirSync(current.source, { withFileTypes: true });
    for (const entry of entries) {
      const sourceEntry = join(current.source, entry.name);
      const targetEntry = join(current.target, entry.name);
      if (entry.isDirectory()) stack.push({ source: sourceEntry, target: targetEntry });
      else copyIfMissing(sourceEntry, targetEntry, copied, skipped);
    }
  }
}
