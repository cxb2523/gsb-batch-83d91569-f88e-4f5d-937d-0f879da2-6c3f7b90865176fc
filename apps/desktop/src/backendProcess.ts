import { appendFileSync } from "node:fs";
import { resolveDesktopRuntimeLayout } from "../../runtime/src/layout";
import { CREDENTIAL_KEYS } from "../../../shared/constants";

interface ReadyMessage {
  type: "ready";
  port: number;
}

export interface BackendChild {
  killed?: boolean;
  kill(): boolean | void;
  postMessage?(message: unknown): void;
  send?(message: unknown): void;
  once?(event: "exit" | "error", listener: (value?: unknown) => void): void;
}

export function parseReadyMessage(line: string): ReadyMessage | null {
  try {
    const parsed = JSON.parse(line) as Partial<ReadyMessage>;
    if (parsed.type === "ready" && typeof parsed.port === "number") return { type: "ready", port: parsed.port };
  } catch {
    return null;
  }
  return null;
}

function parseStartupError(line: string) {
  try {
    const parsed = JSON.parse(line) as { type?: unknown; message?: unknown };
    return parsed.type === "error" && typeof parsed.message === "string" ? parsed.message : undefined;
  } catch {
    return undefined;
  }
}

export function getBackendChildPath(root: string) {
  return resolveDesktopRuntimeLayout({ root, userData: "" }).backendChildPath;
}

export function getBackendCwd(root: string) {
  return resolveDesktopRuntimeLayout({ root, userData: "" }).backendCwd;
}

// The backend child's environment. In the packaged app, API keys come only from Settings (stored
// encrypted), so keys a user happens to have in their shell environment are not picked up silently.
export function backendChildEnv(parent: NodeJS.ProcessEnv, extras: Record<string, string>, { packaged }: { packaged: boolean }) {
  const env = { ...parent, ...extras };
  if (packaged) for (const key of CREDENTIAL_KEYS) delete env[key];
  return env;
}

export async function startBackendProcess(root: string, { logPath, dataDir, apiToken, credentialKey, packaged }: {
  logPath?: string;
  dataDir?: string;
  apiToken?: string;
  credentialKey?: string;
  packaged: boolean;
}): Promise<{ child: BackendChild; port: number }> {
  const { utilityProcess } = await import("electron");
  const layout = resolveDesktopRuntimeLayout({ root, userData: dataDir || process.env.GRT_DATA_DIR || "" });
  const childPath = layout.backendChildPath;
  const log = (message: string) => {
    if (logPath) appendFileSync(logPath, `[backend-process] ${new Date().toISOString()} ${message}\n`);
  };
  const cwd = layout.backendCwd;
  log(`starting ${childPath} cwd=${cwd}`);
  const child = utilityProcess.fork(childPath, [], {
    stdio: "pipe",
    cwd,
    env: backendChildEnv(process.env, {
      ...layout.backendEnv,
      ...(apiToken ? { GRT_API_TOKEN: apiToken } : {}),
      ...(credentialKey ? { GRT_CREDENTIAL_KEY: credentialKey } : {})
    }, { packaged })
  }) as BackendChild & {
    stdout?: NodeJS.ReadableStream;
    stderr?: NodeJS.ReadableStream;
    on(event: "message", listener: (message: unknown) => void): void;
    once(event: "exit" | "error", listener: (value: unknown) => void): void;
  };
  return waitForBackendReady(child, { timeoutMs: 15000, log });
}

type StartingBackend = BackendChild & {
  stdout?: NodeJS.ReadableStream | { on(event: "data", listener: (data: unknown) => void): unknown };
  stderr?: NodeJS.ReadableStream | { on(event: "data", listener: (data: unknown) => void): unknown };
  on(event: "message", listener: (message: unknown) => void): unknown;
  once(event: "exit" | "error", listener: (value: unknown) => void): unknown;
};

// Resolves once the backend reports its port. A backend that never gets there is killed, so it
// cannot keep holding the database file and port after the app gives up on it.
export function waitForBackendReady<Child extends StartingBackend>(child: Child, { timeoutMs, log = () => undefined }: { timeoutMs: number; log?: (message: string) => void }): Promise<{ child: Child; port: number }> {
  return new Promise((resolve, reject) => {
    let settled = false;
    const settle = (outcome: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      outcome();
    };
    const timeout = setTimeout(() => settle(() => {
      log("startup timed out");
      if (!child.killed) child.kill();
      reject(new Error("Backend startup timed out"));
    }), timeoutMs);
    // The backend reports {"type":"error","message":...} when it cannot start, as a process message and
    // on stderr; that reason is what the user should see, rather than a bare exit code.
    let startupError: string | undefined;
    child.on("message", message => {
      log(`message ${JSON.stringify(message)}`);
      if (typeof message !== "object" || !message) return;
      if ((message as ReadyMessage).type === "ready") {
        settle(() => resolve({ child, port: (message as ReadyMessage).port }));
      }
      startupError = parseStartupError(JSON.stringify(message)) ?? startupError;
    });
    child.stdout?.on("data", (data: unknown) => {
      log(`stdout ${String(data).trim()}`);
      for (const line of String(data).split(/\r?\n/)) {
        const ready = parseReadyMessage(line);
        if (ready) settle(() => resolve({ child, port: ready.port }));
        startupError = parseStartupError(line) ?? startupError;
      }
    });
    child.stderr?.on("data", (data: unknown) => {
      log(`stderr ${String(data).trim()}`);
      for (const line of String(data).split(/\r?\n/)) startupError = parseStartupError(line) ?? startupError;
    });
    child.once("exit", code => settle(() => {
      log(`exit ${code}`);
      reject(new Error(startupError ?? `Backend exited before ready: ${code}`));
    }));
    child.once("error", error => settle(() => {
      log(`error ${String(error)}`);
      reject(error instanceof Error ? error : new Error(String(error)));
    }));
  });
}

export function stopBackendProcess(child: BackendChild | null, timeoutMs = 3000): Promise<boolean> {
  if (!child || child.killed) return Promise.resolve(true);
  child.postMessage?.({ type: "shutdown" });
  child.send?.({ type: "shutdown" });

  return new Promise(resolve => {
    let settled = false;
    const finish = (clean: boolean) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolve(clean);
    };
    const timeout = setTimeout(() => {
      if (!child.killed) child.kill();
      finish(false);
    }, timeoutMs);
    timeout.unref?.();
    child.once?.("exit", () => finish(true));
    child.once?.("error", () => finish(false));
  });
}
