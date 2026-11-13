import type { ReleaseAlert } from "../../../shared/types";

// Shows the backend's release alerts (watched games out today, or with a new date) as system
// notifications. It asks soon after startup, then every few minutes, so an alert from a background sync
// arrives while the window sits in the tray. Clicking a notification opens that game.

export const FIRST_ALERT_CHECK_MS = 15_000;
export const ALERT_CHECK_MS = 5 * 60_000;

export interface AlertNotifier {
  isSupported(): boolean;
  show(alert: ReleaseAlert, onClick: () => void): void;
}

export function startReleaseAlerts({
  takeAlerts,
  notifier,
  openRelease,
  log,
  timers = { setTimeout, setInterval, clearTimeout, clearInterval }
}: {
  takeAlerts: () => Promise<ReleaseAlert[]>;
  notifier: AlertNotifier;
  openRelease: (releaseId: string) => void;
  log?: (message: string) => void;
  timers?: {
    setTimeout: (run: () => void, ms: number) => unknown;
    setInterval: (run: () => void, ms: number) => unknown;
    clearTimeout: (handle: never) => void;
    clearInterval: (handle: never) => void;
  };
}) {
  if (!notifier.isSupported()) {
    log?.("notifications are not supported on this system; release alerts are off");
    return () => undefined;
  }
  let checking = false;
  const check = async () => {
    if (checking) return;
    checking = true;
    try {
      for (const alert of await takeAlerts()) notifier.show(alert, () => openRelease(alert.releaseId));
    } catch (error) {
      // The backend may be restarting or busy; the next check tries again.
      log?.(`release alert check failed: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      checking = false;
    }
  };
  const first = timers.setTimeout(() => void check(), FIRST_ALERT_CHECK_MS);
  const every = timers.setInterval(() => void check(), ALERT_CHECK_MS);
  return () => {
    timers.clearTimeout(first as never);
    timers.clearInterval(every as never);
  };
}

// The shape of Electron's Notification this needs, so tests can pass a fake.
export interface SystemNotification {
  on(event: "click" | "close" | "failed", listener: () => void): unknown;
  show(): void;
}

// The AlertNotifier for system notifications. Each shown notification is held until clicked, closed or
// failed, so its click handler is not garbage-collected. Where the system refuses one (Windows, for an
// app with no Start-menu shortcut such as the zip build), `fallback` shows it another way: a tray balloon.
export function createSystemNotifier({ isSupported, create, fallback }: {
  isSupported: () => boolean;
  create: (alert: ReleaseAlert) => SystemNotification;
  fallback?: (alert: ReleaseAlert, onClick: () => void) => void;
}): AlertNotifier {
  const live = new Set<SystemNotification>();
  return {
    isSupported,
    show(alert, onClick) {
      const notification = create(alert);
      live.add(notification);
      const release = () => live.delete(notification);
      notification.on("click", () => {
        release();
        onClick();
      });
      notification.on("close", release);
      notification.on("failed", () => {
        release();
        fallback?.(alert, onClick);
      });
      notification.show();
    }
  };
}
