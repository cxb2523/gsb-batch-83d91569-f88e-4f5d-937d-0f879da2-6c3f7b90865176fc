import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { EXIT_CODES, NATIVE_HOST_NAME } from "./constants.js";
import { CliError } from "./errors.js";

export const EXTENSION_ID_PATTERN = /^[a-p]{32}$/;
export const DEFAULT_HOST_ENTRY = fileURLToPath(
  new URL("../bin/easypost-native-host.js", import.meta.url),
);
export const WINDOWS_REGISTRY_KEY = `HKCU\\Software\\Google\\Chrome\\NativeMessagingHosts\\${NATIVE_HOST_NAME}`;
const execFileAsync = promisify(execFile);

function installError(code, message, details) {
  return new CliError(code, message, {
    exitCode: EXIT_CODES.INPUT,
    details,
  });
}

export function validateExtensionId(extensionId) {
  if (typeof extensionId !== "string" || !EXTENSION_ID_PATTERN.test(extensionId)) {
    throw installError(
      "INVALID_EXTENSION_ID",
      "--extension-id 必须是 32 位 Chrome 扩展 ID（仅含 a-p）",
      { extensionId },
    );
  }
  return extensionId;
}

export function nativeManifestDirectory({ platform = process.platform, home = os.homedir() } = {}) {
  if (platform === "darwin") {
    return path.join(home, "Library", "Application Support", "Google", "Chrome", "NativeMessagingHosts");
  }
  if (platform === "linux") {
    return path.join(home, ".config", "google-chrome", "NativeMessagingHosts");
  }
  if (platform === "win32") return path.win32.join(home, ".easypost", "native-host");
  throw installError("UNSUPPORTED_PLATFORM", "当前操作系统不受支持", { platform });
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", `'"'"'`)}'`;
}

