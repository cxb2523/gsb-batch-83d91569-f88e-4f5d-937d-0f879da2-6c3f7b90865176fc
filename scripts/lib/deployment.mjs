import { readFile, writeFile, mkdir, rm, cp, rename, symlink, readlink, open, realpath } from 'node:fs/promises';
import { resolve, relative } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { randomUUID } from 'node:crypto';
import { validateSeed } from './seed.mjs';

const exec = promisify(execFile);
async function optionalJSON(path) {
  try { return JSON.parse(await readFile(path, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return null; throw error; }
}
async function replaceLink(path, target) {
  const pending = path + '.' + randomUUID();
  await symlink(target, pending, 'dir');
  try { await rename(pending, path); } finally { await rm(pending, { force: true }); }
}
export async function probeServer(port, expected, attempts = 25) {
  for (let n = 0; n < attempts; n++) {
    try {
      const response = await fetch('http://127.0.0.1:' + port + '/api/health', { signal: AbortSignal.timeout(2000) });
      const health = await response.json();
      if (response.ok && health.history_built_at === expected) return;
    } catch { /* Retry while launchd restarts the local process. */ }
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  throw new Error('New local service did not become healthy');
}
export async function refreshDeployment({ root, env = process.env, collect = true, restart,
  probe = probeServer, run, manageService = true } = {}) {
  root = await realpath(root);
  const mode = env.DATA_MODE || 'demo';
  if (collect && mode !== 'live') throw new Error('Scheduled refresh requires DATA_MODE=live');
  const local = resolve(root, '.local'); await mkdir(local, { recursive: true });
  const lockPath = resolve(local, 'refresh.lock');
  let lock;
  try { lock = await open(lockPath, 'wx', 0o600); }
  catch (error) { if (error.code === 'EEXIST') throw new Error('Another refresh is running, or refresh.lock needs review after an interrupted run'); throw error; }
  await lock.writeFile(JSON.stringify({ pid: process.pid, started_at: new Date().toISOString() }));
  const id = new Date().toISOString().replace(/[:.]/g, '-') + '-' + randomUUID().slice(0, 8);
  const release = resolve(local, 'releases', id), link = resolve(local, 'current');
  const seedPath = resolve(root, env.FTSHARE_SEED_FILE || 'data/private/seed.json');
  const stage = resolve(release, 'seed.json');
  let priorLink, previousSeed, changed = false, seedChanged = false;
  const execute = run || (async (script, args, childEnv) => {
    // Do not print subprocess output: upstream error text could contain credentials.
    try { await exec(process.execPath, [script, ...args], { cwd: root, env: childEnv, timeout: 45 * 60 * 1000, maxBuffer: 2 * 1024 * 1024 }); }
    catch { throw new Error(script + ' failed; the existing deployment is retained'); }
  });
  try {
    await mkdir(release, { recursive: true });
    if (mode === 'live') {
      previousSeed = await readFile(seedPath);
      validateSeed(JSON.parse(previousSeed), 'live');
      await writeFile(stage, previousSeed, { mode: 0o600 });
    }
    const childEnv = { ...env, DATA_MODE: mode, FTSHARE_SEED_FILE: stage, BUILD_OUTPUT_DIR: release };
    if (collect) await execute('scripts/collect.mjs', ['--recent'], childEnv);
    // build.mjs recreates its output; keep the candidate seed outside that directory.
    const candidate = resolve(local, 'candidate-' + id + '.json');
    if (mode === 'live') await cp(stage, candidate);
    try {
      const buildEnv = { ...childEnv, FTSHARE_SEED_FILE: candidate };
      await execute('scripts/build.mjs', [], buildEnv);
      await execute('scripts/validate-artifact.mjs', [], buildEnv);
      if (mode === 'live') {
        validateSeed(JSON.parse(await readFile(candidate, 'utf8')), 'live');
        await cp(candidate, stage);
      }
    } finally { await rm(candidate, { force: true }); }
    const metadata = JSON.parse(await readFile(resolve(release, 'metadata.json'), 'utf8'));
    if (metadata.mode !== mode) throw new Error('Build mode mismatch');
    try { priorLink = await readlink(link); } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const installed = manageService ? await optionalJSON(resolve(local, 'macos/installation.json')) : null;
    if (mode === 'live') {
      await mkdir(resolve(local, 'backups'), { recursive: true });
      await writeFile(resolve(local, 'backups', id + '.json'), previousSeed, { mode: 0o600 });
      await cp(stage, seedPath + '.pending'); await rename(seedPath + '.pending', seedPath); seedChanged = true;
    }
    await replaceLink(link, relative(local, release)); changed = true;
    if (installed) {
      const start = restart || (() => exec('/bin/launchctl', ['kickstart', '-k', installed.domain + '/' + installed.label]));
      await start(installed);
      await probe(installed.port, metadata.built_at);
    }
    const result = { release: id, mode, source_date: metadata.source_date, built_at: metadata.built_at, restarted: Boolean(installed) };
    await writeFile(resolve(local, 'last-refresh.json'), JSON.stringify({ ...result, completed_at: new Date().toISOString() }, null, 2) + '\n');
    return result;
  } catch (error) {
    if (changed) {
      if (priorLink) await replaceLink(link, priorLink); else await rm(link, { force: true });
    }
    if (seedChanged) { await writeFile(seedPath + '.pending', previousSeed, { mode: 0o600 }); await rename(seedPath + '.pending', seedPath); }
    if (changed && priorLink) {
      const installed = await optionalJSON(resolve(local, 'macos/installation.json'));
      if (installed) {
        try {
          await (restart || (() => exec('/bin/launchctl', ['kickstart', '-k', installed.domain + '/' + installed.label])))(installed);
          const prior = JSON.parse(await readFile(resolve(link, 'metadata.json'), 'utf8'));
          await probe(installed.port, prior.built_at);
        } catch { throw new Error('Refresh failed; old files restored, but the old service restart needs manual inspection'); }
      }
    }
    await rm(release, { recursive: true, force: true });
    throw error;
  } finally { await lock.close(); await rm(lockPath, { force: true }); }
}
