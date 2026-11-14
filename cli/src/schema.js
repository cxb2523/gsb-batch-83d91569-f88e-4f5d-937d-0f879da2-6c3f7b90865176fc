import path from "node:path";
import { randomUUID } from "node:crypto";
import {
  ASSET_ROLES,
  BROWSER_CONTEXTS,
  CONTENT_TYPES,
  DEFAULT_BROWSER_CONTEXT,
  EXIT_CODES,
} from "./constants.js";
import { CliError } from "./errors.js";

const REQUEST_ID_RE = /^[A-Za-z0-9._:-]{8,128}$/;
const MIME_RE = /^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+~-]*(?:;\s*[a-z0-9!#$&^_.+-]+=[^\r\n;]+)*$/i;
const SHIPINHAO_SHORT_VIDEO_TITLE_RE = /^[\p{L}\p{N} ]+$/u;
const SHIPINHAO_SHORT_VIDEO_TITLE_MAX = 16;

function inputError(message, details) {
  return new CliError("INVALID_INPUT", message, {
    exitCode: EXIT_CODES.INPUT,
    hint: "运行 easypost help 查看输入格式",
    details,
  });
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertOnlyKeys(value, allowed, location) {
  const extras = Object.keys(value).filter((key) => !allowed.has(key));
  if (extras.length) throw inputError(`${location} 包含不支持的字段`, { fields: extras });
}

function validateJsonValue(value, location = "data", seen = new Set()) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number" && Number.isFinite(value)) return;
  if (typeof value !== "object") throw inputError(`${location} 不是有效 JSON 值`);
  if (seen.has(value)) throw inputError(`${location} 包含循环引用`);
  seen.add(value);
  if (Array.isArray(value)) {
    value.forEach((item, index) => validateJsonValue(item, `${location}[${index}]`, seen));
  } else {
    for (const [key, child] of Object.entries(value)) {
      validateJsonValue(child, `${location}.${key}`, seen);
    }
  }
  seen.delete(value);
}

function validatePublishGuard(data, platforms, { allowUnselectedPlatforms = false } = {}) {
  const guard = data.publishGuard;
  if (guard === undefined) return;
  if (!isPlainObject(guard)) throw inputError("data.publishGuard 必须是对象");
  assertOnlyKeys(
    guard,
    new Set(["version", "expectedAccounts", "expectedTargets", "requirePublicUrl"]),
    "data.publishGuard",
  );
  if (guard.version !== 1) throw inputError("data.publishGuard.version 必须是 1");
  if (guard.requirePublicUrl !== true) {
    throw inputError("data.publishGuard.requirePublicUrl 必须为 true");
  }
  const selected = new Set(platforms);
  // expectedAccounts is a deprecated compatibility field; never inspect identities.
  for (const field of ["expectedTargets"]) {
    const values = guard[field] === undefined ? {} : guard[field];
    if (!isPlainObject(values)) throw inputError(`data.publishGuard.${field} 必须是对象`);
    for (const [platform, expected] of Object.entries(values)) {
      if ((!allowUnselectedPlatforms && !selected.has(platform)) ||
          typeof expected !== "string" || !expected.trim() || expected.length > 200) {
        throw inputError(`data.publishGuard.${field}.${platform} 无效`);
      }
    }
  }
  const unsupportedTargets = Object.keys(guard.expectedTargets || {}).filter(
    (platform) => !["jike", "juejin"].includes(platform),
  );
  if (unsupportedTargets.length) {
    throw inputError(`expectedTargets 暂不支持平台：${unsupportedTargets.join(", ")}`);
  }
  if (selected.has("jike") && !guard.expectedTargets?.jike?.trim()) {
    throw inputError("即刻发布必须填写 data.publishGuard.expectedTargets.jike");
  }
}

function validatePlatformDataRules(type, platforms, data) {
  if (type !== "shortVideo" || !platforms.includes("shipinhao") || data.title === undefined) return;
  if (typeof data.title !== "string") {
    throw inputError("视频号短视频 data.title 必须是字符串");
  }
  if (!data.title) return;
  if (data.title.length > SHIPINHAO_SHORT_VIDEO_TITLE_MAX) {
    throw inputError(`视频号短标题最多 ${SHIPINHAO_SHORT_VIDEO_TITLE_MAX} 字`, {
      platform: "shipinhao",
      field: "title",
      count: data.title.length,
      max: SHIPINHAO_SHORT_VIDEO_TITLE_MAX,
    });
  }
  if (!SHIPINHAO_SHORT_VIDEO_TITLE_RE.test(data.title)) {
    throw inputError("视频号短标题只允许文字、字母、数字和普通空格，不支持标点、emoji 或特殊符号", {
      platform: "shipinhao",
      field: "title",
      allowedCharacters: "unicode_letters_numbers_ascii_spaces",
    });
  }
}

export function validateRequestId(value, location = "requestId") {
  if (typeof value !== "string" || !REQUEST_ID_RE.test(value)) {
    throw inputError(`${location} 必须是 8 到 128 位 UUID 或安全标识符`, { value });
  }
  return value;
}

export function normalizeInput(value, { uuid = randomUUID, browserContext: requestedContext } = {}) {
  if (!isPlainObject(value)) throw inputError("输入根节点必须是 JSON 对象");
  assertOnlyKeys(
    value,
    new Set(["requestId", "bridgeId", "browserContext", "comboName", "groupName", "type", "platforms", "data", "assets"]),
    "输入",
  );

  if (value.browserContext !== undefined && !BROWSER_CONTEXTS.includes(value.browserContext)) {
    throw inputError("browserContext 必须是 regular 或 incognito");
  }
  if (requestedContext !== undefined && !BROWSER_CONTEXTS.includes(requestedContext)) {
    throw inputError("--browser-context 必须是 regular 或 incognito");
  }
  if (value.browserContext !== undefined && requestedContext !== undefined && value.browserContext !== requestedContext) {
    throw inputError("输入 browserContext 与 --browser-context 不一致");
  }
  if (value.bridgeId !== undefined && (typeof value.bridgeId !== "string" || !/^bridge-[a-f0-9]{32}$/.test(value.bridgeId))) throw inputError("bridgeId 必须来自在线桥列表");
  const browserContext = requestedContext || value.browserContext || DEFAULT_BROWSER_CONTEXT;
  let comboName;
  if (value.comboName !== undefined) {
    if (typeof value.comboName !== "string" || !value.comboName.trim() || value.comboName.trim().length > 80) {
      throw inputError("comboName 必须是 1 到 80 字的非空字符串");
    }
    comboName = value.comboName.trim();
  }
  let groupName;
  if (value.groupName !== undefined) {
    if (typeof value.groupName !== "string" || !value.groupName.trim() || value.groupName.trim().length > 80) {
      throw inputError("groupName 必须是 1 到 80 字的非空字符串");
    }
    groupName = value.groupName.trim();
  }

  if (!CONTENT_TYPES.includes(value.type)) {
    throw inputError("type 不受支持", { allowed: CONTENT_TYPES, received: value.type });
  }
  const rawPlatforms = value.platforms === undefined ? [] : value.platforms;
  if (!Array.isArray(rawPlatforms)) throw inputError("platforms 必须是数组");
  if (!rawPlatforms.length && !comboName) {
    throw inputError("platforms 与 comboName 至少提供一项");
  }
  if (rawPlatforms.length > 100) throw inputError("platforms 最多包含 100 项");
  const platforms = rawPlatforms.map((platform, index) => {
    if (typeof platform !== "string" || !platform.trim()) {
      throw inputError(`platforms[${index}] 必须是非空字符串`);
    }
    return platform.trim();
  });
  if (new Set(platforms).size !== platforms.length) {
    throw inputError("platforms 不能包含重复项");
  }

  const data = value.data === undefined ? {} : value.data;
  if (!isPlainObject(data)) throw inputError("data 必须是 JSON 对象");
  validateJsonValue(data);
  if (data.personalDeclaration !== undefined && typeof data.personalDeclaration !== "boolean") {
    throw inputError("data.personalDeclaration 必须是布尔值");
  }
  if (data.allowDownload !== undefined && typeof data.allowDownload !== "boolean") {
    throw inputError("data.allowDownload 必须是布尔值");
  }
  for (const [platform, settings] of Object.entries(data.extra || {})) {
    if (settings?.allowDownload !== undefined && typeof settings.allowDownload !== "boolean") {
      throw inputError(`data.extra.${platform}.allowDownload 必须是布尔值`);
    }
    if (settings?.personalDeclaration !== undefined && typeof settings.personalDeclaration !== "boolean") {
      throw inputError(`data.extra.${platform}.personalDeclaration 必须是布尔值`);
    }
  }
  validatePlatformDataRules(value.type, platforms, data);
  validatePublishGuard(data, platforms, {
    allowUnselectedPlatforms: Boolean(comboName && !platforms.length),
  });

  const rawAssets = value.assets === undefined ? [] : value.assets;
  if (!Array.isArray(rawAssets)) throw inputError("assets 必须是数组");
  if (rawAssets.length > 100) throw inputError("assets 最多包含 100 项");
  const assets = rawAssets.map((asset, index) => {
    const location = `assets[${index}]`;
    if (!isPlainObject(asset)) throw inputError(`${location} 必须是对象`);
    assertOnlyKeys(asset, new Set(["path", "role", "type", "sourceUrl"]), location);
    if (typeof asset.path !== "string" || !path.isAbsolute(asset.path)) {
      throw inputError(`${location}.path 必须是绝对路径`);
    }
    let role = "media";
    if (asset.role !== undefined) {
      if (typeof asset.role !== "string" || !asset.role.trim()) {
        throw inputError(`${location}.role 必须是非空字符串`);
      }
      role = asset.role.trim();
    }
    if (!ASSET_ROLES.includes(role)) {
      throw inputError(`${location}.role 不受支持`, { allowed: ASSET_ROLES, received: role });
    }
    let type;
    if (asset.type !== undefined) {
      if (typeof asset.type !== "string" || !MIME_RE.test(asset.type)) {
        throw inputError(`${location}.type 必须是有效 MIME 类型`);
      }
      type = asset.type.trim().toLowerCase();
    }
    let sourceUrl;
    if (asset.sourceUrl !== undefined) {
      try {
        const url = new URL(asset.sourceUrl);
        if (!new Set(["http:", "https:"]).has(url.protocol)) throw new Error("protocol");
        if (url.username || url.password || url.href.length > 4096) throw new Error("credentials-or-length");
        sourceUrl = url.href;
      } catch {
        throw inputError(`${location}.sourceUrl 必须是 http(s) URL`);
      }
    }
    return { path: asset.path, role, ...(type ? { type } : {}), ...(sourceUrl ? { sourceUrl } : {}) };
  });

  const requestId = value.requestId === undefined ? uuid() : validateRequestId(value.requestId);
  return {
    requestId,
    browserContext,
    ...(value.bridgeId ? { bridgeId: value.bridgeId } : {}),
    ...(comboName ? { comboName } : {}),
    ...(groupName ? { groupName } : {}),
    type: value.type,
    platforms,
    data,
    assets,
  };
}

export function parseInputJson(text, source = "stdin") {
  if (typeof text !== "string" || !text.trim()) throw inputError(`${source} 没有 JSON 输入`);
  try {
    return JSON.parse(text);
  } catch (error) {
    throw inputError(`${source} 不是有效 JSON`, { reason: error.message });
  }
}
