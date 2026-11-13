import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, copyFile, readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { gunzipSync } from 'node:zlib';
import { resolve } from 'node:path';
import { tmpdir } from 'node:os';
import { auditRelease, releaseRoots } from '../scripts/lib/release.mjs';
async function fixture(t) {
  const root = await mkdtemp(resolve(tmpdir(), 'etf-public-release-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  const dirs = new Set(['src','scripts','tests','config','docs','third_party','.github']);
  for (const entry of releaseRoots) {
    const path = resolve(root, entry);
    if (dirs.has(entry)) await mkdir(path, { recursive: true });
    else { await mkdir(resolve(path, '..'), { recursive: true }); await writeFile(path, 'Synthetic release fixture\n'); }
  }
  return root;
}
test('public source skips nested generated output and running private workflow but keeps the template', async t => {
  const root = await fixture(t);
  const files = ['config/.local/intraday-dry-run/collector.js','config/.wrangler/state.json','.github/workflows/cloud-test-update.yml','.github/workflows/ci.yml','docs/examples/cloud-test-update.yml','docs/domain-migration-internal.md','src/assets/radar.js'];
  for (const file of files) { const path=resolve(root,file); await mkdir(resolve(path,'..'),{recursive:true}); await writeFile(path,'Synthetic fixture\n'); }
  const selected = await auditRelease(root);
  assert(selected.includes('.github/workflows/ci.yml'));
  assert(selected.includes('docs/examples/cloud-test-update.yml'));
  assert(selected.includes('src/assets/radar.js'));
  for(const file of files.slice(0,3).concat('docs/domain-migration-internal.md'))assert(!selected.includes(file));
});
test('release audit still rejects a credential selected under a public source root',async t=>{
  const root=await fixture(t);await writeFile(resolve(root,'config/accidental.key'),'synthetic');
  await assert.rejects(auditRelease(root),/credential file selected/);
});
test('source archive headers use neutral ownership instead of the build account', async t => {
  const root = await fixture(t);
  for (const path of ['scripts/release-archive.mjs', 'scripts/lib/release.mjs']) {
    await mkdir(resolve(root, path, '..'), { recursive: true });
    await copyFile(new URL('../' + path, import.meta.url), resolve(root, path));
  }
  await writeFile(resolve(root, 'package.json'), JSON.stringify({ name: 'release-fixture', version: '0.1.0', type: 'module' }));
  execFileSync(process.execPath, ['scripts/release-archive.mjs'], { cwd: root, stdio: 'pipe' });
  const tar = gunzipSync(await readFile(resolve(root, 'releases/release-fixture-v0.1.0.tar.gz')));
  let members = 0;
  for (let offset = 0; offset + 512 <= tar.length && tar[offset] !== 0;) {
    const header = tar.subarray(offset, offset + 512);
    const field = (start, end) => header.toString('utf8', start, end).replace(/\0.*$/s, '').trim();
    assert.equal(parseInt(field(108, 116), 8), 0);
    assert.equal(parseInt(field(116, 124), 8), 0);
    assert(['', 'root'].includes(field(265, 297)));
    assert(['', 'root'].includes(field(297, 329)));
    offset += 512 + Math.ceil((parseInt(field(124, 136), 8) || 0) / 512) * 512;
    members++;
  }
  assert(members > 0);
});
