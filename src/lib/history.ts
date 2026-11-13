// Usage history. Two independent, optional sources, each degrading on its own:
//   - vnstat   -> internet (per-interface) totals over days/months
//   - nlbwmon  -> per-device (per-host) usage for the current period
// Both are read via file.exec (JSON output) and parsed here. Missing tool =>
// installed:false and the screen shows an "install X" card.
import { call } from './ubus';
import { getWan, getClients, type Client } from './net';

export interface UsagePoint { label: string; rx: number; tx: number; }

export interface VnstatData {
  installed: boolean;
  iface: string;
  today: { rx: number; tx: number };
  month: { rx: number; tx: number };
  days: UsagePoint[];   // most recent last
  months: UsagePoint[];
}

export interface DeviceUsage { name: string; ip: string; mac: string; rx: number; tx: number; }
export interface PerDeviceData { installed: boolean; rows: DeviceUsage[]; }

const num = (v: unknown): number => {
  const n = typeof v === 'number' ? v : parseFloat(String(v));
  return Number.isFinite(n) ? n : 0;
};

async function exec(command: string, params: string[]): Promise<string | null> {
  try {
    const r = await call<any>('file', 'exec', { command, params });
    if (r && typeof r.code === 'number' && r.code !== 0) return null;
    const out = String(r?.stdout ?? '');
    return out.trim() ? out : null;
  } catch {
    return null;
  }
}

function dayLabel(d: any): string {
  const dt = d?.date ?? d;
  if (dt && dt.month && dt.day) return `${String(dt.day).padStart(2, '0')}/${String(dt.month).padStart(2, '0')}`;
  return '';
}
function monthLabel(m: any): string {
  const dt = m?.date ?? m;
  const names = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  if (dt && dt.month) return names[dt.month] || String(dt.month);
  return '';
}

export async function loadVnstat(): Promise<VnstatData> {
  const empty: VnstatData = { installed: false, iface: '', today: { rx: 0, tx: 0 }, month: { rx: 0, tx: 0 }, days: [], months: [] };
  const out = await exec('vnstat', ['--json']);
  if (!out) return empty;

  let json: any;
  try { json = JSON.parse(out); } catch { return empty; }
  const ifaces: any[] = Array.isArray(json?.interfaces) ? json.interfaces : [];
  if (!ifaces.length) return { ...empty, installed: true };

  // Prefer the WAN device; fall back to the first non-loopback interface.
  const wanDev = await getWan().then((w) => w.device).catch(() => '');
  const pick = ifaces.find((i) => i?.name === wanDev) || ifaces.find((i) => i?.name && i.name !== 'lo') || ifaces[0];
  const t = pick?.traffic ?? {};
  const dayArr: any[] = Array.isArray(t.day) ? t.day : (Array.isArray(t.days) ? t.days : []);
  const monthArr: any[] = Array.isArray(t.month) ? t.month : (Array.isArray(t.months) ? t.months : []);

  const days: UsagePoint[] = dayArr.map((d) => ({ label: dayLabel(d), rx: num(d.rx), tx: num(d.tx) })).slice(-30);
  const months: UsagePoint[] = monthArr.map((m) => ({ label: monthLabel(m), rx: num(m.rx), tx: num(m.tx) })).slice(-12);
  const lastDay = dayArr[dayArr.length - 1] ?? {};
  const lastMonth = monthArr[monthArr.length - 1] ?? {};

  return {
    installed: true,
    iface: pick?.name ?? '',
    today: { rx: num(lastDay.rx), tx: num(lastDay.tx) },
    month: { rx: num(lastMonth.rx), tx: num(lastMonth.tx) },
    days,
    months
  };
}

export async function loadPerDevice(): Promise<PerDeviceData> {
  const out = await exec('nlbw', ['-c', 'json', '-g', 'ip,mac', '-o', 'rx_bytes']);
  if (!out) return { installed: false, rows: [] };

  let json: any;
  try { json = JSON.parse(out); } catch { return { installed: true, rows: [] }; }
  const cols: string[] = Array.isArray(json?.columns) ? json.columns : [];
  const data: any[][] = Array.isArray(json?.data) ? json.data : [];
  const ix = (name: string) => cols.indexOf(name);
  const iIp = ix('ip'), iMac = ix('mac'), iRx = ix('rx_bytes'), iTx = ix('tx_bytes');

  const clients = await getClients().catch(() => [] as Client[]);
  const nameByMac = new Map(clients.map((c) => [c.mac.toUpperCase(), c.name]));
  const nameByIp = new Map(clients.map((c) => [c.ip, c.name]));

  const rows: DeviceUsage[] = data.map((r) => {
    const ip = iIp >= 0 ? String(r[iIp] ?? '') : '';
    const mac = (iMac >= 0 ? String(r[iMac] ?? '') : '').toUpperCase();
    const name = nameByMac.get(mac) || nameByIp.get(ip) || ip || mac || 'unknown';
    return { name, ip, mac, rx: iRx >= 0 ? num(r[iRx]) : 0, tx: iTx >= 0 ? num(r[iTx]) : 0 };
  }).filter((r) => r.rx || r.tx);

  rows.sort((a, b) => (b.rx + b.tx) - (a.rx + a.tx));
  return { installed: true, rows: rows.slice(0, 50) };
}
