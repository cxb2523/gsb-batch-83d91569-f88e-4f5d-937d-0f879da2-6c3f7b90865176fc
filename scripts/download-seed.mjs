import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, mkdir, rename, rm, access } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { gunzipSync } from 'node:zlib';
import { validateSeed } from './lib/seed.mjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const repo = process.env.FTSHARE_ARCHIVE_REPO, tag = process.env.FTSHARE_ARCHIVE_TAG;
const path = resolve(root, 'data/private/seed.json'), directory = resolve(root, '.local/bootstrap');
try {
  if (process.argv.includes('--help')) {
    console.log('npm run data:bootstrap\nSet FTSHARE_ARCHIVE_REPO=OWNER/REPO and FTSHARE_ARCHIVE_TAG=TAG. Downloads the specified data release using gh login, verifies its checksum and imports the snapshot.');
  } else {
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo || '') || !tag || tag.startsWith('-')) throw new Error('Set FTSHARE_ARCHIVE_REPO and FTSHARE_ARCHIVE_TAG for your data source');
    try { await access(path); throw new Error('A private snapshot already exists; keep it or import another snapshot explicitly'); }
    catch (error) { if (error.code !== 'ENOENT') throw error; }
    await mkdir(directory, { recursive: true });
    await promisify(execFile)('gh', ['release', 'download', tag, '--repo', repo, '--pattern', 'seed.json.gz', '--pattern', 'seed.json.gz.sha256', '--dir', directory, '--clobber'], { cwd: root });
    const bytes = await readFile(resolve(directory, 'seed.json.gz'));
    const expected = (await readFile(resolve(directory, 'seed.json.gz.sha256'), 'utf8')).trim().split(/\s+/)[0];
    if (!/^[a-f0-9]{64}$/.test(expected) || createHash('sha256').update(bytes).digest('hex') !== expected) throw new Error('Historical snapshot checksum mismatch');
    const seed = validateSeed(JSON.parse(gunzipSync(bytes, { maxOutputLength: 50 * 1024 * 1024 }).toString('utf8')), 'live');
    await mkdir(resolve(root, 'data/private'), { recursive: true });
    await writeFile(path + '.pending', JSON.stringify(seed) + '\n', { mode: 0o600 }); await rename(path + '.pending', path);
    await rm(directory, { recursive: true, force: true });
    console.log('Imported ' + seed.universe.length + ' ETFs; broad history starts ' + seed.broad.dates[0] + ', through ' + seed.latest_flow_date + '. Configure your collector for live updates.');
  }
} catch (error) {
  console.error(error.code || error.status ? 'Snapshot download failed; check gh authentication and private repository access, or use data:import.' : error.message);
  process.exitCode = 1;
}
