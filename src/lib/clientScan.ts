// Pure device-collection logic: merge host hints, DHCP leases and wireless
// association data into one device table while recording how each source
// fared. Kept free of ubus/Svelte imports so it can be exercised against fake
// ubus replies in tests/clientScan.test.ts.

export type DeviceKind =
  | 'd-phone' | 'd-laptop' | 'd-desktop' | 'd-tv' | 'd-game'
  | 'd-speaker' | 'd-tablet' | 'd-printer' | 'd-router' | 'd-cloud' | 'd-generic';
export type Band = '5' | '24' | '6' | 'wired' | '?';

/** How a device's connection was determined.
 *  - `assoc`:   present in the wireless association table.
 *  - `wired`:   absent from it, but the wireless subsystem answered, so we can
 *               trust that the device is not associated over Wi-Fi.
 *  - `unknown`: the wireless subsystem did not answer; we cannot tell whether
 *               the device is wired or wireless, so it must not be shown as
 *               Wired. */
export type ClientLink = 'assoc' | 'wired' | 'unknown';

export interface Client {
  id: string; name: string; mac: string; ip: string;
  kind: DeviceKind; band: Band; signal: number;
  link: ClientLink;
}

export type SourceId = 'hostHints' | 'leases' | 'wireless';

/** Outcome of one collection source for this scan. */
export interface SourceStatus {
  id: SourceId;
  /** Short name for the UI ("Host hints"). */
  label: string;
  /** The ubus method(s) that back this source. */
  endpoint: string;
  ok: boolean;
  /** Human-readable failure cause; '' when ok. */
  reason: string;
  /** Records this source contributed (devices, leases or associations). */
  count: number;
  /** Extra context: transport used, partial per-interface failures, etc. */
  detail: string;
}

export interface ClientScan {
  clients: Client[];
  sources: SourceStatus[];
  /** First wireless problem, '' when the wireless source succeeded. This keeps
   *  the historical `wifiDiag` ("show the first problem") semantics. */
  wifiDiag: string;
  /** True when at least one wireless interface answered. */
  wirelessOk: boolean;
}

/** The slice of the ubus client this module needs. */
export interface UbusLike {
  call(object: string, method: string, params?: Record<string, unknown>): Promise<any>;
  listObjects(pattern: string): Promise<Record<string, unknown>>;
}

const num = (x: unknown): number => (typeof x === 'number' ? x : 0);

function errText(e: unknown): string {
  if (e instanceof Error) return e.message || e.name;
  return String(e ?? 'unknown error');
}

// ---- device kind heuristics ------------------------------------------------
const NAME_RULES: [RegExp, DeviceKind][] = [
  [/iphone|galaxy|pixel|phone|oneplus|xiaomi|redmi/i, 'd-phone'],
  [/ipad|tablet|\btab\b/i, 'd-tablet'],
  [/macbook|laptop|thinkpad|notebook/i, 'd-laptop'],
  [/imac|desktop|workstation|\bpc\b/i, 'd-desktop'],
  [/\btv\b|roku|firetv|chromecast|appletv|bravia|shield/i, 'd-tv'],
  [/playstation|\bps[45]\b|xbox|nintendo|switch/i, 'd-game'],
  [/echo|alexa|homepod|sonos|speaker/i, 'd-speaker'],
  [/printer|epson|canon|brother/i, 'd-printer']
];
function guessKind(name: string): DeviceKind {
  for (const [re, k] of NAME_RULES) if (re.test(name)) return k;
  return 'd-generic';
}

// ---- band / signal helpers -------------------------------------------------
// Resolve a radio's band from the `network.wireless status` object. OpenWRT
// reports it as `config.band` = "2g"/"5g"/"6g" on 21.02+, older builds use
// `config.hwmode` (11a/11g/…), and as a last resort we infer from the channel.
function radioBand(radio: any): Band {
  const cfg = radio?.config ?? {};
  const b = String(cfg.band ?? '').toLowerCase();
  if (b.includes('6')) return '6';
  if (b.includes('5')) return '5';
  if (b.includes('2')) return '24';
  const hw = String(cfg.hwmode ?? '').toLowerCase();
  if (hw.includes('a')) return '5'; // 11a/11ac/11ax-5
  if (hw.includes('g') || hw.includes('b')) return '24';
  const ch = num(cfg.channel);
  if (ch >= 36) return '5';
  if (ch > 0) return '24';
  return '?';
}
function bandFromFreq(mhz: number): Band {
  if (mhz >= 5925) return '6';
  if (mhz >= 4900) return '5';
  if (mhz >= 2400) return '24';
  return '?';
}
function dbmToBars(dbm: number): number {
  if (dbm >= -55) return 4;
  if (dbm >= -66) return 3;
  if (dbm >= -77) return 2;
  return dbm ? 1 : 0;
}

const MAC_RE = /^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i;

