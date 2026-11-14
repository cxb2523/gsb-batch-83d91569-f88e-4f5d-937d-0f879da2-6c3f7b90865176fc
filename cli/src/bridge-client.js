import net from "node:net";
import fs from "node:fs/promises";
import path from "node:path";
import { readBridgeRegistry, registryDirectory } from "./bridge-registry.js";
import { randomUUID } from "node:crypto";
import {
  DEFAULT_DOCTOR_WAIT_MS,
  DEFAULT_BROWSER_CONTEXT,
  DEFAULT_TIMEOUT_MS,
  EXIT_CODES,
  PROTOCOL_VERSION,
} from "./constants.js";
import { CliError, remoteErrorToCliError } from "./errors.js";
import { NdjsonParser, encodeNdjson } from "./ndjson.js";
import { getSocketCandidates } from "./socket-path.js";

export const BRIDGE_ACTIONS = new Set(["doctor", "capabilities", "execute", "status", "cancel", "describe"]);

function bridgeError(code, message, details, cause) {
  return new CliError(code, message, {
    exitCode: EXIT_CODES.BRIDGE,
    hint: "确认 Chrome 正在运行、EasyPost 扩展已启用，并运行 easypost doctor --wait",
    details,
    cause,
  });
}

export function createBridgeRequest(
  action,
  payload = {},
  { id = randomUUID(), browserContext = DEFAULT_BROWSER_CONTEXT, bridgeTarget } = {},
) {
  if (!BRIDGE_ACTIONS.has(action)) throw new TypeError(`Unsupported bridge action: ${action}`);
  return {
    protocolVersion: PROTOCOL_VERSION,
    kind: "request",
    id,
    browserContext,
    ...(bridgeTarget ? { bridgeTarget } : {}),
    action,
    payload,
  };
}

export async function requestBridge(
  action,
  payload = {},
  {
    socketPath,
    socketPaths,
    bridgeTarget,
    timeoutMs = DEFAULT_TIMEOUT_MS,
    id = randomUUID(),
    browserContext = DEFAULT_BROWSER_CONTEXT,
  } = {},
) {
  const resolvedSocketPath = socketPath || await selectBridgeSocketPath(
    socketPaths || getSocketCandidates({ browserContext }),
  );
  const request = createBridgeRequest(action, payload, { id, browserContext, bridgeTarget });
  return await new Promise((resolve, reject) => {
    const socket = net.createConnection({ path: resolvedSocketPath });
    const parser = new NdjsonParser();
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      callback(value);
    };
    const timer = timeoutMs === null
      ? null
      : setTimeout(() => {
          finish(
            reject,
            bridgeError("BRIDGE_TIMEOUT", "等待一键发扩展响应超时", { timeoutMs, action }),
          );
        }, timeoutMs);
    timer?.unref?.();

    socket.once("connect", () => {
      try {
        socket.write(encodeNdjson(request));
      } catch (error) {
        finish(reject, bridgeError("BRIDGE_PROTOCOL_ERROR", error.message, undefined, error));
      }
    });
    socket.on("data", (chunk) => {
      try {
        for (const response of parser.push(chunk)) {
          if (!response || response.id !== id) continue;
          if (response.protocolVersion !== PROTOCOL_VERSION) {
            finish(reject, bridgeError("BRIDGE_PROTOCOL_ERROR", "桥返回了不兼容的协议版本"));
            return;
          }
          if (bridgeTarget && response.ok !== false && (response.bridgeTarget?.bridgeId !== bridgeTarget.bridgeId || response.bridgeTarget?.instanceId !== bridgeTarget.instanceId)) {
            finish(reject, bridgeError("BRIDGE_IDENTITY_MISMATCH", "响应来自不同桥实例"));
            return;
          }
          if (response.ok === false) finish(reject, remoteErrorToCliError(response.error));
          else if (response.ok === true) finish(resolve, response.result);
          else finish(reject, bridgeError("BRIDGE_PROTOCOL_ERROR", "桥响应缺少 ok 字段"));
          return;
        }
      } catch (error) {
        finish(reject, bridgeError("BRIDGE_PROTOCOL_ERROR", error.message, undefined, error));
      }
    });
    socket.once("error", (error) => {
      const unavailable = ["ENOENT", "ECONNREFUSED", "ECONNRESET", "EPIPE"].includes(error.code);
      finish(
        reject,
        bridgeError(
          unavailable ? "BRIDGE_UNAVAILABLE" : "BRIDGE_ERROR",
          unavailable ? "一键发本机桥尚未连接" : "无法连接一键发本机桥",
          { reason: error.code, socketPath: resolvedSocketPath },
          error,
        ),
      );
    });
    socket.once("end", () => {
      if (!settled) finish(reject, bridgeError("BRIDGE_CLOSED", "本机桥在响应前关闭了连接"));
    });
  });
}

async function socketIsReachable(socketPath) {
  return await new Promise((resolve) => {
    const socket = net.createConnection({ path: socketPath });
    const finish = (value) => {
      clearTimeout(timer);
      socket.destroy();
      resolve(value);
    };
    const timer = setTimeout(() => finish(false), 150);
    timer.unref?.();
    socket.once("connect", () => finish(true));
    socket.once("error", () => finish(false));
  });
}

