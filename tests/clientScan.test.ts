// Local, router-free checks for the three-source device collection.
//
// Run with:  npm test
// Uses Node's built-in test runner and native TypeScript type stripping, so it
// needs Node 22.18+ (or 23.6+/24). No router, dev server or extra package. Type
// checking stays with `npm run check`; this file is outside its tsconfig scope.
//
// Each case drives `scanClients()` with a hand-built ubus double, so no router
// or dev server is needed. The three cases mirror the ways the collection can
// degrade: everything answers, wireless fails while leases answer, and only
// host hints fail.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scanClients, type ClientScan } from '../src/lib/clientScan.ts';

type Reply = unknown | Error;

/** Minimal ubus double: methods are addressed as "object.method". */
function fakeUbus(replies: Record<string, Reply>, objects: string[] = []) {
  return {
    async call(object: string, method: string) {
      const key = `${object}.${method}`;
      if (!(key in replies)) throw new Error(`not implemented: ${key}`);
      const r = replies[key];
      if (r instanceof Error) throw r;
      return r;
    },
    async listObjects(pattern: string) {
      assert.equal(pattern, 'hostapd.*');
      return Object.fromEntries(objects.map((o) => [o, {}]));
    }
  };
}

const wirelessSucceeds = {
  'network.wireless.status': {
    radio0: { config: { band: '5g', channel: 36 }, interfaces: [{ ifname: 'phy0-ap0' }] },
    radio1: { config: { band: '2g', channel: 6 }, interfaces: [{ ifname: 'phy1-ap0' }] }
  },
  'hostapd.phy0-ap0.get_clients': {
    freq: 5180,
    clients: {
      'AA:BB:CC:00:00:01': { assoc: true, signal: -50 },
      'AA:BB:CC:00:00:DE': { assoc: false, signal: -70 } // stale entry, must be filtered
    }
  },
  'hostapd.phy1-ap0.get_clients': {
    freq: 2437,
    clients: { 'AA:BB:CC:00:00:02': { assoc: true, signal: -72 } }
  }
};

const hintsSucceed = {
  'luci-rpc.getHostHints': {
    'AA:BB:CC:00:00:01': { name: 'Living Room TV', ipv4: '10.1.10.11' },
    'AA:BB:CC:00:00:02': { name: 'Bedroom Speaker', ipv4: '10.1.10.12' },
    'AA:BB:CC:00:00:03': { name: 'Office Printer', ipv4: '10.1.10.13' },
    'AA:BB:CC:00:00:04': { name: 'No Address Yet' }, // no IP -> dropped
    'NOT-A-MAC-ADDR': { name: 'Bogus', ipv4: '10.1.10.99' } // illegal MAC -> dropped
  }
};

const leasesSucceed = {
  'luci-rpc.getDHCPLeases': {
    dhcp_leases: [
      { macaddr: 'AA:BB:CC:00:00:01', ipaddr: '10.1.10.11', hostname: 'tv' },
      { macaddr: 'AA:BB:CC:00:00:02', ipaddr: '10.1.10.12', hostname: 'speaker' },
      { macaddr: 'AA:BB:CC:00:00:03', ipaddr: '10.1.10.13', hostname: '*' },
      { macaddr: 'AA:BB:CC:00:00:DE', ipaddr: '10.1.10.14', hostname: 'stale' }
    ]
  }
};

function byMac(scan: ClientScan) {
  return Object.fromEntries(scan.clients.map((c) => [c.mac, c]));
}
function source(scan: ClientScan, id: string) {
  const s = scan.sources.find((x) => x.id === id);
  assert.ok(s, `source ${id} present`);
  return s!;
}

test('all three sources answer: devices are classified per source', async () => {
  const scan = await scanClients(fakeUbus({ ...hintsSucceed, ...leasesSucceed, ...wirelessSucceeds }));

  // Per-source outcomes.
  assert.deepEqual(scan.sources.map((s) => [s.id, s.ok]), [
    ['hostHints', true], ['leases', true], ['wireless', true]
  ]);
  assert.equal(source(scan, 'wireless').reason, '');
  assert.equal(scan.wifiDiag, '');
  assert.equal(scan.wirelessOk, true);

  const d = byMac(scan);
  // Associated -> band from the radio, link=assoc.
  assert.equal(d['AA:BB:CC:00:00:01'].link, 'assoc');
  assert.equal(d['AA:BB:CC:00:00:01'].band, '5');
  assert.equal(d['AA:BB:CC:00:00:02'].link, 'assoc');
  assert.equal(d['AA:BB:CC:00:00:02'].band, '24');
  // Absent from every association table while wireless answered -> wired.
  assert.equal(d['AA:BB:CC:00:00:03'].link, 'wired');
  assert.equal(d['AA:BB:CC:00:00:03'].band, 'wired');

  // assoc:false is not associated; it is still in the table (lease) but not wireless.
  assert.equal(d['AA:BB:CC:00:00:DE'].link, 'wired');
  // Illegal MAC and no-IP devices are dropped.
  assert.equal(scan.clients.length, 4);
  assert.ok(!scan.clients.some((c) => c.mac.includes('NOT') || c.name === 'No Address Yet'));
  // Sorted by name. Leases are merged after host hints, so a lease hostname wins.
  assert.deepEqual(scan.clients.map((c) => c.name), ['Office Printer', 'speaker', 'stale', 'tv']);
});

