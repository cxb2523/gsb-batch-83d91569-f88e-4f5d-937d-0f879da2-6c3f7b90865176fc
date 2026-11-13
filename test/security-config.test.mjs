import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Docker exposes only the required Codex log sources", async () => {
  const [compose, dockerfile] = await Promise.all([
    readFile(new URL("../compose.yaml", import.meta.url), "utf8"),
    readFile(new URL("../Dockerfile", import.meta.url), "utf8"),
  ]);
  assert.match(compose, /target:\s*\/codex-data\/sessions/);
  assert.match(compose, /target:\s*\/codex-data\/archived_sessions/);
  assert.match(compose, /target:\s*\/codex-data\/session_index\.jsonl/);
  assert.doesNotMatch(compose, /target:\s*\/codex-data\s*(?:\r?\n|$)/);
  assert.doesNotMatch(compose, /auth\.json/i);
  assert.equal((compose.match(/read_only:\s*true/g) || []).length >= 4, true);
  assert.match(compose, /cap_drop:\s*\r?\n\s*- ALL/);
  assert.match(dockerfile, /rm -rf \/usr\/local\/lib\/node_modules\/npm/);
  assert.match(dockerfile, /rm -f \/usr\/local\/bin\/npm \/usr\/local\/bin\/npx/);
});

test("credential files are excluded from source control and Docker context", async () => {
  const [gitignore, dockerignore] = await Promise.all([
    readFile(new URL("../.gitignore", import.meta.url), "utf8"),
    readFile(new URL("../.dockerignore", import.meta.url), "utf8"),
  ]);
  assert.match(gitignore, /^auth\.json$/m);
  assert.match(dockerignore, /^auth\.json$/m);
});

test("reporting machines never receive a shared private-Site credential", async () => {
  const clientFiles = await Promise.all([
    "../src/mesh-agent.mjs",
    "../src/usage-collector.mjs",
    "../compose.yaml",
    "../.env.example",
    "../docs/reporting-agent.md",
  ].map((file) => readFile(new URL(file, import.meta.url), "utf8")));
  const clientSource = clientFiles.join("\n");
  assert.doesNotMatch(clientSource, /MESH_SITES_BYPASS_TOKEN/);
  assert.doesNotMatch(clientSource, /OAI-Sites-Authorization/i);
  assert.match(clientSource, /one-time enrollment code|code expires after ten minutes/i);

  const ingress = await readFile(new URL("../mesh-ingress/src/worker.mjs", import.meta.url), "utf8");
  assert.match(ingress, /SITES_UPSTREAM_AUTH_TOKEN/);
  assert.match(ingress, /oai-sites-authorization/);
  assert.doesNotMatch(ingress, /logger\.(?:log|info|warn|error)\([^\n]*(?:body|headers|token)/i);
});

test("the strict CSP is kept without runtime inline styles", async () => {
  const [server, app] = await Promise.all([
    readFile(new URL("../server.mjs", import.meta.url), "utf8"),
    readFile(new URL("../public/app.js", import.meta.url), "utf8"),
  ]);
  assert.match(server, /style-src 'self'/);
  assert.doesNotMatch(server, /style-src[^;]*'unsafe-inline'/);
  assert.doesNotMatch(app, /\sstyle=/);
  assert.doesNotMatch(app, /\.style\./);
});

test("dynamic KPI metadata is escaped before HTML insertion", async () => {
  const app = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.equal((app.match(/title="\$\{escapeHtml\(meta\)\}">\$\{escapeHtml\(meta\)\}/g) || []).length, 2);
  assert.doesNotMatch(app, /title="\$\{escapeHtml\(meta\)\}">\$\{meta\}/);
});

test("the published image instructions keep Codex mounts scoped and read-only", async () => {
  const [readme, packageSource, dockerfile] = await Promise.all([
    readFile(new URL("../README.md", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../Dockerfile", import.meta.url), "utf8"),
  ]);
  const version = JSON.parse(packageSource).version;
  const escapedVersion = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  assert.match(readme, new RegExp(`capitaine/codex-usage-dashboard:${escapedVersion}`));
  assert.match(dockerfile, new RegExp(`org\\.opencontainers\\.image\\.version="${escapedVersion}"`));
  assert.match(readme, /ghcr\.io\/capisoft-lib\/codex-usage-dashboard:1\.0\.2/);
  assert.match(readme, /target=\/codex-data\/sessions,readonly/);
  assert.match(readme, /target=\/codex-data\/archived_sessions,readonly/);
  assert.match(readme, /target=\/codex-data\/session_index\.jsonl,readonly/);
  assert.doesNotMatch(readme, /target=\/codex-data(?:[,"'\s]|$)/);
  assert.doesNotMatch(readme, /auth\.json,target=/i);
});
