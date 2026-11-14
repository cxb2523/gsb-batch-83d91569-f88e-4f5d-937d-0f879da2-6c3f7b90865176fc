import fs from "node:fs";
import path from "node:path";
import { createHash, randomBytes } from "node:crypto";
import { Readable, Transform } from "node:stream";
import { pipeline } from "node:stream/promises";

export const FETCH_DEFAULTS = Object.freeze({
  timeoutMs: 30_000,
  maxAttempts: 3,
  backoffMs: 250,
});

class FetchError extends Error {
  constructor(message, { retryable = false, status, code } = {}) {
    super(message);
    this.name = "FetchError";
    this.retryable = retryable;
    this.status = status;
    this.code = code;
  }
}

function invalidUrlError(message) {
  return new FetchError(message, { retryable: false, code: "INVALID_SOURCE_URL" });
}

export function parseSourceUrl(sourceUrl) {
  if (typeof sourceUrl !== "string" || !sourceUrl) {
    throw invalidUrlError("sourceUrl 必须是非空字符串");
  }
  let url;
  try {
    url = new URL(sourceUrl);
  } catch {
    throw invalidUrlError("sourceUrl 不是合法 URL");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw invalidUrlError("sourceUrl 仅支持 http/https");
  }
  if (url.username || url.password) {
    throw invalidUrlError("sourceUrl 不得包含账号密码");
  }
  if (url.href.length > 4096) throw invalidUrlError("sourceUrl 过长");
  return url;
}

// Remote integrity metadata: prefer an explicit SHA-256 the server volunteers
// (Digest, sha256 ETag as emitted by the local asset server, or X-Content-Sha256).
export function remoteSha256FromHeaders(headers) {
  const digest = headers.get("digest");
  if (digest) {
    const match = /sha-256=([A-Za-z0-9+/=]+)/i.exec(digest);
    if (match) {
      try {
        return Buffer.from(match[1], "base64").toString("hex");
      } catch {
        /* fall through to other headers */
      }
    }
  }
  const etag = headers.get("etag");
  if (etag) {
    const match = /^"?sha256-([0-9a-f]{64})"?$/i.exec(etag.trim());
    if (match) return match[1].toLowerCase();
  }
  const explicit = headers.get("x-content-sha256") || headers.get("x-sha256");
  if (explicit && /^[0-9a-f]{64}$/i.test(explicit.trim())) return explicit.trim().toLowerCase();
  return null;
}

function remoteSizeFromHeaders(headers) {
  const value = headers.get("content-length");
  if (value === null) return null;
  const size = Number(value);
  return Number.isSafeInteger(size) && size >= 0 ? size : null;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function timeoutError(timeoutMs) {
  return new FetchError(`请求超时（${timeoutMs}ms）`, {
    retryable: true,
    code: "FETCH_TIMEOUT",
  });
}

function mapFetchError(error, controller) {
  if (error instanceof FetchError) return error;
  if (error?.name === "AbortError" && controller.signal.reason instanceof FetchError) {
    return controller.signal.reason;
  }
  // Undici surfaces network failures as TypeError with a cause; all of them
  // (DNS, refused, reset, TLS) are transient enough to justify a retry.
  return new FetchError(`网络错误：${error?.cause?.code || error?.message || "unknown"}`, {
    retryable: true,
    code: "NETWORK_ERROR",
  });
}

// One HTTP request bounded by a single timeout that covers both the response
// headers and (via `consume`) streaming the body. Aborting the controller
// also tears down an in-flight body stream.
async function requestWithTimeout(url, method, timeoutMs, consume = (response) => response) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(timeoutError(timeoutMs)), timeoutMs);
  try {
    const response = await fetch(url, { method, redirect: "follow", signal: controller.signal });
    return await consume(response);
  } catch (error) {
    throw mapFetchError(error, controller);
  } finally {
    clearTimeout(timer);
  }
}

function assertOkResponse(response, context) {
  if (response.ok) return;
  const status = response.status;
  const retryable = status >= 500 && status <= 599;
  throw new FetchError(`${context} 返回 HTTP ${status}`, {
    retryable,
    status,
    code: retryable ? "HTTP_5XX" : "HTTP_4XX",
  });
}

