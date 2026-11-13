import { call, uciSet, uciApply } from './ubus';

export interface SysCfg { id: string; hostname: string; timezone: string; zonename: string; }

export async function loadSystem(): Promise<SysCfg> {
  const r = await call<any>('uci', 'get', { config: 'system' });
  const values = r?.values ?? {};
  for (const [id, s] of Object.entries<any>(values)) {
    if (s?.['.type'] === 'system') {
      return { id, hostname: s.hostname ?? 'OpenWrt', timezone: s.timezone ?? 'UTC', zonename: s.zonename ?? 'UTC' };
    }
  }
  return { id: '@system[0]', hostname: 'OpenWrt', timezone: 'UTC', zonename: 'UTC' };
}

export async function saveSystem(c: SysCfg): Promise<void> {
  await uciSet('system', c.id, { hostname: c.hostname, timezone: c.timezone, zonename: c.zonename });
  await uciApply();
}

/** Set the router (root) password. Needs rpcd-mod-luci on the device. */
export async function setPassword(password: string): Promise<void> {
  await call('luci', 'setPassword', { username: 'root', password });
}

/** Reboot via the file.exec method (rpcd-mod-file, ACL-gated). */
export async function reboot(): Promise<void> {
  await call('file', 'exec', { command: '/sbin/reboot' });
}

// ---- Scheduled reboot (a cron line we own, marked for safe round-tripping) --
const CRON_PATH = '/etc/crontabs/root';
const CRON_MARK = '# untangled-reboot';

export interface RebootSchedule {
  enabled: boolean;
  hour: number;    // 0–23
  minute: number;  // 0–59
  day: string;     // cron day-of-week: '*' = every day, '0'(Sun)…'6'(Sat)
}

async function readCron(): Promise<string> {
  try {
    const r = await call<any>('file', 'read', { path: CRON_PATH });
    return typeof r?.data === 'string' ? r.data : '';
  } catch {
    return '';
  }
}

export async function loadRebootSchedule(): Promise<RebootSchedule> {
  const line = (await readCron()).split('\n').find((l) => l.includes(CRON_MARK));
  const def: RebootSchedule = { enabled: false, hour: 4, minute: 0, day: '*' };
  if (!line) return def;
  // minute hour dom month dow  cmd
  const m = line.trim().match(/^(\d+)\s+(\d+)\s+\S+\s+\S+\s+(\S+)/);
  if (!m) return { ...def, enabled: true };
  return { enabled: true, minute: +m[1], hour: +m[2], day: m[3] };
}

export async function saveRebootSchedule(s: RebootSchedule): Promise<void> {
  const kept = (await readCron())
    .split('\n')
    .filter((l) => l.trim() && !l.includes(CRON_MARK));
  if (s.enabled) {
    // Clamp every field before it reaches the crontab file: these are the only
    // values interpolated into a line written as root, so a bad value must not
    // be able to inject extra cron fields or a command.
    const min = Math.min(59, Math.max(0, Math.trunc(Number(s.minute) || 0)));
    const hr = Math.min(23, Math.max(0, Math.trunc(Number(s.hour) || 0)));
    const dow = /^[0-6]$/.test(String(s.day)) ? String(s.day) : '*';
    kept.push(`${min} ${hr} * * ${dow} /sbin/reboot ${CRON_MARK}`);
  }
  await call('file', 'write', { path: CRON_PATH, data: kept.join('\n') + '\n', mode: 600 });
  // Make sure crond is enabled and picks up the change.
  await call('file', 'exec', { command: '/etc/init.d/cron', params: ['enable'] }).catch(() => {});
  await call('file', 'exec', { command: '/etc/init.d/cron', params: ['restart'] }).catch(() => {});
}

// ---- Default page: make http://router/ open UnTangled ----------------------
// uhttpd's index_page is an ordered list; our package ships /www/untangled-home.html
// (a redirect to /untangled/). Putting it first makes "/" land on UnTangled while
// /untangled/ still serves its own index.html. LuCI's files are never touched.
const HOME = 'untangled-home.html';

async function indexPages(): Promise<string[]> {
  const r = await call<any>('uci', 'get', { config: 'uhttpd', section: 'main', option: 'index_page' }).catch(() => null);
  return ([] as string[]).concat(r?.value ?? []);
}

export async function loadDefaultPage(): Promise<boolean> {
  return (await indexPages()).includes(HOME);
}

export async function setDefaultPage(on: boolean): Promise<void> {
  const rest = (await indexPages()).filter((v) => v !== HOME);
  // Only our entry moves; a user's own index list is preserved.
  const list = on ? [HOME, ...(rest.length ? rest : ['index.html'])] : rest;
  if (list.length && !(list.length === 1 && list[0] === 'index.html')) {
    await uciSet('uhttpd', 'main', { index_page: list });
  } else {
    await call('uci', 'delete', { config: 'uhttpd', section: 'main', option: 'index_page' }).catch(() => {});
  }
  await uciApply();
  await call('file', 'exec', { command: '/etc/init.d/uhttpd', params: ['reload'] }).catch(() => {});
}

// A short, friendly timezone list (POSIX TZ strings). Extend as needed.
export const TIMEZONES: { zonename: string; timezone: string }[] = [
  { zonename: 'UTC', timezone: 'UTC' },
  { zonename: 'Europe/London', timezone: 'GMT0BST,M3.5.0/1,M10.5.0' },
  { zonename: 'Europe/Berlin', timezone: 'CET-1CEST,M3.5.0,M10.5.0/3' },
  { zonename: 'Asia/Kolkata', timezone: 'IST-5:30' },
  { zonename: 'Asia/Dhaka', timezone: 'BDT-6' },
  { zonename: 'Asia/Singapore', timezone: '+08' },
  { zonename: 'America/New_York', timezone: 'EST5EDT,M3.2.0,M11.1.0' },
  { zonename: 'America/Los_Angeles', timezone: 'PST8PDT,M3.2.0,M11.1.0' }
];
