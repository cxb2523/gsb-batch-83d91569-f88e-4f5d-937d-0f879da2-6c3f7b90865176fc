import { readFile, writeFile, mkdir, rename } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { checkCandidate, githubArchive, packSnapshot } from './lib/cloud-archive.mjs';
const exec = promisify(execFile), root = fileURLToPath(new URL('../', import.meta.url));
const directory = resolve(root, '.local/cloud-update'), seedFile = resolve(directory, 'seed.json');
const env = process.env;
const repository = env.GITHUB_REPOSITORY, token = env.GH_TOKEN || env.GITHUB_TOKEN;
const archive = githubArchive({ repository, token });
const mode = process.argv[2] || 'update';
await mkdir(directory, { recursive: true });
async function writeSeed(seed) { await writeFile(seedFile + '.pending', JSON.stringify(seed) + '\n', { mode: 0o600 }); await rename(seedFile + '.pending', seedFile); }
function nextArchive(seed, trigger) {
  const now = new Date().toISOString(), id = now.replace(/[-:]/g, '').replace(/\.\d{3}/, '') + '-' + (env.GITHUB_RUN_ID || 'bootstrap') + '-' + (env.GITHUB_RUN_ATTEMPT || '1');
  return packSnapshot(seed, { id, trigger, collectedAt: now });
}
if (mode === 'bootstrap') {
  if (!env.FTSHARE_SEED_FILE) throw new Error('Set an authorized seed file for bootstrap');
  const packed = nextArchive(JSON.parse(await readFile(resolve(root, env.FTSHARE_SEED_FILE), 'utf8')), 'bootstrap');
  console.log(JSON.stringify(await archive.save(packed, env.GITHUB_SHA)));
} else if (mode === 'restore') {
  const restored = await archive.restore(env.CLOUD_ARCHIVE_ID); await writeSeed(restored.seed);
  console.log(JSON.stringify({ restored: restored.manifest.id, flow_through: restored.seed.latest_flow_date }));
} else if (mode === 'update') {
  const restored = await archive.restore(); await writeSeed(restored.seed);
  // No credentials appear in arguments or captured output. A failed collector leaves the archive and site untouched.
  let collected = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    try { await exec(process.execPath, ['scripts/collect.mjs', '--recent'], { cwd: root, env: { ...env, FTSHARE_SEED_FILE: seedFile }, maxBuffer: 1024 * 1024 }); collected = true; break; }
    catch (error) {
      let detail = String(error.stderr || error.message);
      for (const secret of [env.FTSHARE_API_KEY, env.CLOUDFLARE_API_TOKEN, token].filter(Boolean)) detail = detail.replaceAll(secret, '[redacted]');
      detail = detail.replace(/ftshare_sk_[A-Za-z0-9_-]+/g, '[redacted]');
      console.error('Collection attempt ' + (attempt + 1) + ' failed:\n' + detail.slice(-2400));
      if (/^\s*code:\s*['"](?:quota_exceeded|rate_limited)['"]/m.test(detail) || attempt === 2) break;
      await new Promise(resolve => setTimeout(resolve, attempt ? 15000 : 5000));
    }
  }
  if (!collected) throw new Error('Cloud collection failed; previous archive and deployed site are retained');
  const next = JSON.parse(await readFile(seedFile, 'utf8')); checkCandidate(restored.seed, next);
  // This reads the already-published shared cache; it never starts another provider collection.
  const cacheProject = env.CLOUDFLARE_TEST_PROJECT || env.CLOUDFLARE_PAGES_PROJECT;
  try {
    if (/^[a-z0-9-]+$/.test(cacheProject || '')) {
    const r = await fetch('https://' + cacheProject + '.pages.dev/api/live', { signal: AbortSignal.timeout(15000) });
    const live = r.ok ? await r.json() : null;
    if (live?.cache?.mode === 'background' && live.provider === 'FTShare' && live.table?.length === 20 && live.slots?.length === next.minute_slots.length) next.live_snapshot = live;
    }
  } catch { /* keep the previous embedded success if the cache cannot be read */ }
  const packed = nextArchive(next, env.GITHUB_EVENT_NAME || 'manual');
  await archive.save(packed, env.GITHUB_SHA);
  // Exercise download, checksum and schema validation against the actual archived bytes before building.
  const verified = await archive.restore(packed.manifest.id); await writeSeed(verified.seed);
  await writeFile(resolve(directory, 'manifest.json'), JSON.stringify(packed.manifest, null, 2));
  console.log(JSON.stringify({ archived: packed.manifest.id, verified_restore: true, flow_through: next.latest_flow_date, market_through: next.latest_market_date }));
} else throw new Error('Use update, restore or bootstrap');
