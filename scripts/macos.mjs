import { mkdir, writeFile, readFile, rm, chmod, access } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { homedir, networkInterfaces } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { macJobs, plist } from './lib/macos.mjs';
import { refreshDeployment, probeServer } from './lib/deployment.mjs';
import { loadAPIKey } from './lib/key.mjs';

const exec = promisify(execFile), root = fileURLToPath(new URL('../', import.meta.url));
const action = process.argv[2] || 'help';
const domain = 'gui/' + process.getuid?.(), local = resolve(root, '.local/macos');
const labels = ['com.ftshare.etf-dashboard', 'com.ftshare.etf-dashboard.refresh'];
const agent = label => resolve(homedir(), 'Library/LaunchAgents', label + '.plist');
try {
  if (!['install', 'status', 'uninstall'].includes(action)) {
    console.log('npm run mac:install [-- --demo|--dry-run|--lan]\nnpm run mac:status\nnpm run mac:uninstall\nDefault binding: loopback for Caddy on this Mac. --lan explicitly enables LAN HTTP. Live mode requires .env, a snapshot and an API key.');
  } else {
    if (process.platform !== 'darwin' && !process.argv.includes('--dry-run')) throw new Error('macOS is required');
    if (process.getuid?.() === 0) throw new Error('Run as the Mac login user, without sudo');
    if (action === 'status') {
      for (const label of labels) {
        try { const r = await exec('/bin/launchctl', ['print', domain + '/' + label]); console.log(r.stdout); }
        catch { console.log(label + ': not loaded'); }
      }
      try { console.log(await readFile(resolve(root, '.local/last-refresh.json'), 'utf8')); } catch {}
    } else if (action === 'uninstall') {
      for (const label of labels) { try { await exec('/bin/launchctl', ['bootout', domain + '/' + label]); } catch {} await rm(agent(label), { force: true }); }
      await rm(resolve(local, 'installation.json'), { force: true });
      console.log('Stopped and removed LaunchAgents; snapshots, credentials and logs retained.');
    } else {
      const demo = process.argv.includes('--demo'), dry = process.argv.includes('--dry-run');
      const mode = process.env.DATA_MODE || 'demo';
      if (!dry && !demo && mode !== 'live') throw new Error('Set DATA_MODE=live in .env; use --demo only for a synthetic demonstration');
      if (!dry && demo && mode !== 'demo') throw new Error('--demo requires DATA_MODE=demo');
      const lan = process.argv.includes('--lan');
      const jobs = macJobs({ root, node: process.execPath, port: Number(process.env.PORT || 8080), demo, lan });
      if (dry) {
        await mkdir(local, { recursive: true });
        for (const job of jobs) await writeFile(resolve(local, job.Label + '.plist'), plist(job), { mode: 0o600 });
        console.log('Dry run: generated plists in .local/macos; no services installed or started.');
      } else {
        await access(resolve(root, '.env'));
        if (!demo && !await loadAPIKey()) throw new Error('Configure FTSHARE_API_KEY_FILE before installing live service');
        // Refuse to replace an unrelated service using the same label.
        for (const label of labels) {
          try {
            const old = await readFile(agent(label), 'utf8');
            if (!old.includes(plist({ path: root }).split('<string>')[1].split('</string>')[0])) throw new Error('A different checkout already owns ' + label);
          } catch (error) { if (error.code !== 'ENOENT') throw error; }
        }
        // Installation also repairs unloaded jobs; it bootstraps and probes them below.
        await refreshDeployment({ root, collect: false, manageService: false });
        await mkdir(local, { recursive: true }); await mkdir(resolve(root, '.local/logs'), { recursive: true });
        await mkdir(resolve(homedir(), 'Library/LaunchAgents'), { recursive: true });
        await chmod(resolve(root, '.env'), 0o600);
        for (const label of labels) { try { await exec('/bin/launchctl', ['bootout', domain + '/' + label]); } catch {} }
        for (const job of jobs) {
          await writeFile(agent(job.Label), plist(job), { mode: 0o600 });
          await exec('/usr/bin/plutil', ['-lint', agent(job.Label)]);
          await exec('/bin/launchctl', ['enable', domain + '/' + job.Label]);
          await exec('/bin/launchctl', ['bootstrap', domain, agent(job.Label)]);
        }
        if (demo) await rm(agent(labels[1]), { force: true });
        await writeFile(resolve(local, 'installation.json'), JSON.stringify({ domain, label: labels[0], port: Number(process.env.PORT || 8080) }) + '\n', { mode: 0o600 });
        const metadata = JSON.parse(await readFile(resolve(root, '.local/current/metadata.json'), 'utf8'));
        await probeServer(Number(process.env.PORT || 8080), metadata.built_at);
        console.log('Installed. Visit http://127.0.0.1:' + (process.env.PORT || 8080));
        if (lan) for (const rows of Object.values(networkInterfaces())) for (const row of rows || []) if (row.family === 'IPv4' && !row.internal) console.log('LAN candidate: http://' + row.address + ':' + (process.env.PORT || 8080));
        console.log(lan ? 'LAN HTTP enabled explicitly; never expose port 8080 to the internet.' : 'Node is loopback-only. Serve HTTPS through Caddy on this Mac.');
        console.log('User login, power and network are required.');
      }
    }
  }
} catch (error) { console.error(error.message.replace(/ftshare_sk_[A-Za-z0-9_-]+/g, '[redacted]')); process.exitCode = 1; }
