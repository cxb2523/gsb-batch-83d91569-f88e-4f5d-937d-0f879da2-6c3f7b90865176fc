// Dual WAN (mwan3): use two internet connections for failover or load
// balancing. This is a *simplified* front-end — saving rewrites a clean,
// known-good mwan3 config for the two chosen interfaces. Degrades to "not
// installed" when mwan3 is absent.
import { call, uciGet, uciSet, uciAdd, uciDelete, uciApply } from './ubus';

export type DualMode = 'off' | 'failover' | 'balance';

export interface WanIf { name: string; proto: string; }

export interface DualWanState {
  installed: boolean;
  mode: DualMode;
  primary: string;
  backup: string;
  candidates: WanIf[];
}

const text = (v: unknown): string => (v == null ? '' : String(Array.isArray(v) ? v[0] : v));

async function wanCandidates(): Promise<WanIf[]> {
  const r = await uciGet('network').catch(() => ({} as any));
  const v = (r as any)?.values ?? r ?? {};
  const out: WanIf[] = [];
  for (const [id, s] of Object.entries<any>(v)) {
    if (s?.['.type'] !== 'interface') continue;
    const name = text(s['.name']) || id;
    if (name === 'loopback' || name === 'lan') continue;
    const proto = text(s.proto);
    if (!['dhcp', 'pppoe', 'static', 'dhcpv6', 'wwan', 'qmi', 'ncm'].includes(proto) && !/^wan/i.test(name)) continue;
    out.push({ name, proto: proto || '?' });
  }
  return out;
}

export async function loadDualWan(): Promise<DualWanState> {
  const candidates = await wanCandidates();
  const guessPrimary = candidates[0]?.name ?? 'wan';
  const guessBackup = candidates.find((c) => c.name !== guessPrimary)?.name ?? '';

  let values: Record<string, any>;
  try {
    const r = await uciGet('mwan3');
    values = ((r as any)?.values ?? r ?? {}) as Record<string, any>;
  } catch {
    return { installed: false, mode: 'off', primary: guessPrimary, backup: guessBackup, candidates };
  }

  // Best-effort read of our generated shape.
  const members = Object.values<any>(values).filter((s) => s?.['.type'] === 'member');
  const enabledIf = Object.values<any>(values)
    .filter((s) => s?.['.type'] === 'interface' && text(s.enabled) === '1')
    .map((s) => text(s['.name']));

  if (enabledIf.length < 2 || members.length < 2) {
    return { installed: true, mode: 'off', primary: guessPrimary, backup: guessBackup, candidates };
  }
  // Mode from member metrics: equal => balance, different => failover.
  const metrics = members.map((m) => parseInt(text(m.metric) || '1', 10));
  const mode: DualMode = new Set(metrics).size === 1 ? 'balance' : 'failover';
  const sorted = members.slice().sort((a, b) => (parseInt(text(a.metric) || '1') - parseInt(text(b.metric) || '1')));
  return {
    installed: true,
    mode,
    primary: text(sorted[0]?.interface) || guessPrimary,
    backup: text(sorted[1]?.interface) || guessBackup,
    candidates
  };
}

function ifaceSection() {
  return {
    enabled: '1', family: 'ipv4',
    track_ip: ['8.8.8.8', '1.1.1.1'],
    track_method: 'ping',
    reliability: '1', count: '1', timeout: '2', interval: '5',
    down: '3', up: '3'
  };
}

export async function saveDualWan(mode: DualMode, primary: string, backup: string): Promise<void> {
  // Clear any sections we might have written before (idempotent rewrite).
  const r = await uciGet('mwan3').catch(() => ({} as any));
  const v = (r as any)?.values ?? r ?? {};
  for (const [id, s] of Object.entries<any>(v)) {
    const t = s?.['.type'];
    if (t === 'member' || t === 'policy' || t === 'rule') await uciDelete('mwan3', id).catch(() => {});
    if (t === 'interface') await uciSet('mwan3', id, { enabled: '0' }).catch(() => {});
  }

  if (mode !== 'off' && primary && backup) {
    // Recreate the two interface sections cleanly. Delete first so uciAdd
    // always produces a well-formed, correctly-typed section (a plain uciSet
    // on a missing named section can leave it untyped on some uci builds).
    for (const name of [primary, backup]) {
      await uciDelete('mwan3', name).catch(() => {});
      await uciAdd('mwan3', 'interface', name, ifaceSection());
    }
    const pm = `${primary}_m`, bm = `${backup}_m`;
    await uciAdd('mwan3', 'member', pm, { interface: primary, metric: '1', weight: '3' });
    await uciAdd('mwan3', 'member', bm, {
      interface: backup,
      metric: mode === 'failover' ? '2' : '1',   // same metric = balance
      weight: '2'
    });
    await uciAdd('mwan3', 'policy', 'untangled_policy', { use_member: [pm, bm] });
    await uciAdd('mwan3', 'rule', 'untangled_default', {
      dest_ip: '0.0.0.0/0', use_policy: 'untangled_policy'
    });
  }

  await uciApply();
  await call('file', 'exec', { command: '/etc/init.d/mwan3', params: ['restart'] }).catch(() => {});
}
