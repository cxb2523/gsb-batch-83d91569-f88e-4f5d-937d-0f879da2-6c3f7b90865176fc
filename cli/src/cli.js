import fs from "node:fs";
import path from "node:path";
import { TextDecoder } from "node:util";
import {
  COMMANDS,
  BROWSER_CONTEXTS,
  CONTENT_TYPES,
  DEFAULT_DOCTOR_WAIT_MS,
  DEFAULT_TIMEOUT_MS,
  EXIT_CODES,
  PACKAGE_NAME,
  PREPARED_SCHEMA,
  PROTOCOL_VERSION,
  VERSION,
} from "./constants.js";
import { BRIDGE_ID_PATTERN, rememberRequestRoute, readRequestRoute } from "./bridge-registry.js";
import { CliError, asCliError, exitCodeForRemoteCode, remoteErrorToCliError } from "./errors.js";
import { parseInputJson, normalizeInput, validateRequestId } from "./schema.js";
import { inspectAssets } from "./assets.js";
import { prepareXArticleImages } from "./x-article-images.js";
import { createPayloadDigest } from "./canonical-json.js";
import { startAssetServer } from "./asset-server.js";
import { requestBridge, waitForBridge, discoverBridges, resolveBridgeSelection, waitForBridgeSelection } from "./bridge-client.js";
import {
  diagnoseNativeHost,
  discoverExtensionIds,
  inspectNativeHostInstallation,
  installNativeHost,
  uninstallNativeHost,
} from "./host-install.js";

const FLAG_DEFINITIONS = new Map([
  ["--bridge-id", { name: "bridgeId", value: true }],
  ["--profile", { name: "profile", value: true }],
  ["--input", { name: "input", value: true }],
  ["--personal-declaration", { name: "personalDeclaration", value: true }],
  ["--allow-download", { name: "allowDownload", value: true }],
  ["--request-id", { name: "requestId", value: true }],
  ["--extension-id", { name: "extensionId", value: true }],
  ["--browser-context", { name: "browserContext", value: true }],
  ["--timeout", { name: "timeout", value: true }],
  ["--yes", { name: "yes", value: false }],
  ["--dry-run", { name: "dryRun", value: false }],
  ["--repair", { name: "repair", value: false }],
  ["--wait", { name: "wait", optionalSeconds: true }],
  ["--help", { name: "help", value: false }],
  ["-h", { name: "help", value: false }],
]);

const FLAGS_BY_COMMAND = Object.freeze({
  help: new Set(),
  version: new Set(),
  bridges: new Set(["browserContext", "timeout", "help"]),
  doctor: new Set(["bridgeId", "profile", "browserContext", "timeout", "wait", "repair", "help"]),
  capabilities: new Set(["bridgeId", "profile", "browserContext", "timeout", "help"]),
  prepare: new Set(["bridgeId", "profile", "browserContext", "input", "personalDeclaration", "allowDownload", "help"]),
  fill: new Set(["bridgeId", "profile", "browserContext", "input", "personalDeclaration", "allowDownload", "dryRun", "help"]),
  publish: new Set(["bridgeId", "profile", "browserContext", "input", "personalDeclaration", "allowDownload", "dryRun", "yes", "help"]),
  status: new Set(["bridgeId", "profile", "browserContext", "requestId", "timeout", "help"]),
  cancel: new Set(["bridgeId", "profile", "browserContext", "requestId", "timeout", "help"]),
  "install-host": new Set(["extensionId", "help"]),
  "uninstall-host": new Set(["help"]),
});

function commandError(message, details) {
  return new CliError("INVALID_ARGUMENT", message, {
    exitCode: EXIT_CODES.INPUT,
    hint: "运行 easypost help 查看可用命令和参数",
    details,
  });
}

function parsePositiveInteger(value, flag) {
  if (!/^\d+$/.test(String(value)) || Number(value) <= 0 || !Number.isSafeInteger(Number(value))) {
    throw commandError(`${flag} 必须是正整数毫秒数`, { value });
  }
  return Number(value);
}

function parseWaitSeconds(value) {
  const seconds = parsePositiveInteger(value, "--wait");
  const milliseconds = seconds * 1_000;
  if (!Number.isSafeInteger(milliseconds)) throw commandError("--wait 秒数过大", { value });
  return milliseconds;
}

