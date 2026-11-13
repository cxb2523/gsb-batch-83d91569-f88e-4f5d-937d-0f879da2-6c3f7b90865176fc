export interface NavItem {
  id: string;
  label: string;
  icon: string;
  soon?: boolean;
}
export interface NavGroup {
  label: string;
  items: NavItem[];
}

export const nav: NavGroup[] = [
  {
    label: 'General',
    items: [
      { id: 'map', label: 'Network Map', icon: 'i-map' },
      { id: 'devices', label: 'Devices', icon: 'i-clients' },
      { id: 'guest', label: 'Guest Network', icon: 'i-guest' },
      { id: 'traffic', label: 'Traffic Monitor', icon: 'i-qos' },
      { id: 'usage', label: 'Usage History', icon: 'i-qos' },
      { id: 'parental', label: 'Parental Controls', icon: 'i-kids' },
      { id: 'extend', label: 'Extend Wi-Fi', icon: 'i-ext' },
      { id: 'aiprotect', label: 'Network Protection', icon: 'i-shield' }
    ]
  },
  {
    label: 'Advanced Settings',
    items: [
      { id: 'wireless', label: 'Wireless', icon: 'i-wifi' },
      { id: 'wan', label: 'Internet (WAN)', icon: 'i-wan' },
      { id: 'ddns', label: 'Dynamic DNS', icon: 'i-wan' },
      { id: 'qos', label: 'QoS (Smart Queue)', icon: 'i-qos' },
      { id: 'dualwan', label: 'Dual WAN', icon: 'i-wan' },
      { id: 'upnp', label: 'UPnP', icon: 'i-port' },
      { id: 'portfwd', label: 'Port Forwarding', icon: 'i-port' },
      { id: 'vpn', label: 'VPN', icon: 'i-vpn' },
      { id: 'tailscale', label: 'Tailscale', icon: 'i-vpn' },
      { id: 'lan', label: 'LAN', icon: 'i-lan' },
      { id: 'ipv6', label: 'IPv6', icon: 'i-ipv6' },
      { id: 'firewall', label: 'Firewall', icon: 'i-fire' },
      { id: 'dmz', label: 'DMZ', icon: 'i-port' },
      { id: 'admin', label: 'Administration', icon: 'i-admin' },
      { id: 'log', label: 'System Log', icon: 'i-log' }
    ]
  },
  {
    label: 'System',
    items: [
      { id: 'usb', label: 'USB Storage', icon: 'i-pkg' },
      { id: 'firmware', label: 'Firmware', icon: 'i-power' },
      { id: 'software', label: 'Software', icon: 'i-pkg' }
    ]
  }
];

export const titles: Record<string, string> = Object.fromEntries(
  nav.flatMap((g) => g.items.map((i) => [i.id, i.label]))
);