const SOURCE_META: Record<SourceId, { label: string; endpoint: string }> = {
  hostHints: { label: 'Host hints', endpoint: 'luci-rpc getHostHints' },
  leases: { label: 'DHCP leases', endpoint: 'luci-rpc getDHCPLeases' },
  wireless: { label: 'Wireless associations', endpoint: 'hostapd.<ifname> get_clients → iwinfo assoclist' }
};

function sourceStatus(
  id: SourceId, ok: boolean, reason: string, count: number, detail = ''
): SourceStatus {
  return { id, ...SOURCE_META[id], ok, reason, count, detail };
}

// ---- source 1: host hints --------------------------------------------------
interface HintsResult { map: Record<string, any>; status: SourceStatus }

async function readHostHints(ubus: UbusLike): Promise<HintsResult> {
  try {
    const r = await ubus.call('luci-rpc', 'getHostHints');
    if (!r || typeof r !== 'object') throw new Error('reply was not a host map');
    const map = r as Record<string, any>;
    return { map, status: sourceStatus('hostHints', true, '', Object.keys(map).length) };
  } catch (e) {
    return {
      map: {},
      status: sourceStatus('hostHints', false, `luci-rpc getHostHints failed: ${errText(e)}`, 0)
    };
  }
}

// ---- source 2: DHCP leases -------------------------------------------------
interface LeasesResult { list: any[]; status: SourceStatus }

async function readLeases(ubus: UbusLike): Promise<LeasesResult> {
  try {
    const r = await ubus.call('luci-rpc', 'getDHCPLeases');
    if (!r || typeof r !== 'object') throw new Error('reply was not an object');
    const list = Array.isArray(r) ? r : Array.isArray((r as any).dhcp_leases) ? (r as any).dhcp_leases : null;
    if (!list) throw new Error('reply had no dhcp_leases list');
    return { list, status: sourceStatus('leases', true, '', list.length) };
  } catch (e) {
    return {
      list: [],
      status: sourceStatus('leases', false, `luci-rpc getDHCPLeases failed: ${errText(e)}`, 0)
    };
  }
}

// ---- source 3: wireless associations --------------------------------------
interface WirelessResult {
  map: Record<string, { band: Band; signal: number }>;
  status: SourceStatus;
  ok: boolean;
  /** First problem, used for `wifiDiag`. */
  firstProblem: string;
}

/** Read `hostapd.<ifname> get_clients`; returns null on success, else the
 *  readable problem. Clients with `assoc === false` are not associated and are
 *  deliberately dropped. */
async function readHostapd(
  ubus: UbusLike, ifname: string, band: Band,
  map: Record<string, { band: Band; signal: number }>
): Promise<string | null> {
  try {
    const r = await ubus.call('hostapd.' + ifname, 'get_clients');
    if (!r || typeof r !== 'object' || !r.clients || typeof r.clients !== 'object') {
      throw new Error('reply had no clients map');
    }
    const b: Band = band !== '?' ? band : bandFromFreq(num(r.freq));
    for (const [mac, c] of Object.entries<any>(r.clients)) {
      if (c?.assoc === false) continue;
      map[mac.toUpperCase()] = { band: b, signal: c?.signal != null ? dbmToBars(num(c.signal)) : 3 };
    }
    return null;
  } catch (e) {
    return `hostapd.${ifname}: ${errText(e)}`;
  }
}

/** Fallback `iwinfo assoclist`; returns null on success, else the problem. */
async function readIwinfo(
  ubus: UbusLike, ifname: string, band: Band,
  map: Record<string, { band: Band; signal: number }>
): Promise<string | null> {
  try {
    const al = await ubus.call('iwinfo', 'assoclist', { device: ifname });
    if (!al || !Array.isArray(al.results)) throw new Error('reply had no results list');
    for (const r of al.results) {
      if (r?.mac) map[String(r.mac).toUpperCase()] = { band, signal: dbmToBars(num(r.signal)) };
    }
    return null;
  } catch (e) {
    return `iwinfo assoclist ${ifname}: ${errText(e)}`;
  }
}

