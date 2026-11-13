// Parental controls: per-device internet access, as fw4 time rules.
// A device's limit is one firewall `rule` (src lan -> dest wan, src_mac, target REJECT):
//   - paused    : rule active all the time (blocks now)
//   - scheduled : rule active on selected weekdays between start/stop (blocks then)
import { call, uciSet, uciAdd, uciDelete, firewallApply } from './ubus';

export const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function toArr(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v === 'string' && v.trim()) return v.trim().split(/\s+/);
  return [];
}

export type ParentalMode = 'off' | 'paused' | 'scheduled';
export interface ParentalRule {
  id: string;
  mac: string;
  mode: ParentalMode;
  days: string[];
  from: string;
  to: string;
}

export async function loadParental(): Promise<Record<string, ParentalRule>> {
  const r = await call<any>('uci', 'get', { config: 'firewall' });
  const values = r?.values ?? r ?? {};
  const map: Record<string, ParentalRule> = {};
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'rule') continue;
    if (!String(s.name ?? '').startsWith('Parental')) continue;
    const mac = String(s.src_mac ?? '').toUpperCase();
    if (!mac) continue;
    const scheduled = !!(s.start_time || s.stop_time || s.weekdays);
    map[mac] = {
      id,
      mac,
      mode: s.enabled === '0' ? 'off' : scheduled ? 'scheduled' : 'paused',
      days: toArr(s.weekdays),
      from: String(s.start_time ?? '20:00'),
      to: String(s.stop_time ?? '22:00')
    };
  }
  return map;
}

async function clearTimeOptions(id: string) {
  for (const opt of ['weekdays', 'start_time', 'stop_time']) {
    await uciDelete('firewall', id, opt).catch(() => {});
  }
}

/** Block the device all the time (pause now). */
export async function pauseDevice(mac: string, name: string, existingId: string | null): Promise<void> {
  const base = { name: `Parental: ${name}`, src: 'lan', dest: 'wan', src_mac: mac, target: 'REJECT', enabled: '1' };
  if (existingId) {
    await uciSet('firewall', existingId, base);
    await clearTimeOptions(existingId);
  } else {
    await uciAdd('firewall', 'rule', undefined, base);
  }
  await firewallApply();
}

/** Block the device on the given days between from–to (same-day window). */
export async function scheduleDevice(
  mac: string, name: string, days: string[], from: string, to: string, existingId: string | null
): Promise<void> {
  const values: Record<string, unknown> = {
    name: `Parental: ${name}`, src: 'lan', dest: 'wan', src_mac: mac, target: 'REJECT', enabled: '1',
    start_time: from, stop_time: to
  };
  if (days.length && days.length < 7) values.weekdays = days;
  if (existingId) {
    await uciSet('firewall', existingId, values);
    if (!(days.length && days.length < 7)) await uciDelete('firewall', existingId, 'weekdays').catch(() => {});
  } else {
    await uciAdd('firewall', 'rule', undefined, values);
  }
  await firewallApply();
}

/** Remove all limits for the device. */
export async function clearDevice(id: string): Promise<void> {
  await uciDelete('firewall', id);
  await firewallApply();
}
