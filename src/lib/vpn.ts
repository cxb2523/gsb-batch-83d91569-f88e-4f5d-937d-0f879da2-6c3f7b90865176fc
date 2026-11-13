// VPN: WireGuard (interfaces + peers) and OpenVPN (instances), covering both
// a SERVER role (let devices in) and a CLIENT role (dial out to a provider).
//   WireGuard  -> /etc/config/network  (proto 'wireguard' + wireguard_<iface> peers)
//   OpenVPN    -> /etc/config/openvpn  (one section per instance; .ovpn via file 'config')
import { call, uciSet, uciAdd, uciDelete, uciApply } from './ubus';

const truthy = (v: unknown) => v === '1' || v === 1 || v === true;
function toArr(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String);
  if (typeof v === 'string' && v.trim()) return v.trim().split(/\s+/);
  return [];
}
function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'vpn';
}

export type Role = 'server' | 'client' | 'unknown';

export interface WgPeer { id: string; description: string; publicKey: string; endpoint: string; allowedIps: string[]; }
export interface WgIface {
  id: string; name: string; role: Role;
  disabled: boolean; addresses: string[]; listenPort: string; peers: WgPeer[];
}
export interface OvpnInstance { id: string; name: string; role: Role; enabled: boolean; }

export interface VpnState { wg: WgIface[]; ovpn: OvpnInstance[]; }

export async function loadVpn(): Promise<VpnState> {
  const net = await call<any>('uci', 'get', { config: 'network' });
  const values = net?.values ?? net ?? {};
  const wg: WgIface[] = [];
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] === 'interface' && s.proto === 'wireguard') {
      wg.push({ id, name: id, role: 'server', disabled: truthy(s.disabled), addresses: toArr(s.addresses), listenPort: String(s.listen_port ?? ''), peers: [] });
    }
  }
  for (const [id, s] of Object.entries<any>(values)) {
    const t = String(s?.['.type'] ?? '');
    if (!t.startsWith('wireguard_')) continue;
    const parent = wg.find((w) => w.name === t.slice('wireguard_'.length));
    if (parent) {
      const endpoint = s.endpoint_host ? `${s.endpoint_host}:${s.endpoint_port ?? '51820'}` : '';
      parent.peers.push({ id, description: s.description ?? '', publicKey: s.public_key ?? '', endpoint, allowedIps: toArr(s.allowed_ips) });
    }
  }
  // a WG interface whose peer has an endpoint is dialing out -> client
  for (const w of wg) if (w.peers.some((p) => p.endpoint)) w.role = 'client';

  let ovpn: OvpnInstance[] = [];
  try {
    const o = await call<any>('uci', 'get', { config: 'openvpn' });
    const ov = o?.values ?? {};
    for (const [id, s] of Object.entries<any>(ov)) {
      if (s?.['.type'] !== 'openvpn') continue;
      const role: Role = truthy(s.client) || s.config ? 'client' : s.server || s.server_bridge ? 'server' : 'unknown';
      ovpn.push({ id, name: s.name || id, role, enabled: s.enabled !== '0' });
    }
  } catch { /* openvpn package not installed */ }

  return { wg, ovpn };
}

// ---- WireGuard server peers ----
export async function setWgEnabled(id: string, enabled: boolean): Promise<void> {
  await uciSet('network', id, { disabled: enabled ? '0' : '1' });
  await uciApply();
}
export async function addPeer(ifaceName: string, description: string, publicKey: string, allowedIp: string): Promise<void> {
  await uciAdd('network', `wireguard_${ifaceName}`, undefined, {
    description, public_key: publicKey, allowed_ips: [allowedIp], route_allowed_ips: '1'
  });
  await uciApply();
}
export async function deletePeer(id: string): Promise<void> {
  await uciDelete('network', id);
  await uciApply();
}

// ---- OpenVPN instances ----
export async function setOvpnEnabled(id: string, enabled: boolean): Promise<void> {
  await uciSet('openvpn', id, { enabled: enabled ? '1' : '0' });
  await uciApply();
}
export async function deleteOvpn(id: string): Promise<void> {
  await uciDelete('openvpn', id);
  await uciApply();
}

// ---- Client: add an outbound connection ----
/** Import an OpenVPN client profile: write the .ovpn and register an instance. */
export async function addOvpnClient(name: string, ovpnText: string): Promise<void> {
  const file = `/etc/openvpn/${slug(name)}.ovpn`;
  await call('file', 'write', { path: file, data: ovpnText, mode: 384 /* 0600 */ });
  await uciAdd('openvpn', 'openvpn', slug(name), { enabled: '1', config: file });
  await uciApply();
}

/** Parse a wg-quick config and create a WireGuard client interface + peer. */
export async function addWgClient(name: string, wgQuick: string): Promise<void> {
  const get = (re: RegExp) => (wgQuick.match(re)?.[1] ?? '').trim();
  const privateKey = get(/PrivateKey\s*=\s*(.+)/i);
  const address = get(/Address\s*=\s*(.+)/i);
  const publicKey = get(/PublicKey\s*=\s*(.+)/i);
  const endpoint = get(/Endpoint\s*=\s*(.+)/i);
  const allowed = get(/AllowedIPs\s*=\s*(.+)/i) || '0.0.0.0/0';
  if (!privateKey || !publicKey) throw new Error('Not a valid WireGuard config');
  const ifn = `vpnc_${slug(name)}`.slice(0, 15);
  const [host, port] = endpoint.split(':');
  await uciAdd('network', 'interface', ifn, {
    proto: 'wireguard',
    private_key: privateKey,
    addresses: address.split(',').map((s) => s.trim()).filter(Boolean)
  });
  await uciAdd('network', `wireguard_${ifn}`, undefined, {
    description: name,
    public_key: publicKey,
    endpoint_host: host || '',
    endpoint_port: port || '51820',
    allowed_ips: allowed.split(',').map((s) => s.trim()).filter(Boolean),
    route_allowed_ips: '1',
    persistent_keepalive: '25'
  });
  await uciApply();
}
