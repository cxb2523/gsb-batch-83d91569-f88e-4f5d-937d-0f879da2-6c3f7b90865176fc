import { call, uciSet, uciApply } from './ubus';

// On-device "safety" services. Each maps to a package's uci config; if the
// package isn't installed, the config read fails and we mark it unavailable.
export interface Feature {
  id: string;
  label: string;
  desc: string;
  pkg: string;
  config: string;
  section: string;
  option: string;
  installed: boolean;
  enabled: boolean;
  link?: string;   // for services run from their own UI (e.g. AdGuard Home)
}

const DEFS: Omit<Feature, 'installed' | 'enabled'>[] = [
  { id: 'adblock', label: 'Block ads & trackers', desc: 'Removes most ads and hidden trackers for every device.', pkg: 'adblock', config: 'adblock', section: 'global', option: 'adb_enabled' },
  { id: 'banip', label: 'Block dangerous sites', desc: 'Blocks known malicious and abuse IPs using threat feeds.', pkg: 'banip', config: 'banip', section: 'global', option: 'ban_enabled' }
];

function findGlobal(values: any, type: string): { id: string; s: any } | null {
  for (const [id, s] of Object.entries<any>(values ?? {})) {
    if (s?.['.type'] === type) return { id, s };
  }
  return null;
}

export async function loadProtection(): Promise<Feature[]> {
  const out: Feature[] = [];
  for (const d of DEFS) {
    try {
      const r = await call<any>('uci', 'get', { config: d.config });
      const g = findGlobal(r?.values, d.config);
      const section = g?.id ?? d.section;
      const enabled = (g?.s?.[d.option] ?? '0') === '1';
      out.push({ ...d, section, installed: true, enabled });
    } catch {
      out.push({ ...d, installed: false, enabled: false });
    }
  }
  out.push(await loadAdGuard());
  return out;
}

// AdGuard Home runs its own daemon and web UI (default :3000), so it's not a
// UCI toggle like adblock/banip. Detect it via its `adguardhome` uci config and
// link out to its interface rather than show a switch that couldn't control it.
async function loadAdGuard(): Promise<Feature> {
  const base: Omit<Feature, 'installed' | 'enabled'> = {
    id: 'adguardhome', label: 'AdGuard Home', pkg: 'adguardhome',
    desc: 'Network-wide DNS ad & tracker blocking, managed in its own dashboard.',
    config: 'adguardhome', section: 'config', option: 'enabled',
    link: `${location.protocol}//${location.hostname}:3000/`
  };
  try {
    const r = await call<any>('uci', 'get', { config: 'adguardhome' });
    const g = findGlobal(r?.values, 'adguardhome');
    return { ...base, installed: true, enabled: (g?.s?.enabled ?? '1') === '1' };
  } catch {
    return { ...base, installed: false, enabled: false };
  }
}

export async function setFeature(f: Feature, on: boolean): Promise<void> {
  await uciSet(f.config, f.section, { [f.option]: on ? '1' : '0' });
  await uciApply();
}