export function parseArgv(argv) {
  const args = [...argv];
  if (args.length === 0) return { command: "help", options: {}, positionals: [] };
  if (["--version", "-V"].includes(args[0])) return { command: "version", options: {}, positionals: [] };
  if (["--help", "-h"].includes(args[0])) return { command: "help", options: {}, positionals: [] };
  const command = args.shift();
  if (!COMMANDS.includes(command)) throw commandError(`未知命令：${command}`, { command });

  const options = {};
  const positionals = [];
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === "--") {
      positionals.push(...args.slice(index + 1));
      break;
    }
    if (!argument.startsWith("-")) {
      positionals.push(argument);
      continue;
    }
    const equalIndex = argument.indexOf("=");
    const flag = equalIndex >= 0 ? argument.slice(0, equalIndex) : argument;
    const inlineValue = equalIndex >= 0 ? argument.slice(equalIndex + 1) : undefined;
    const definition = FLAG_DEFINITIONS.get(flag);
    if (!definition) throw commandError(`未知参数：${flag}`, { command, flag });
    if (!FLAGS_BY_COMMAND[command].has(definition.name)) {
      throw commandError(`${command} 不支持 ${flag}`, { command, flag });
    }
    if (options[definition.name] !== undefined) throw commandError(`${flag} 不能重复`);
    if (definition.optionalSeconds) {
      if (inlineValue !== undefined) {
        options[definition.name] = parseWaitSeconds(inlineValue);
      } else if (args[index + 1] !== undefined && !args[index + 1].startsWith("-")) {
        options[definition.name] = parseWaitSeconds(args[++index]);
      } else {
        options[definition.name] = true;
      }
      continue;
    }
    if (!definition.value) {
      if (inlineValue !== undefined) throw commandError(`${flag} 不接受值`);
      options[definition.name] = true;
      continue;
    }
    const value = inlineValue !== undefined ? inlineValue : args[++index];
    if (value === undefined || value.startsWith("--")) throw commandError(`${flag} 缺少值`);
    options[definition.name] = value;
  }
  if (options.timeout !== undefined) options.timeout = parsePositiveInteger(options.timeout, "--timeout");
  if (options.personalDeclaration !== undefined) {
    if (!["true", "false"].includes(options.personalDeclaration)) throw commandError("--personal-declaration 必须是 true 或 false");
    options.personalDeclaration = options.personalDeclaration === "true";
  }
  if (options.allowDownload !== undefined) {
    if (!["true", "false"].includes(options.allowDownload)) throw commandError("--allow-download 必须是 true 或 false");
    options.allowDownload = options.allowDownload === "true";
  }
  if (options.bridgeId !== undefined && !BRIDGE_ID_PATTERN.test(options.bridgeId)) throw commandError("--bridge-id 必须来自 bridges list");
  if (options.profile !== undefined && (!options.profile.trim() || options.profile.length > 80)) throw commandError("--profile 必须是 1 到 80 字的目标别名");
  if (options.browserContext !== undefined && !BROWSER_CONTEXTS.includes(options.browserContext)) {
    throw commandError("--browser-context 必须是 regular 或 incognito", { value: options.browserContext });
  }
  return { command: options.help ? "help" : command, helpFor: options.help ? command : undefined, options, positionals };
}