export async function selectBridgeSocketPath(socketPaths = getSocketCandidates()) {
  const candidates = [...new Set(socketPaths.filter(Boolean))];
  for (const candidate of candidates) {
    if (await socketIsReachable(candidate)) return candidate;
  }
  return candidates[0];
}

function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export async function waitForBridge(
  action,
  payload = {},
  {
    waitMs = DEFAULT_DOCTOR_WAIT_MS,
    attemptTimeoutMs = 1_000,
    retryMs = 100,
    socketPath,
    socketPaths,
    bridgeTarget,
    browserContext = DEFAULT_BROWSER_CONTEXT,
  } = {},
) {
  const deadline = Date.now() + waitMs;
  let lastError;
  do {
    try {
      return await requestBridge(action, payload, {
        socketPath,
        socketPaths,
        bridgeTarget,
        browserContext,
        timeoutMs: Math.min(attemptTimeoutMs, Math.max(1, deadline - Date.now())),
      });
    } catch (error) {
      lastError = error;
      if (!(error instanceof CliError) || error.exitCode !== EXIT_CODES.BRIDGE) throw error;
    }
    if (Date.now() < deadline) await delay(Math.min(retryMs, deadline - Date.now()));
  } while (Date.now() < deadline);
  throw lastError || bridgeError("BRIDGE_UNAVAILABLE", "一键发本机桥尚未连接");
}

// Discovery is bounded and serial. Registry data is only a hint until a live
// host confirms the exact stable identity and connection epoch.
export async function discoverBridges({ directory = registryDirectory(), browserContext, env = process.env } = {}) {
  const online = [];
  const registrations = await readBridgeRegistry({ directory });
  for (const entry of registrations) {
    if (env.YIJIANFA_SOCKET_PATH && entry.socketPath !== env.YIJIANFA_SOCKET_PATH) continue;
    if (browserContext && entry.browserContext !== browserContext) continue;
    try {
      const result = await requestBridge("describe", {}, { socketPath: entry.socketPath, browserContext: entry.browserContext,
        bridgeTarget: entry, timeoutMs: 500 });
      if (result.bridgeId === entry.bridgeId && result.instanceId === entry.instanceId) online.push({ ...result, identityVerified: true });
    } catch { /* Offline/stale registrations cannot be selected. */ }
  }
  let legacyPaths = env.YIJIANFA_SOCKET_PATH ? [env.YIJIANFA_SOCKET_PATH] : [];
  if (!env.YIJIANFA_SOCKET_PATH) {
    const names = await fs.readdir(directory).catch(() => []);
    legacyPaths = names.filter((name) => /^bridge-v1(?:-store)?(?:-browser-[a-f0-9]{12})?(?:-incognito)?\.sock$/.test(name)).map((name) => path.join(directory, name));
    if (process.platform === "win32") legacyPaths.push(...getSocketCandidates({ browserContext: browserContext || DEFAULT_BROWSER_CONTEXT, env }));
  }
  for (const socketPath of [...new Set(legacyPaths)].slice(0, 128)) {
    if (online.some((entry) => entry.socketPath === socketPath)) continue;
    const context = socketPath.includes("-incognito") ? "incognito" : (browserContext || DEFAULT_BROWSER_CONTEXT);
    if (browserContext && context !== browserContext) continue;
    try {
      const result = await requestBridge("doctor", {}, { socketPath, browserContext: context, timeoutMs: 500 });
      online.push({ socketPath, browserContext: context, identityVerified: false, routingVersion: 1, extensionId: result.runtime?.id || null });
    } catch { /* Missing legacy sockets are normal. */ }
  }
  return online;
}

export async function resolveBridgeSelection({ bridgeId, profile, browserContext = DEFAULT_BROWSER_CONTEXT, directory, env } = {}) {
  const online = await discoverBridges({ directory, browserContext, env });
  const candidates = online.filter((item) => (!bridgeId || item.bridgeId === bridgeId) && (!profile || item.profileName === profile));
  if (!candidates.length) throw bridgeError("BRIDGE_UNAVAILABLE", "没有找到指定的在线桥", { bridgeId, profile, browserContext });
  if (candidates.length !== 1) throw bridgeError("BRIDGE_AMBIGUOUS", "有多个在线桥，请使用 --bridge-id 明确选择", { bridges: candidates });
  const selected = candidates[0];
  if ((bridgeId || profile) && !selected.identityVerified) throw bridgeError("BRIDGE_IDENTITY_UNAVAILABLE", "旧桥不支持目标身份校验，请升级扩展与 Native host");
  return { socketPath: selected.socketPath, browserContext: selected.browserContext,
    ...(selected.identityVerified ? { bridgeTarget: selected } : {}) };
}

export async function waitForBridgeSelection(selection, { waitMs = DEFAULT_DOCTOR_WAIT_MS + 5_000, retryMs = 250 } = {}) {
  const deadline = Date.now() + waitMs;
  do {
    try { return await resolveBridgeSelection(selection); }
    catch (error) {
      if (error.code !== "BRIDGE_UNAVAILABLE" || Date.now() >= deadline) throw error;
    }
    await delay(Math.min(retryMs, Math.max(1, deadline - Date.now())));
  } while (true);
}
