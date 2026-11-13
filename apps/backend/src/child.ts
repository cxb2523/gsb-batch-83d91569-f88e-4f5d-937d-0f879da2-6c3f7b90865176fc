import { openDatabase } from "./database/db";
import { runMigrations } from "./database/migrations";
import { seedOverrides } from "./sync/overrides";
import { createBackendApp } from "./server";
import { createFileDiagnosticLogger } from "./diagnostics/logger";
import { resolveBackendRuntimeLayout } from "../../runtime/src/layout";
import { configureProcessCipher } from "./settings/secretCipher";
import { createSettingsStore } from "./settings/settingsStore";

let processFailureScheduled = false;

function describeError(error: unknown) {
  return {
    message: error instanceof Error ? error.message : String(error),
    stack: error instanceof Error ? error.stack : undefined
  };
}

function logProcessFailure(event: string, error: unknown) {
  const details = describeError(error);
  try {
    createFileDiagnosticLogger(resolveBackendRuntimeLayout().logDir).log(event, details);
  } catch {
    // A logging failure must not hide the original process failure.
  }
  console.error(JSON.stringify({ type: event, ...details }));
}

function handleProcessFailure(event: string, error: unknown) {
  if (processFailureScheduled) return;
  processFailureScheduled = true;
  logProcessFailure(event, error);
  setImmediate(() => process.exit(1));
}

process.on("uncaughtException", error => handleProcessFailure("process.uncaught_exception", error));
process.on("unhandledRejection", reason => handleProcessFailure("process.unhandled_rejection", reason));

async function main() {
  const layout = resolveBackendRuntimeLayout();
  const db = openDatabase(layout.dbPath);
  runMigrations(db);
  // The desktop app's credential data key (OS-protected); API keys are encrypted at rest with it.
  configureProcessCipher(process.env.GRT_CREDENTIAL_KEY || undefined);
  delete process.env.GRT_CREDENTIAL_KEY;
  const sealed = createSettingsStore(db).encryptStoredCredentials();
  if (sealed > 0) createFileDiagnosticLogger(layout.logDir).log("credentials.encrypted_legacy_values", { count: sealed });
  // No seed file is the normal case; a seed file that fails to load is worth a log line.
  await seedOverrides(db, layout.seedOverridesPath).catch(error => {
    if ((error as NodeJS.ErrnoException)?.code !== "ENOENT") logProcessFailure("backend.seed_overrides_failed", error);
  });
  // Set by the desktop app for each launch; absent when the backend is started directly for development.
  const apiToken = process.env.GRT_API_TOKEN || undefined;
  delete process.env.GRT_API_TOKEN;
  const app = createBackendApp({ db, autoSync: true, apiToken });
  const address = await app.listen({ host: "127.0.0.1", port: 0 });
  const port = Number(new URL(address).port);
  const message = JSON.stringify({ type: "ready", port });
  process.parentPort?.postMessage({ type: "ready", port });
  if (process.send) process.send({ type: "ready", port });
  console.log(message);

  const shutdown = async () => {
    await app.close();
    db.close();
    process.exit(0);
  };
  process.parentPort?.on("message", event => {
    const data = typeof event === "object" && event && "data" in event ? event.data : event;
    if (data === "shutdown" || (typeof data === "object" && data && (data as { type?: string }).type === "shutdown")) void shutdown();
  });
  process.on("message", message => {
    if (message === "shutdown" || (typeof message === "object" && message && (message as { type?: string }).type === "shutdown")) void shutdown();
  });
  process.on("SIGTERM", () => void shutdown());
}

void main().catch(error => {
  logProcessFailure("backend.startup_failure", error);
  const failure = { type: "error", message: error instanceof Error ? error.message : String(error) };
  process.parentPort?.postMessage(failure);
  if (process.send) process.send(failure);
  console.error(JSON.stringify(failure));
  // Exit once the message and stderr have been flushed, so the desktop app can show the reason.
  process.exitCode = 1;
  setTimeout(() => process.exit(1), 250).unref();
});
