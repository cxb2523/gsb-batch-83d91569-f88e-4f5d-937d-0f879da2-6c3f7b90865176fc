// UPnP / NAT-PMP (miniupnpd). Lets games and apps open their own inbound ports
// automatically. One `config upnpd` section in /etc/config/upnpd. Degrades to
// "not installed" when miniupnpd isn't present.
import { call, uciGet, uciSet, uciAdd, uciApply } from './ubus';

export interface UpnpState {
  installed: boolean;
  id: string;        // section id ('config' by default)
  enabled: boolean;
  secure: boolean;   // secure_mode: only let a device map ports to itself
}

const truthy = (v: unknown) => v === '1' || v === 1 || v === true;

function findCfg(values: any): { id: string; s: any } | null {
  for (const [id, s] of Object.entries<any>(values ?? {})) {
    if (s?.['.type'] === 'upnpd') return { id, s };
  }
  return null;
}

export async function loadUpnp(): Promise<UpnpState> {
  try {
    const r = await uciGet('upnpd');
    const v = (r as any)?.values ?? r ?? {};
    const g = findCfg(v);
    if (!g) return { installed: true, id: 'config', enabled: false, secure: true };
    return {
      installed: true,
      id: g.id,
      enabled: truthy(g.s.enabled) || truthy(g.s.enable_upnp),
      secure: g.s.secure_mode === undefined ? true : truthy(g.s.secure_mode)
    };
  } catch {
    return { installed: false, id: 'config', enabled: false, secure: true };
  }
}

async function ensureSection(state: UpnpState): Promise<string> {
  // If miniupnpd has no config section yet, create the canonical one.
  const r = await uciGet('upnpd').catch(() => ({} as any));
  const v = (r as any)?.values ?? r ?? {};
  if (findCfg(v)) return state.id;
  await uciAdd('upnpd', 'upnpd', 'config', {
    enabled: '0', secure_mode: '1', enable_natpmp: '1', enable_upnp: '1',
    internal_iface: 'lan', external_iface: 'wan', log_output: '0'
  });
  return 'config';
}

export async function saveUpnp(state: UpnpState): Promise<void> {
  const id = await ensureSection(state);
  await uciSet('upnpd', id, {
    enabled: state.enabled ? '1' : '0',
    enable_upnp: state.enabled ? '1' : '0',
    enable_natpmp: state.enabled ? '1' : '0',
    secure_mode: state.secure ? '1' : '0'
  });
  await uciApply();
  await call('file', 'exec', { command: '/etc/init.d/miniupnpd', params: [state.enabled ? 'restart' : 'stop'] }).catch(() => {});
  if (state.enabled) await call('file', 'exec', { command: '/etc/init.d/miniupnpd', params: ['enable'] }).catch(() => {});
}
