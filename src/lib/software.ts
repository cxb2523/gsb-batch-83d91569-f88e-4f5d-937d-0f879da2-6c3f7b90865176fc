// Package + firmware info.
//
// The Software screen is read-only: it lists installed packages by running the
// on-device package manager through a path-scoped `file.exec` grant
// (`opkg list-installed` on stable 23.05/24.10/25.x, `apk list --installed` on
// snapshot — apk is snapshot-only). Installing and removing packages is left to
// opkg/apk on the command line. "Notable apps" (tailscale, vnstat, …) are
// flagged so the UI can link to the dedicated screen we have for them.
import { call } from './ubus';

export interface FwInfo { firmware: string; kernel: string; target: string; }
export interface Pkg { name: string; version: string; installed: boolean; notable?: NotableApp; }

export async function getFirmware(): Promise<FwInfo> {
  const b = await call<any>('system', 'board');
  const rel = b?.release ?? {};
  return {
    firmware: rel.description || [rel.distribution, rel.version].filter(Boolean).join(' ') || 'OpenWRT',
    kernel: b?.kernel ?? '',
    target: rel.target ?? ''
  };
}

export interface SoftwareList {
  available: boolean;          // can we install/remove from here?
  managed: boolean;            // did we get a real installed list at all?
  packages: Pkg[];
  message?: string;
}

// Apps we recognise and can point the user at. `screen` is a nav id that has a
// real frontend; `hint` explains what it does when there's no dedicated screen.
export interface NotableApp { id: string; label: string; screen?: string; hint: string; }
const NOTABLE: Record<string, NotableApp> = {
  tailscale: { id: 'tailscale', label: 'Tailscale VPN', screen: 'tailscale', hint: 'Mesh VPN — reach your network from anywhere.' },
  vnstat: { id: 'vnstat', label: 'vnStat', screen: 'usage', hint: 'Internet usage history (see Usage History).' },
  vnstat2: { id: 'vnstat', label: 'vnStat', screen: 'usage', hint: 'Internet usage history (see Usage History).' },
  nlbwmon: { id: 'nlbwmon', label: 'Per-device usage', screen: 'usage', hint: 'Per-device bandwidth accounting (see Usage History).' },
  'sqm-scripts': { id: 'sqm', label: 'Smart Queue (SQM)', screen: 'qos', hint: 'Bufferbloat control (see QoS).' },
  'ddns-scripts': { id: 'ddns', label: 'Dynamic DNS', screen: 'ddns', hint: 'Keep a hostname pointed at your IP (see Dynamic DNS).' },
  mwan3: { id: 'mwan3', label: 'Dual WAN', screen: 'dualwan', hint: 'Multi-WAN failover/balancing (see Dual WAN).' },
  'miniupnpd-nftables': { id: 'upnp', label: 'UPnP', screen: 'upnp', hint: 'Automatic port forwarding (see UPnP).' },
  miniupnpd: { id: 'upnp', label: 'UPnP', screen: 'upnp', hint: 'Automatic port forwarding (see UPnP).' },
  adblock: { id: 'adblock', label: 'Ad/threat blocking', screen: 'aiprotect', hint: 'DNS ad/threat blocking (see Network Protection).' },
  banip: { id: 'banip', label: 'IP blocking', screen: 'aiprotect', hint: 'Threat IP blocking (see Network Protection).' },
  ksmbd: { id: 'ksmbd', label: 'File sharing (SMB)', screen: 'usb', hint: 'Share USB storage over SMB (see USB Storage).' },
  'ksmbd-server': { id: 'ksmbd', label: 'File sharing (SMB)', screen: 'usb', hint: 'Share USB storage over SMB (see USB Storage).' },
  minidlna: { id: 'minidlna', label: 'Media server (DLNA)', screen: 'usb', hint: 'Stream media from USB (see USB Storage).' },
  wireguard: { id: 'wireguard', label: 'WireGuard VPN', screen: 'vpn', hint: 'WireGuard VPN (see VPN).' },
  'wireguard-tools': { id: 'wireguard', label: 'WireGuard VPN', screen: 'vpn', hint: 'WireGuard VPN (see VPN).' },
  'luci-proto-wireguard': { id: 'wireguard', label: 'WireGuard VPN', screen: 'vpn', hint: 'WireGuard VPN (see VPN).' }
};

function notableFor(name: string): NotableApp | undefined {
  if (NOTABLE[name]) return NOTABLE[name];
  // tailscale ships as `tailscale` + `tailscaled`; match the family loosely.
  if (/^tailscale/.test(name)) return NOTABLE.tailscale;
  return undefined;
}

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

// `apk list --installed` -> lines like: "tailscale-1.80.3-r1 x86_64 {tailscale} ..."
function parseApk(out: string): Pkg[] {
  const pkgs: Pkg[] = [];
  for (const line of out.split('\n')) {
    const m = line.trim().match(/^([a-z0-9][a-z0-9._+-]*?)-(\d[^ ]*)\s/i);
    if (!m) continue;
    pkgs.push({ name: m[1], version: m[2], installed: true, notable: notableFor(m[1]) });
  }
  return pkgs;
}

// `opkg list-installed` -> lines like: "tailscale - 1.80.3-1"
function parseOpkg(out: string): Pkg[] {
  const pkgs: Pkg[] = [];
  for (const line of out.split('\n')) {
    const m = line.trim().match(/^(\S+)\s+-\s+(\S+)/);
    if (!m) continue;
    pkgs.push({ name: m[1], version: m[2], installed: true, notable: notableFor(m[1]) });
  }
  return pkgs;
}

async function listViaExec(): Promise<Pkg[] | null> {
  // Try apk first (snapshot only), then fall back to opkg (stable: 23.05 / 24.10
  // / 25.x). apk's installed flag is `--installed` on some builds and `-I` on
  // others, so try both forms before giving up.
  for (const args of [['list', '--installed'], ['list', '-I']]) {
    const apk = await exec('apk', args);
    if (apk) {
      const pkgs = parseApk(apk);
      if (pkgs.length) return pkgs;
    }
  }
  const opkg = await exec('opkg', ['list-installed']);
  if (opkg) {
    const pkgs = parseOpkg(opkg);
    if (pkgs.length) return pkgs;
  }
  return null;
}

export async function listPackages(): Promise<SoftwareList> {
  const installed = await listViaExec();
  if (installed) {
    installed.sort((a, b) => {
      if (!!a.notable !== !!b.notable) return a.notable ? -1 : 1; // notable apps first
      return a.name.localeCompare(b.name);
    });
    return {
      available: false,
      managed: true,
      packages: installed,
      message: 'Packages installed on this router. Install or remove packages with opkg or apk on the router itself.'
    };
  }
  return {
    available: false,
    managed: false,
    packages: [],
    message:
      "Could not read the package list. The router's package manager (opkg/apk) " +
      'did not respond, or the UnTangled ACL does not allow running it.'
  };
}