// Interface names come from `network.wireless status`; when that yields none we
// fall back to listing the hostapd.* ubus objects directly.
async function scanWireless(ubus: UbusLike): Promise<WirelessResult> {
  const map: Record<string, { band: Band; signal: number }> = {};
  const ifaces: { ifname: string; band: Band }[] = [];
  const problems: string[] = [];

  try {
    const status = await ubus.call('network.wireless', 'status');
    const radios = status && typeof status === 'object'
      ? Object.values(status as Record<string, any>)
      : [];
    if (!radios.length) problems.push('network.wireless status returned no radios');
    for (const radio of radios) {
      const band = radioBand(radio);
      for (const iface of (radio as any)?.interfaces ?? []) {
        // ifname sits directly on the interface or under its config, by build.
        const ifname = iface?.ifname || iface?.config?.ifname || iface?.iface;
        if (ifname) ifaces.push({ ifname: String(ifname), band });
      }
    }
    if (radios.length && !ifaces.length) {
      problems.push('network.wireless reported no radio interfaces');
    }
  } catch (e) {
    problems.push(`network.wireless status: ${errText(e)}`);
  }

  let discoveredBy = 'network.wireless status';
  if (!ifaces.length) {
    try {
      const objects = await ubus.listObjects('hostapd.*');
      for (const name of Object.keys(objects ?? {})) {
        if (name.startsWith('hostapd.')) {
          ifaces.push({ ifname: name.slice('hostapd.'.length), band: '?' });
        }
      }
      if (ifaces.length) discoveredBy = 'ubus list hostapd.*';
      else problems.push('ubus list hostapd.* found no access points');
    } catch (e) {
      problems.push(`ubus list hostapd.*: ${errText(e)}`);
    }
  }

  // Walk interfaces sequentially so the first problem (and therefore
  // `wifiDiag`) is deterministic across scans.
  const transports = new Set<'hostapd' | 'iwinfo'>();
  let answered = 0;
  for (const { ifname, band } of ifaces) {
    const hostapdProblem = await readHostapd(ubus, ifname, band, map);
    if (!hostapdProblem) { answered++; transports.add('hostapd'); continue; }
    const iwinfoProblem = await readIwinfo(ubus, ifname, band, map);
    if (!iwinfoProblem) { answered++; transports.add('iwinfo'); continue; }
    problems.push(`${hostapdProblem}; ${iwinfoProblem}`);
  }

  const ok = answered > 0;
  const via = [...transports]
    .map((t) => (t === 'iwinfo' ? 'iwinfo assoclist' : 'hostapd get_clients'))
    .join(' + ');
  const base = ifaces.length
    ? `${answered}/${ifaces.length} interface${ifaces.length === 1 ? '' : 's'} answered${via ? ` via ${via}` : ''}`
    : 'no wireless interfaces discovered';
  const discoveryNote = discoveredBy === 'network.wireless status'
    ? ''
    : `interfaces from ${discoveredBy}`;
  const detailParts = [[base, discoveryNote].filter(Boolean).join(' · ')];
  if (ok && problems.length) {
    detailParts.push(`some interfaces failed: ${problems.join('; ')}`);
  } else if (!ok && problems.length > 1) {
    detailParts.push(problems.slice(1).join('; '));
  }

  const firstProblem = problems[0] ?? (ifaces.length
    ? 'no wireless interface answered'
    : 'no wireless interfaces found');
  return {
    map,
    ok,
    firstProblem,
    status: sourceStatus('wireless', ok, ok ? '' : firstProblem, Object.keys(map).length,
      detailParts.join(' · '))
  };
}

// ---- merge -----------------------------------------------------------------
/**
 * Collect the device table from the three sources. Each source records its own
 * outcome and never rejects: a failed source contributes nothing but the other
 * two still populate the table, so devices seen by a healthy source survive.
 */
export async function scanClients(ubus: UbusLike): Promise<ClientScan> {
  const [hints, leases, wireless] = await Promise.all([
    readHostHints(ubus),
    readLeases(ubus),
    scanWireless(ubus)
  ]);

  const assoc = wireless.map;
  const wifiOk = wireless.ok;

  const byMac = new Map<string, Client>();
  const put = (mac: string, patch: Partial<Client>) => {
    if (!MAC_RE.test(mac)) return; // illegal MAC: drop
    const m = mac.toUpperCase();
    const cur =
      byMac.get(m) ??
      ({ id: m.replace(/:/g, ''), name: '', mac: m, ip: '', kind: 'd-generic', band: '?', signal: 0, link: 'unknown' } as Client);
    byMac.set(m, {
      ...cur,
      ...patch,
      name: patch.name || cur.name,
      ip: patch.ip || cur.ip
    });
  };

  for (const [mac, h] of Object.entries<any>(hints.map ?? {})) {
    put(mac, { name: h?.name || h?.host || '', ip: h?.ipv4 || h?.ipaddrs?.[0] || '' });
  }
  for (const l of leases.list) {
    if (l?.macaddr) put(l.macaddr, { name: l.hostname && l.hostname !== '*' ? l.hostname : '', ip: l.ipaddr || '' });
  }

  const out: Client[] = [];
  for (const c of byMac.values()) {
    const a = assoc[c.mac];
    const name = c.name || c.ip || c.mac;
    let link: ClientLink, band: Band, signal: number;
    if (a) {
      link = 'assoc'; band = a.band; signal = a.signal;
    } else if (wifiOk) {
      // The wireless subsystem answered and this device is absent from every
      // association table, so "wired" is a real finding.
      link = 'wired'; band = 'wired'; signal = 4;
    } else {
      // Wireless could not be read: do NOT claim wired. Band stays Unknown.
      link = 'unknown'; band = '?'; signal = 0;
    }
    out.push({ ...c, name, kind: guessKind(name), band, signal, link });
  }

  const clients = out.filter((c) => c.ip).sort((a, b) => a.name.localeCompare(b.name));

  return {
    clients,
    sources: [hints.status, leases.status, wireless.status],
    wifiDiag: wireless.ok ? '' : wireless.firstProblem,
    wirelessOk: wireless.ok
  };
}
