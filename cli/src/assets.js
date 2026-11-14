import fs from "node:fs";
import path from "node:path";
import { createHash } from "node:crypto";
import { EXIT_CODES } from "./constants.js";
import { CliError } from "./errors.js";
import { resolveMime } from "./mime.js";

function assetError(message, details, cause) {
  return new CliError("INVALID_ASSET", message, {
    exitCode: EXIT_CODES.INPUT,
    hint: "确认素材存在、是普通文件，并使用绝对路径",
    details,
    cause,
  });
}

export async function inspectAsset(asset) {
  let initialStat;
  try {
    initialStat = await fs.promises.stat(asset.path);
  } catch (error) {
    throw assetError("无法读取素材", { path: asset.path, reason: error.code }, error);
  }
  if (!initialStat.isFile()) throw assetError("素材路径不是普通文件", { path: asset.path });

  const hash = createHash("sha256");
  let size = 0;
  let firstBytes = Buffer.alloc(0);
  try {
    const stream = fs.createReadStream(asset.path);
    for await (const chunk of stream) {
      size += chunk.length;
      hash.update(chunk);
      if (firstBytes.length < 4100) {
        firstBytes = Buffer.concat([firstBytes, chunk.subarray(0, 4100 - firstBytes.length)]);
      }
    }
  } catch (error) {
    throw assetError("读取素材内容失败", { path: asset.path, reason: error.code }, error);
  }

  if (size !== initialStat.size) {
    throw assetError("素材在读取期间发生变化", {
      path: asset.path,
      expectedSize: initialStat.size,
      actualSize: size,
    });
  }

  const normalized = {
    path: asset.path,
    role: asset.role,
    name: path.basename(asset.path),
    type: resolveMime(asset.path, firstBytes, asset.type),
    size,
    sha256: hash.digest("hex"),
  };
  if (normalized.name.length > 255 || /[/\\]/.test(normalized.name)) {
    throw assetError("素材文件名不符合桥接协议", { path: asset.path });
  }
  if (normalized.type.length > 160) {
    throw assetError("素材 MIME 类型过长", { path: asset.path });
  }
  if (asset.sourceUrl !== undefined) normalized.sourceUrl = asset.sourceUrl;
  Object.defineProperty(normalized, "_fileIdentity", {
    enumerable: false,
    value: {
      dev: initialStat.dev,
      ino: initialStat.ino,
      mtimeMs: initialStat.mtimeMs,
      ctimeMs: initialStat.ctimeMs,
    },
  });
  return normalized;
}

export async function inspectAssets(assets) {
  const result = [];
  // Deliberately serial: local disks and large media are finite resources, and
  // command latency is normally dominated by the browser job that follows.
  for (const asset of assets) result.push(await inspectAsset(asset));
  return result;
}
