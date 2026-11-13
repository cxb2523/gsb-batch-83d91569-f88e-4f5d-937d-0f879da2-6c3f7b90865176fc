import { describe, expect, test, vi } from "vitest";
import { ALERT_CHECK_MS, FIRST_ALERT_CHECK_MS, createSystemNotifier, startReleaseAlerts } from "../../apps/desktop/src/releaseAlerts";
import type { ReleaseAlert } from "../../shared/types";

const alert: ReleaseAlert = { releaseId: "igdb-1", kind: "out", title: "Out today: Out Now", body: "A game on your watchlist comes out today." };

function fakeTimers() {
  const scheduled: Array<{ run: () => void; ms: number; repeat: boolean }> = [];
  return {
    scheduled,
    timers: {
      setTimeout: (run: () => void, ms: number) => scheduled.push({ run, ms, repeat: false }),
      setInterval: (run: () => void, ms: number) => scheduled.push({ run, ms, repeat: true }),
      clearTimeout: vi.fn(),
      clearInterval: vi.fn()
    }
  };
}

const flush = () => new Promise(resolve => setTimeout(resolve, 0));

describe("release alerts on the desktop", () => {
  test("checks soon after startup and then every few minutes; a clicked notification opens its game", async () => {
    const { scheduled, timers } = fakeTimers();
    const shown: Array<{ alert: ReleaseAlert; onClick: () => void }> = [];
    const openRelease = vi.fn();
    const takeAlerts = vi.fn(async () => [alert]);
    startReleaseAlerts({ takeAlerts, notifier: { isSupported: () => true, show: (item, onClick) => shown.push({ alert: item, onClick }) }, openRelease, timers });

    expect(scheduled.map(({ ms, repeat }) => [ms, repeat])).toEqual([[FIRST_ALERT_CHECK_MS, false], [ALERT_CHECK_MS, true]]);
    scheduled[0].run();
    await flush();
    expect(shown.map(entry => entry.alert.title)).toEqual(["Out today: Out Now"]);

    shown[0].onClick();
    expect(openRelease).toHaveBeenCalledWith("igdb-1");
  });

  test("a failed check is logged and the next one tries again", async () => {
    const { scheduled, timers } = fakeTimers();
    const log = vi.fn();
    const takeAlerts = vi.fn().mockRejectedValueOnce(new Error("backend busy")).mockResolvedValue([]);
    startReleaseAlerts({ takeAlerts, notifier: { isSupported: () => true, show: vi.fn() }, openRelease: vi.fn(), log, timers });

    scheduled[1].run();
    await flush();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("backend busy"));
    scheduled[1].run();
    await flush();
    expect(takeAlerts).toHaveBeenCalledTimes(2);
  });

  test("without system notifications nothing is scheduled", () => {
    const { scheduled, timers } = fakeTimers();
    startReleaseAlerts({ takeAlerts: vi.fn(), notifier: { isSupported: () => false, show: vi.fn() }, openRelease: vi.fn(), timers });
    expect(scheduled).toEqual([]);
  });
});

describe("system notifier", () => {
  function fakeNotification() {
    const listeners: Record<string, () => void> = {};
    return { listeners, notification: { on: (event: string, listener: () => void) => { listeners[event] = listener; }, show: vi.fn() } };
  }

  test("shows a notification whose click opens the game", () => {
    const { listeners, notification } = fakeNotification();
    const notifier = createSystemNotifier({ isSupported: () => true, create: () => notification });
    const onClick = vi.fn();

    notifier.show(alert, onClick);
    expect(notification.show).toHaveBeenCalled();
    listeners.click();
    expect(onClick).toHaveBeenCalledOnce();
  });

  test("a notification the system refuses is shown through the fallback, which still opens the game", () => {
    const { listeners, notification } = fakeNotification();
    const fallback = vi.fn();
    const notifier = createSystemNotifier({ isSupported: () => true, create: () => notification, fallback });
    const onClick = vi.fn();

    notifier.show(alert, onClick);
    listeners.failed();

    expect(fallback).toHaveBeenCalledWith(alert, onClick);
  });
});
