// Dynamic DNS (ddns-scripts). Keeps a hostname pointed at your changing public
// IP. Each entry is a `config service` in /etc/config/ddns. If ddns-scripts
// isn't installed the config read fails and we report it as unavailable.
import { call, uciGet, uciAdd, uciSet, uciDelete, uciApply } from './ubus';

export interface DdnsService {
  id: string;
  name: string;      // section name (e.g. myddns_ipv4)
  provider: string;  // service_name
  hostname: string;  // lookup_host / domain
  username: string;
  enabled: boolean;
}

export interface DdnsState {
  installed: boolean;
  services: DdnsService[];
}

// A short list of common providers (service_name values ddns-scripts ships).
export const DDNS_PROVIDERS: { value: string; label: string }[] = [
  { value: 'duckdns.org', label: 'DuckDNS' },
  { value: 'dynv6.com', label: 'dynv6' },
  { value: 'noip.com', label: 'No-IP' },
  { value: 'dyn.com', label: 'Dyn' },
  { value: 'cloudflare.com-v4', label: 'Cloudflare' },
  { value: 'freedns.afraid.org', label: 'FreeDNS (afraid.org)' },
  { value: 'google.com', label: 'Google Domains' }
];

const text = (v: unknown): string => (v == null ? '' : String(Array.isArray(v) ? v[0] : v));

export async function loadDdns(): Promise<DdnsState> {
  let values: Record<string, any>;
  try {
    const r = await uciGet('ddns');
    values = ((r as any)?.values ?? r ?? {}) as Record<string, any>;
  } catch {
    return { installed: false, services: [] };
  }
  const services: DdnsService[] = [];
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'service') continue;
    services.push({
      id,
      name: text(s['.name']) || id,
      provider: text(s.service_name),
      hostname: text(s.lookup_host) || text(s.domain),
      username: text(s.username),
      enabled: text(s.enabled) === '1'
    });
  }
  return { installed: true, services };
}

async function reload(): Promise<void> {
  await call('file', 'exec', { command: '/etc/init.d/ddns', params: ['reload'] }).catch(() => {});
}

export async function setDdnsEnabled(id: string, on: boolean): Promise<void> {
  await uciSet('ddns', id, { enabled: on ? '1' : '0' });
  await uciApply();
  await reload();
}

export interface NewDdns {
  name: string;
  provider: string;
  hostname: string;
  username: string;
  password: string;
}

export async function addDdns(d: NewDdns): Promise<void> {
  const name = (d.name || d.hostname).trim().replace(/[^A-Za-z0-9_]+/g, '_').replace(/^_+|_+$/g, '') || 'ddns';
  const values: Record<string, unknown> = {
    enabled: '1',
    service_name: d.provider,
    lookup_host: d.hostname,
    domain: d.hostname,
    username: d.username,
    password: d.password,
    interface: 'wan',
    ip_source: 'network',
    ip_network: 'wan',
    use_https: '1',
    check_interval: '10',
    check_unit: 'minutes'
  };
  await uciAdd('ddns', 'service', name, values);
  await uciApply();
  await reload();
}

export async function deleteDdns(id: string): Promise<void> {
  await uciDelete('ddns', id);
  await uciApply();
  await reload();
}
