import { call, uciSet, uciApplyRollback } from './ubus';

export interface LanCfg {
  ipaddr: string; netmask: string;
  dhcp: boolean; start: string; limit: string; leasetime: string;
}

export async function loadLan(): Promise<LanCfg> {
  const [n, d] = await Promise.all([
    call<any>('uci', 'get', { config: 'network', section: 'lan' }).catch(() => ({ values: {} })),
    call<any>('uci', 'get', { config: 'dhcp', section: 'lan' }).catch(() => ({ values: {} }))
  ]);
  const nv = n?.values ?? {};
  const dv = d?.values ?? {};
  return {
    ipaddr: nv.ipaddr ?? '192.168.1.1',
    netmask: nv.netmask ?? '255.255.255.0',
    dhcp: dv.ignore !== '1',
    start: String(dv.start ?? '100'),
    limit: String(dv.limit ?? '150'),
    leasetime: String(dv.leasetime ?? '12h')
  };
}

export async function saveLan(c: LanCfg): Promise<void> {
  await uciSet('network', 'lan', { ipaddr: c.ipaddr, netmask: c.netmask });
  await uciSet('dhcp', 'lan', { ignore: c.dhcp ? '0' : '1', start: c.start, limit: c.limit, leasetime: c.leasetime });
  await uciApplyRollback();
}
