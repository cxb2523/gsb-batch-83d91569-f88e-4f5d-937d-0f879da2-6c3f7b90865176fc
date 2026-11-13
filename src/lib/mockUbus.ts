// Dev-only mock ubus backend.
//
// When enabled, `call()` in ubus.ts routes here instead of doing a real
// POST /ubus — so the UI can be driven without an OpenWRT router. It returns
// the same `[status, data]` shapes the real router does (ubus status 0 = OK),
// so callers and the net.ts normalizers are exercised exactly as in prod.
//
// Enabled only when BOTH hold:
//   • import.meta.env.DEV  (Vite dev; always false in production builds)
//   • VITE_MOCK !== 'false' (so you can opt out with VITE_MOCK=false npm run dev
//                            to hit a real router through the /ubus proxy)
// This file is tree-shaken out of production builds since the guard is a
// compile-time constant there.

// Dev-only: `?wan=10.122.5.9` on the URL simulates a CGNAT/private WAN address.
const MOCK_WAN_IP = (typeof location !== 'undefined' && new URLSearchParams(location.search).get('wan')) || '203.0.113.47';

export const MOCK_ENABLED =
  import.meta.env.DEV && import.meta.env.VITE_MOCK !== 'false';

// ---- seed: ~31 devices spread realistically across bands -------------------
// band tags map to net.ts radioBand()/assoclist expectations:
//   5 GHz / 2.4 GHz come from iwinfo assoclist (with a signal in dBm),
//   wired devices are simply absent from every assoclist.
type Seed = { name: string; kind: string; band: '5' | '24' | 'wired'; dbm?: number };

const SEED: Seed[] = [
  // 5 GHz (12)
  { name: 'Living Room Apple TV', kind: 'tv', band: '5', dbm: -48 },
  { name: "Krish's iPhone 15", kind: 'phone', band: '5', dbm: -52 },
  { name: "Maya's MacBook Pro", kind: 'laptop', band: '5', dbm: -57 },
  { name: 'Office iMac', kind: 'desktop', band: '5', dbm: -45 },
  { name: 'iPad Pro', kind: 'tablet', band: '5', dbm: -61 },
  { name: 'PlayStation 5', kind: 'game', band: '5', dbm: -55 },
  { name: 'Bedroom Roku', kind: 'tv', band: '5', dbm: -66 },
  { name: "Sam's Pixel 8", kind: 'phone', band: '5', dbm: -59 },
  { name: 'Studio Mac mini', kind: 'desktop', band: '5', dbm: -50 },
  { name: 'Galaxy Tab S9', kind: 'tablet', band: '5', dbm: -63 },
  { name: 'Nintendo Switch', kind: 'game', band: '5', dbm: -70 },
  { name: "Work ThinkPad", kind: 'laptop', band: '5', dbm: -54 },
  // 2.4 GHz (13) — IoT-heavy, weaker signals
  { name: 'Kitchen Echo Dot', kind: 'speaker', band: '24', dbm: -68 },
  { name: 'Bedroom HomePod', kind: 'speaker', band: '24', dbm: -72 },
  { name: 'Sonos One', kind: 'speaker', band: '24', dbm: -65 },
  { name: 'Nest Thermostat', kind: 'generic', band: '24', dbm: -74 },
  { name: 'Front Door Cam', kind: 'generic', band: '24', dbm: -79 },
  { name: 'Backyard Cam', kind: 'generic', band: '24', dbm: -81 },
  { name: 'Garage Door', kind: 'generic', band: '24', dbm: -77 },
  { name: 'Hue Bridge', kind: 'generic', band: '24', dbm: -60 },
  { name: 'Smart Plug Lamp', kind: 'generic', band: '24', dbm: -73 },
  { name: 'Robot Vacuum', kind: 'generic', band: '24', dbm: -76 },
  { name: 'Bathroom Scale', kind: 'generic', band: '24', dbm: -83 },
  { name: 'Old Android Phone', kind: 'phone', band: '24', dbm: -70 },
  { name: 'Kids Fire Tablet', kind: 'tablet', band: '24', dbm: -75 },
  // Wired (6)
  { name: 'Home Server (NAS)', kind: 'desktop', band: 'wired' },
  { name: 'Living Room TV', kind: 'tv', band: 'wired' },
  { name: 'Office Printer', kind: 'printer', band: 'wired' },
  { name: 'Desktop PC', kind: 'desktop', band: 'wired' },
  { name: 'Xbox Series X', kind: 'game', band: 'wired' },
  { name: 'Mesh Node (Study)', kind: 'generic', band: 'wired' }
];

