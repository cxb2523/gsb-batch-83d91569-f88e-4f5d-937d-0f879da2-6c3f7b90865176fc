import fs from "node:fs";
import path from "node:path";
import {
  BROWSER_CONTEXTS,
  DEFAULT_BROWSER_CONTEXT,
  OFFICIAL_EXTENSION_ID,
  LEGACY_EXTENSION_ID,
} from "./constants.js";

export function currentUid() {
  return typeof process.getuid === "function" ? process.getuid() : 0;
}

export function defaultRuntimeDirectory({ uid = currentUid(), platform = process.platform, env = process.env } = {}) {
  const runtimeDir = env.EASYPOST_RUNTIME_DIR || env.YIJIANFA_RUNTIME_DIR;
  if (runtimeDir) {
    if (!(platform === "win32" ? path.win32 : path).isAbsolute(runtimeDir)) throw new Error("EASYPOST_RUNTIME_DIR must be absolute");
    return runtimeDir;
  }
  if (platform === "win32") return null;
  return path.join("/tmp", `easypost-${uid}`);
}

export function defaultWindowsPipeName({ env = process.env } = {}) {
  const identity = String(env.USERNAME || env.USER || "current-user")
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "") || "current-user";
  return `\\\\.\\pipe\\easypost-${identity}-bridge-v1`;
}

export function extensionIdFromOrigin(origin) {
  const match = String(origin || "").match(/^chrome-extension:\/\/([a-p]{32})\/?$/);
  return match ? match[1] : null;
}

function isOfficialChannel({ extensionId, channel } = {}) {
  return channel === "store" || extensionId === OFFICIAL_EXTENSION_ID || extensionId === LEGACY_EXTENSION_ID;
}

export function getSocketPath({
  env = process.env,
  uid = currentUid(),
  platform = process.platform,
  extensionId = null,
  channel = null,
  browserContext = DEFAULT_BROWSER_CONTEXT,
  browserNamespace = "",
} = {}) {
  if (!BROWSER_CONTEXTS.includes(browserContext)) {
    throw new Error(`Unsupported browser context: ${browserContext}`);
  }
  if (env.YIJIANFA_SOCKET_PATH) {
    const isAbsolute = platform === "win32"
      ? /^\\\\[.?]\\pipe\\[^\\]+/i.test(env.YIJIANFA_SOCKET_PATH)
      : path.isAbsolute(env.YIJIANFA_SOCKET_PATH);
    if (!isAbsolute) {
      throw new Error("YIJIANFA_SOCKET_PATH must be absolute");
    }
    return env.YIJIANFA_SOCKET_PATH;
  }
  const official = isOfficialChannel({ extensionId, channel });
  if (browserNamespace && !/^browser-[a-f0-9]{12}$/.test(browserNamespace)) {
    throw new Error("Invalid browser socket namespace");
  }
  const browserSuffix = browserNamespace ? `-${browserNamespace}` : "";
  const contextSuffix = browserContext === "incognito" ? "-incognito" : "";
  if (platform === "win32") {
    const base = defaultWindowsPipeName({ env });
    return `${official ? `${base}-store` : base}${browserSuffix}${contextSuffix}`;
  }
  return path.join(
    defaultRuntimeDirectory({ uid, platform, env }),
    `${official ? "bridge-v1-store" : "bridge-v1"}${browserSuffix}${contextSuffix}.sock`,
  );
}

export function getSocketCandidates(options = {}) {
  if (options.env?.YIJIANFA_SOCKET_PATH) return [getSocketPath(options)];
  return [
    getSocketPath({ ...options, channel: "store" }),
    getSocketPath({ ...options, channel: "local" }),
  ];
}

export async function ensureSecureSocketDirectory(
  socketPath,
  { uid = currentUid(), platform = process.platform } = {},
) {
  if (platform === "win32") return null;
  const directory = path.dirname(socketPath);
  await fs.promises.mkdir(directory, { recursive: true, mode: 0o700 });
  const stat = await fs.promises.lstat(directory);
  if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error("Socket runtime path is not a directory");
  if (typeof process.getuid === "function" && stat.uid !== uid) {
    throw new Error("Socket runtime directory is not owned by the current user");
  }
  await fs.promises.chmod(directory, 0o700);
  return directory;
}
