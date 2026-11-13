// Extend Wi-Fi: scan for upstream networks and join one as a client.
// (Sharing that connection with the LAN uses relayd — see the screen's note.)
import { call, uciGet, uciSet, uciAdd, uciApply } from './ubus';
import { loadWireless } from './wireless';

export interface ScanResult { ssid: string; signal: number; locked: boolean; bssid: string; }

function dbmToBars(dbm: number): number {
  if (dbm >= -55) return 4;
  if (dbm >= -66) return 3;
  if (dbm >= -77) return 2;
  return dbm ? 1 : 0;
}

export async function scan(): Promise<ScanResult[]> {
  const radios = await loadWireless();
  const st = await call<any>('network.wireless', 'status').catch(() => ({}));
  let dev = '';
  for (const radio of Object.values<any>(st ?? {})) {
    const i = (radio?.interfaces ?? [])[0];
    if (i?.ifname) { dev = i.ifname; break; }
  }
  if (!dev && radios[0]) dev = radios[0].id;
  const r = await call<any>('iwinfo', 'scan', { device: dev });
  const map = new Map<string, ScanResult>();
  for (const x of r?.results ?? []) {
    const ssid = x.ssid || '(hidden)';
    const res: ScanResult = { ssid, signal: dbmToBars(x.signal ?? 0), locked: !!x?.encryption?.enabled, bssid: x.bssid || '' };
    const e = map.get(ssid);
    if (!e || res.signal > e.signal) map.set(ssid, res);
  }
  return [...map.values()].sort((a, b) => b.signal - a.signal);
}

export async function joinNetwork(ssid: string, key: string): Promise<void> {
  const radios = await loadWireless();
  const device = radios[0]?.id ?? 'radio0';
  await uciAdd('network', 'interface', 'wwan', { proto: 'dhcp' }).catch(() => {});

  // Reuse an existing STA iface on this radio instead of stacking a new one
  // each time join is called (which would leave duplicate client interfaces).
  const wl = await uciGet('wireless').catch(() => ({} as any));
  const wv = (wl as any)?.values ?? wl ?? {};
  let staId: string | null = null;
  for (const [id, s] of Object.entries<any>(wv)) {
    if (s?.['.type'] === 'wifi-iface' && s.mode === 'sta') { staId = id; break; }
  }
  const cfg = {
    device,
    mode: 'sta',
    network: 'wwan',
    ssid,
    encryption: key ? 'psk2' : 'none',
    key
  };
  if (staId) await uciSet('wireless', staId, cfg);
  else await uciAdd('wireless', 'wifi-iface', undefined, cfg);
  await uciApply();
}
