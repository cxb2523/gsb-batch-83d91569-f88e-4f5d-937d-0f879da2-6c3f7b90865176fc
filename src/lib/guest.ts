// Guest Wi-Fi: manage guest wifi-ifaces, and provision the full stack on first use.
import { call, uciSet, uciAdd, uciApply } from './ubus';
import { loadWireless } from './wireless';

const truthy = (v: unknown) => v === '1' || v === 1 || v === true;

export interface GuestNet {
  ifaceId: string;
  ssid: string;
  key: string;
  encryption: string;
  disabled: boolean;
  isolate: boolean;
  device: string;
  bandLabel: string;
}

export async function loadGuests(): Promise<GuestNet[]> {
  const [wl, radios] = await Promise.all([call<any>('uci', 'get', { config: 'wireless' }), loadWireless()]);
  const bandByDev: Record<string, string> = {};
  for (const r of radios) bandByDev[r.id] = r.bandLabel;
  const values = wl?.values ?? wl ?? {};
  const out: GuestNet[] = [];
  for (const [name, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'wifi-iface') continue;
    const net = String(s.network ?? '');
    const isGuest = net.startsWith('guest') || /guest/i.test(String(s.ssid ?? ''));
    if (!isGuest) continue;
    out.push({
      ifaceId: name,
      ssid: s.ssid ?? '',
      key: s.key ?? '',
      encryption: s.encryption ?? 'psk2',
      disabled: truthy(s.disabled),
      isolate: truthy(s.isolate),
      device: String(s.device ?? ''),
      bandLabel: bandByDev[String(s.device ?? '')] ?? 'Wi-Fi'
    });
  }
  return out;
}

export async function saveGuest(g: GuestNet): Promise<void> {
  await uciSet('wireless', g.ifaceId, {
    ssid: g.ssid,
    key: g.encryption === 'none' ? '' : g.key,
    encryption: g.encryption,
    disabled: g.disabled ? '1' : '0',
    isolate: g.isolate ? '1' : '0'
  });
  await uciApply();
}

/**
 * Best-effort provisioning of a standard isolated guest network:
 * a /24 guest interface + DHCP + a firewall zone that can reach the internet
 * but not the LAN, and a guest SSID on the first radio.
 * Verify on-device; drivers/bridge naming vary slightly by target.
 */
export async function createGuest(ssid = 'OpenWrt-Guest', key = 'guest-wifi-1234'): Promise<void> {
  // 1) network interface (netifd auto-bridges the attached wifi as br-guest)
  await uciAdd('network', 'interface', 'guest', {
    proto: 'static',
    ipaddr: '192.168.3.1',
    netmask: '255.255.255.0'
  });
  // 2) DHCP pool for guests
  await uciAdd('dhcp', 'dhcp', 'guest', {
    interface: 'guest',
    start: '100',
    limit: '150',
    leasetime: '12h'
  });
  // 3) firewall zone + internet forwarding + allow DHCP/DNS from guests
  await uciAdd('firewall', 'zone', 'guest', {
    name: 'guest',
    network: ['guest'],
    input: 'REJECT',
    output: 'ACCEPT',
    forward: 'REJECT'
  });
  await uciAdd('firewall', 'forwarding', undefined, { src: 'guest', dest: 'wan' });
  await uciAdd('firewall', 'rule', undefined, {
    name: 'Guest-DHCP-DNS',
    src: 'guest',
    proto: ['tcp', 'udp'],
    dest_port: '53 67 68',
    target: 'ACCEPT'
  });
  // 4) guest SSID on the first radio
  const radios = await loadWireless();
  if (radios[0]) {
    await uciAdd('wireless', 'wifi-iface', undefined, {
      device: radios[0].id,
      mode: 'ap',
      network: 'guest',
      ssid,
      encryption: 'psk2',
      key,
      isolate: '1'
    });
  }
  await uciApply();
}
