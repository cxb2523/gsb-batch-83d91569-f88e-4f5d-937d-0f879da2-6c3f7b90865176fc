// Firewall zones + DMZ, via the uci ubus object (fw4 / nftables on 24.10).
import { call, uciSet, uciAdd, uciDelete, firewallApply } from './ubus';

const truthy = (v: unknown) => v === '1' || v === 1 || v === true;
function toArr(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v === 'string' && v.trim()) return v.trim().split(/\s+/);
  return [];
}

export type Policy = 'ACCEPT' | 'REJECT' | 'DROP';

export interface FwZone {
  id: string;
  name: string;
  input: Policy;
  output: Policy;
  forward: Policy;
  masq: boolean;
  networks: string[];
}
export interface FwForward { id: string; src: string; dest: string; }

export async function loadFirewall(): Promise<{ zones: FwZone[]; forwards: FwForward[] }> {
  const r = await call<any>('uci', 'get', { config: 'firewall' });
  const values = r?.values ?? r ?? {};
  const zones: FwZone[] = [];
  const forwards: FwForward[] = [];
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] === 'zone') {
      zones.push({
        id,
        name: s.name ?? id,
        input: (s.input ?? 'ACCEPT') as Policy,
        output: (s.output ?? 'ACCEPT') as Policy,
        forward: (s.forward ?? 'REJECT') as Policy,
        masq: truthy(s.masq),
        networks: toArr(s.network)
      });
    } else if (s?.['.type'] === 'forwarding') {
      forwards.push({ id, src: s.src ?? '', dest: s.dest ?? '' });
    }
  }
  return { zones, forwards };
}

export async function saveZone(z: FwZone): Promise<void> {
  await uciSet('firewall', z.id, {
    input: z.input,
    output: z.output,
    forward: z.forward,
    masq: z.masq ? '1' : '0'
  });
  await firewallApply(true);
}

// ---- DMZ (a full-cone DNAT of all WAN inbound to one host) -----------------
export interface DmzState { enabled: boolean; host: string; redirectId: string | null; }

export async function loadDmz(): Promise<DmzState> {
  const r = await call<any>('uci', 'get', { config: 'firewall' });
  const values = r?.values ?? r ?? {};
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] === 'redirect' && (s.name === 'DMZ' || s.name === 'dmz' || id === 'dmz')) {
      return { enabled: s.enabled !== '0', host: s.dest_ip ?? '', redirectId: id };
    }
  }
  return { enabled: false, host: '', redirectId: null };
}

export async function setDmz(host: string): Promise<void> {
  const cur = await loadDmz();
  if (cur.redirectId) {
    await uciSet('firewall', cur.redirectId, { dest_ip: host, enabled: '1' });
  } else {
    await uciAdd('firewall', 'redirect', 'dmz', {
      name: 'DMZ',
      src: 'wan',
      dest: 'lan',
      proto: 'all',
      target: 'DNAT',
      dest_ip: host
    });
  }
  await firewallApply(true);
}

export async function clearDmz(): Promise<void> {
  const cur = await loadDmz();
  if (cur.redirectId) {
    await uciDelete('firewall', cur.redirectId);
    await firewallApply();
  }
}

// ---- Port forwarding (DNAT redirects with an external port) ----------------
export interface PortFwd {
  id: string; name: string; proto: string; port: string; destIp: string; enabled: boolean;
}

function protoCanon(v: unknown): string {
  const a = toArr(v).map((x) => x.toLowerCase());
  return a.includes('tcp') && a.includes('udp') ? 'tcp udp' : a[0] || 'tcp';
}
function protoVal(p: string): string | string[] {
  return p === 'tcp udp' ? ['tcp', 'udp'] : p;
}
function isDmzLike(s: any, id: string): boolean {
  return s.name === 'DMZ' || s.name === 'dmz' || id === 'dmz' || (String(s.proto) === 'all' && !s.src_dport);
}

