import assert from "node:assert/strict";
import test from "node:test";
import { defaultCustomRange, latestTimestamp, normalizeCustomRange, quotaCountdownParts, resolveDateRange, resolveWeeklyRange, theoreticalWeeklyQuotaPeriod, timestampInRange, toDateTimeLocalValue } from "../public/date-range.js";

test("stores datetime-local values without converting their local wall time", () => {
  const date = new Date(2026, 7, 13, 14, 5);
  assert.equal(toDateTimeLocalValue(date), "2026-08-13T14:05");
  assert.deepEqual(defaultCustomRange(date), { start: "2026-08-13T00:00", end: null });
});

test("restores a valid custom range and falls back safely for corrupt storage", () => {
  const now = new Date(2026, 7, 13, 14, 5);
  assert.deepEqual(normalizeCustomRange({ start: "2026-08-01T08:30", end: "2026-08-02T17:45" }, now), { start: "2026-08-01T08:30", end: "2026-08-02T17:45" });
  assert.deepEqual(normalizeCustomRange({ start: "broken", end: "broken" }, now), { start: "2026-08-13T00:00", end: null });
});

test("a null custom end means now mode and adds no upper filter bound", () => {
  const range = resolveDateRange("custom", { start: "2026-08-01T00:00", end: null }, new Date(2026, 7, 13, 14, 5));
  assert.equal(range.end, null);
  assert.equal(timestampInRange("2026-08-20T00:00:00Z", range), true);
  assert.equal(timestampInRange("2026-07-30T23:59:59Z", range), false);
});

test("an explicit custom end is inclusive and latest calls sort by actual call time", () => {
  const range = resolveDateRange("custom", { start: "2026-08-01T00:00", end: "2026-08-02T12:00" });
  assert.equal(timestampInRange("2026-08-02T12:00:00", range), true);
  assert.equal(timestampInRange("2026-08-02T12:00:01", range), false);
  assert.equal(latestTimestamp([{ timestamp: "2026-08-01T12:00:00Z" }, { timestamp: "2026-08-02T09:00:00Z" }]), "2026-08-02T09:00:00Z");
});

test("12 months and all history are distinct main-page ranges", () => {
  const now = new Date(2026, 7, 27, 14, 5);
  const rollingYear = resolveDateRange("12m", null, now);
  const allHistory = resolveDateRange("all", null, now);

  assert.deepEqual(rollingYear.start, new Date(2025, 7, 27, 0, 0, 0, 0));
  assert.equal(rollingYear.end.getTime(), now.getTime());
  assert.equal(timestampInRange(new Date(2025, 7, 26, 23, 59, 59).toISOString(), rollingYear), false);
  assert.equal(timestampInRange(new Date(2025, 7, 27, 0, 0, 0).toISOString(), rollingYear), true);
  assert.equal(allHistory.start.getTime(), 0);
  assert.equal(timestampInRange("2024-01-01T00:00:00.000Z", allHistory), true);
});

test("WeeklyQuota includes the exact current quota start through now and rolls over at reset", () => {
  const quota = { startsAt: "2026-09-03T14:37:00Z", resetsAt: "2026-09-10T14:37:00Z" };
  const now = new Date("2026-09-07T15:00:00Z");
  const range = resolveDateRange("weeklyQuota", null, now, quota);
  assert.equal(range.start.toISOString(), "2026-09-03T14:37:00.000Z");
  assert.deepEqual(range.end, now);
  assert.equal(timestampInRange("2026-09-03T14:36:59Z", range), false);
  assert.equal(timestampInRange(quota.startsAt, range), true);
  const next = resolveDateRange("weeklyQuota", null, new Date(quota.resetsAt), quota);
  assert.equal(next.start.toISOString(), "2026-09-10T14:37:00.000Z");
});

test("WeeklyQuota uses the existing seven-day fallback without quota observations", () => {
  const range = resolveDateRange("weeklyQuota", null, new Date("2026-09-07T15:00:00Z"));
  assert.equal(range.start.toISOString(), "2026-08-31T15:00:00.000Z");
});

