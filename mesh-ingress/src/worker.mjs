const ROUTES = new Map([
  ["/api/mesh/enroll", { maxBytes: 16 * 1024, limiter: "ENROLL_RATE_LIMITER", key: "client" }],
  ["/api/mesh/ingest", { maxBytes: 8 * 1024 * 1024, limiter: "NODE_RATE_LIMITER", key: "node" }],
  ["/api/mesh/usage", { maxBytes: 64 * 1024, limiter: "NODE_RATE_LIMITER", key: "node" }],
]);

const JSON_CONTENT_TYPE = /^application\/json(?:\s*;.*)?$/i;
const SECURITY_HEADERS = {
  "cache-control": "no-store",
  "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
  "referrer-policy": "no-referrer",
  "x-content-type-options": "nosniff",
};

function json(body, status, extraHeaders = {}) {
  return Response.json(body, {
    status,
    headers: { ...SECURITY_HEADERS, ...extraHeaders },
  });
}

function environment(env) {
  const token = String(env?.SITES_UPSTREAM_AUTH_TOKEN || "");
  let upstream;
  try {
    upstream = new URL(String(env?.MESH_UPSTREAM_ORIGIN || ""));
  } catch {
    return null;
  }
  if (upstream.protocol !== "https:" || upstream.username || upstream.password
    || upstream.pathname !== "/" || upstream.search || upstream.hash
    || token.length < 32 || /[\r\n]/.test(token)
    || typeof env?.ENROLL_RATE_LIMITER?.limit !== "function"
    || typeof env?.NODE_RATE_LIMITER?.limit !== "function") {
    return null;
  }
  return { origin: upstream.origin, token };
}

async function readLimitedBody(request, maxBytes) {
  const declaredHeader = request.headers.get("content-length");
  if (declaredHeader !== null) {
    if (!/^\d+$/.test(declaredHeader)) return { error: json({ error: "Content-Length invalide." }, 400) };
    if (Number(declaredHeader) > maxBytes) return { error: json({ error: "Charge utile trop volumineuse." }, 413) };
  }
  const reader = request.body?.getReader();
  if (!reader) return { error: json({ error: "Corps JSON requis." }, 400) };
  const chunks = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > maxBytes) {
      await reader.cancel();
      return { error: json({ error: "Charge utile trop volumineuse." }, 413) };
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  let value;
  try {
    value = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return { error: json({ error: "JSON invalide." }, 400) };
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return { error: json({ error: "Objet JSON requis." }, 400) };
  }
  return { bytes, value };
}

async function limited(env, route, request, body) {
  const binding = env[route.limiter];
  const clientKey = request.headers.get("cf-connecting-ip") || "unknown-client";
  const nodeId = typeof body.nodeId === "string" && body.nodeId.length <= 256 ? body.nodeId : "unknown-node";
  const key = route.key === "node" ? nodeId : clientKey;
  try {
    const result = await binding.limit({ key });
    return result?.success === true;
  } catch {
    return false;
  }
}

export async function handleMeshIngress(request, env, fetchImpl = fetch, logger = console) {
  const url = new URL(request.url);
  const configured = environment(env);

  if (url.pathname === "/healthz" && request.method === "GET" && !url.search) {
    return configured
      ? json({ status: "ok", service: "codex-usage-mesh-ingress" }, 200)
      : json({ status: "unavailable" }, 503);
  }

  const route = ROUTES.get(url.pathname);
  if (!route || url.search) return json({ error: "Route inconnue." }, 404);
  if (request.method !== "POST") return json({ error: "Méthode refusée." }, 405, { allow: "POST" });
  if (!configured) return json({ error: "Passerelle indisponible." }, 503);
  if (!JSON_CONTENT_TYPE.test(request.headers.get("content-type") || "")) {
    return json({ error: "Content-Type application/json requis." }, 415);
  }
  const contentEncoding = request.headers.get("content-encoding");
  if (contentEncoding && contentEncoding.toLowerCase() !== "identity") {
    return json({ error: "Content-Encoding non pris en charge." }, 415);
  }

  const body = await readLimitedBody(request, route.maxBytes);
  if (body.error) return body.error;
  if (!await limited(env, route, request, body.value)) {
    return json({ error: "Trop de requêtes." }, 429, { "retry-after": "60" });
  }

  const upstreamUrl = new URL(url.pathname, configured.origin);
  let upstreamResponse;
  try {
    upstreamResponse = await fetchImpl(upstreamUrl, {
      method: "POST",
      redirect: "manual",
      headers: {
        accept: "application/json",
        "cache-control": "no-store",
        "content-type": "application/json",
        "oai-sites-authorization": `Bearer ${configured.token}`,
      },
      body: body.bytes,
    });
  } catch (error) {
    logger.error(JSON.stringify({
      event: "mesh_upstream_fetch_failed",
      errorName: error instanceof Error ? error.name : "UnknownError",
      errorMessage: error instanceof Error ? error.message : "Unknown upstream failure",
    }));
    return json({ error: "Hub privé indisponible." }, 502);
  }

  if (upstreamResponse.status >= 300 && upstreamResponse.status < 400) {
    try { await upstreamResponse.body?.cancel(); } catch {}
    return json({ error: "Redirection refusée par la passerelle." }, 502);
  }
  if (!JSON_CONTENT_TYPE.test(upstreamResponse.headers.get("content-type") || "")) {
    try { await upstreamResponse.body?.cancel(); } catch {}
    return json({ error: "Réponse invalide du hub privé." }, 502);
  }
  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    headers: { ...SECURITY_HEADERS, "content-type": "application/json" },
  });
}

export default {
  fetch(request, env) {
    return handleMeshIngress(request, env);
  },
};
