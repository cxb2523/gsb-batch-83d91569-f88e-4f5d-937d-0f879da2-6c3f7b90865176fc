import { appendFileSync, mkdirSync, renameSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";
import { resolveBackendRuntimeLayout } from "../../../runtime/src/layout";

export interface DiagnosticLogger {
  log(event: string, details?: Record<string, unknown>): void;
}

interface LogRotation {
  // Size at which the current file is rotated to .1 (older files shift up).
  maxBytes?: number;
  // Rotated files kept besides the current one.
  keepFiles?: number;
}

const SECRET_KEY = /secret|token|credential|api[_-]?key|password|authorization|client[_-]?id|cookie/i;
// Secrets that can hide inside free text: query parameters and bearer headers in URLs or error messages.
const SECRET_IN_TEXT: Array<[RegExp, string]> = [
  [/\b(client_secret|client_id|access_token|refresh_token|api_key|apikey|token)=([^&\s"']+)/gi, "$1=[redacted]"],
  [/\bBearer\s+[A-Za-z0-9._~+/=-]+/g, "Bearer [redacted]"]
];

// A JSON-lines diagnostics log, capped in size: the Electron main process and the backend child both
// append to it, so the size is read from disk before each write rather than tracked in memory. Both
// processes may rotate at the same moment, and a failed write is dropped: logging never throws.
export function createFileDiagnosticLogger(
  logDir = resolveBackendRuntimeLayout().logDir,
  { maxBytes = 5 * 1024 * 1024, keepFiles = 3 }: LogRotation = {}
): DiagnosticLogger {
  mkdirSync(logDir, { recursive: true });
  const logPath = join(logDir, "game-release-tracker.log");
  return {
    log(event, details = {}) {
      const line = `${JSON.stringify({ time: new Date().toISOString(), event, details: sanitize(details) })}\n`;
      try {
        if (currentSize(logPath) + Buffer.byteLength(line) > maxBytes) rotate(logPath, keepFiles);
        appendFileSync(logPath, line, "utf8");
      } catch {
        // The log is best effort; the other process may have rotated the file away underneath us.
      }
    }
  };
}

function currentSize(path: string) {
  try {
    return statSync(path).size;
  } catch {
    return 0;
  }
}

function rotate(path: string, keepFiles: number) {
  rmSync(`${path}.${keepFiles}`, { force: true });
  for (let index = keepFiles - 1; index >= 1; index--) renameIfPresent(`${path}.${index}`, `${path}.${index + 1}`);
  renameIfPresent(path, `${path}.1`);
}

function renameIfPresent(from: string, to: string) {
  try {
    renameSync(from, to);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
}

function sanitize(value: unknown): unknown {
  if (typeof value === "string") return SECRET_IN_TEXT.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value);
  if (Array.isArray(value)) return value.map(sanitize);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => {
    if (SECRET_KEY.test(key)) return [key, "[redacted]"];
    return [key, sanitize(item)];
  }));
}
