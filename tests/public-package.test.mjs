import test from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { readFile } from 'node:fs/promises';
import { auditRelease } from '../scripts/lib/release.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
test('data bootstrap requires the deployer to select a repository before any download', () => {
  const env = { ...process.env, FTSHARE_ARCHIVE_REPO: '', FTSHARE_ARCHIVE_TAG: '', PATH: '' };
  assert.throws(() => execFileSync(process.execPath, ['scripts/download-seed.mjs'], { cwd: root, env, stdio: 'pipe' }), e => e.status === 1 && e.stderr.toString().includes('Set FTSHARE_ARCHIVE_REPO'));
  const help = execFileSync(process.execPath, ['scripts/download-seed.mjs', '--help'], { cwd: root, env, encoding: 'utf8' });
  assert(help.includes('FTSHARE_ARCHIVE_REPO')); assert(help.includes('FTSHARE_ARCHIVE_TAG'));
});
test('public package keeps CI and the collector template with generic deployment targets', async () => {
  const files = await auditRelease(root);
  assert(files.includes('.github/workflows/ci.yml'));
  assert(!files.includes('.github/workflows/cloud-test-update.yml'));
  assert(!files.some(f => f.startsWith('docs/domain-migration-')));
  assert(files.includes('docs/examples/cloud-test-update.yml'));
  const template = await readFile(new URL('../docs/examples/cloud-test-update.yml', import.meta.url), 'utf8');
  assert(template.includes('CLOUDFLARE_FORMAL_PROJECT:'));
  assert(template.includes('CLOUDFLARE_TEST_PROJECT:'));
  const ignore = await readFile(new URL('../.gitignore', import.meta.url), 'utf8');
  assert(ignore.includes('config/intraday-worker.local.jsonc'));
});
