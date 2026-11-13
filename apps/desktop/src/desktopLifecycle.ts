import { appendFileSync, mkdirSync } from "node:fs";
import { backfillRuntimeData, resolveDesktopRuntimeLayout } from "../../runtime/src/layout";
import { createFileDiagnosticLogger } from "../../backend/src/diagnostics/logger";

export interface DesktopAppPaths {
  isPackaged: boolean;
  getAppPath(): string;
  getPath(name: "userData"): string;
}

interface DesktopRuntimeContext {
  root: string;
  layout: ReturnType<typeof resolveDesktopRuntimeLayout>;
  logPath: string;
}

export function resolveDesktopRoot(appPaths: Pick<DesktopAppPaths, "isPackaged" | "getAppPath">, cwd = process.cwd()) {
  return appPaths.isPackaged ? appPaths.getAppPath() : cwd;
}

export function prepareDesktopRuntime(appPaths: DesktopAppPaths, cwd = process.cwd()): DesktopRuntimeContext {
  const root = resolveDesktopRoot(appPaths, cwd);
  const layout = resolveDesktopRuntimeLayout({ root, userData: appPaths.getPath("userData") });
  backfillRuntimeData(layout);
  mkdirSync(layout.logDir, { recursive: true });
  appendDesktopLog(layout.startupLogPath, `starting root=${root}`);
  return { root, layout, logPath: layout.startupLogPath };
}

export function logDesktopFatalStartup(appPaths: DesktopAppPaths, error: unknown, cwd = process.cwd()) {
  const message = formatDesktopError(error);
  try {
    const root = resolveDesktopRoot(appPaths, cwd);
    const layout = resolveDesktopRuntimeLayout({ root, userData: appPaths.getPath("userData") });
    mkdirSync(layout.logDir, { recursive: true });
    appendDesktopLog(layout.startupLogPath, `fatal ${message}`);
  } catch {
    // Ignore logging failures during fatal startup handling.
  }
  return message;
}

export function logBackendStoppedBeforeQuit(appPaths: DesktopAppPaths, logPath?: string, cwd = process.cwd()) {
  try {
    const root = resolveDesktopRoot(appPaths, cwd);
    const layout = resolveDesktopRuntimeLayout({ root, userData: appPaths.getPath("userData") });
    mkdirSync(layout.logDir, { recursive: true });
    appendDesktopLog(logPath || layout.startupLogPath, "backend stopped before quit");
  } catch {
    // Ignore logging failures during shutdown.
  }
}

export function logDesktopProcessFailure(appPaths: DesktopAppPaths, event: string, error: unknown, cwd = process.cwd()) {
  const message = formatDesktopError(error);
  try {
    const root = resolveDesktopRoot(appPaths, cwd);
    const layout = resolveDesktopRuntimeLayout({ root, userData: appPaths.getPath("userData") });
    createFileDiagnosticLogger(layout.logDir).log(event, {
      message,
      stack: error instanceof Error ? error.stack : undefined
    });
  } catch {
    // Ignore logging failures while reporting a process failure.
  }
  return message;
}

function appendDesktopLog(logPath: string, message: string) {
  appendFileSync(logPath, `[main] ${new Date().toISOString()} ${message}\n`);
}

function formatDesktopError(error: unknown) {
  return error instanceof Error ? error.stack || error.message : String(error);
}

interface StartupFailureSteps {
  logFatal(error: unknown): string;
  showError(message: string): void;
  stopBackend(): Promise<unknown>;
  quit(): void;
}

// A failed startup has no window, so Electron would never quit on its own: log, tell the user,
// stop any backend that did start, then quit.
export async function handleStartupFailure(error: unknown, steps: StartupFailureSteps) {
  const message = steps.logFatal(error);
  steps.showError(message);
  try {
    await steps.stopBackend();
  } catch {
    // Quitting matters more than a clean backend stop here.
  }
  steps.quit();
}