test('wireless hostapd and iwinfo both fail, leases succeed: devices survive and are Unknown, not Wired', async () => {
  const scan = await scanClients(fakeUbus({
    ...hintsSucceed,
    ...leasesSucceed,
    'network.wireless.status': { radio0: { config: { band: '5g' }, interfaces: [{ ifname: 'phy0-ap0' }] } },
    'hostapd.phy0-ap0.get_clients': new Error('ubus status 4 (NOT_FOUND)'),
    'iwinfo.assoclist': new Error('ubus status 4 (NOT_FOUND)')
  }));

  const wifi = source(scan, 'wireless');
  assert.equal(wifi.ok, false);
  assert.match(wifi.reason, /hostapd\.phy0-ap0/);
  assert.match(wifi.reason, /iwinfo assoclist phy0-ap0/);
  assert.equal(scan.wirelessOk, false);
  // "First problem" semantics, still populated for the Network Map hint.
  assert.equal(scan.wifiDiag, wifi.reason);

  // Host hints and leases still populated the table.
  assert.equal(source(scan, 'hostHints').ok, true);
  assert.equal(source(scan, 'leases').ok, true);
  assert.ok(scan.clients.length >= 3);

  // Nothing may claim Wired when the wireless subsystem did not answer.
  assert.ok(scan.clients.every((c) => c.link === 'unknown'));
  assert.ok(scan.clients.every((c) => c.band === '?'));
});

test('host hints fail, leases and wireless succeed: table and wired/assoc verdicts survive', async () => {
  const scan = await scanClients(fakeUbus({
    'luci-rpc.getHostHints': new Error('ubus status 6 (PERMISSION_DENIED)'),
    ...leasesSucceed,
    ...wirelessSucceeds
  }));

  const hints = source(scan, 'hostHints');
  assert.equal(hints.ok, false);
  assert.match(hints.reason, /getHostHints failed/);
  assert.match(hints.reason, /PERMISSION_DENIED/);

  const d = byMac(scan);
  // Devices come from leases alone, with lease hostnames.
  assert.equal(d['AA:BB:CC:00:00:01'].name, 'tv');
  assert.equal(d['AA:BB:CC:00:00:01'].ip, '10.1.10.11');
  // Wireless verdicts still apply.
  assert.equal(d['AA:BB:CC:00:00:01'].link, 'assoc');
  assert.equal(d['AA:BB:CC:00:00:03'].link, 'wired');
  // '*' hostname is not a device name.
  assert.notEqual(d['AA:BB:CC:00:00:03'].name, '*');
  assert.equal(source(scan, 'wireless').ok, true);
  assert.equal(scan.wifiDiag, '');
});

test('interface names fall back to ubus list hostapd.* when network.wireless status fails', async () => {
  const scan = await scanClients(
    fakeUbus({
      ...hintsSucceed,
      ...leasesSucceed,
      'network.wireless.status': new Error('ubus status 4 (NOT_FOUND)'),
      'hostapd.phy0-ap0.get_clients': {
        freq: 5180,
        clients: { 'AA:BB:CC:00:00:01': { assoc: true, signal: -55 } }
      }
    }, ['hostapd.phy0-ap0'])
  );

  const wifi = source(scan, 'wireless');
  assert.equal(wifi.ok, true);
  assert.match(wifi.detail, /interfaces from ubus list hostapd\.\*/);
  assert.equal(byMac(scan)['AA:BB:CC:00:00:01'].band, '5'); // freq fallback
  assert.equal(byMac(scan)['AA:BB:CC:00:00:03'].link, 'wired');
});

test('a partially answering wireless source reports success with the failed interface in detail', async () => {
  const scan = await scanClients(fakeUbus({
    ...hintsSucceed,
    ...leasesSucceed,
    'network.wireless.status': {
      radio0: { config: { band: '5g' }, interfaces: [{ ifname: 'phy0-ap0' }] },
      radio1: { config: { band: '2g' }, interfaces: [{ ifname: 'phy1-ap0' }] }
    },
    'hostapd.phy0-ap0.get_clients': { clients: {} },
    'hostapd.phy1-ap0.get_clients': new Error('ubus timeout'),
    'iwinfo.assoclist': new Error('iwinfo module not installed')
  }));

  const wifi = source(scan, 'wireless');
  assert.equal(wifi.ok, true);
  assert.equal(wifi.reason, '');
  assert.match(wifi.detail, /1\/2 interfaces answered/);
  assert.match(wifi.detail, /some interfaces failed: .*phy1-ap0/);
  // Wireless succeeded, so absence from the table is still a genuine wired verdict.
  assert.equal(byMac(scan)['AA:BB:CC:00:00:03'].link, 'wired');
});
