import { describe, expect, test, vi } from "vitest";
import { AUTO_SYNC_CHECK_MS, AUTO_SYNC_STARTUP_DELAY_MS, scheduleAutoSync } from "../../apps/backend/src/sync/autoSyncSchedule";

describe("auto-sync schedule", () => {
  test("syncs shortly after startup and at every check while the app stays open, only when a sync is due", () => {
    vi.useFakeTimers();
    try {
      let due = true;
      const sync = vi.fn();
      const stop = scheduleAutoSync({ isDue: () => due, sync });

      vi.advanceTimersByTime(AUTO_SYNC_STARTUP_DELAY_MS);
      expect(sync).toHaveBeenCalledTimes(1);

      due = false;
      vi.advanceTimersByTime(AUTO_SYNC_CHECK_MS);
      expect(sync).toHaveBeenCalledTimes(1);

      due = true;
      vi.advanceTimersByTime(AUTO_SYNC_CHECK_MS);
      expect(sync).toHaveBeenCalledTimes(2);

      stop();
      vi.advanceTimersByTime(AUTO_SYNC_CHECK_MS * 4);
      expect(sync).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