function mac(i: number): string {
  const h = (n: number) => n.toString(16).padStart(2, '0');
  return `DE:AD:BE:${h((i >> 8) & 0xff)}:${h(i & 0xff)}:${h((i * 37) & 0xff)}`.toUpperCase();
}
function ip(i: number): string {
  return `10.1.10.${100 + i}`;
}

// Precompute the device table once so IDs/IPs/MACs stay stable across the
// 5-second polling refresh (otherwise the map would reshuffle every tick).
const DEVICES = SEED.map((s, i) => ({ ...s, mac: mac(i + 1), ip: ip(i + 1) }));

const now = Math.floor(Date.now() / 1000);
const UPTIME = 6 * 86400 + 4 * 3600 + 23 * 60; // 6d 4h 23m

// ---- per-object mock responses (return the inner `data`; call() wraps it) --
function board() {
  return {
    model: 'UnTangled Demo Router (mock)',
    board_name: 'generic/demo',
    hostname: 'untangled-demo',
    release: { distribution: 'OpenWRT', version: '24.10.0', description: 'OpenWRT 24.10.0 (mock)' }
  };
}

function systemInfo() {
  const total = 512 * 1024 * 1024;
  const free = Math.round(total * 0.38);
  // gentle jitter so the live tiles visibly update each poll
  const jitter = () => 1 + (Math.random() - 0.5) * 0.04;
  return {
    uptime: UPTIME + (Math.floor(Date.now() / 1000) - now),
    load: [Math.round(0.42 * 65536 * jitter()), Math.round(0.37 * 65536), Math.round(0.3 * 65536)],
    memory: { total, free: Math.round(free * jitter()), available: Math.round(free * jitter()) }
  };
}

function interfaceDump() {
  return {
    interface: [
      {
        interface: 'wan',
        up: true,
        proto: 'dhcp',
        l3_device: 'eth1',
        device: 'eth1',
        uptime: UPTIME,
        'ipv4-address': [{ address: MOCK_WAN_IP, mask: 24 }],
        'dns-server': ['1.1.1.1', '8.8.8.8'],
        route: [{ target: '0.0.0.0', mask: 0, nexthop: '203.0.113.1' }]
      },
      { interface: 'lan', up: true, proto: 'static', l3_device: 'br-lan', device: 'br-lan', uptime: UPTIME },
      { interface: 'loopback', up: true, proto: 'static', l3_device: 'lo', device: 'lo', uptime: UPTIME }
    ]
  };
}

function hostHints() {
  const out: Record<string, { name: string; ipv4: string }> = {};
  for (const d of DEVICES) out[d.mac] = { name: d.name, ipv4: d.ip };
  return out;
}

function dhcpLeases() {
  return {
    dhcp_leases: DEVICES.map((d) => ({
      macaddr: d.mac,
      ipaddr: d.ip,
      hostname: d.name,
      expires: 43200
    }))
  };
}

// Two radios; each advertises one interface we can "assoclist".
function wirelessStatus() {
  return {
    radio0: { config: { band: '5g', channel: 36 }, interfaces: [{ ifname: 'phy0-ap0' }] },
    radio1: { config: { band: '2g', channel: 6 }, interfaces: [{ ifname: 'phy1-ap0' }] }
  };
}

function assoclist(ifname: string) {
  const band = ifname.startsWith('phy0') ? '5' : '24';
  return {
    results: DEVICES.filter((d) => d.band === band).map((d) => ({ mac: d.mac, signal: d.dbm ?? -60 }))
  };
}

/** Return the mock `data` for a given ubus object/method, or undefined if we
 *  don't model it (caller then gets an empty object, matching net.ts catches). */
export function mockCall(object: string, method: string, params: Record<string, unknown>): unknown {
  const key = `${object}.${method}`;
  switch (key) {
    case 'session.login':
      return {
        ubus_rpc_session: 'mocksession0000000000000000000000',
        timeout: 3600,
        expires: 3600,
        acls: {},
        data: { username: String(params.username ?? 'root') }
      };
    case 'session.destroy':
      return {};
    case 'system.board':
      return board();
    case 'system.info':
      return systemInfo();
    case 'network.interface.dump':
      return interfaceDump();
    case 'luci-rpc.getHostHints':
      return hostHints();
    case 'luci-rpc.getDHCPLeases':
      return dhcpLeases();
    case 'network.wireless.status':
      return wirelessStatus();
    case 'iwinfo.assoclist':
      return assoclist(String(params.device ?? ''));
    default:
      // Unknown object: behave like NO_DATA so callers fall back gracefully.
      return {};
  }
}