test("weekly range starts 7 days before the current Codex reset", () => {
  const now = new Date("2026-08-14T15:00:00.000Z");
  const range = resolveWeeklyRange({ windowMinutes: 10080, resetsAt: "2026-08-20T12:00:00.000Z" }, now);
  assert.equal(range.start.toISOString(), "2026-08-13T12:00:00.000Z");
  assert.equal(range.end.toISOString(), now.toISOString());
  assert.equal(range.resetsAt.toISOString(), "2026-08-20T12:00:00.000Z");
});

test("a stale weekly reset rolls forward into the current 7-day cycle", () => {
  const now = new Date("2026-08-14T15:00:00.000Z");
  const range = resolveWeeklyRange({ windowMinutes: 10080, resetsAt: "2026-08-07T12:00:00.000Z" }, now);
  assert.equal(range.start.toISOString(), "2026-08-14T12:00:00.000Z");
  assert.equal(range.resetsAt.toISOString(), "2026-08-21T12:00:00.000Z");
  assert.equal(timestampInRange("2026-08-14T14:00:00.000Z", range), true);
  assert.equal(timestampInRange("2026-08-14T11:00:00.000Z", range), false);
});

test("an expired observed quota creates an unobserved theoretical current week", () => {
  const theoretical = theoreticalWeeklyQuotaPeriod({
    startsAt: "2026-08-13T03:29:39.000Z",
    endsAt: "2026-08-20T03:29:39.000Z",
    resetsAt: "2026-08-20T03:29:39.000Z",
    windowMinutes: 10080,
    usedPercent: 74,
    remainingPercent: 26,
    planType: "pro",
  }, "2026-08-20T05:07:00.000Z");

  assert.equal(theoretical.startsAt, "2026-08-20T03:29:39.000Z");
  assert.equal(theoretical.resetsAt, "2026-08-27T03:29:39.000Z");
  assert.equal(theoretical.usedPercent, null);
  assert.equal(theoretical.remainingPercent, null);
  assert.equal(theoretical.planType, null);
  assert.equal(theoretical.theoretical, true);
});

test("theoretical rollover skips fully elapsed unobserved weeks", () => {
  const theoretical = theoreticalWeeklyQuotaPeriod({
    resetsAt: "2026-08-06T12:00:00.000Z",
    windowMinutes: 10080,
  }, "2026-08-20T12:00:00.000Z");

  assert.equal(theoretical.startsAt, "2026-08-20T12:00:00.000Z");
  assert.equal(theoretical.resetsAt, "2026-08-27T12:00:00.000Z");
});

test("an observed quota that has not ended does not create a theoretical week", () => {
  assert.equal(theoreticalWeeklyQuotaPeriod({
    resetsAt: "2026-08-20T12:00:00.000Z",
    windowMinutes: 10080,
  }, "2026-08-20T11:59:59.999Z"), null);
});

test("without a reset date, weekly range is the last 7 days from now", () => {
  const now = new Date("2026-08-14T15:00:00.000Z");
  const range = resolveWeeklyRange(null, now);
  assert.equal(range.start.toISOString(), "2026-08-07T15:00:00.000Z");
  assert.equal(range.resetsAt, null);
});

test("a reset more than one week ahead is rewound to the current cycle", () => {
  const now = new Date("2026-08-14T15:00:00.000Z");
  const range = resolveWeeklyRange({ windowMinutes: 10080, resetsAt: "2026-09-03T12:00:00.000Z" }, now);
  assert.equal(range.start.toISOString(), "2026-08-13T12:00:00.000Z");
  assert.equal(range.resetsAt.toISOString(), "2026-08-20T12:00:00.000Z");
});

test("weekly quota countdown exposes days, hours, minutes, and seconds", () => {
  assert.deepEqual(
    quotaCountdownParts("2026-08-20T12:00:00.000Z", "2026-08-19T08:57:54.500Z"),
    { days: 1, hours: 3, minutes: 2, seconds: 6 },
  );
  assert.deepEqual(
    quotaCountdownParts("2026-08-19T08:57:54.000Z", "2026-08-19T08:57:55.000Z"),
    { days: 0, hours: 0, minutes: 0, seconds: 0 },
  );
  assert.equal(quotaCountdownParts("not-a-date"), null);
});