async function withRetries(operation, { maxAttempts, backoffMs }) {
  let attempt = 0;
  for (;;) {
    attempt += 1;
    try {
      return { value: await operation(), attempts: attempt };
    } catch (error) {
      const retryable = error instanceof FetchError ? error.retryable : false;
      if (!retryable || attempt >= maxAttempts) {
        error.attempts = attempt;
        throw error;
      }
      await sleep(backoffMs * 2 ** (attempt - 1));
    }
  }
}

async function headRemote(url, options) {
  try {
    return await requestWithTimeout(url, "HEAD", options.timeoutMs, (response) => {
      // Any HEAD refusal (4xx/405/5xx) falls back to GET rather than failing
      // the asset: some servers only implement GET correctly.
      if (!response.ok) return null;
      return {
        size: remoteSizeFromHeaders(response.headers),
        sha256: remoteSha256FromHeaders(response.headers),
      };
    });
  } catch {
    return null; // HEAD 不可用时退回下载后比对
  }
}

async function hashLocalFile(filePath) {
  const hash = createHash("sha256");
  let size = 0;
  const stream = fs.createReadStream(filePath);
  for await (const chunk of stream) {
    size += chunk.length;
    hash.update(chunk);
  }
  return { size, sha256: hash.digest("hex") };
}

async function statLocal(filePath) {
  try {
    const stat = await fs.promises.stat(filePath);
    if (!stat.isFile()) return null;
    return { size: stat.size };
  } catch {
    return null;
  }
}

function tempPathFor(targetPath) {
  return `${targetPath}.easypost-${randomBytes(8).toString("hex")}.tmp`;
}

// Local filesystem failures on the temp file are not transient: retrying a
// missing parent directory or a permission denial cannot succeed.
const LOCAL_FS_ERROR_CODES = new Set([
  "ENOENT", "ENOTDIR", "EACCES", "EPERM", "EROFS", "EISDIR", "ENOSPC",
]);

async function downloadToTemp(url, tempPath, options) {
  const hash = createHash("sha256");
  let size = 0;
  let expectedSize = null;
  let remoteSha256 = null;
  await requestWithTimeout(url, "GET", options.timeoutMs, async (response) => {
    assertOkResponse(response, "下载");
    expectedSize = remoteSizeFromHeaders(response.headers);
    remoteSha256 = remoteSha256FromHeaders(response.headers);
    const counter = new Transform({
      transform(chunk, _encoding, callback) {
        size += chunk.length;
        hash.update(chunk);
        callback(null, chunk);
      },
    });
    try {
      await pipeline(
        Readable.fromWeb(response.body),
        counter,
        fs.createWriteStream(tempPath, { flags: "wx" }),
      );
    } catch (error) {
      await fs.promises.unlink(tempPath).catch(() => undefined);
      if (error?.code === "EEXIST") {
        throw new FetchError("临时文件已存在", { retryable: false, code: "TEMP_EXISTS" });
      }
      if (LOCAL_FS_ERROR_CODES.has(error?.code)) {
        throw new FetchError(`本地临时文件不可写：${error.code}`, {
          retryable: false,
          code: "LOCAL_FS_ERROR",
        });
      }
      throw new FetchError(`传输中断：${error?.message || "unknown"}`, {
        retryable: true,
        code: "TRANSFER_INTERRUPTED",
      });
    }
  });
  if (expectedSize !== null && size !== expectedSize) {
    await fs.promises.unlink(tempPath).catch(() => undefined);
    throw new FetchError(`下载大小不符：期望 ${expectedSize}，实收 ${size}`, {
      retryable: true,
      code: "SIZE_MISMATCH",
    });
  }
  return { size, sha256: hash.digest("hex"), remoteSha256 };
}

function resultRecord(asset, index, fields) {
  return {
    index,
    path: asset.path,
    sourceUrl: asset.sourceUrl,
    ...fields,
  };
}

