import assert from "node:assert/strict";
import test from "node:test";
import { handleMeshIngress } from "../src/worker.mjs";

function limiter(success = true) {
  return { calls: [], async limit(input) { this.calls.push(input); return { success }; } };
}

function environment(overrides = {}) {
  return {
    MESH_UPSTREAM_ORIGIN: "https://private.example",
    SITES_UPSTREAM_AUTH_TOKEN: "server-side-secret-with-at-least-32-characters",
    ENROLL_RATE_LIMITER: limiter(),
    NODE_RATE_LIMITER: limiter(),
    ...overrides,
  };
}

function request(path, options = {}) {
  return new Request(`https://ingress.example${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", "cf-connecting-ip": "203.0.113.7", ...options.headers },
    body: options.body ?? JSON.stringify({ nodeId: "node_test", payload: {} }),
  });
}

test("health fails closed until every server-side binding is configured", async () => {
  const healthy = await handleMeshIngress(new Request("https://ingress.example/healthz"), environment());
  assert.equal(healthy.status, 200);
  assert.deepEqual(await healthy.json(), { status: "ok", service: "codex-usage-mesh-ingress" });
  const missingSecret = await handleMeshIngress(new Request("https://ingress.example/healthz"), environment({ SITES_UPSTREAM_AUTH_TOKEN: "" }));
  assert.equal(missingSecret.status, 503);
  assert.doesNotMatch(await missingSecret.text(), /secret|token/i);
});

test("only exact Mesh POST routes are reachable", async () => {
  const env = environment();
  const fetchImpl = async () => Response.json({ ok: true });
  assert.equal((await handleMeshIngress(request("/admin"), env, fetchImpl)).status, 404);
  assert.equal((await handleMeshIngress(request("/api/mesh/enroll?redirect=/admin"), env, fetchImpl)).status, 404);
  const get = new Request("https://ingress.example/api/mesh/enroll", { method: "GET" });
  const getResponse = await handleMeshIngress(get, env, fetchImpl);
  assert.equal(getResponse.status, 405);
  assert.equal(getResponse.headers.get("allow"), "POST");
});

test("the ingress rejects unsupported encodings, media types, and oversized bodies", async () => {
  const env = environment();
  assert.equal((await handleMeshIngress(request("/api/mesh/enroll", { headers: { "content-type": "text/plain" } }), env)).status, 415);
  assert.equal((await handleMeshIngress(request("/api/mesh/enroll", { headers: { "content-encoding": "gzip" } }), env)).status, 415);
  const oversized = request("/api/mesh/enroll", { body: JSON.stringify({ value: "x".repeat(20 * 1024) }) });
  assert.equal((await handleMeshIngress(oversized, env)).status, 413);
  const invalid = request("/api/mesh/enroll", { body: "{" });
  assert.equal((await handleMeshIngress(invalid, env)).status, 400);
});

test("client credentials and metadata are stripped before forwarding", async () => {
  const env = environment();
  let forwarded;
  const response = await handleMeshIngress(request("/api/mesh/ingest", {
    headers: {
      authorization: "Bearer attacker",
      cookie: "session=attacker",
      "oai-sites-authorization": "Bearer client-supplied",
      "x-forwarded-for": "198.51.100.8",
    },
  }), env, async (url, options) => {
    forwarded = { url: String(url), options };
    return Response.json({ accepted: true }, { status: 202, headers: { "set-cookie": "private=1" } });
  });

  assert.equal(response.status, 202);
  assert.equal(forwarded.url, "https://private.example/api/mesh/ingest");
  assert.deepEqual(Object.keys(forwarded.options.headers).sort(), ["accept", "cache-control", "content-type", "oai-sites-authorization"]);
  assert.equal(forwarded.options.headers["oai-sites-authorization"], `Bearer ${env.SITES_UPSTREAM_AUTH_TOKEN}`);
  assert.equal(response.headers.has("set-cookie"), false);
  assert.equal(response.headers.has("access-control-allow-origin"), false);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), { accepted: true });
});

test("rate limits are keyed by client during enrollment and by machine afterward", async () => {
  const enrollLimiter = limiter();
  const nodeLimiter = limiter();
  const env = environment({ ENROLL_RATE_LIMITER: enrollLimiter, NODE_RATE_LIMITER: nodeLimiter });
  const fetchImpl = async () => Response.json({ ok: true });
  await handleMeshIngress(request("/api/mesh/enroll"), env, fetchImpl);
  await handleMeshIngress(request("/api/mesh/usage", { body: JSON.stringify({ nodeId: "node_alpha" }) }), env, fetchImpl);
  assert.deepEqual(enrollLimiter.calls, [{ key: "203.0.113.7" }]);
  assert.deepEqual(nodeLimiter.calls, [{ key: "node_alpha" }]);

  const denied = environment({ ENROLL_RATE_LIMITER: limiter(false) });
  const deniedResponse = await handleMeshIngress(request("/api/mesh/enroll"), denied, fetchImpl);
  assert.equal(deniedResponse.status, 429);
  assert.equal(deniedResponse.headers.get("retry-after"), "60");
});

test("upstream redirects and non-JSON errors fail closed without disclosure", async () => {
  const env = environment();
  const failedFetch = await handleMeshIngress(request("/api/mesh/enroll"), env, async () => {
    throw new TypeError("redirect blocked");
  }, { error() {} });
  assert.equal(failedFetch.status, 502);
  assert.doesNotMatch(await failedFetch.text(), /server-side-secret|redirect blocked/);

  const redirect = await handleMeshIngress(request("/api/mesh/enroll"), env, async () => new Response(null, {
    status: 302,
    headers: { location: "https://private.example/login" },
  }));
  assert.equal(redirect.status, 502);
  assert.equal(redirect.headers.has("location"), false);

  const html = await handleMeshIngress(request("/api/mesh/enroll"), env, async () => new Response("private login page", {
    status: 401,
    headers: { "content-type": "text/html" },
  }));
  assert.equal(html.status, 502);
  assert.doesNotMatch(await html.text(), /private login page/);
});
