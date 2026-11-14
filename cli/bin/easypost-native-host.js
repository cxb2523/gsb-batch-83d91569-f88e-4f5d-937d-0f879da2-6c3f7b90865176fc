#!/usr/bin/env node
import { EXIT_CODES } from "../src/constants.js";
import { startNativeHost } from "../src/native-host.js";
import { nativeHostBrowserNamespace } from "../src/browser-owner.js";

try {
  const callerOrigin = process.argv.slice(2).find((value) => value.startsWith("chrome-extension://")) || null;
  const browserNamespace = nativeHostBrowserNamespace();
  const host = await startNativeHost({ callerOrigin, browserContext: null, browserNamespace, registrationTimeoutMs: 5_000, requireRegistration: true });
  const shutdown = async () => {
    await host.close();
    process.exitCode = 0;
  };
  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);
} catch (error) {
  process.stderr.write(
    `${JSON.stringify({
      level: "error",
      code: error.code || "NATIVE_HOST_START_FAILED",
      message: error.message,
    })}\n`,
  );
  process.exitCode = EXIT_CODES.BRIDGE;
}