function helpResult(command) {
  const result = {
    name: PACKAGE_NAME,
    version: VERSION,
    protocolVersion: PROTOCOL_VERSION,
    usage: "easypost <command> [options]",
    browserContexts: BROWSER_CONTEXTS,
    bridgeSelection: { bridgeId: "--bridge-id <id> from bridges list", profile: "--profile <unique alias>; not a physical Chrome profile directory" },
    accountPolicy: "current_browser_session",
    accountNameRequired: false,
    expectedAccounts: "deprecated; accepted and ignored; never ask for account names or nicknames",
    publishGuard: { version: 1, requirePublicUrl: true, expectedTargets: "Jike circle required; Juejin circle supported" },
    personalDeclaration: {
      flag: "--personal-declaration true|false (prepare/fill/publish); overrides data.personalDeclaration",
      task: "data.personalDeclaration: optional boolean; omitted uses extension preference",
      platform: "data.extra.<platform>.personalDeclaration: optional boolean; overrides task setting",
      persistence: "task-only; never changes the extension preference",
    },
    downloadPermission: {
      flag: "--allow-download true|false (prepare/fill/publish); overrides data.allowDownload",
      task: "data.allowDownload: optional boolean; omitted uses extension preference (default true)",
      platform: "data.extra.<platform>.allowDownload: optional boolean; overrides task setting",
      platforms: ["douyin", "kuaishou"],
      contentType: "shortVideo",
      persistence: "task-only; never changes the extension preference",
    },
    commands: {
      help: "返回机器可读帮助",
      version: "返回 CLI 版本",
      doctor: "检查 Native Messaging 桥、扩展唤醒和 ID 漂移；--repair 自动修复 host 配置",
      bridges: "列出所有在线桥及目标身份（bridges list）",
      capabilities: "读取扩展支持的内容类型、平台与已保存发布组合",
      prepare: "校验输入并流式计算素材大小、MIME 和 SHA256",
      fill: "让扩展打开平台页面并填入内容；支持 --dry-run",
      publish: "执行直接发布；必须显式传 --yes；支持 --dry-run",
      status: "查询指定 requestId 的状态",
      cancel: "取消尚未进入不可逆动作的请求",
      "install-host": "为 Chrome 扩展安装当前用户级 Native Messaging host",
      "uninstall-host": "卸载当前用户级 Native Messaging host",
    },
    input: {
      sources: ["--input <json-file>", "stdin"],
      schema: {
        requestId: "optional 8-128 character UUID or safe identifier",
        browserContext: "optional regular|incognito; defaults to regular",
        comboName: "optional 1-80 character saved publish-combo selector; platforms may be omitted",
        groupName: "optional 1-80 character Chrome tab-group label",
        type: CONTENT_TYPES,
        platforms: ["platform id; optional when comboName is provided"],
        data: "optional JSON object",
        assets: [
          {
            path: "absolute regular-file path",
            role: "optional; defaults to media",
            type: "optional MIME override",
            sourceUrl: "optional http(s) source URL",
          },
        ],
      },
    },
    exitCodes: {
      0: "success",
      2: "invalid input or unsupported platform",
      10: "explicit publish confirmation missing",
      20: "authentication required",
      21: "quota exceeded",
      22: "authorization service unavailable",
      30: "local bridge or extension unavailable",
      40: "execution failed, partial, or needs manual checking",
    },
  };
  if (command) result.command = command;
  return result;
}

async function readUtf8File(filePath) {
  let buffer;
  try {
    if (filePath === "-") {
      const chunks = [];
      for await (const chunk of process.stdin) {
        chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
      }
      buffer = Buffer.concat(chunks);
    } else {
      buffer = await fs.promises.readFile(filePath);
    }
  } catch (error) {
    throw new CliError("INPUT_READ_FAILED", "无法读取 JSON 输入", {
      exitCode: EXIT_CODES.INPUT,
      details: { source: filePath, reason: error.code },
      cause: error,
    });
  }
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(buffer);
  } catch (error) {
    throw new CliError("INVALID_INPUT_ENCODING", "JSON 输入必须使用 UTF-8", {
      exitCode: EXIT_CODES.INPUT,
      cause: error,
    });
  }
}

async function loadInput(options) {
  const source = options.input || "stdin";
  const text = await readUtf8File(options.input || "-");
  const input = normalizeInput(parseInputJson(text, source), { browserContext: options.browserContext });
  if (options.bridgeId && input.bridgeId && options.bridgeId !== input.bridgeId) throw commandError("输入 bridgeId 与 --bridge-id 不一致");
  if (options.bridgeId) input.bridgeId = options.bridgeId;
  if (options.personalDeclaration !== undefined) input.data = { ...input.data, personalDeclaration: options.personalDeclaration };
  if (options.allowDownload !== undefined) input.data = { ...input.data, allowDownload: options.allowDownload };
  return input;
}

export async function prepareInput(input, mode) {
  if (input.type === "article" && (input.platforms.includes("x") || input.comboName)) {
    input = { ...input, data: { ...input.data, xArticleImageSourcePaths: Object.fromEntries(
      input.assets.filter(asset => (asset.role || "media") === "media")
        .map(asset => [path.basename(asset.path), asset.path]),
    ) } };
  }
  input = prepareXArticleImages(input);
  if (mode === "publish" && !input.data?.publishGuard && !input.comboName) {
    throw new CliError("PUBLISH_GUARD_REQUIRED", "publish 必须提供 data.publishGuard", {
      exitCode: EXIT_CODES.INPUT,
      hint: "确认圈子等发布目标，并要求公开链接读回",
    });
  }
  const assets = await inspectAssets(input.assets);
  const payloadDigest = createPayloadDigest({
    browserContext: input.browserContext,
    ...(input.bridgeId ? { bridgeId: input.bridgeId } : {}),
    comboName: input.comboName,
    groupName: input.groupName,
    type: input.type,
    mode,
    platforms: input.platforms,
    data: input.data,
    assets,
  });
  const prepared = {
    schema: PREPARED_SCHEMA,
    status: "prepared_local",
    requestId: input.requestId,
    browserContext: input.browserContext,
    ...(input.bridgeId ? { bridgeId: input.bridgeId } : {}),
    ...(input.comboName ? { comboName: input.comboName } : {}),
    ...(input.groupName ? { groupName: input.groupName } : {}),
    type: input.type,
    mode,
    platforms: input.platforms,
    data: input.data,
    assets,
    payloadDigest,
  };
  return prepared;
}

