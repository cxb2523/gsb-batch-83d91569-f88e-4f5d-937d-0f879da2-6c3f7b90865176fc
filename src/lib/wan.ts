import { call, uciSet, uciDelete, uciApplyRollback } from './ubus';

export interface WanCfg {
  proto: string; username: string; password: string;
  ipaddr: string; netmask: string; gateway: string;
  peerdns: boolean; dns: string;
}

export async function loadWan(): Promise<WanCfg> {
  const r = await call<any>('uci', 'get', { config: 'network', section: 'wan' }).catch(() => ({ values: {} }));
  const v = r?.values ?? r ?? {};
  return {
    proto: v.proto ?? 'dhcp',
    username: v.username ?? '',
    password: v.password ?? '',
    ipaddr: v.ipaddr ?? '',
    netmask: v.netmask ?? '255.255.255.0',
    gateway: v.gateway ?? '',
    peerdns: v.peerdns !== '0',
    dns: Array.isArray(v.dns) ? v.dns.join(' ') : (v.dns ?? '')
  };
}

export async function saveWan(c: WanCfg): Promise<void> {
  const values: Record<string, unknown> = { proto: c.proto, peerdns: c.peerdns ? '1' : '0' };
  if (c.proto === 'pppoe') { values.username = c.username; values.password = c.password; }
  if (c.proto === 'static') { values.ipaddr = c.ipaddr; values.netmask = c.netmask; values.gateway = c.gateway; }
  // Custom DNS only applies when peerdns is off; set it as a uci list, else
  // remove the option entirely (writing '' leaves a bogus empty list element).
  const customDns = !c.peerdns && c.dns.trim() ? c.dns.trim().split(/\s+/) : null;
  if (customDns) values.dns = customDns;
  await uciSet('network', 'wan', values);
  if (!customDns) await uciDelete('network', 'wan', 'dns').catch(() => {});
  await uciApplyRollback();
}
