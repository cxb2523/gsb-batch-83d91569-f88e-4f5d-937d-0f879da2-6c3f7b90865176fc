// Minimal ubus JSON-RPC client for uhttpd-mod-ubus (the /ubus endpoint).
//
// Every call is: POST /ubus  { jsonrpc, id, method:"call", params:[session,obj,method,args] }
// and the reply's `result` is a tuple [status, data] where status 0 === OK.

export const UBUS_URL = '/ubus';
const NULL_SESSION = '00000000000000000000000000000000';

// Dev-only mock backend (tree-shaken from production builds). When enabled,
// every call() is served from in-memory fixtures instead of POST /ubus.
import { MOCK_ENABLED, mockCall } from './mockUbus';
import { session } from './stores';

// The ubus session token. Persisted to sessionStorage so an in-tab reload or
// an iOS/Safari/Firefox tab-discard-and-restore (which wipes JS memory) keeps
// the user signed in; closing the tab still drops it. Router admin tokens are
// short-lived server-side anyway (see login timeout below), so sessionStorage
// is the right scope — not localStorage, which would outlive the tab.
const SESSION_KEY = 'untangled-session';

function loadSession(): string {
  try {
    const id = sessionStorage.getItem(SESSION_KEY);
    if (id && /^[0-9a-f]{32}$/.test(id)) return id;
  } catch { /* storage may be unavailable (private mode, etc.) */ }
  return NULL_SESSION;
}

let sessionId = MOCK_ENABLED ? NULL_SESSION : loadSession();
let rpcId = 1;

export function setSession(id: string) {
  sessionId = id;
  try {
    if (id && id !== NULL_SESSION) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
  } catch { /* storage may be unavailable */ }
}
export function getSession() {
  return sessionId;
}

/**
 * Restore a persisted session on app boot. Returns the username if a token was
 * stored AND is still valid server-side, otherwise null (and clears the token).
 * Called once from App startup before deciding Login vs Shell, so a stale token
 * falls back to the login screen cleanly instead of a half-broken UI.
 */
export async function restoreSession(): Promise<string | null> {
  if (MOCK_ENABLED || sessionId === NULL_SESSION) return null;
  try {
    // `session access` (ACL-granted, no object) succeeds for any live session.
    await call('session', 'access', {});
    // Recover the username from rpcd's own session info for the UI header.
    try {
      const info = await call<{ data?: { username?: string } }>('session', 'get', {});
      return info?.data?.username ?? 'root';
    } catch {
      return 'root';
    }
  } catch {
    setSession(NULL_SESSION);
    return null;
  }
}

// ubus status codes (ubus_msg_status)
const STATUS = [
  'OK', 'INVALID_COMMAND', 'INVALID_ARGUMENT', 'METHOD_NOT_FOUND', 'NOT_FOUND',
  'NO_DATA', 'PERMISSION_DENIED', 'TIMEOUT', 'NOT_SUPPORTED', 'UNKNOWN', 'CONNECTION_FAILED'
];

export class UbusError extends Error {
  constructor(public code: number, message: string) {
    super(message);
    this.name = 'UbusError';
  }
}

export async function call<T = unknown>(
  object: string,
  method: string,
  params: Record<string, unknown> = {}
): Promise<T> {
  // Dev mock: serve from fixtures, skipping the network entirely.
  if (MOCK_ENABLED) {
    await new Promise((r) => setTimeout(r, 120)); // mimic a little latency
    return mockCall(object, method, params) as T;
  }

  const body = {
    jsonrpc: '2.0',
    id: rpcId++,
    method: 'call',
    params: [sessionId, object, method, params]
  };

  const res = await fetch(UBUS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  });
  if (!res.ok) throw new UbusError(-1, `HTTP ${res.status}`);

  const json = await res.json();
  if (json.error) throw await denied(new UbusError(json.error.code ?? -1, json.error.message ?? 'RPC error'), object);

  const result = json.result;
  // Some ubus methods reply with just the data; most reply [status, data].
  if (Array.isArray(result)) {
    const [status, data] = result;
    if (status !== 0) throw await denied(new UbusError(status, STATUS[status] ?? `ubus status ${status}`), object);
    return data as T;
  }
  return result as T;
}

/**
 * A denial (uhttpd's -32002 "Access denied" or rpcd's status 6) means either
 * "the ACL does not allow this" or "the session expired". Tell them apart with
 * one probe: `session access` with no object succeeds for any live session.
 * If the probe fails too, the session is gone: clear it so the login screen
 * shows, and say so instead of leaking a bare permission error.
 */