function requestIdFrom(parsed) {
  const candidates = [parsed.options.requestId, ...parsed.positionals].filter(Boolean);
  if (candidates.length !== 1) {
    throw commandError(`${parsed.command} 需要一个 requestId`, { received: candidates.length });
  }
  return validateRequestId(candidates[0], "requestId");
}

export function throwForExecuteStatus(result) {
  const status = result?.status;
  const businessError = result?.error || result?.result?.error;
  if (businessError?.code) {
    const mappedExitCode = exitCodeForRemoteCode(businessError.code);
    if (mappedExitCode !== EXIT_CODES.EXECUTION) throw remoteErrorToCliError(businessError);
  }
  if (["partial", "needs_check", "failed", "cancelled_partial"].includes(status)) {
    throw new CliError(`EXECUTION_${status.toUpperCase()}`, `任务状态：${status}`, {
      exitCode: EXIT_CODES.EXECUTION,
      hint: "运行 easypost status <requestId> 查看逐平台结果",
      details: result,
    });
  }
  if (status === "waiting_for_login") {
    throw new CliError("LOGIN_REQUIRED", "任务仍在等待平台登录", {
      exitCode: EXIT_CODES.AUTH,
      hint: "在 Chrome 中完成登录后重试",
      details: result,
    });
  }
}

async function executePrepared(prepared, { confirmed, selection = {} }) {
  const route = await waitForBridgeSelection({ ...selection, bridgeId: prepared.bridgeId || selection.bridgeId,
    browserContext: prepared.browserContext });
  if (route.bridgeTarget) {
    prepared.bridgeId = route.bridgeTarget.bridgeId;
    prepared.payloadDigest = createPayloadDigest(prepared);
    await rememberRequestRoute(prepared.requestId, route.bridgeTarget);
  }
  // CLI 不能反向连接 MV3。先等待周期 alarm 唤醒 service worker 并恢复 Native
  // 端口，再启动素材服务；这里仅做 doctor 探测，绝不重复发送 execute。
  await waitForBridge("doctor", {}, {
    ...route,
    browserContext: prepared.browserContext,
    waitMs: DEFAULT_DOCTOR_WAIT_MS + 5_000,
    attemptTimeoutMs: 1_000,
    retryMs: 250,
  });
  const assetServer = await startAssetServer(prepared.assets);
  let cancelStarted = false;
  const requestCancellation = () => {
    if (cancelStarted) return;
    cancelStarted = true;
    // Signal handling is cooperative: keep the original execute socket and
    // loopback asset server alive until the extension reports a terminal state.
    void requestBridge("cancel", { requestId: prepared.requestId }, {
      ...route,
      browserContext: prepared.browserContext,
      timeoutMs: 5_000,
    })
      .catch(() => undefined);
  };
  const onSigint = () => requestCancellation();
  const onSigterm = () => requestCancellation();
  process.on("SIGINT", onSigint);
  process.on("SIGTERM", onSigterm);
  try {
    const task = {
      requestId: prepared.requestId,
      browserContext: prepared.browserContext,
      ...(prepared.bridgeId ? { bridgeId: prepared.bridgeId } : {}),
      ...(prepared.comboName ? { comboName: prepared.comboName } : {}),
      ...(prepared.groupName ? { groupName: prepared.groupName } : {}),
      type: prepared.type,
      mode: prepared.mode,
      platforms: prepared.platforms,
      data: prepared.data,
      assets: assetServer.transportAssets,
      confirmed,
      payloadDigest: prepared.payloadDigest,
    };
    // The extension intentionally holds the first execute response until a
    // terminal result. A default deadline here would tear down blobUrl while
    // Chrome is still running or waiting for login.
    const result = await requestBridge("execute", { task }, {
      ...route,
      browserContext: prepared.browserContext,
      timeoutMs: null,
    });
    throwForExecuteStatus(result);
    return result;
  } finally {
    process.off("SIGINT", onSigint);
    process.off("SIGTERM", onSigterm);
    await assetServer.close();
  }
}

