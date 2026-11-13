import { networkInterfaces } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, mkdir, writeFile, stat } from 'node:fs/promises';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { isIP } from 'node:net';

const exec = promisify(execFile), root = fileURLToPath(new URL('../', import.meta.url));
const report = { checked_at: new Date().toISOString(), platform: process.platform, node: process.version,
  interfaces: Object.entries(networkInterfaces()).flatMap(([name, rows]) => (rows || []).filter(r => !r.internal).map(r => ({ name, family: r.family, address: r.address }))),
  proxy_environment_present: ['HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','http_proxy','https_proxy','all_proxy'].filter(k => Boolean(process.env[k])),
  public_inbound_access: 'Not tested: requires an independent external client; outbound IP is not proof.' };
async function externalIP(url, family) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const ip = (await r.text()).trim(); return isIP(ip) === family ? ip : null;
  } catch { return null; }
}
// Report IP addresses only. Never read or print the API key, proxy URL or raw headers.
[report.egress_ipv4, report.egress_ipv6] = await Promise.all([externalIP('https://api.ipify.org', 4), externalIP('https://api6.ipify.org', 6)]);
report.egress_ipv4_is_assigned_to_mac = report.egress_ipv4 ? report.interfaces.some(i => i.address === report.egress_ipv4) : null;
if (process.platform === 'darwin') {
  try {
    const { stdout } = await exec('/usr/sbin/lsof', ['-nP','-iTCP','-sTCP:LISTEN'], { timeout: 5000 });
    report.listeners = stdout.split('\n').filter(line => /:(?:22|80|443|445|5900|2019|8080)\s+\(LISTEN\)/.test(line)).map(line => {
      const fields = line.trim().split(/\s+/); return { process: fields[0], endpoint: fields.at(-2) };
    });
  } catch { report.listeners = []; }
  try { report.firewall = (await exec('/usr/libexec/ApplicationFirewall/socketfilterfw', ['--getglobalstate'], { timeout: 5000 })).stdout.trim(); }
  catch { report.firewall = 'Unable to read; check System Settings'; }
  try {
    const raw = (await exec('/usr/sbin/scutil', ['--proxy'], { timeout: 5000 })).stdout;
    report.system_proxy_enabled_flags = [...raw.matchAll(/(\w+Enable)\s*:\s*(\d+)/g)].map(m => ({ name: m[1], enabled: m[2] === '1' }));
  } catch { report.system_proxy_enabled_flags = []; }
}
const keyPath = process.env.FTSHARE_API_KEY_FILE;
report.key_environment_present = Boolean(process.env.FTSHARE_API_KEY);
if (keyPath) {
  try {
    const info = await stat(resolve(root, keyPath));
    report.key_file = { exists: true, restrictive_permissions: (info.mode & 0o077) === 0, permissions: (info.mode & 0o777).toString(8) };
  } catch { report.key_file = { exists: false }; }
}
try {
  const port = Number(process.env.PORT || 8080);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid port');
  const r = await fetch('http://127.0.0.1:' + port + '/api/health', { signal: AbortSignal.timeout(3000) });
  const h = await r.json();
  report.local_service = { status: r.status, mode: h.mode, configured: h.configured, funds: h.funds, history_built_at: h.history_built_at };
} catch { report.local_service = { reachable: false }; }
try { report.last_refresh = JSON.parse(await readFile(resolve(root, '.local/last-refresh.json'), 'utf8')); } catch {}
await mkdir(resolve(root, '.local'), { recursive: true });
await writeFile(resolve(root, '.local/macmini-check.json'), JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
console.log(JSON.stringify(report, null, 2));
console.log('\nSaved .local/macmini-check.json. Outbound IP does not establish public reachability. No DNS, firewall, sharing or power settings were changed.');