export async function loadPortForwards(): Promise<PortFwd[]> {
  const r = await call<any>('uci', 'get', { config: 'firewall' });
  const values = r?.values ?? r ?? {};
  const out: PortFwd[] = [];
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'redirect') continue;
    if (String(s.target ?? 'DNAT').toUpperCase() !== 'DNAT') continue;
    if (isDmzLike(s, id) || !s.src_dport) continue;
    out.push({
      id,
      name: s.name ?? '',
      proto: protoCanon(s.proto),
      port: String(s.src_dport ?? ''),
      destIp: s.dest_ip ?? '',
      enabled: s.enabled !== '0'
    });
  }
  return out;
}

export async function addPortForward(p: Omit<PortFwd, 'id' | 'enabled'>): Promise<void> {
  await uciAdd('firewall', 'redirect', undefined, {
    name: p.name,
    src: 'wan',
    dest: 'lan',
    target: 'DNAT',
    proto: protoVal(p.proto),
    src_dport: p.port,
    dest_ip: p.destIp,
    dest_port: p.port
  });
  await firewallApply();
}

export async function savePortForward(p: PortFwd): Promise<void> {
  await uciSet('firewall', p.id, {
    name: p.name,
    proto: protoVal(p.proto),
    src_dport: p.port,
    dest_ip: p.destIp,
    dest_port: p.port,
    enabled: p.enabled ? '1' : '0'
  });
  await firewallApply();
}

export async function deletePortForward(id: string): Promise<void> {
  await uciDelete('firewall', id);
  await firewallApply();
}

// ---- Traffic rules (generic `config rule`) ---------------------------------
// Excludes rules owned by other screens (Devices "Block:", Parental "Parental:").
export interface FwRule {
  id: string; name: string; src: string; dest: string;
  proto: string; destPort: string; target: Policy; enabled: boolean;
  srcMac: string; srcIp: string; srcPort: string;
}

function ownedElsewhere(name: string): boolean {
  return name.startsWith('Block:') || name.startsWith('Parental:');
}

export async function loadRules(): Promise<FwRule[]> {
  const r = await call<any>('uci', 'get', { config: 'firewall' });
  const values = r?.values ?? r ?? {};
  const out: FwRule[] = [];
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'rule') continue;
    const name = String(s.name ?? '');
    if (ownedElsewhere(name)) continue;
    out.push({
      id, name,
      src: String(s.src ?? ''), dest: String(s.dest ?? ''),
      proto: protoCanon(s.proto), destPort: String(s.dest_port ?? ''),
      target: (s.target ?? 'ACCEPT') as Policy,
      enabled: s.enabled !== '0',
      srcMac: String(s.src_mac ?? ''), srcIp: String(s.src_ip ?? ''), srcPort: String(s.src_port ?? '')
    });
  }
  return out;
}

function ruleValues(r: Omit<FwRule, 'id'>): Record<string, unknown> {
  const v: Record<string, unknown> = {
    name: r.name, src: r.src, dest: r.dest, target: r.target,
    enabled: r.enabled ? '1' : '0'
  };
  if (r.proto && r.proto !== 'any') v.proto = protoVal(r.proto);
  if (r.destPort) v.dest_port = r.destPort;
  if (r.srcMac) v.src_mac = r.srcMac.toUpperCase();
  if (r.srcIp) v.src_ip = r.srcIp;
  if (r.srcPort) v.src_port = r.srcPort;
  return v;
}

export async function addRule(r: Omit<FwRule, 'id'>): Promise<void> {
  await uciAdd('firewall', 'rule', undefined, ruleValues(r));
  await firewallApply();
}

export async function saveRule(r: FwRule): Promise<void> {
  // Clear optional options when emptied, so edits that remove them take effect.
  await uciSet('firewall', r.id, ruleValues(r));
  if (!r.proto || r.proto === 'any') await uciDelete('firewall', r.id, 'proto').catch(() => {});
  if (!r.destPort) await uciDelete('firewall', r.id, 'dest_port').catch(() => {});
  if (!r.srcMac) await uciDelete('firewall', r.id, 'src_mac').catch(() => {});
  if (!r.srcIp) await uciDelete('firewall', r.id, 'src_ip').catch(() => {});
  if (!r.srcPort) await uciDelete('firewall', r.id, 'src_port').catch(() => {});
  await firewallApply();
}

export async function deleteRule(id: string): Promise<void> {
  await uciDelete('firewall', id);
  await firewallApply();
}
