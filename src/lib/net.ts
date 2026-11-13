// Network data layer: fetch from ubus/luci-rpc and normalize into UI shapes.
// Field shapes follow OpenWRT 23.05 / 24.10; adjust if your build differs.
import { call, listObjects } from './ubus';
import {
  scanClients,
  type ClientScan, type Client, type Band
} from './clientScan';

export type { DeviceKind, Band, Client, ClientLink, ClientScan, SourceId, SourceStatus } from './clientScan';

export interface BoardInfo { model: string; hostname: string; firmware: string; }
export interface SysInfo { uptimeSec: number; load1: number; memUsedPct: number; }
export interface WanStatus {
  up: boolean; proto: string; device: string;
  ipv4: string | null; gateway: string | null; dns: string[]; uptimeSec: number;
}

const num = (x: unknown): number => (typeof x === 'number' ? x : 0);

export async function getBoard(): Promise<BoardInfo> {
  const b = await call<any>('system', 'board');
  const rel = b?.release ?? {};
  const firmware =
    rel.description ||
    [rel.distribution, rel.version].filter(Boolean).join(' ') ||
    b?.kernel || 'OpenWRT';
  return { model: b?.model || b?.board_name || 'Router', hostname: b?.hostname || 'openwrt', firmware };
}

export async function getSysInfo(): Promise<SysInfo> {
  const s = await call<any>('system', 'info');
  const mem = s?.memory ?? {};
  const total = num(mem.total);
  const avail = num(mem.available ?? mem.free);
  const memUsedPct = total ? Math.round(((total - avail) / total) * 100) : 0;
  const load1 = Array.isArray(s?.load) ? +(num(s.load[0]) / 65536).toFixed(2) : 0;
  return { uptimeSec: num(s?.uptime), load1, memUsedPct };
}

/** RFC1918 or CGNAT (100.64/10) address → the router sits behind another NAT. */
export function isPrivateIp(ip: string | null | undefined): boolean {
  if (!ip) return false;
  const m = ip.match(/^(\d+)\.(\d+)\./);
  if (!m) return false;
  const a = +m[1], b = +m[2];
  return a === 10 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
}

let publicIpCache: { ip: string | null; at: number } | null = null;
/**
 * The address the internet sees. The router cannot know this behind carrier
 * NAT, so the *browser* asks a public echo service (nothing goes through the
 * router's own software). Cached for 10 minutes; null when offline/blocked.
 */
export async function getPublicIp(): Promise<string | null> {
  if (publicIpCache && Date.now() - publicIpCache.at < 600_000) return publicIpCache.ip;
  let ip: string | null = null;
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 5000);
    const r = await fetch('https://api.ipify.org?format=json', { signal: ctl.signal, cache: 'no-store' });
    clearTimeout(t);
    const j = await r.json();
    if (typeof j?.ip === 'string' && /^[0-9a-f.:]+$/i.test(j.ip)) ip = j.ip;
  } catch { /* offline, blocked, or no CORS — leave null */ }
  publicIpCache = { ip, at: Date.now() };
  return ip;
}

export async function getWan(): Promise<WanStatus> {
  const dump = await call<any>('network.interface', 'dump');
  const list: any[] = dump?.interface ?? [];
  const w =
    list.find((i) => i.interface === 'wan') ||
    list.find((i) => Array.isArray(i.route) && i.route.some((r: any) => r.target === '0.0.0.0' || r.target === '::')) ||
    list.find((i) => i.interface !== 'loopback' && i.up);
  if (!w) return { up: false, proto: '?', device: '', ipv4: null, gateway: null, dns: [], uptimeSec: 0 };
  return {
    up: !!w.up,
    proto: w.proto || '?',
    device: w.l3_device || w.device || '',
    ipv4: w['ipv4-address']?.[0]?.address ?? null,
    gateway: (w.route ?? []).find((r: any) => r.target === '0.0.0.0')?.nexthop ?? null,
    dns: w['dns-server'] ?? [],
    uptimeSec: num(w.uptime)
  };
}

/** Why the last wireless lookup could not classify devices ('' when it worked). Shown as a hint in the UI. Kept for the Network Map's existing "first problem" hint; the Devices screen reads the per-source status instead. */
export let wifiDiag = '';

/**
 * Collect the device table. Each of the three sources (host hints, DHCP
 * leases, wireless associations) reports success or a readable failure, and a
 * failed source never discards what the other sources found.
 */
export async function scanDeviceSources(): Promise<ClientScan> {
  const scan = await scanClients({ call, listObjects });
  wifiDiag = scan.wifiDiag;
  return scan;
}

/** Device table only (fresh scan). Use `scanDeviceSources()` when the
 *  per-source status matters. */
export async function getClients(): Promise<Client[]> {
  return (await scanDeviceSources()).clients;
}

export function formatUptime(sec: number): string {
  if (!sec) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h ${m}m` : h ? `${h}h ${m}m` : `${m}m`;
}

export const bandName: Record<Band, string> = { '5': '5 GHz', '24': '2.4 GHz', '6': '6 GHz', wired: 'Wired', '?': 'Unknown' };
export const bandStroke: Record<Band, string> = { '5': '#0fb5c4', '24': '#f79009', '6': '#7a5af8', wired: '#17b26a', '?': '#7c8d97' };
export const bandClass: Record<Band, string> = { '5': 'b5', '24': 'b24', '6': 'b6', wired: 'bwired', '?': 'bunk' };

// ---- Traffic (per-device byte counters from network.device status) ---------
export interface DevStat {
  name: string; up: boolean;
  rxBytes: number; txBytes: number;
}
export async function getDevices(): Promise<DevStat[]> {
  const st = await call<any>('network.device', 'status');
  const out: DevStat[] = [];
  for (const [name, d] of Object.entries<any>(st ?? {})) {
    const s = d?.statistics ?? {};
    out.push({ name, up: !!d?.up, rxBytes: num(s.rx_bytes), txBytes: num(s.tx_bytes) });
  }
  return out;
}

export function formatBytes(b: number): string {
  if (b >= 1e12) return (b / 1e12).toFixed(2) + ' TB';
  if (b >= 1e9) return (b / 1e9).toFixed(2) + ' GB';
  if (b >= 1e6) return (b / 1e6).toFixed(1) + ' MB';
  if (b >= 1e3) return (b / 1e3).toFixed(0) + ' KB';
  return b + ' B';
}

// ---- System log (logd ubus) ------------------------------------------------
export interface LogEntry { time: number; priority: number; source: number; msg: string; }

export const LOG_LEVELS = ['emerg', 'alert', 'crit', 'err', 'warning', 'notice', 'info', 'debug'];

export async function getLog(lines = 200): Promise<LogEntry[]> {
  const r = await call<any>('log', 'read', { lines, stream: false });
  const arr = Array.isArray(r?.log) ? r.log : [];
  return arr.map((e: any) => ({
    time: num(e.time),
    priority: num(e.priority),
    source: num(e.source),
    msg: String(e.msg ?? '')
  }));
}

export function logLevelClass(p: number): string {
  return p <= 3 ? 'lv-err' : p === 4 ? 'lv-warn' : 'lv-info';
}

/** logd timestamps vary by build (us / ms / s); normalize to ms. */
export function logTimeMs(t: number): number {
  if (t > 1e14) return Math.floor(t / 1000);
  if (t > 1e11) return t;
  return t * 1000;
}
export function formatClock(ms: number): string {
  if (!ms) return '';
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}
