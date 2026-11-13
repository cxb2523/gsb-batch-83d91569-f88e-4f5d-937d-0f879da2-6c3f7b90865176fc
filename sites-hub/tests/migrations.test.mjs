import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { cp, mkdir, mkdtemp, readdir, rm } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const projectRoot = fileURLToPath(new URL("../", import.meta.url));

test("committed migration snapshots leave schema generation with no changes", async () => {
  const cacheRoot = path.join(projectRoot, ".cache");
  await mkdir(cacheRoot, { recursive: true });
  const directory = await mkdtemp(path.join(cacheRoot, "migration-check-"));
  const outputDirectory = path.join(directory, "drizzle");
  try {
    await cp(path.join(projectRoot, "drizzle"), outputDirectory, { recursive: true });
    const before = (await readdir(outputDirectory)).sort();
    const result = spawnSync(process.execPath, [
      path.join(projectRoot, "node_modules/drizzle-kit/bin.cjs"),
      "generate", "--dialect", "sqlite", "--schema", "./db/schema.ts",
      "--out", path.relative(projectRoot, outputDirectory).replaceAll("\\", "/"),
    ], { cwd: projectRoot, encoding: "utf8", timeout: 30_000 });
    assert.ifError(result.error);
    assert.equal(result.status, 0, result.stderr || result.stdout);
    assert.deepEqual((await readdir(outputDirectory)).sort(), before, result.stdout);
    assert.match(result.stdout, /No schema changes/);
  } finally {
    assert.equal(path.dirname(directory), cacheRoot);
    await rm(directory, { recursive: true, force: true });
  }
});
