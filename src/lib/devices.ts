// Device management: fixed IP (static DHCP lease), block internet (fw4 rule),
// and Wake-on-LAN. Reservations and blocks are plain UCI, so they work on a
// stock router. WoL uses file.exec and needs the `etherwake` package; it fails
// gracefully (a toast) when that isn't installed.
import { call, uciGet, uciAdd, uciSet, uciDelete, uciApply, firewallApply } from './ubus';
import { getClients, type Client, type Band, type DeviceKind } from './net';

const BLOCK_PREFIX = 'Block:';

export interface DeviceRow {
  mac: string;
  name: string;
  ip: string;            // current or reserved address
  online: boolean;
  band: Band;
  signal: number;
  kind: DeviceKind;
  reservedIp: string | null;   // fixed IP, if a dhcp host entry exists
  reserveId: string | null;    // dhcp section id
  draftIp: string;             // editable value bound in the UI
  blocked: boolean;
  blockId: string | null;      // firewall rule id
}

const text = (v: unknown): string => (v == null ? '' : String(Array.isArray(v) ? v[0] : v));

function values(r: unknown): Record<string, any> {
  return ((r as any)?.values ?? r ?? {}) as Record<string, any>;
}

async function loadReservations(): Promise<{ id: string; mac: string; ip: string; name: string }[]> {
  const v = values(await uciGet('dhcp'));
  const out: { id: string; mac: string; ip: string; name: string }[] = [];
  for (const [id, s] of Object.entries<any>(v)) {
    if (s?.['.type'] !== 'host') continue;
    const mac = text(s.mac).toUpperCase();
    if (!mac) continue;
    out.push({ id, mac, ip: text(s.ip), name: text(s.name) });
  }
  return out;
}

async function loadBlocks(): Promise<{ id: string; mac: string; enabled: boolean }[]> {
  const v = values(await uciGet('firewall'));
  const out: { id: string; mac: string; enabled: boolean }[] = [];
  for (const [id, s] of Object.entries<any>(v)) {
    if (s?.['.type'] !== 'rule') continue;
    if (!text(s.name).startsWith(BLOCK_PREFIX)) continue;
    const mac = text(s.src_mac).toUpperCase();
    if (!mac) continue;
    out.push({ id, mac, enabled: s.enabled !== '0' });
  }
  return out;
}

/** Merge live clients with reservations and block rules (so offline but
 *  reserved/blocked devices still appear and can be managed/woken). */
export async function loadDevices(): Promise<DeviceRow[]> {
  const [clients, reservations, blocks] = await Promise.all([
    getClients().catch(() => [] as Client[]),
    loadReservations().catch(() => []),
    loadBlocks().catch(() => [])
  ]);

  const byMac = new Map<string, DeviceRow>();
  for (const c of clients) {
    byMac.set(c.mac, {
      mac: c.mac, name: c.name, ip: c.ip, online: true,
      band: c.band, signal: c.signal, kind: c.kind,
      reservedIp: null, reserveId: null, draftIp: c.ip, blocked: false, blockId: null
    });
  }
  const ensure = (mac: string): DeviceRow => {
    let row = byMac.get(mac);
    if (!row) {
      row = {
        mac, name: mac, ip: '', online: false, band: '?', signal: 0, kind: 'd-generic',
        reservedIp: null, reserveId: null, draftIp: '', blocked: false, blockId: null
      };
      byMac.set(mac, row);
    }
    return row;
  };

  for (const r of reservations) {
    const row = ensure(r.mac);
    row.reservedIp = r.ip; row.reserveId = r.id;
    if (!row.ip) row.ip = r.ip;
    row.draftIp = r.ip || row.draftIp;
    if ((!row.name || row.name === row.mac) && r.name) row.name = r.name;
  }
  for (const b of blocks) {
    const row = ensure(b.mac);
    row.blocked = b.enabled; row.blockId = b.id;
  }

  // Surface devices you've acted on: blocked first, then those with a fixed IP,
  // then online, then by name — so an applied change jumps to the top of the list.
  const rank = (r: DeviceRow) => (r.blocked ? 0 : 1);
  return [...byMac.values()].sort(
    (a, b) =>
      rank(a) - rank(b) ||
      Number(!!b.reservedIp) - Number(!!a.reservedIp) ||
      Number(b.online) - Number(a.online) ||
      a.name.localeCompare(b.name)
  );
}

/** Reserve (or update) a fixed IP for a device via a dhcp `host` entry. */
export async function reserveIp(mac: string, ip: string, name: string, existingId: string | null): Promise<void> {
  const v: Record<string, unknown> = { mac: mac.toUpperCase(), ip };
  const hn = name.trim().replace(/[^A-Za-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
  if (hn && hn.toUpperCase() !== mac.toUpperCase()) v.name = hn;
  if (existingId) await uciSet('dhcp', existingId, v);
  else await uciAdd('dhcp', 'host', undefined, v);
  await uciApply();
}

export async function removeReservation(id: string): Promise<void> {
  await uciDelete('dhcp', id);
  await uciApply();
}

/** Rename a device: set the `name` on its dhcp `host` entry (creating one if
 *  there's no reservation yet). An empty name clears it. Hostnames allow only
 *  letters, digits and hyphens. */
export async function renameDevice(mac: string, name: string, existingId: string | null): Promise<void> {
  const hn = name.trim().replace(/[^A-Za-z0-9-]+/g, '-').replace(/^-+|-+$/g, '');
  if (existingId) await uciSet('dhcp', existingId, { name: hn });
  else if (hn) await uciAdd('dhcp', 'host', undefined, { mac: mac.toUpperCase(), name: hn });
  await uciApply();
}

/** Block or unblock a device's internet access with an fw4 rule (by MAC). */
export async function setBlocked(mac: string, name: string, blocked: boolean, existingId: string | null): Promise<void> {
  if (blocked) {
    const v = {
      name: `${BLOCK_PREFIX} ${name}`, src: 'lan', dest: 'wan',
      src_mac: mac.toUpperCase(), target: 'REJECT', enabled: '1'
    };
    if (existingId) await uciSet('firewall', existingId, v);
    else await uciAdd('firewall', 'rule', undefined, v);
  } else if (existingId) {
    await uciDelete('firewall', existingId);
  }
  await firewallApply();
}

async function execOnce(command: string, params: string[]): Promise<void> {
  const r = await call<any>('file', 'exec', { command, params });
  if (r && typeof r.code === 'number' && r.code !== 0) {
    throw new Error(text(r.stderr) || `exit ${r.code}`);
  }
}

/** Send a Wake-on-LAN magic packet (needs `etherwake` on the router). */
export async function wake(mac: string, iface = 'br-lan'): Promise<void> {
  try {
    await execOnce('etherwake', ['-i', iface, mac]);
  } catch {
    // Some builds ship the busybox applet as ether-wake instead.
    await execOnce('ether-wake', ['-i', iface, mac]);
  }
}