function assertNoPositionals(parsed) {
  if (parsed.positionals.length) {
    throw commandError(`${parsed.command} 不接受位置参数`, { positionals: parsed.positionals });
  }
}

export async function runParsedCommand(parsed) {
  const timeoutMs = parsed.options.timeout || DEFAULT_TIMEOUT_MS;
  switch (parsed.command) {
    case "help":
      return helpResult(parsed.helpFor);
    case "version":
      assertNoPositionals(parsed);
      return { name: PACKAGE_NAME, version: VERSION, bridgeRoutingVersion: 2, node: process.version };
    case "bridges": {
      if (parsed.positionals.length && (parsed.positionals.length !== 1 || parsed.positionals[0] !== "list")) throw commandError("请使用 bridges list");
      return { bridges: await discoverBridges({ browserContext: parsed.options.browserContext }) };
    }
    case "doctor": {
      assertNoPositionals(parsed);
      const route = await (parsed.options.wait
        ? waitForBridgeSelection(parsed.options, { waitMs: typeof parsed.options.wait === "number" ? parsed.options.wait : (parsed.options.timeout || DEFAULT_DOCTOR_WAIT_MS) })
        : resolveBridgeSelection(parsed.options)).catch((error) => {
        if (error.code === "BRIDGE_UNAVAILABLE" && !parsed.options.wait && !parsed.options.bridgeId && !parsed.options.profile) return {};
        throw error;
      });
      let installation = await inspectNativeHostInstallation().catch((error) => ({
        installed: false,
        error: error.message,
      }));
      const discoveredExtensionIds = await discoverExtensionIds().catch(() => []);
      let diagnosis = diagnoseNativeHost({ installation, extensionIds: discoveredExtensionIds });
      let repaired = false;
      if (parsed.options.repair && diagnosis.recoverable && discoveredExtensionIds.length) {
        await installNativeHost({ extensionIds: discoveredExtensionIds });
        installation = await inspectNativeHostInstallation();
        diagnosis = diagnoseNativeHost({ installation, extensionIds: discoveredExtensionIds });
        repaired = true;
      }
      const bridgeRequest = parsed.options.wait
        ? waitForBridge("doctor", {}, {
            ...route,
            browserContext: parsed.options.browserContext,
            waitMs: typeof parsed.options.wait === "number"
              ? parsed.options.wait
              : (parsed.options.timeout || DEFAULT_DOCTOR_WAIT_MS),
          })
        : requestBridge("doctor", {}, {
            ...route,
            browserContext: parsed.options.browserContext,
            timeoutMs: Math.min(timeoutMs, 5_000),
          });
      const extension = await bridgeRequest.catch(() => null);
      const expectedOrigin = extension?.runtime?.id
        ? `chrome-extension://${extension.runtime.id}/`
        : null;
      const manifest = installation.manifest;
      const checks = {
        node: {
          ok: Number(process.versions.node.split(".")[0]) >= 20,
          current: process.version,
          required: ">=20",
        },
        bridge: {
          ok: extension?.protocolVersion === PROTOCOL_VERSION &&
            extension?.runtime?.browserContext === (parsed.options.browserContext || "regular"),
          protocolVersion: extension?.protocolVersion,
          browserContext: extension?.runtime?.browserContext,
        },
        manifest: {
          ok: Boolean(
            installation.installed &&
            (manifest?.name === NATIVE_HOST_NAME || manifest?.name === "com.yijianfa.cli") &&
            manifest?.type === "stdio" &&
            manifest?.path === installation.wrapperPath &&
            typeof manifest?.path === "string" &&
            path.isAbsolute(manifest.path)
          ),
          state: installation.installed ? "installed" : "missing",
        },
        allowedOrigin: {
          ok: Boolean(
            expectedOrigin &&
            Array.isArray(manifest?.allowed_origins) &&
            manifest.allowed_origins.includes(expectedOrigin)
          ),
          state: diagnosis.state,
        },
        wrapper: {
          ok: Boolean(
            installation.wrapper?.exists &&
            installation.wrapper?.executable &&
            typeof installation.wrapperPath === "string" &&
            path.isAbsolute(installation.wrapperPath)
          ),
          state: installation.wrapper?.exists ? "installed" : "missing",
        },
      };
      return {
        healthy: Object.values(checks).every((check) => check.ok),
        state: extension
          ? (diagnosis.state === "configured" ? "healthy" : diagnosis.state)
          : (diagnosis.state === "configured" ? "extension_asleep" : diagnosis.state),
        repaired,
        selectedBridge: route.bridgeTarget || null,
        checks,
        node: { ok: Number(process.versions.node.split(".")[0]) >= 20, version: process.version, required: ">=20" },
        nativeHost: {
          installed: installation.installed === true,
          allowedExtensionCount: Array.isArray(manifest?.allowed_origins) ? manifest.allowed_origins.length : 0,
        },
        extension: extension || { bridge: { state: "disconnected" } },
      };
    }
    case "capabilities":
      assertNoPositionals(parsed);
      return await requestBridge("capabilities", {}, {
        ...await resolveBridgeSelection(parsed.options),
        browserContext: parsed.options.browserContext,
        timeoutMs,
      });
    case "prepare": {
      assertNoPositionals(parsed);
      const prepared = await prepareInput(await loadInput(parsed.options), "prepare");
      return { ...prepared, bridgeSelection: { bridgeId: prepared.bridgeId || null, profile: parsed.options.profile || null, state: "not_connected" } };
    }
    case "fill":
    case "publish": {
      assertNoPositionals(parsed);
      if (parsed.command === "publish" && !parsed.options.yes) {
        throw new CliError("CONFIRMATION_REQUIRED", "publish 必须显式传 --yes", {
          exitCode: EXIT_CODES.CONFIRMATION_REQUIRED,
          hint: "确认内容与平台后重新运行，并添加 --yes",
        });
      }
      const prepared = await prepareInput(await loadInput(parsed.options), parsed.command);
      if (parsed.options.dryRun) return { ...prepared, bridgeSelection: { bridgeId: prepared.bridgeId || null, profile: parsed.options.profile || null, state: "not_connected" } };
      return await executePrepared(prepared, {
        confirmed: parsed.command === "publish",
        selection: parsed.options,
      });
    }
    case "status":
    case "cancel": {
      const requestId = requestIdFrom(parsed);
      const saved = await readRequestRoute(requestId);
      if (saved && ((parsed.options.bridgeId && saved.bridgeId !== parsed.options.bridgeId) ||
          (parsed.options.browserContext && saved.browserContext !== parsed.options.browserContext))) throw commandError("该 requestId 已绑定其他目标或上下文");
      const route = await resolveBridgeSelection({ ...parsed.options,
        bridgeId: saved?.bridgeId || parsed.options.bridgeId,
        browserContext: saved?.browserContext || parsed.options.browserContext });
      const result = await requestBridge(parsed.command, { requestId }, { ...route, timeoutMs });
      if (parsed.command === "cancel") throwForExecuteStatus(result);
      return result;
    }
    case "install-host":
      assertNoPositionals(parsed);
      return await installNativeHost({ extensionId: parsed.options.extensionId });
    case "uninstall-host":
      assertNoPositionals(parsed);
      return await uninstallNativeHost();
    default:
      throw commandError(`未知命令：${parsed.command}`);
  }
}

export function writeJson(stream, value) {
  stream.write(`${JSON.stringify(value)}\n`);
}

export async function runCli(
  argv,
  { stdout = process.stdout, stderr = process.stderr, setExitCode = (code) => (process.exitCode = code) } = {},
) {
  let command = null;
  try {
    const major = Number(process.versions.node.split(".")[0]);
    if (!Number.isInteger(major) || major < 20) {
      throw new CliError("UNSUPPORTED_NODE", "easypost 需要 Node.js 20 或更高版本", {
        exitCode: EXIT_CODES.INPUT,
        details: { current: process.version, required: ">=20" },
      });
    }
    const parsed = parseArgv(argv);
    command = parsed.command;
    const result = await runParsedCommand(parsed);
    writeJson(stdout, { ok: true, command, result });
    setExitCode(EXIT_CODES.OK);
    return EXIT_CODES.OK;
  } catch (error) {
    const cliError = asCliError(error);
    writeJson(stderr, { ok: false, command, error: cliError.toJSON() });
    setExitCode(cliError.exitCode);
    return cliError.exitCode;
  }
}
