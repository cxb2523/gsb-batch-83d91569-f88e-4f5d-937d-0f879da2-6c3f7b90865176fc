import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { promoteTest, publicationTarget, verifyFormalSource, verifyRadarSnapshot } from './lib/cloud-publication.mjs';
const env = process.env, exec = promisify(execFile);
const project = env.CLOUDFLARE_PAGES_PROJECT, account = env.CLOUDFLARE_ACCOUNT_ID;
const target = publicationTarget(env);
if (!/^[a-f0-9]{32}$/.test(account || '') || !env.CLOUDFLARE_API_TOKEN) throw new Error('Configure the Pages account and publish token');
const checkedOutRef = (await exec('git', ['rev-parse', 'HEAD'])).stdout.trim();
const endpoint = 'https://api.cloudflare.com/client/v4/accounts/' + account + '/pages/projects/' + project;
async function cf(path = '', method = 'GET') {
  const r = await fetch(endpoint + path, { method, headers: { authorization: 'Bearer ' + env.CLOUDFLARE_API_TOKEN }, signal: AbortSignal.timeout(60000) });
  const body = await r.json(); if (!r.ok || !body.success) throw new Error('Cloudflare project request failed (HTTP ' + r.status + ')'); return body.result;
}
const projectState = await cf();
if (projectState.production_branch !== 'main') throw new Error('Unexpected Pages project production branch');
const before = projectState.canonical_deployment;
if (!before?.id) throw new Error('A previously working deployment is required');
async function deploy(branch) {
  try {
    const result = await exec(process.execPath, ['node_modules/wrangler/bin/wrangler.js', 'pages', 'deploy', 'dist/pages', '--project-name', project, '--branch', branch,
      '--commit-hash', checkedOutRef, '--commit-dirty=false', '--commit-message', 'Cloud ' + target + ' snapshot ' + env.GITHUB_RUN_ID], { env, maxBuffer: 2 * 1024 * 1024 });
    const urls = result.stdout.match(/https:\/\/[a-z0-9]+\.[a-z0-9-]+\.pages\.dev/g);
    if (!urls?.length) throw new Error('Missing deployment URL'); return urls.at(-1);
  } catch { throw new Error('Pages upload failed for ' + target); }
}
const expected = JSON.parse(await readFile('.local/cloud-update/seed.json', 'utf8'));
const radarEnabled = env.ENABLE_RADAR === '1';
if (radarEnabled) verifyRadarSnapshot(expected);
async function verify(base) {
  let last;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const [h, b] = await Promise.all(['/api/health', '/api/board'].map(async p => {
        const r = await fetch(base + p, { signal: AbortSignal.timeout(30000), cache: 'no-store' }); if (!r.ok) throw new Error('HTTP check failed'); return r.json();
      }));
      assert.equal(h.mode, 'live'); assert.equal(h.configured, true); assert.equal(h.history_built_at, expected.built_at);
      assert.equal(b.cloud_update?.archive_id, expected.cloud_update.archive_id); assert.deepEqual(b.broad, expected.broad);
      const asset = await fetch(base + '/assets/dashboard.js', { signal: AbortSignal.timeout(30000) }); assert(asset.ok);
      if (radarEnabled) {
        const page = await fetch(base + '/', { signal: AbortSignal.timeout(30000) }); assert(page.ok);
        assert((await page.text()).includes('data-radar="on"'), 'Radar must remain enabled after scheduled publication');
        const radar = await fetch(base + '/assets/radar.js', { signal: AbortSignal.timeout(30000) }); assert(radar.ok);
        assert((await radar.text()).includes('radarLongMultiple'), 'Dual baseline radar asset missing');
        assert.deepEqual(b.core_fund_daily, expected.core_fund_daily); verifyRadarSnapshot(b);
      }
      return;
    } catch (error) { last = error; if (attempt < 3) await new Promise(resolve => setTimeout(resolve, 5000)); }
  }
  throw new Error('Published snapshot did not pass validation');
}
if (target === 'formal') await verifyFormalSource({ expected, proof: JSON.parse(await readFile('.local/cloud-update/test-publish-result.json', 'utf8')),
  sourceRef: env.CLOUDFLARE_FORMAL_SOURCE_REF, checkedOutRef, testProject: env.CLOUDFLARE_TEST_PROJECT, verify });
const { preview, published } = await promoteTest({ before, deploy, verify, label: target === 'formal' ? 'Formal' : 'Test',
  stableURL: 'https://' + project + '.pages.dev',
  current: async () => (await cf()).canonical_deployment,
  rollback: id => cf('/deployments/' + id + '/rollback', 'POST') });
const result = { target, source_ref: checkedOutRef, preview, published, site: 'https://' + project + '.pages.dev', archive_id: expected.cloud_update.archive_id, flow_through: expected.latest_flow_date, verified_at: new Date().toISOString() };
await writeFile('.local/cloud-update/publish-result.json', JSON.stringify(result, null, 2));
console.log(JSON.stringify(result));