function windowsBatchQuote(value) {
  if (/[\r\n"]/.test(value)) throw installError("INVALID_HOST_PATH", "Windows host 路径包含无效字符");
  return `"${String(value).replaceAll("%", "%%")}"`;
}

export function createWrapper({
  execPath = process.execPath,
  hostPath = DEFAULT_HOST_ENTRY,
  platform = process.platform,
} = {}) {
  const platformPath = platform === "win32" ? path.win32 : path;
  if (!platformPath.isAbsolute(execPath) || !platformPath.isAbsolute(hostPath)) {
    throw installError("INVALID_HOST_PATH", "Node 和 host 路径必须是绝对路径");
  }
  if (platform === "win32") {
    return `@echo off\r\n${windowsBatchQuote(execPath)} ${windowsBatchQuote(hostPath)} %*\r\n`;
  }
  return `#!/bin/sh\nexec ${shellQuote(execPath)} ${shellQuote(hostPath)} "$@"\n`;
}

export function createNativeManifest({ extensionId, extensionIds, wrapperPath, platform = process.platform }) {
  const ids = [...new Set([...(extensionIds || []), ...(extensionId ? [extensionId] : [])])];
  if (!ids.length) throw installError("EXTENSION_NOT_FOUND", "未发现 EasyPost 扩展 ID，请先在 Chrome / Edge 安装扩展，或传入 --extension-id <id>");
  ids.forEach(validateExtensionId);
  const platformPath = platform === "win32" ? path.win32 : path;
  if (!platformPath.isAbsolute(wrapperPath)) throw installError("INVALID_HOST_PATH", "wrapper 路径必须是绝对路径");
  return {
    name: NATIVE_HOST_NAME,
    description: "EasyPost CLI Native Messaging bridge",
    path: wrapperPath,
    type: "stdio",
    allowed_origins: ids.map((id) => `chrome-extension://${id}/`),
  };
}

function chromeUserDataDirectory({ platform = process.platform, home = os.homedir() } = {}) {
  if (platform === "darwin") return path.join(home, "Library", "Application Support", "Google", "Chrome");
  if (platform === "linux") return path.join(home, ".config", "google-chrome");
  if (platform === "win32") {
    return path.win32.join(home, "AppData", "Local", "Google", "Chrome", "User Data");
  }
  return null;
}

export async function discoverExtensionIds({ platform = process.platform, home = os.homedir() } = {}) {
  const userData = chromeUserDataDirectory({ platform, home });
  if (!userData) return [];
  let profiles = [];
  try {
    profiles = (await fs.promises.readdir(userData, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory() && (entry.name === "Default" || /^Profile \d+$/.test(entry.name)))
      .map((entry) => entry.name);
  } catch (_error) {
    return [];
  }
  const ids = new Set();
  for (const profile of profiles) {
    for (const preferenceName of ["Preferences", "Secure Preferences"]) {
      try {
        const parsed = JSON.parse(await fs.promises.readFile(path.join(userData, profile, preferenceName), "utf8"));
        const settings = parsed?.extensions?.settings || {};
        for (const [id, setting] of Object.entries(settings)) {
          let manifest = setting?.manifest || {};
          if (!manifest.name && typeof setting?.path === "string" && path.isAbsolute(setting.path)) {
            try {
              manifest = JSON.parse(await fs.promises.readFile(path.join(setting.path, "manifest.json"), "utf8"));
            } catch (_error) {}
          }
          if (!EXTENSION_ID_PATTERN.test(id)) continue;
          const isMatch =
            manifest.name === "快推 EasyPost" ||
            manifest.name === "一键发" ||
            manifest.name === "__MSG_extensionName__" ||
            (typeof manifest.name === "string" && (manifest.name.includes("EasyPost") || manifest.name.includes("快推") || manifest.name.includes("一键发"))) ||
            (typeof manifest.homepage_url === "string" && (manifest.homepage_url.includes("yijianfa") || manifest.homepage_url.includes("easypost")));
          if (isMatch) ids.add(id);
        }
      } catch (_error) {
        // 单个 profile 的偏好文件可能被 Chrome 原子替换；继续检查其他来源。
      }
    }
  }
  return [...ids].sort();
}

async function atomicWrite(filePath, content, mode) {
  const tempPath = `${filePath}.tmp-${process.pid}-${randomBytes(6).toString("hex")}`;
  try {
    await fs.promises.writeFile(tempPath, content, { encoding: "utf8", mode, flag: "wx" });
    if (process.platform !== "win32") await fs.promises.chmod(tempPath, mode);
    await fs.promises.rename(tempPath, filePath);
  } finally {
    await fs.promises.rm(tempPath, { force: true }).catch(() => {});
  }
}

export function installationPaths({ platform = process.platform, home = os.homedir() } = {}) {
  const manifestDirectory = nativeManifestDirectory({ platform, home });
  const platformPath = platform === "win32" ? path.win32 : path;
  const stateDirectory = platformPath.join(home, ".easypost", "native-host");
  return {
    stateDirectory,
    wrapperPath: platformPath.join(
      stateDirectory,
      platform === "win32" ? `${NATIVE_HOST_NAME}.cmd` : `${NATIVE_HOST_NAME}.sh`,
    ),
    manifestPath: platformPath.join(manifestDirectory, `${NATIVE_HOST_NAME}.json`),
    ...(platform === "win32" ? { registryKey: WINDOWS_REGISTRY_KEY } : {}),
  };
}

export const windowsRegistry = {
  async set(key, value) {
    await execFileAsync("reg.exe", ["ADD", key, "/ve", "/t", "REG_SZ", "/d", value, "/f"], {
      windowsHide: true,
    });
  },
  async get(key) {
    try {
      const { stdout } = await execFileAsync("reg.exe", ["QUERY", key, "/ve"], {
        windowsHide: true,
        encoding: "utf8",
      });
      const match = stdout.match(/REG_SZ\s+(.+)\s*$/m);
      return match ? match[1].trim() : null;
    } catch (error) {
      if ([1, 2].includes(error.code)) return null;
      throw error;
    }
  },
  async remove(key) {
    try {
      await execFileAsync("reg.exe", ["DELETE", key, "/f"], { windowsHide: true });
      return true;
    } catch (error) {
      if ([1, 2].includes(error.code)) return false;
      throw error;
    }
  },
};

export async function installNativeHost({
  extensionId,
  extensionIds,
  platform = process.platform,
  home = os.homedir(),
  execPath = process.execPath,
  hostPath = DEFAULT_HOST_ENTRY,
  registry = windowsRegistry,
} = {}) {
  const discovered = extensionId || extensionIds?.length
    ? []
    : await discoverExtensionIds({ platform, home });
  const resolvedIds = [...new Set([...(extensionIds || []), ...(extensionId ? [extensionId] : []), ...discovered])];
  if (!resolvedIds.length) {
    throw installError("EXTENSION_NOT_FOUND", "未在 Chrome 配置中发现一键发扩展", {
      hint: "确认扩展已安装，或显式传 --extension-id",
    });
  }
  resolvedIds.forEach(validateExtensionId);
  const paths = installationPaths({ platform, home });
  const wrapper = createWrapper({ execPath, hostPath, platform });
  const manifest = createNativeManifest({
    extensionIds: resolvedIds,
    wrapperPath: paths.wrapperPath,
    platform,
  });

  await fs.promises.mkdir(paths.stateDirectory, { recursive: true, mode: 0o700 });
  if (platform !== "win32") await fs.promises.chmod(paths.stateDirectory, 0o700);
  await fs.promises.mkdir(path.dirname(paths.manifestPath), { recursive: true });
  await atomicWrite(paths.wrapperPath, wrapper, 0o700);
  await atomicWrite(paths.manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 0o644);
  if (platform === "win32") await registry.set(paths.registryKey, paths.manifestPath);

  return {
    status: "installed",
    hostName: NATIVE_HOST_NAME,
    platform,
    extensionIds: resolvedIds,
    files: {
      manifest: "installed",
      wrapper: "installed",
      ...(platform === "win32" ? { registry: "installed" } : {}),
    },
  };
}

async function removeFile(filePath) {
  try {
    await fs.promises.unlink(filePath);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

export async function uninstallNativeHost({
  platform = process.platform,
  home = os.homedir(),
  registry = windowsRegistry,
} = {}) {
  const paths = installationPaths({ platform, home });
  const removedRegistry = platform === "win32" ? await registry.remove(paths.registryKey) : undefined;
  const removedManifest = await removeFile(paths.manifestPath);
  const removedWrapper = await removeFile(paths.wrapperPath);
  return {
    status: "uninstalled",
    hostName: NATIVE_HOST_NAME,
    platform,
    removed: {
      manifest: removedManifest,
      wrapper: removedWrapper,
      ...(platform === "win32" ? { registry: removedRegistry } : {}),
    },
  };
}

export async function inspectNativeHostInstallation({
  platform = process.platform,
  home = os.homedir(),
  registry = windowsRegistry,
} = {}) {
  const paths = installationPaths({ platform, home });
  const result = { ...paths, installed: false, manifest: null };
  if (platform === "win32") {
    result.registryManifestPath = await registry.get(paths.registryKey);
  }
  try {
    const text = await fs.promises.readFile(paths.manifestPath, "utf8");
    result.manifest = JSON.parse(text);
    result.installed = result.manifest?.name === NATIVE_HOST_NAME && (
      platform !== "win32" || result.registryManifestPath === paths.manifestPath
    );
  } catch (error) {
    if (error.code !== "ENOENT") result.error = error.message;
  }
  try {
    const stat = await fs.promises.stat(paths.wrapperPath);
    result.wrapper = {
      exists: stat.isFile(),
      executable: stat.isFile() && (platform === "win32" || (stat.mode & 0o111) !== 0),
      mode: stat.mode & 0o777,
    };
  } catch (error) {
    result.wrapper = {
      exists: false,
      executable: false,
      ...(error.code !== "ENOENT" ? { error: error.message } : {}),
    };
  }
  return result;
}

export function diagnoseNativeHost({ installation, extensionIds = [] } = {}) {
  if (!installation?.installed) return { state: "host_not_installed", recoverable: true };
  if (!installation.wrapper?.exists || !installation.wrapper?.executable || installation.manifest?.type !== "stdio") {
    return { state: "host_config_error", recoverable: true };
  }
  const allowed = new Set(Array.isArray(installation.manifest?.allowed_origins)
    ? installation.manifest.allowed_origins
    : []);
  const missing = extensionIds.filter((id) => !allowed.has(`chrome-extension://${id}/`));
  if (extensionIds.length && missing.length) {
    return { state: "extension_id_mismatch", recoverable: true, missingExtensionIds: missing };
  }
  return { state: "configured", recoverable: false };
}
