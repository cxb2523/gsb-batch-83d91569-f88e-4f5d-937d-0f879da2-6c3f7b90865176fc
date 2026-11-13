import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("mesh transport never references Codex credentials or raw JSONL", async () => {
  const files = await Promise.all([
    readFile(new URL("../src/mesh-agent.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/mesh-privacy.mjs", import.meta.url), "utf8"),
    readFile(new URL("../src/mesh-protocol.mjs", import.meta.url), "utf8"),
  ]);
  const implementation = files.join("\n");
  assert.doesNotMatch(implementation, /auth\.json|session_index|\.jsonl|prompt|reasoning_content|tool_output/i);
});

test("deployment templates contain bindings but no owner-specific linkage", async () => {
  const [hostingSource, ingressSource, gitignore] = await Promise.all([
    readFile(new URL("../sites-hub/.openai/hosting.example.json", import.meta.url), "utf8"),
    readFile(new URL("../mesh-ingress/wrangler.example.jsonc", import.meta.url), "utf8"),
    readFile(new URL("../.gitignore", import.meta.url), "utf8"),
  ]);
  const hosting = JSON.parse(hostingSource);
  const ingress = JSON.parse(ingressSource);

  assert.equal(hosting.d1, "DB");
  assert.equal(hosting.r2, null);
  assert.equal(hosting.project_id, undefined);
  assert.equal(JSON.stringify(hosting).match(/appgprj_|token|secret|password|key/i), null);

  assert.equal(ingress.name, "replace-with-your-mesh-ingress");
  assert.equal(ingress.vars.MESH_UPSTREAM_ORIGIN, "https://your-private-site.example");
  assert.deepEqual(
    ingress.ratelimits.map(({ namespace_id }) => namespace_id),
    ["1001", "1002"],
  );
  assert.doesNotMatch(ingressSource, /\.chatgpt\.site|appgprj_/i);
  assert.match(gitignore, /^sites-hub\/\.openai\/hosting\.json$/m);
  assert.match(gitignore, /^mesh-ingress\/wrangler\.jsonc$/m);
});
