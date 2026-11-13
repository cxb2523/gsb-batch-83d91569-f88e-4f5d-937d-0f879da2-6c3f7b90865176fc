// Rollback-confirm flow for connectivity-risky config changes.
// A screen stages + applies with uciApplyRollback, then calls
// startRollbackConfirm(): the router will auto-revert unless the user (who can
// still reach the UI, proving the change didn't break their connection) keeps it.
import { writable } from 'svelte/store';
import { uciConfirm, uciRollback } from './ubus';

export interface ConfirmState { active: boolean; seconds: number; label: string; }
export const confirmState = writable<ConfirmState>({ active: false, seconds: 0, label: '' });

let timer: ReturnType<typeof setInterval> | undefined;
let onKeepCb: (() => void) | null = null;
let onRevertCb: (() => void) | null = null;

export function startRollbackConfirm(
  label: string,
  opts: { timeout?: number; onKeep?: () => void; onRevert?: () => void } = {}
) {
  // Single-flight: if a confirm is already pending, finalize it before starting
  // a new one. The user is still connected (they just triggered another change),
  // so the earlier change is safe to keep — otherwise its callbacks would be
  // clobbered and its router-side rollback timer would silently revert it.
  if (onKeepCb || onRevertCb) void keepChanges();
  const timeout = opts.timeout ?? 90;
  onKeepCb = opts.onKeep ?? null;
  onRevertCb = opts.onRevert ?? null;
  confirmState.set({ active: true, seconds: timeout, label });
  clearInterval(timer);
  timer = setInterval(() => {
    confirmState.update((s) => {
      if (!s.active) return s;
      const n = s.seconds - 1;
      if (n <= 0) { void doRevert(); return { active: false, seconds: 0, label: '' }; }
      return { ...s, seconds: n };
    });
  }, 1000);
}

function stop() {
  clearInterval(timer);
  confirmState.set({ active: false, seconds: 0, label: '' });
}

export async function keepChanges() {
  stop();
  const cb = onKeepCb; onKeepCb = onRevertCb = null;  // capture before await
  try { await uciConfirm(); } catch { /* ignore */ }
  cb?.();
}

export async function revertChanges() { await doRevert(); }

async function doRevert() {
  stop();
  const cb = onRevertCb; onKeepCb = onRevertCb = null;  // capture before await
  try { await uciRollback(); } catch { /* ignore — router auto-reverts on its own timer */ }
  cb?.();
}
