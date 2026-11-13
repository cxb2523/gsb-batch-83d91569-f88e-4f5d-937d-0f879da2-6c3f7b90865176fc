import { describe, expect, test } from "vitest";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import {
  backfillRuntimeData,
  resolveBackendRuntimeLayout,
  resolveDesktopRuntimeLayout
} from "../../apps/runtime/src/layout";

type EnvCase = {
  name: string;
  env: NodeJS.ProcessEnv;
};

const isWin = process.platform === "win32";

const homeDir = isWin ? "C:\\Users\\Tester" : "/home/tester";
const cwd = isWin ? "C:\\repo\\game-release-tracker" : "/repo/game-release-tracker";
const desktopRoot = isWin ? "C:\\app\\resources\\app.asar" : "/app/resources/app.asar";
const userData = isWin
  ? "C:\\Users\\Tester\\AppData\\Roaming\\Game Release Tracker"
  : "/home/tester/.config/Game Release Tracker";

function legacyAppDataPath(env: NodeJS.ProcessEnv) {
  if (env.GRT_DATA_DIR) return env.GRT_DATA_DIR;
  if (isWin) {
    return join(homeDir, "AppData", "Roaming", "Game Release Tracker");
  } else if (process.platform === "darwin") {
    return join(homeDir, "Library", "Application Support", "Game Release Tracker");
  } else {
    return join(homeDir, ".config", "Game Release Tracker");
  }
}

