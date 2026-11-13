import { afterEach, describe, expect, test } from "vitest";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import {
  logBackendStoppedBeforeQuit,
  logDesktopFatalStartup,
  logDesktopProcessFailure,
  prepareDesktopRuntime,
  resolveDesktopRoot,
  type DesktopAppPaths
} from "../../apps/desktop/src/desktopLifecycle";

let dirs: string[] = [];

function makeAppPaths(options: { isPackaged?: boolean; appPath?: string; userData?: string } = {}): DesktopAppPaths {
  const userData = options.userData ?? mkdtempSync(join(tmpdir(), "grt-desktop-user-data-"));
  dirs.push(userData);
  return {
    isPackaged: options.isPackaged ?? false,
    getAppPath: () => options.appPath ?? "C:\\app\\resources\\app.asar",
    getPath: () => userData
  };
}

afterEach(() => {
  for (const dir of dirs) rmSync(dir, { recursive: true, force: true });
  dirs = [];
  delete process.env.GRT_DATA_DIR;
  delete process.env.GRT_LOG_DIR;
  delete process.env.GRT_ASSET_ROOT;
});

describe("desktop lifecycle", () => {
  test("resolves dev and packaged roots through one module", () => {
    expect(resolveDesktopRoot(makeAppPaths({ isPackaged: false }), "C:\\repo")).toBe("C:\\repo");
    expect(resolveDesktopRoot(makeAppPaths({ isPackaged: true, appPath: "C:\\app\\resources\\app.asar" }), "C:\\repo")).toBe("C:\\app\\resources\\app.asar");
  });

  test("prepares runtime layout, backfills legacy user data, and writes startup log", () => {
    const userData = mkdtempSync(join(tmpdir(), "grt-desktop-legacy-"));
    dirs.push(userData);
    const dataDir = mkdtempSync(join(tmpdir(), "grt-desktop-data-"));
    dirs.push(dataDir);
    process.env.GRT_DATA_DIR = dataDir;
    const legacyDb = join(userData, "game-release-tracker.db");
    const appPaths = makeAppPaths({ userData });
    writeFileSync(legacyDb, "legacy-db");

    const context = prepareDesktopRuntime(appPaths, "C:\\repo");

    expect(context.root).toBe("C:\\repo");
    expect(context.layout.backendDataDir).toBe(dataDir);
    expect(readFileSync(join(dataDir, "game-release-tracker.db"), "utf8")).toBe("legacy-db");
    expect(readFileSync(context.logPath, "utf8")).toContain("starting root=C:\\repo");
  });

  test("logs fatal startup and shutdown through the same lifecycle module", () => {
    const appPaths = makeAppPaths();
    const message = logDesktopFatalStartup(appPaths, new Error("boom"), "C:\\repo");

    expect(message).toContain("boom");
    const startupLog = join(appPaths.getPath("userData"), "logs", "startup.log");
    expect(readFileSync(startupLog, "utf8")).toContain("fatal Error: boom");

    logBackendStoppedBeforeQuit(appPaths, startupLog, "C:\\repo");

    expect(existsSync(startupLog)).toBe(true);
    expect(readFileSync(startupLog, "utf8")).toContain("backend stopped before quit");
  });

  test("writes process failures to the diagnostic JSONL log", () => {
    const appPaths = makeAppPaths();

    logDesktopProcessFailure(appPaths, "process.uncaught_exception", new Error("boom"), "C:\repo");

    const diagnosticLog = join(appPaths.getPath("userData"), "logs", "game-release-tracker.log");
    const entry = JSON.parse(readFileSync(diagnosticLog, "utf8").trim());
    expect(entry.event).toBe("process.uncaught_exception");
    expect(entry.details.message).toContain("boom");
  });
});
