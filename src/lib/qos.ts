// Smart Queue (QoS) via sqm-scripts. One `config queue` per WAN interface in
// /etc/config/sqm, running a CAKE/HTB shaper at set download/upload rates to
// kill bufferbloat. Rates are the MEASURED line speed (from a speed test, set
// a little below the result), not the advertised plan — otherwise cake polices
// the wrong queue. If sqm-scripts isn't installed the read fails and we report
// it unavailable.
import { call, uciGet, uciAdd, uciSet, uciApply } from './ubus';
import { getWan } from './net';

export interface QosQueue {
  id: string | null;     // null = no queue section yet
  interface: string;     // device the shaper attaches to (e.g. eth1, wan)
  enabled: boolean;
  // MEASURED (speed-test) rates, NOT the advertised plan — set a bit below the
  // tested result so cake controls the queue instead of fighting the ISP's.
  downMbps: number;      // 0 = don't limit this direction
  upMbps: number;
  script: string;        // piece_of_cake.qos (simple) | layer_cake.qos (prioritised)
}

export interface QosState {
  installed: boolean;
  wanDevice: string;     // detected WAN device, used as a default interface
  queue: QosQueue;
}

const text = (v: unknown): string => (v == null ? '' : String(Array.isArray(v) ? v[0] : v));
const kbitToMbps = (k: string): number => Math.round((parseInt(k, 10) || 0) / 1000);
const mbpsToKbit = (m: number): string => String(Math.max(0, Math.round(m)) * 1000);

export async function loadQos(): Promise<QosState> {
  const wanDevice = await getWan().then((w) => w.device || 'eth1').catch(() => 'eth1');

  let values: Record<string, any>;
  try {
    const r = await uciGet('sqm');
    values = ((r as any)?.values ?? r ?? {}) as Record<string, any>;
  } catch {
    return {
      installed: false,
      wanDevice,
      queue: { id: null, interface: wanDevice, enabled: false, downMbps: 0, upMbps: 0, script: 'piece_of_cake.qos' }
    };
  }

  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] !== 'queue') continue;
    return {
      installed: true,
      wanDevice,
      queue: {
        id,
        interface: text(s.interface) || wanDevice,
        enabled: text(s.enabled) === '1',
        downMbps: kbitToMbps(text(s.download)),
        upMbps: kbitToMbps(text(s.upload)),
        script: text(s.script) || 'piece_of_cake.qos'
      }
    };
  }
  // sqm installed but no queue configured yet.
  return {
    installed: true,
    wanDevice,
    queue: { id: null, interface: wanDevice, enabled: false, downMbps: 0, upMbps: 0, script: 'piece_of_cake.qos' }
  };
}

export async function saveQos(q: QosQueue): Promise<void> {
  const values: Record<string, unknown> = {
    interface: q.interface,
    enabled: q.enabled ? '1' : '0',
    download: mbpsToKbit(q.downMbps),
    upload: mbpsToKbit(q.upMbps),
    qdisc: 'cake',
    script: q.script,
    linklayer: 'none'
  };
  if (q.id) await uciSet('sqm', q.id, values);
  else await uciAdd('sqm', 'queue', undefined, values);
  await uciApply();
  // Restart the shaper so the new rates take effect immediately.
  await call('file', 'exec', { command: '/etc/init.d/sqm', params: ['restart'] }).catch(() => {});
}