function legacyBackendLayout(env: NodeJS.ProcessEnv) {
  const dataDir = legacyAppDataPath(env);
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

function expectedDesktopLayout(env: NodeJS.ProcessEnv) {
  const dataDir = env.GRT_DATA_DIR || userData;
  const logDir = env.GRT_LOG_DIR || join(dataDir, "logs");
  return {
    root: desktopRoot,
    backendChildPath: join(desktopRoot, "dist", "apps", "backend", "src", "child.js"),
    backendCwd: desktopRoot.endsWith("app.asar") ? dirname(desktopRoot) : desktopRoot,
    backendDataDir: dataDir,
    backendEnv: {
      GRT_ASSET_ROOT: env.GRT_ASSET_ROOT || desktopRoot,
      GRT_DATA_DIR: dataDir,
      GRT_LOG_DIR: logDir
    },
    legacyDataDirs: env.GRT_DATA_DIR && env.GRT_DATA_DIR !== userData ? [userData] : [],
    logDir,
    startupLogPath: join(logDir, "startup.log"),
    diagnosticLogPath: join(logDir, "game-release-tracker.log"),
    preloadPath: join(desktopRoot, "dist", "apps", "desktop", "src", "preload.js"),
    frontendIndexPath: join(desktopRoot, "dist", "frontend", "index.html"),
    frontendDevUrl: env.VITE_DEV_SERVER_URL || "http://127.0.0.1:5173"
  };
}

describe("runtime layout extraction", () => {
  const envCases: EnvCase[] = [
    { name: "no env", env: {} },
    { name: "data dir only", env: { GRT_DATA_DIR: isWin ? "D:\\GameTracker\\data" : "/var/GameTracker/data" } },
    { name: "asset root only", env: { GRT_ASSET_ROOT: isWin ? "D:\\GameTracker\\assets" : "/var/GameTracker/assets" } },
    { name: "log dir only", env: { GRT_LOG_DIR: isWin ? "D:\\GameTracker\\logs" : "/var/GameTracker/logs" } },
    {
      name: "all env",
      env: {
        GRT_DATA_DIR: isWin ? "D:\\GameTracker\\data" : "/var/GameTracker/data",
        GRT_ASSET_ROOT: isWin ? "D:\\GameTracker\\assets" : "/var/GameTracker/assets",
        GRT_LOG_DIR: isWin ? "D:\\GameTracker\\logs" : "/var/GameTracker/logs",
        VITE_DEV_SERVER_URL: "http://127.0.0.1:4321"
      }
    }
  ];

  test("backend layout matches legacy path resolution across env combinations", () => {
    const results = envCases.map(({ name, env }) => {
      const legacy = legacyBackendLayout(env);
      const layout = resolveBackendRuntimeLayout({ env, cwd, homeDir });
      expect(layout).toEqual(legacy);
      return { name, layout };
    });

    expect(results.length).toBe(5);
  });

  test("desktop layout applies explicit env precedence and coherent writable paths", () => {
    const results = envCases.map(({ name, env }) => {
      const legacy = expectedDesktopLayout(env);
      const layout = resolveDesktopRuntimeLayout({ env, root: desktopRoot, userData });
      expect(layout).toEqual(legacy);
      return { name, layout };
    });

    expect(results.length).toBe(5);
  });

  test("runtime data backfill copies old userData files into explicit data and log dirs without overwriting", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-layout-"));
    try {
      const oldUserData = join(dir, "old-user-data");
      const newData = join(dir, "new-data");
      const explicitLogs = join(dir, "explicit-logs");
      mkdirSync(join(oldUserData, "artworks"), { recursive: true });
      mkdirSync(join(oldUserData, "logs"), { recursive: true });
      mkdirSync(newData, { recursive: true });
      writeFileSync(join(oldUserData, "game-release-tracker.db"), "old-db");
      writeFileSync(join(oldUserData, "game-release-tracker.db-wal"), "old-wal");
      writeFileSync(join(oldUserData, "artworks", "hero.png"), "old-art");
      writeFileSync(join(oldUserData, "startup.log"), "old-startup");
      writeFileSync(join(oldUserData, "logs", "game-release-tracker.log"), "old-jsonl");
      writeFileSync(join(newData, "game-release-tracker.db"), "new-db");

      const layout = resolveDesktopRuntimeLayout({
        env: { GRT_DATA_DIR: newData, GRT_LOG_DIR: explicitLogs },
        root: desktopRoot,
        userData: oldUserData
      });
      const result = backfillRuntimeData(layout);

      expect(result.copied.sort()).toEqual([
        join(explicitLogs, "game-release-tracker.log"),
        join(explicitLogs, "startup.log"),
        join(newData, "artworks", "hero.png"),
        join(newData, "game-release-tracker.db-wal")
      ].sort());
      expect(result.skipped).toContain(join(newData, "game-release-tracker.db"));
      expect(readFileSync(join(newData, "game-release-tracker.db"), "utf8")).toBe("new-db");
      expect(readFileSync(join(newData, "game-release-tracker.db-wal"), "utf8")).toBe("old-wal");
      expect(readFileSync(join(newData, "artworks", "hero.png"), "utf8")).toBe("old-art");
      expect(readFileSync(join(explicitLogs, "startup.log"), "utf8")).toBe("old-startup");
      expect(readFileSync(join(explicitLogs, "game-release-tracker.log"), "utf8")).toBe("old-jsonl");
      expect(existsSync(join(oldUserData, "game-release-tracker.db"))).toBe(true);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
  test("discovers and restores the Linux app-data backup without overwriting the Windows database, and drops the retired Excel copy", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-linux-restore-"));
    try {
      const restoreDir = join(dir, "game-release-tracker");
      const windowsData = join(dir, "windows-data");
      mkdirSync(join(restoreDir, "completed-library"), { recursive: true });
      mkdirSync(join(restoreDir, "wallpaper"), { recursive: true });
      mkdirSync(windowsData, { recursive: true });
      writeFileSync(join(restoreDir, "game-release-tracker.db"), "linux-db");
      writeFileSync(join(restoreDir, "completed-library", "completed-games.xlsx"), "linux-xlsx");
      writeFileSync(join(restoreDir, "wallpaper", "current.png"), "linux-wallpaper");

      const layout = resolveDesktopRuntimeLayout({ env: {}, root: dir, userData: windowsData });
      expect(layout.legacyDataDirs).toContain(restoreDir);
      const result = backfillRuntimeData(layout);

      expect(result.copied).toEqual(expect.arrayContaining([
        join(windowsData, "game-release-tracker.db"),
        join(windowsData, "wallpaper", "current.png")
      ]));
      expect(readFileSync(join(windowsData, "game-release-tracker.db"), "utf8")).toBe("linux-db");
      expect(existsSync(join(windowsData, "completed-library"))).toBe(false);
      expect(readFileSync(join(windowsData, "wallpaper", "current.png"), "utf8")).toBe("linux-wallpaper");

      writeFileSync(join(restoreDir, "game-release-tracker.db"), "new-linux-db");
      const second = backfillRuntimeData(layout);
      expect(second.skipped).toContain(join(windowsData, "game-release-tracker.db"));
      expect(readFileSync(join(windowsData, "game-release-tracker.db"), "utf8")).toBe("linux-db");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("does not discover a packaged linux-restore resource", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-packaged-restore-"));
    try {
      const packagedRestore = join(dir, "resources", "linux-restore");
      mkdirSync(packagedRestore, { recursive: true });
      writeFileSync(join(packagedRestore, "game-release-tracker.db"), "packaged-db");
      const layout = resolveDesktopRuntimeLayout({
        env: {},
        root: join(dir, "resources", "app.asar"),
        userData: join(dir, "user-data")
      });
      expect(layout.legacyDataDirs).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test("accepts an explicit restore directory", () => {
    const dir = mkdtempSync(join(tmpdir(), "grt-explicit-restore-"));
    try {
      const restoreDir = join(dir, "linux-backup");
      const windowsData = join(dir, "windows-data");
      mkdirSync(restoreDir, { recursive: true });
      writeFileSync(join(restoreDir, "game-release-tracker.db"), "linux-db");

      const layout = resolveDesktopRuntimeLayout({
        env: { GRT_RESTORE_DIR: restoreDir },
        root: join(dir, "other-root"),
        userData: windowsData
      });

      expect(layout.legacyDataDirs).toEqual([restoreDir]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
