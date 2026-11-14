import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";

// Chrome and embedded Chromium browsers can load the same extension ID.
// Keep Chrome's public bridge stable; isolate other macOS browser executables.
export function browserSocketNamespace(executable) {
  const owner = String(executable || "").trim();
  if (!owner) throw new Error("Cannot identify native host browser owner");
  if (owner.endsWith("/Google Chrome.app/Contents/MacOS/Google Chrome")) return "";
  return `browser-${createHash("sha256").update(owner).digest("hex").slice(0, 12)}`;
}

export function nativeHostBrowserNamespace({
  platform = process.platform,
  parentPid = process.ppid,
  readExecutable = (pid) => execFileSync("/bin/ps", ["-p", String(pid), "-o", "comm="], {
    encoding: "utf8", timeout: 2_000, maxBuffer: 16_384,
  }),
} = {}) {
  if (platform !== "darwin") return "";
  return browserSocketNamespace(readExecutable(parentPid));
}
