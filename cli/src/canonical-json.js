import { createHash } from "node:crypto";

function normalizeForCanonicalJson(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("Canonical JSON only supports finite numbers");
    return value;
  }
  if (Array.isArray(value)) return value.map(normalizeForCanonicalJson);
  if (value && typeof value === "object") {
    const result = {};
    for (const key of Object.keys(value).sort()) {
      const child = value[key];
      if (child === undefined) continue;
      result[key] = normalizeForCanonicalJson(child);
    }
    return result;
  }
  throw new TypeError(`Canonical JSON does not support ${typeof value}`);
}

export function canonicalStringify(value) {
  return JSON.stringify(normalizeForCanonicalJson(value));
}

export function sha256CanonicalJson(value) {
  return createHash("sha256").update(canonicalStringify(value), "utf8").digest("hex");
}

export function assetDigestMetadata(asset) {
  const metadata = {
    role: asset.role,
    name: asset.name,
    type: asset.type,
    size: asset.size,
    sha256: asset.sha256,
  };
  if (asset.sourceUrl !== undefined) metadata.sourceUrl = asset.sourceUrl;
  return metadata;
}

export function createPayloadDigest({ bridgeId, browserContext, comboName, groupName, type, mode, platforms, data, assets }) {
  return sha256CanonicalJson({
    ...(bridgeId ? { bridgeId, browserContext } : {}),
    ...(comboName ? { comboName } : {}),
    ...(groupName ? { groupName } : {}),
    type,
    mode,
    platforms,
    data,
    assets: assets.map(assetDigestMetadata),
  });
}
