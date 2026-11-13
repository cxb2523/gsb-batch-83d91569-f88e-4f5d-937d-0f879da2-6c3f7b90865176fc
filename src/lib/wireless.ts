// Wireless config read/write via the uci ubus object.
import { call, uciSet, uciDelete, uciApplyRollback } from './ubus';

export type WBand = '5' | '24' | '6' | '?';

export interface WifiRadio {
  id: string;        // wifi-device section (e.g. radio0)
  band: WBand;
  bandLabel: string;
  disabled: boolean;
  channel: string;   // 'auto' or a number
  htmode: string;
  // primary AP interface on this radio
  ifaceId: string;   // wifi-iface section (e.g. default_radio0)
  ssid: string;
  encryption: string;
  key: string;
  hidden: boolean;
  // advanced
  country: string;    // regulatory domain (wifi-device), e.g. US, DE, IN
  txpower: string;    // '' = driver max, else dBm (wifi-device)
  roaming: boolean;   // 802.11r fast transition (wifi-iface ieee80211r)
  wmm: boolean;       // Wi-Fi Multimedia / QoS (wifi-iface wmm)
  isolate: boolean;   // block client-to-client traffic (wifi-iface isolate)
}

const BAND_LABEL: Record<WBand, string> = { '5': '5 GHz', '24': '2.4 GHz', '6': '6 GHz', '?': 'Wi-Fi' };
const truthy = (v: unknown) => v === '1' || v === 1 || v === true;

function normBand(dev: any): WBand {
  const b = String(dev.band ?? '').toLowerCase();
  if (b.includes('6')) return '6';
  if (b.includes('5')) return '5';
  if (b.includes('2')) return '24';
  const hw = String(dev.hwmode ?? '').toLowerCase();
  if (hw.includes('a')) return '5';
  if (hw.includes('g') || hw.includes('b')) return '24';
  const ch = parseInt(String(dev.channel ?? '0'), 10);
  if (ch >= 36) return '5';
  if (ch > 0) return '24';
  return '?';
}

export async function loadWireless(): Promise<WifiRadio[]> {
  const r = await call<any>('uci', 'get', { config: 'wireless' });
  const values = r?.values ?? r ?? {};
  const devices: any[] = [];
  const ifaces: any[] = [];
  for (const [name, s] of Object.entries<any>(values)) {
    if (!s || typeof s !== 'object') continue;
    if (s['.type'] === 'wifi-device') devices.push({ __name: name, ...s });
    else if (s['.type'] === 'wifi-iface') ifaces.push({ __name: name, ...s });
  }
  return devices.map((dev) => {
    const ap =
      ifaces.find((i) => i.device === dev.__name && (i.mode === 'ap' || !i.mode)) ||
      ifaces.find((i) => i.device === dev.__name);
    const band = normBand(dev);
    return {
      id: dev.__name,
      band,
      bandLabel: BAND_LABEL[band],
      disabled: truthy(dev.disabled),
      channel: String(dev.channel ?? 'auto'),
      htmode: String(dev.htmode ?? ''),
      ifaceId: ap?.__name ?? '',
      ssid: ap?.ssid ?? '',
      encryption: ap?.encryption ?? 'none',
      key: ap?.key ?? '',
      hidden: truthy(ap?.hidden),
      country: String(dev.country ?? ''),
      txpower: String(dev.txpower ?? ''),
      roaming: truthy(ap?.ieee80211r),
      wmm: ap?.wmm === undefined ? true : truthy(ap?.wmm),
      isolate: truthy(ap?.isolate)
    };
  });
}

export async function saveWireless(r: WifiRadio): Promise<void> {
  if (r.ifaceId) {
    await uciSet('wireless', r.ifaceId, {
      ssid: r.ssid,
      encryption: r.encryption,
      key: r.encryption === 'none' ? '' : r.key,
      hidden: r.hidden ? '1' : '0',
      wmm: r.wmm ? '1' : '0',
      isolate: r.isolate ? '1' : '0',
      ieee80211r: r.roaming ? '1' : '0'
    });
    if (r.roaming) {
      // 802.11r needs a mobility domain shared across APs; '4f57' must match the
      // value the mesh helper writes (openwrt/files-mesh/.../untangled.mesh) so
      // roaming works between core-configured and mesh-configured APs.
      await uciSet('wireless', r.ifaceId, { mobility_domain: '4f57', ft_over_ds: '0', ft_psk_generate_local: '1' });
    }
  }
  const dev: Record<string, unknown> = { disabled: r.disabled ? '1' : '0', channel: r.channel, htmode: r.htmode };
  if (r.country.trim()) dev.country = r.country.trim().toUpperCase();
  await uciSet('wireless', r.id, dev);
  // txpower: set when given, otherwise clear so the driver uses its maximum.
  if (r.txpower.trim()) await uciSet('wireless', r.id, { txpower: r.txpower.trim() });
  else await uciDelete('wireless', r.id, 'txpower').catch(() => {});
  await uciApplyRollback();
}

export const ENC_OPTIONS = [
  { v: 'sae', label: 'WPA3-Personal' },
  { v: 'sae-mixed', label: 'WPA2/WPA3-Personal' },
  { v: 'psk2', label: 'WPA2-Personal' },
  { v: 'none', label: 'Open (no password)' }
];

export function channelOptions(band: WBand, current: string): string[] {
  const base =
    band === '5'
      ? ['auto', '36', '40', '44', '48', '149', '153', '157', '161']
      : band === '6'
        ? ['auto', '1', '5', '9', '13', '17', '21']
        : ['auto', '1', '6', '11', '2', '3', '4', '5', '7', '8', '9', '10'];
  if (current && !base.includes(current)) base.splice(1, 0, current);
  return base;
}

export function htmodeOptions(current: string): string[] {
  const base = ['HT20', 'HT40', 'VHT20', 'VHT40', 'VHT80', 'VHT160', 'HE20', 'HE40', 'HE80', 'HE160'];
  if (current && !base.includes(current)) base.unshift(current);
  return base;
}

export function pwStrength(k: string): { label: string; color: string } {
  if (k.length < 8) return { label: 'Weak', color: 'var(--crit)' };
  if (k.length < 12) return { label: 'Fair', color: 'var(--warn)' };
  return { label: 'Strong', color: 'var(--good)' };
}
