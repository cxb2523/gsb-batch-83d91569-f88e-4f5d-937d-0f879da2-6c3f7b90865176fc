import fs from "node:fs";
import http from "node:http";
import { randomBytes } from "node:crypto";
import { once } from "node:events";

function applySecurityHeaders(response) {
  response.setHeader("Access-Control-Allow-Origin", "*");
  response.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
  response.setHeader("Access-Control-Allow-Headers", "Range, Content-Type");
  response.setHeader(
    "Access-Control-Expose-Headers",
    "Accept-Ranges, Content-Length, Content-Range, Content-Type, ETag",
  );
  response.setHeader("Access-Control-Allow-Private-Network", "true");
  response.setHeader("Cache-Control", "no-store, max-age=0");
  response.setHeader("Pragma", "no-cache");
  response.setHeader("Cross-Origin-Resource-Policy", "cross-origin");
  response.setHeader("X-Content-Type-Options", "nosniff");
}

function sendEmpty(response, status, headers = {}) {
  response.writeHead(status, { "Content-Length": "0", ...headers });
  response.end();
}

export function parseByteRange(header, size) {
  if (header === undefined) return null;
  if (typeof header !== "string" || !header.startsWith("bytes=") || header.includes(",")) {
    return { invalid: true };
  }
  const match = /^bytes=(\d*)-(\d*)$/.exec(header);
  if (!match || (!match[1] && !match[2]) || size === 0) return { invalid: true };

  let start;
  let end;
  if (!match[1]) {
    const suffix = Number(match[2]);
    if (!Number.isSafeInteger(suffix) || suffix <= 0) return { invalid: true };
    start = Math.max(0, size - suffix);
    end = size - 1;
  } else {
    start = Number(match[1]);
    end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start > end || start >= size) {
      return { invalid: true };
    }
    end = Math.min(end, size - 1);
  }
  return { start, end };
}

function routeFor(token, index, name) {
  return `/v1/assets/${token}/${index}/${encodeURIComponent(name)}`;
}

function publicAsset(asset, blobUrl) {
  const result = {
    role: asset.role,
    name: asset.name,
    type: asset.type,
    size: asset.size,
    sha256: asset.sha256,
  };
  if (asset.sourceUrl !== undefined) result.sourceUrl = asset.sourceUrl;
  result.blobUrl = blobUrl;
  return result;
}

export async function startAssetServer(
  assets,
  { host = "127.0.0.1", token = randomBytes(32).toString("hex") } = {},
) {
  if (host !== "127.0.0.1") throw new TypeError("Asset server must bind to 127.0.0.1");
  if (!/^[a-f0-9]{32,}$/i.test(token)) throw new TypeError("Asset token is too short");

  const routes = new Map();
  assets.forEach((asset, index) => routes.set(routeFor(token, index, asset.name), asset));

  const server = http.createServer(async (request, response) => {
    applySecurityHeaders(response);
    const pathname = String(request.url || "").split("?", 1)[0];
    const asset = routes.get(pathname);
    if (!asset) {
      sendEmpty(response, 404);
      return;
    }
    if (request.method === "OPTIONS") {
      sendEmpty(response, 204);
      return;
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      sendEmpty(response, 405, { Allow: "GET, HEAD, OPTIONS" });
      return;
    }

    let stat;
    try {
      stat = await fs.promises.stat(asset.path);
    } catch {
      sendEmpty(response, 404);
      return;
    }
    const identity = asset._fileIdentity;
    const identityChanged = identity && (
      stat.dev !== identity.dev ||
      stat.ino !== identity.ino ||
      stat.mtimeMs !== identity.mtimeMs ||
      stat.ctimeMs !== identity.ctimeMs
    );
    if (!stat.isFile() || stat.size !== asset.size || identityChanged) {
      sendEmpty(response, 409);
      return;
    }

    const range = parseByteRange(request.headers.range, asset.size);
    if (range?.invalid) {
      sendEmpty(response, 416, { "Content-Range": `bytes */${asset.size}` });
      return;
    }
    const start = range ? range.start : 0;
    const end = range ? range.end : Math.max(0, asset.size - 1);
    const length = asset.size === 0 ? 0 : end - start + 1;
    const headers = {
      "Accept-Ranges": "bytes",
      "Content-Length": String(length),
      "Content-Type": asset.type,
      ETag: `"sha256-${asset.sha256}"`,
    };
    if (range) headers["Content-Range"] = `bytes ${start}-${end}/${asset.size}`;
    response.writeHead(range ? 206 : 200, headers);
    if (request.method === "HEAD" || asset.size === 0) {
      response.end();
      return;
    }

    const stream = fs.createReadStream(asset.path, { start, end });
    stream.on("error", () => response.destroy());
    stream.pipe(response);
  });
  server.on("clientError", (_error, socket) => socket.destroy());
  server.listen(0, host);
  await once(server, "listening");
  const address = server.address();
  const baseUrl = `http://${host}:${address.port}`;
  const transportAssets = assets.map((asset, index) =>
    publicAsset(asset, `${baseUrl}${routeFor(token, index, asset.name)}`),
  );

  let closed = false;
  return {
    host,
    port: address.port,
    transportAssets,
    async close() {
      if (closed) return;
      closed = true;
      await new Promise((resolve) => {
        server.close(resolve);
        server.closeIdleConnections?.();
        server.closeAllConnections?.();
      });
    },
  };
}
