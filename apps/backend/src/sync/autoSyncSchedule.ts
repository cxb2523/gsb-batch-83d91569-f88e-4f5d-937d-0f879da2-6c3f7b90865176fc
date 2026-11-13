// When auto-sync runs: shortly after the backend starts (after the renderer's first load), then at every
// check while the app stays open (often in the tray). Each time it syncs only if a sync is due: auto-sync
// is on and the last successful sync is over 12 hours old (`shouldAutoSync`).
export const AUTO_SYNC_STARTUP_DELAY_MS = 3000;
export const AUTO_SYNC_CHECK_MS = 30 * 60 * 1000;

export function scheduleAutoSync({ isDue, sync, timers = { setTimeout, setInterval, clearTimeout, clearInterval } }: {
  isDue: () => boolean;
  sync: () => void;
  timers?: {
    setTimeout: (run: () => void, ms: number) => unknown;
    setInterval: (run: () => void, ms: number) => unknown;
    clearTimeout: (handle: never) => void;
    clearInterval: (handle: never) => void;
  };
}) {
  const runIfDue = () => {
    if (isDue()) sync();
  };
  const startup = timers.setTimeout(runIfDue, AUTO_SYNC_STARTUP_DELAY_MS);
  const every = timers.setInterval(runIfDue, AUTO_SYNC_CHECK_MS);
  // Neither timer keeps the backend process alive on its own.
  (startup as { unref?: () => void }).unref?.();
  (every as { unref?: () => void }).unref?.();
  return () => {
    timers.clearTimeout(startup as never);
    timers.clearInterval(every as never);
  };
}
