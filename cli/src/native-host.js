import fs from "node:fs";
import net from "node:net";
import { once } from "node:events";
import { createBridgeIdentity, instanceSocketPath, registerBridge, registryDirectory } from "./bridge-registry.js";
import {
  BROWSER_CONTEXTS,
  DEFAULT_BROWSER_CONTEXT,
  PROTOCOL_VERSION,
} from "./constants.js";
import { BRIDGE_ACTIONS } from "./bridge-client.js";
import { NdjsonParser, encodeNdjson } from "./ndjson.js";
import { NativeMessageParser, writeNativeMessage } from "./native-framing.js";
import { ensureSecureSocketDirectory, extensionIdFromOrigin, getSocketPath } from "./socket-path.js";

function log(stream, level, code, message, details) {
  const entry = { level, code, message };
  if (details !== undefined) entry.details = details;
  stream.write(`${JSON.stringify(entry)}\n`);
}

function errorResponse(id, code, message, details) {
  const error = { code, message };
  if (details !== undefined) error.details = details;
  return {
    protocolVersion: PROTOCOL_VERSION,
    kind: "response",
    id: id || null,
    ok: false,
    error,
  };
}

function validateRequest(request, browserContext, identity) {
  if (!request || typeof request !== "object") return "请求必须是对象";
  if (request.protocolVersion !== PROTOCOL_VERSION) return "协议版本不兼容";
  if (request.kind !== "request") return "kind 必须是 request";
  if (typeof request.id !== "string" || !request.id) return "id 必须是非空字符串";
  if (request.browserContext !== browserContext) return "browserContext 与 Native host 上下文不一致";
  if (request.bridgeTarget && (!identity || request.bridgeTarget.bridgeId !== identity.bridgeId || request.bridgeTarget.instanceId !== identity.instanceId)) return "bridgeTarget 与当前桥实例不一致";
  if (identity && ["execute", "cancel"].includes(request.action) && !request.bridgeTarget) return "执行与取消必须显式绑定 bridgeTarget";
  if (!BRIDGE_ACTIONS.has(request.action)) return "action 不受支持";
  if (!request.payload || typeof request.payload !== "object" || Array.isArray(request.payload)) {
    return "payload 必须是对象";
  }
  return null;
}

async function waitForBridgeRegistration(stdin, timeoutMs, requireRegistration) {
  const parser = new NativeMessageParser();
  return await new Promise((resolve, reject) => {
    let settled = false;
    const finish = (callback, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      stdin.off("data", onData);
      stdin.off("end", onEnd);
      stdin.off("error", onError);
      callback(value);
    };
    const onData = (chunk) => {
      try {
        for (const message of parser.push(chunk)) {
          if (message?.kind !== "bridge_registration" ||
              message.protocolVersion !== PROTOCOL_VERSION ||
              !BROWSER_CONTEXTS.includes(message.browserContext)) {
            finish(reject, new Error("Invalid browser-context registration from extension"));
            return;
          }
          finish(resolve, message);
          return;
        }
      } catch (error) {
        finish(reject, error);
      }
    };
    const onEnd = () => finish(reject, new Error("Extension closed before browser-context registration"));
    const onError = (error) => finish(reject, error);
    const timer = setTimeout(() => requireRegistration
      ? finish(reject, new Error("Extension did not register its browser context"))
      : finish(resolve, { browserContext: DEFAULT_BROWSER_CONTEXT }), timeoutMs);
    stdin.on("data", onData);
    stdin.once("end", onEnd);
    stdin.once("error", onError);
  });
}