async function denied(err: UbusError, object: string): Promise<UbusError> {
  const isDenial = err.code === 6 || err.code === -32002;
  if (!isDenial || object === 'session' || sessionId === NULL_SESSION) return err;
  try {
    await call('session', 'access', {});
    return err; // session is fine: a real ACL denial
  } catch {
    setSession(NULL_SESSION);
    session.set({ username: null });
    return new UbusError(err.code, 'Your session expired. Please sign in again.');
  }
}

/** `ubus list <pattern>` over JSON-RPC: object name -> its methods (only those the session may call). */
export async function listObjects(pattern: string): Promise<Record<string, unknown>> {
  if (MOCK_ENABLED) return {};
  const res = await fetch(UBUS_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: rpcId++, method: 'list', params: [sessionId, pattern] })
  });
  if (!res.ok) throw new UbusError(-1, `HTTP ${res.status}`);
  const json = await res.json();
  if (json.error) throw new UbusError(json.error.code ?? -1, json.error.message ?? 'RPC error');
  return (json.result && typeof json.result === 'object' ? json.result : {}) as Record<string, unknown>;
}

export interface LoginResult {
  ubus_rpc_session: string;
  timeout: number;
  expires: number;
  acls: Record<string, unknown>;
  data: { username: string };
}

/** Authenticate against rpcd's session object and keep the returned token.
 *  Request a 1-hour session (rpcd defaults to 300s, which lapses quickly on
 *  mobile where the tab is often backgrounded); rpcd slides the expiry forward
 *  on each authenticated call, so an active user effectively stays signed in. */
export async function login(username: string, password: string): Promise<LoginResult> {
  const prev = sessionId;
  sessionId = NULL_SESSION; // login always runs on the null session
  try {
    const data = await call<LoginResult>('session', 'login', { username, password, timeout: 3600 });
    setSession(data.ubus_rpc_session);
    return data;
  } catch (e) {
    setSession(prev);
    throw e;
  }
}

export async function logout(): Promise<void> {
  try {
    await call('session', 'destroy', {});
  } finally {
    setSession(NULL_SESSION);
  }
}

// ---- Convenience wrappers over UCI (used across screens) -------------------

export function uciGet(config: string, section?: string) {
  return call<Record<string, unknown>>('uci', 'get', section ? { config, section } : { config });
}
export function uciSet(config: string, section: string, values: Record<string, unknown>) {
  return call('uci', 'set', { config, section, values });
}
export function uciAdd(config: string, type: string, name: string | undefined, values: Record<string, unknown> = {}) {
  return call<{ section: string }>('uci', 'add', name ? { config, type, name, values } : { config, type, values });
}
export function uciDelete(config: string, section: string, option?: string) {
  return call('uci', 'delete', option ? { config, section, option } : { config, section });
}
/** Commit staged changes and reload affected services (no rollback window). */
export function uciApply() {
  return call('uci', 'apply', { rollback: false });
}
/** Apply with a rollback timer: if uciConfirm isn't called within `timeout`
 *  seconds, the router restores the previous config. Prevents lockouts.
 *  Keep this LONGER than the UI confirm countdown (confirm.ts, 90s) so a
 *  last-second "Keep" reaches the router before it auto-reverts. */
export function uciApplyRollback(timeout = 120) {
  return call('uci', 'apply', { rollback: true, timeout });
}
/** Keep changes applied with uciApplyRollback (cancels the revert timer). */
export function uciConfirm() {
  return call('uci', 'confirm', {});
}
/** Immediately roll back changes applied with uciApplyRollback. */
export function uciRollback() {
  return call('uci', 'rollback', {});
}

/** Apply firewall UCI and make nftables reflect it. `uci apply` alone does not
 *  reliably rebuild fw4's ruleset for added/removed rules, so kick the service
 *  like the other service paths do (usb/system/ddns). Best-effort reload. */
export async function firewallApply(rollback = false, timeout = 120) {
  await (rollback ? uciApplyRollback(timeout) : uciApply());
  try {
    await call('file', 'exec', { command: '/etc/init.d/firewall', params: ['reload'] });
  } catch (e) {
    // The UCI change is saved; say so, but do not hide that the running ruleset may lag.
    throw new Error(`Settings saved, but the firewall service did not reload: ${(e as Error).message}`);
  }
}