async function fetchOne(asset, index, options) {
  let url;
  try {
    url = parseSourceUrl(asset.sourceUrl);
  } catch (error) {
    return resultRecord(asset, index, {
      status: "failed",
      reason: error.message,
      code: error.code,
      attempts: 0,
    });
  }

  const local = await statLocal(asset.path);
  let head = null;
  let localHash = null;
  if (local) {
    head = await headRemote(url, options);
    if (head && head.sha256) {
      localHash = await hashLocalFile(asset.path).catch(() => null);
      if (localHash &&
          (head.size === null || head.size === localHash.size) &&
          head.sha256 === localHash.sha256) {
        return resultRecord(asset, index, {
          status: "skipped",
          reason: "already_ready",
          attempts: 0,
          size: localHash.size,
          sha256: localHash.sha256,
        });
      }
    }
  }

  const tempPath = tempPathFor(asset.path);
  let downloaded;
  let attempts;
  try {
    ({ value: downloaded, attempts } = await withRetries(
      () => downloadToTemp(url, tempPath, options),
      options,
    ));
  } catch (error) {
    await fs.promises.unlink(tempPath).catch(() => undefined);
    return resultRecord(asset, index, {
      status: "failed",
      reason: error.message,
      code: error.code || "FETCH_FAILED",
      ...(error.status !== undefined ? { httpStatus: error.status } : {}),
      attempts: error.attempts || 1,
    });
  }

  // Integrity: when the server volunteered a hash, the payload must match it.
  const expectedSha256 = downloaded.remoteSha256 || head?.sha256 || null;
  if (expectedSha256 && downloaded.sha256 !== expectedSha256) {
    await fs.promises.unlink(tempPath).catch(() => undefined);
    return resultRecord(asset, index, {
      status: "failed",
      reason: "下载内容与远端摘要不一致",
      code: "HASH_MISMATCH",
      attempts,
    });
  }

  // No trustworthy remote hash: fall back to comparing the downloaded bytes
  // with the existing local file so a matching file is still reported ready.
  if (local && !expectedSha256) {
    localHash = localHash || await hashLocalFile(asset.path).catch(() => null);
    if (localHash && localHash.size === downloaded.size && localHash.sha256 === downloaded.sha256) {
      await fs.promises.unlink(tempPath).catch(() => undefined);
      return resultRecord(asset, index, {
        status: "skipped",
        reason: "already_ready",
        attempts,
        size: downloaded.size,
        sha256: downloaded.sha256,
      });
    }
  }

  try {
    // Same-directory temp file + rename keeps the swap atomic on one volume;
    // the final path never holds a partial payload.
    await fs.promises.rename(tempPath, asset.path);
  } catch (error) {
    await fs.promises.unlink(tempPath).catch(() => undefined);
    return resultRecord(asset, index, {
      status: "failed",
      reason: `原子替换失败：${error.code || error.message}`,
      code: "RENAME_FAILED",
      attempts,
    });
  }
  return resultRecord(asset, index, {
    status: "downloaded",
    reason: "fetched",
    attempts,
    size: downloaded.size,
    sha256: downloaded.sha256,
  });
}

// Fetches every asset that carries a sourceUrl. Each asset gets its own
// outcome; one failure never aborts the others. Assets sharing a path share a
// single in-flight download: the first is the writer, the rest wait and reuse.
export async function fetchRemoteAssets(assets, options = {}) {
  const settings = { ...FETCH_DEFAULTS, ...options };
  const remoteAssets = assets
    .map((asset, index) => ({ asset, index }))
    .filter(({ asset }) => asset && asset.sourceUrl !== undefined);

  const inFlightByPath = new Map();
  const results = await Promise.all(remoteAssets.map(({ asset, index }) => {
    const key = path.resolve(asset.path);
    const existing = inFlightByPath.get(key);
    if (existing) {
      return existing.then((record) => ({
        ...record,
        index,
        path: asset.path,
        sourceUrl: asset.sourceUrl,
        reused: true,
      }));
    }
    const pending = fetchOne(asset, index, settings);
    inFlightByPath.set(key, pending);
    return pending;
  }));

  return {
    total: results.length,
    downloaded: results.filter((r) => r.status === "downloaded").length,
    skipped: results.filter((r) => r.status === "skipped").length,
    failed: results.filter((r) => r.status === "failed").length,
    results,
  };
}