async function socketIsActive(socketPath) {
  return await new Promise((resolve) => {
    const socket = net.createConnection({ path: socketPath });
    const timer = setTimeout(() => {
      socket.destroy();
      resolve(false);
    }, 150);
    socket.once("connect", () => {
      clearTimeout(timer);
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => {
      clearTimeout(timer);
      resolve(false);
    });
  });
}

async function prepareSocketPath(socketPath, platform) {
  if (platform === "win32") return;
  await ensureSecureSocketDirectory(socketPath, { platform });
  try {
    const stat = await fs.promises.lstat(socketPath);
    if (!stat.isSocket()) throw new Error("Existing bridge path is not a Unix socket");
    if (await socketIsActive(socketPath)) throw new Error("Another easypost native host is active");
    await fs.promises.unlink(socketPath);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
}

export async function startNativeHost({
  stdin = process.stdin,
  stdout = process.stdout,
  stderr = process.stderr,
  callerOrigin = null,
  socketPath = null,
  browserContext = DEFAULT_BROWSER_CONTEXT,
  registrationTimeoutMs = 500,
  requireRegistration = false,
  platform = process.platform,
  browserNamespace = "",
  registryPath = registryDirectory({ platform }),
} = {}) {
  const registration = browserContext === null
    ? await waitForBridgeRegistration(stdin, registrationTimeoutMs, requireRegistration)
    : { browserContext };
  const resolvedBrowserContext = registration.browserContext;
  const identity = registration.installationId ? createBridgeIdentity({
    installationId: registration.installationId,
    extensionId: extensionIdFromOrigin(callerOrigin),
    browserContext: resolvedBrowserContext, browserNamespace,
    profileName: registration.profileName, extensionVersion: registration.extensionVersion,
  }) : null;
  if (!BROWSER_CONTEXTS.includes(resolvedBrowserContext)) {
    throw new Error(`Unsupported browser context: ${resolvedBrowserContext}`);
  }
  const resolvedSocketPath = socketPath || (identity ? instanceSocketPath(identity, { platform, directory: registryPath }) : getSocketPath({
    extensionId: extensionIdFromOrigin(callerOrigin),
    browserContext: resolvedBrowserContext,
    platform,
    browserNamespace,
  }));
  await prepareSocketPath(resolvedSocketPath, platform);
  const pending = new Map();
  const clients = new Set();
  let closed = false;
  let nativeWriteQueue = Promise.resolve();
  let unregister = async () => {};
  const describe = () => ({ ...identity, routingVersion: identity ? 2 : 1, socketPath: resolvedSocketPath });

  const enqueueNative = (message, client) => {
    nativeWriteQueue = nativeWriteQueue
      .then(() => writeNativeMessage(stdout, message))
      .catch((error) => {
        pending.delete(message.id);
        client.write(
          encodeNdjson(errorResponse(message.id, error.code || "NATIVE_WRITE_FAILED", error.message)),
        );
      });
  };

  const server = net.createServer((client) => {
    clients.add(client);
    const parser = new NdjsonParser();
    client.on("data", (chunk) => {
      try {
        for (const request of parser.push(chunk)) {
          const validationError = validateRequest(request, resolvedBrowserContext, identity);
          if (validationError) {
            const code = validationError.includes("bridgeTarget")
              ? (request?.bridgeTarget ? "BRIDGE_IDENTITY_MISMATCH" : "BRIDGE_IDENTITY_REQUIRED") : "INVALID_REQUEST";
            client.write(encodeNdjson(errorResponse(request?.id, code, validationError)));
            continue;
          }
          if (request.action === "describe") {
            client.write(encodeNdjson({ protocolVersion: PROTOCOL_VERSION, kind: "response", id: request.id,
              ok: true, result: describe(), ...(identity ? { bridgeTarget: identity } : {}) }));
            continue;
          }
          if (pending.has(request.id)) {
            client.write(
              encodeNdjson(errorResponse(request.id, "DUPLICATE_REQUEST_ID", "请求 ID 正在处理中")),
            );
            continue;
          }
          pending.set(request.id, { client });
          enqueueNative(request, client);
        }
      } catch (error) {
        log(stderr, "error", error.code || "INVALID_NDJSON", error.message);
        client.destroy();
      }
    });
    client.on("close", () => {
      clients.delete(client);
      for (const [id, entry] of pending) {
        if (entry.client === client) pending.delete(id);
      }
    });
    client.on("error", (error) => {
      log(stderr, "warn", "CLI_SOCKET_ERROR", error.message);
    });
  });
  server.listen(resolvedSocketPath);
  await once(server, "listening");
  if (platform !== "win32") await fs.promises.chmod(resolvedSocketPath, 0o600);

  const nativeParser = new NativeMessageParser();
  const onNativeData = (chunk) => {
    try {
      for (const response of nativeParser.push(chunk)) {
        const entry = response && pending.get(response.id);
        if (!entry) {
          log(stderr, "warn", "UNMATCHED_NATIVE_RESPONSE", "收到无法匹配的扩展响应", {
            id: response?.id,
          });
          continue;
        }
        pending.delete(response.id);
        entry.client.write(encodeNdjson({ ...response, ...(identity ? { bridgeTarget: identity } : {}) }));
      }
    } catch (error) {
      log(stderr, "error", error.code || "NATIVE_PROTOCOL_ERROR", error.message);
      void close();
    }
  };
  const onNativeEnd = () => void close();
  const onNativeError = (error) => {
    log(stderr, "error", "NATIVE_STDIN_ERROR", error.message);
    void close();
  };
  stdin.on("data", onNativeData);
  stdin.once("end", onNativeEnd);
  stdin.once("error", onNativeError);

  async function close() {
    if (closed) return;
    closed = true;
    await unregister();
    stdin.off("data", onNativeData);
    stdin.off("end", onNativeEnd);
    stdin.off("error", onNativeError);
    for (const [id, entry] of pending) {
      entry.client.write(
        encodeNdjson(errorResponse(id, "EXTENSION_UNAVAILABLE", "Chrome 扩展连接已关闭")),
      );
    }
    pending.clear();
    for (const client of clients) client.destroy();
    await new Promise((resolve) => server.close(resolve));
    if (platform !== "win32") {
      await fs.promises.unlink(resolvedSocketPath).catch((error) => {
        if (error.code !== "ENOENT") throw error;
      });
    }
  }

  if (identity) {
    try {
      unregister = await registerBridge(identity, resolvedSocketPath, { directory: registryPath, platform });
      await writeNativeMessage(stdout, { protocolVersion: PROTOCOL_VERSION, kind: "bridge_ready", bridgeTarget: identity });
    } catch (error) { await close(); throw error; }
  }
  return {
    identity,
    socketPath: resolvedSocketPath,
    browserContext: resolvedBrowserContext,
    callerOrigin,
    extensionId: extensionIdFromOrigin(callerOrigin),
    server,
    pending,
    close,
  };
}
