import assert from "node:assert/strict";
import { mkdtemp } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { handleMeshIngress } from "../mesh-ingress/src/worker.mjs";
import { MeshAgent } from "../src/mesh-agent.mjs";
import { MeshHubStore } from "../src/mesh-hub-store.mjs";

const allow = { async limit() { return { success: true }; } };

test("a machine enrolls and synchronizes through ingress without receiving the Sites credential", async () => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "codex-mesh-ingress-"));
  const store = new MeshHubStore();
  const enrollment = await store.createEnrollment();
  const upstreamSecret = "private-upstream-secret-never-sent-to-machines";
  const ingressEnvironment = {
    MESH_UPSTREAM_ORIGIN: "https://private-site.example",
    SITES_UPSTREAM_AUTH_TOKEN: upstreamSecret,
    ENROLL_RATE_LIMITER: allow,
    NODE_RATE_LIMITER: allow,
  };
  const clientRequests = [];
  const upstreamRequests = [];

  const upstreamFetch = async (url, options) => {
    upstreamRequests.push({ url: String(url), headers: options.headers });
    assert.equal(options.headers["oai-sites-authorization"], `Bearer ${upstreamSecret}`);
    const body = JSON.parse(new TextDecoder().decode(options.body));
    try {
      if (String(url).endsWith("/enroll")) return Response.json(await store.enroll(body), { status: 201 });
      if (String(url).endsWith("/ingest")) return Response.json(await store.ingest(body), { status: 202 });
      if (String(url).endsWith("/usage")) return Response.json(await store.readUsage(body));
      return Response.json({ error: "not found" }, { status: 404 });
    } catch (error) {
      return Response.json({ error: error.message, code: error.code }, { status: error.status || 500 });
    }
  };

  const agentFetch = async (url, options) => {
    clientRequests.push({ url, headers: options.headers });
    const headers = new Headers(options.headers);
    headers.set("cf-connecting-ip", "203.0.113.9");
    return handleMeshIngress(new Request(url, { ...options, headers }), ingressEnvironment, upstreamFetch);
  };

  const agent = new MeshAgent({
    hubUrl: "https://public-ingress.example",
    alias: "Secure PC",
    statePath: path.join(directory, "agent.json"),
    enrollmentCode: enrollment.code,
    fetchImpl: agentFetch,
    logger: { log() {} },
  });
  await agent.sync({
    analyzerVersion: 3,
    generatedAt: new Date().toISOString(),
    source: { mode: "local", sessionsAvailable: true, archivedSessionsAvailable: false, sessionIndexAvailable: false },
    weeklyQuota: null,
    weeklyQuotaHistory: [],
    sessions: [],
    errors: [],
  });
  const usage = await agent.centralizedUsage();
  assert.equal(usage.nodes[0].alias, "Secure PC");
  assert.equal(clientRequests.length, 3);
  assert.ok(clientRequests.every(({ headers }) => !Object.keys(headers).some((name) => name.toLowerCase() === "oai-sites-authorization")));
  assert.ok(upstreamRequests.every(({ headers }) => headers["oai-sites-authorization"] === `Bearer ${upstreamSecret}`));

  await store.revokeNode(agent.state.nodeId);
  await assert.rejects(() => agent.centralizedUsage(), /révoquée/);
});
