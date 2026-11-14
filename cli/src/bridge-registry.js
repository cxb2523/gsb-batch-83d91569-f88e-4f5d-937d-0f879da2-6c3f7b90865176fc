import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { currentUid, defaultRuntimeDirectory, ensureSecureSocketDirectory } from "./socket-path.js";

export const BRIDGE_ID_PATTERN = /^bridge-[a-f0-9]{32}$/;
export const INSTANCE_ID_PATTERN = /^[a-f0-9-]{36}$/;

export function registryDirectory({ platform = process.platform, uid = currentUid() } = {}) {
  return defaultRuntimeDirectory({ platform, uid }) || path.join(os.tmpdir(), `easypost-${uid}-${process.env.USERNAME || "user"}`);
}

export function createBridgeIdentity({ installationId, extensionId, browserContext, browserNamespace = "", profileName = "", extensionVersion = "", instanceId = randomUUID() }) {
  if (!INSTANCE_ID_PATTERN.test(installationId) || !/^[a-p]{32}$/.test(extensionId) ||
      !["regular", "incognito"].includes(browserContext) || !INSTANCE_ID_PATTERN.test(instanceId)) {
    throw new Error("Invalid bridge identity registration");
  }
  const bridgeId = `bridge-${createHash("sha256").update(JSON.stringify([browserNamespace, extensionId, installationId, browserContext])).digest("hex").slice(0, 32)}`;
  return { bridgeId, instanceId, installationId, extensionId, browserContext, browserNamespace,
    channel: (extensionId === "ajdpfajmgibbniipjfgjiappllekpiak" || extensionId === "dmcejnbkknlkpcbaggoeiminccbpliaj") ? "store" : "local",
    extensionVersion: typeof extensionVersion === "string" ? extensionVersion.slice(0, 32) : "",
    profileName: typeof profileName === "string" ? profileName.trim().slice(0, 80) : "" };
}

export function instanceSocketPath(identity, { platform = process.platform, directory = registryDirectory({ platform }) } = {}) {
  return platform === "win32" ? `\\\\.\\pipe\\easypost-v2-${identity.instanceId}` : path.join(directory, `b2-${identity.instanceId.replaceAll("-", "").slice(0, 16)}.sock`);
}

export async function registerBridge(identity, socketPath, { directory = registryDirectory(), platform = process.platform } = {}) {
  if (platform !== "win32") await ensureSecureSocketDirectory(path.join(directory, "registry.sock"), { platform });
  else await fs.mkdir(directory, { recursive: true });
  const filename = path.join(directory, `bridge-v2-${identity.instanceId}.json`);
  const temporary = `${filename}.${randomUUID()}.tmp`;
  try {
    await fs.writeFile(temporary, JSON.stringify({ ...identity, socketPath, routingVersion: 2 }), { flag: "wx", mode: 0o600 });
    await fs.rename(temporary, filename);
  } finally {
    await fs.unlink(temporary).catch(() => {});
  }
  return async () => { await fs.unlink(filename).catch((error) => { if (error.code !== "ENOENT") throw error; }); };
}

export async function readBridgeRegistry({ directory = registryDirectory(), platform = process.platform } = {}) {
  let entries;
  try {
    const stat = await fs.lstat(directory);
    if (!stat.isDirectory() || stat.isSymbolicLink() || (platform !== "win32" && (stat.uid !== currentUid() || (stat.mode & 0o077) !== 0))) return [];
    entries = await fs.readdir(directory);
  } catch (error) { if (error.code === "ENOENT") return []; throw error; }
  const bridges = [];
  for (const name of entries.filter((name) => /^bridge-v2-[a-f0-9-]{36}\.json$/.test(name)).slice(0, 128)) {
    try {
      const filename = path.join(directory, name);
      const stat = await fs.lstat(filename);
      if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 8192 || (platform !== "win32" && stat.uid !== currentUid())) continue;
      const item = JSON.parse(await fs.readFile(filename, "utf8"));
      if (!BRIDGE_ID_PATTERN.test(item.bridgeId) || !INSTANCE_ID_PATTERN.test(item.instanceId) ||
          name !== `bridge-v2-${item.instanceId}.json` || item.socketPath !== instanceSocketPath(item, { directory, platform })) continue;
      bridges.push(item);
    } catch { /* A disconnected host may remove its own entry while discovery runs. */ }
  }
  return bridges;
}

function routePath(requestId, directory) {
  return path.join(directory, `route-${createHash("sha256").update(requestId).digest("hex")}.json`);
}

export async function rememberRequestRoute(requestId, target, { directory = registryDirectory() } = {}) {
  await ensureSecureSocketDirectory(path.join(directory, "route.sock"));
  const filename = routePath(requestId, directory);
  const route = { requestId, bridgeId: target.bridgeId, browserContext: target.browserContext };
  try { await fs.writeFile(filename, JSON.stringify(route), { flag: "wx", mode: 0o600 }); }
  catch (error) {
    if (error.code !== "EEXIST") throw error;
    const existing = await readRequestRoute(requestId, { directory });
    if (existing?.bridgeId !== route.bridgeId || existing?.browserContext !== route.browserContext) throw new Error("requestId is already bound to a different bridge");
  }
}

export async function readRequestRoute(requestId, { directory = registryDirectory() } = {}) {
  try {
    const stat = await fs.lstat(routePath(requestId, directory));
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 1024 || (process.platform !== "win32" && stat.uid !== currentUid())) throw new Error("Unsafe request route file");
    const route = JSON.parse(await fs.readFile(routePath(requestId, directory), "utf8"));
    if (route.requestId !== requestId || !BRIDGE_ID_PATTERN.test(route.bridgeId) || !["regular", "incognito"].includes(route.browserContext)) throw new Error("Invalid request route");
    return route;
  } catch (error) { if (error.code === "ENOENT") return null; throw error; }
}
