import { call, uciSet, uciDelete, uciApply } from './ubus';

// Simplified IPv6 control: enable/disable the IPv6 WAN, and choose how the LAN
// hands out IPv6 (off / server / relay). Maps to network.wan6 + dhcp.lan ra/dhcpv6.
// In server mode the router can also announce specific IPv6 DNS servers to
// clients (RA + DHCPv6) via the dhcp.lan `dns` list; empty = announce itself.
export interface Ipv6Cfg { wanEnabled: boolean; lanMode: string; hasWan6: boolean; dns: string[]; }

/** Normalize a UCI value that may be a string or an array into string[]. */
function toList(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(String).filter(Boolean);
  if (typeof v === 'string' && v.trim()) return v.trim().split(/\s+/);
  return [];
}

export async function loadIpv6(): Promise<Ipv6Cfg> {
  const [w, d] = await Promise.all([
    call<any>('uci', 'get', { config: 'network', section: 'wan6' }).catch(() => null),
    call<any>('uci', 'get', { config: 'dhcp', section: 'lan' }).catch(() => ({ values: {} }))
  ]);
  const wv = w?.values ?? null;
  const dv = d?.values ?? {};
  return {
    hasWan6: !!wv,
    wanEnabled: wv ? wv.disabled !== '1' : true,
    lanMode: String(dv.ra ?? dv.dhcpv6 ?? 'server'),
    dns: toList(dv.dns)
  };
}

export async function saveIpv6(c: Ipv6Cfg): Promise<void> {
  if (c.hasWan6) await uciSet('network', 'wan6', { disabled: c.wanEnabled ? '0' : '1' }).catch(() => {});
  const mode = c.lanMode; // 'server' | 'relay' | 'disabled'
  // Announced IPv6 DNS servers only apply in server mode; clear the list
  // otherwise so a mode switch doesn't leave stale entries behind.
  const dns = mode === 'server' ? c.dns.map((s) => s.trim()).filter(Boolean) : [];
  if (dns.length) {
    await uciSet('dhcp', 'lan', { ra: mode, dhcpv6: mode, dns });
  } else {
    // Writing an empty list leaves a bogus empty element, so set the modes and
    // remove the option entirely instead (same pattern as the WAN DNS field).
    await uciSet('dhcp', 'lan', { ra: mode, dhcpv6: mode });
    await uciDelete('dhcp', 'lan', 'dns').catch(() => {});
  }
  await uciApply();
}
