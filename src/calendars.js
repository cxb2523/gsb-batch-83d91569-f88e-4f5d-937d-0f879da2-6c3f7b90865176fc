/* Calendar fetching shared by every card on the page.
 *
 * Each get_events call records its outcome (ok / service error / timeout / malformed response).
 * A successful result is cached for the current day and re-used by all cards (one request per
 * entity and kind). Failed reads keep the last successful payload for computation and are
 * retried with a growing delay; only a calendar that never succeeded is reported as unavailable.
 */
import { addDays, dayKey, midnight, eventDays } from './schedule.js';

export const CAL_OK = 'ok';
export const CAL_ERROR = 'error';     // callWS rejected (service error)
export const CAL_TIMEOUT = 'timeout'; // callWS hung past our deadline, or an abort
export const CAL_INVALID = 'invalid'; // response without response[entity].events

/* Our own deadline: callWS may hang forever (a restarting Home Assistant, a sleeping host…). */
export const FETCH_TIMEOUT_MS = 10 * 1000;
/* Retry delays after a failure, capped at 15 minutes. */
export const RETRY_DELAYS = [15 * 1000, 30 * 1000, 60 * 1000, 2 * 60 * 1000, 5 * 60 * 1000, 10 * 60 * 1000, 15 * 60 * 1000];

/* Defaults, overridable in tests (never by the card itself). */
const timing = { timeoutMs: FETCH_TIMEOUT_MS, retryDelays: RETRY_DELAYS, now: () => Date.now() };
export function configureCalendarFetch(patch = {}) {
  if (Number.isFinite(Number(patch.timeoutMs)) && Number(patch.timeoutMs) > 0) timing.timeoutMs = Number(patch.timeoutMs);
  if (Array.isArray(patch.retryDelays) && patch.retryDelays.length) timing.retryDelays = patch.retryDelays.map(Number);
  if (typeof patch.now === 'function') timing.now = patch.now;
}
export function resetCalendarFetch() {
  timing.timeoutMs = FETCH_TIMEOUT_MS; timing.retryDelays = RETRY_DELAYS; timing.now = () => Date.now();
}

const cache = new Map(); // `${kind}|${entityId}` → entry

/* Card calendars look 60 days back and 60 days ahead (start + 121 days, as before).
   Holiday / Workday calendars cover about a year back to a year and a bit ahead. */
const range = kind => {
  const today = midnight(new Date(timing.now()));
  if (kind === 'days') return [addDays(today, -380), addDays(today, 420)];
  const start = addDays(today, -60);
  return [start, addDays(start, 121)];
};

const asOutcome = err => {
  const name = String(err?.name || '').toLowerCase();
  const code = String(err?.code || '').toLowerCase();
  const msg = String(err?.message ?? err ?? '').toLowerCase();
  return name === 'timeouterror' || name === 'aborterror' || code === 'etimedout'
    || /tim(?:e|ed)\s*out|timeout|aborted/.test(msg) ? CAL_TIMEOUT : CAL_ERROR;
};

const retryDelay = attempt => {
  const delays = timing.retryDelays;
  if (!Array.isArray(delays) || !delays.length) return Math.max(0, Number(delays) || 0);
  return Math.max(0, Number(delays[Math.min(Math.max(0, attempt - 1), delays.length - 1)]) || 0);
};

function notify(entry) {
  for (const fn of entry.listeners) {
    try { fn(entry); } catch (e) { /* one card must not break the shared fetch */ }
  }
}

function scheduleRetry(entry) {
  const delay = retryDelay(entry.attempts);
  const now = timing.now();
  entry.nextRetryAt = now + delay;
  if (entry.timer) clearTimeout(entry.timer);
  // unref'd: a pending retry never keeps a Node process (or test run) alive on its own
  entry.timer = setTimeout(() => {
    entry.timer = null;
    if (!entry.promise) startFetch(entry);
  }, delay);
  entry.timer?.unref?.();
}

/* One callWS guarded by our own deadline. Never rejects: resolves { outcome, data }.
   data is the raw events array (kind 'events') or a Set of days (kind 'days'). */
function attempt(entry) {
  return new Promise(resolve => {
    const timeoutMs = Math.max(1, Number(timing.timeoutMs) || FETCH_TIMEOUT_MS);
    const [start, end] = range(entry.kind);
    let settled = false, timer = null;
    const finish = (outcome, data) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve({ outcome, data });
    };
    timer = setTimeout(() => finish(CAL_TIMEOUT), timeoutMs);
    timer?.unref?.();
    let result;
    try {
      result = entry.hass.callWS({
        type: 'call_service', domain: 'calendar', service: 'get_events', return_response: true,
        target: { entity_id: entry.entity },
        service_data: { start_date_time: start.toISOString(), end_date_time: end.toISOString() },
      });
    } catch (err) { finish(asOutcome(err)); return; }
    Promise.resolve(result).then(response => {
      const events = response?.response?.[entry.entity]?.events;
      // missing `response` or `events` (Home Assistant without return_response support, bad payload)
      if (!Array.isArray(events)) { finish(CAL_INVALID); return; }
      finish(CAL_OK, entry.kind === 'days' ? eventDays(events) : events);
    }, err => finish(asOutcome(err)));
  });
}

function startFetch(entry) {
  if (entry.promise) return entry.promise;
  if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; } // supersedes a pending retry
  entry.day = dayKey(midnight(new Date(timing.now())));
  const promise = attempt(entry).then(result => {
    entry.promise = null;
    if (result.outcome === CAL_OK) {
      entry.outcome = CAL_OK;
      entry.data = result.data;
      entry.everOk = true;
      entry.lastOkAt = timing.now();
      entry.attempts = 0;
      entry.nextRetryAt = 0;
      if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; }
    } else {
      // keep entry.data (the last successful payload): computation goes on with known dates
      entry.outcome = result.outcome;
      entry.attempts += 1;
      scheduleRetry(entry);
    }
    notify(entry);
    // the request outlived its day (started before midnight): read again for the new day,
    // starting over with the shortest retry delay
    if (entry.day !== dayKey(midnight(new Date(timing.now())))) {
      if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; }
      entry.attempts = 0;
      entry.nextRetryAt = 0;
      startFetch(entry);
    }
    return entry;
  });
  entry.promise = promise;
  return promise;
}

/* Shared entry for one calendar entity and fetch kind ('events' for a card calendar,
   'days' for Holiday / Workday calendars). Starts a request when needed.
   Successes are cached per entity and day; failures wait for their scheduled retry. */
export function calendarEntry(hass, entityId, kind = 'days') {
  if (!hass?.callWS || !entityId) return null;
  const key = `${kind}|${entityId}`;
  let entry = cache.get(key);
  if (!entry) {
    entry = {
      kind, entity: entityId, hass, day: null,
      outcome: null, data: null, everOk: false, lastOkAt: 0, attempts: 0, nextRetryAt: 0,
      promise: null, timer: null, listeners: new Set(),
    };
    cache.set(key, entry);
  } else {
    entry.hass = hass;
  }
  const today = dayKey(midnight(new Date(timing.now())));
  if (entry.day !== today) {
    // new day (or first use): yesterday's success is no longer valid, read again.
    // data / everOk stay so a failed read still computes from the last known events.
    if (entry.timer) { clearTimeout(entry.timer); entry.timer = null; }
    entry.nextRetryAt = 0;
    entry.attempts = 0; // each new day starts with the shortest retry delay
    if (!entry.promise) startFetch(entry);
    return entry;
  }
  if (entry.promise) return entry;                                        // in flight, shared
  if (entry.outcome === CAL_OK) return entry;                             // cached for this day
  if (entry.timer && entry.nextRetryAt > timing.now()) return entry;      // retry pending
  startFetch(entry);
  return entry;
}

/* The calendar entity itself changed (HA pushed a new state object): re-read it, but at most
   once every `minIntervalMs` so a busy calendar is not polled. A broken calendar keeps to its
   retry schedule instead of being hammered by every push. */
export function refreshCalendar(entry, minIntervalMs = 30 * 60000) {
  if (!entry || entry.promise) return;
  if (entry.outcome && entry.outcome !== CAL_OK) return;   // retry already scheduled
  if (entry.everOk && timing.now() - entry.lastOkAt < minIntervalMs) return;
  startFetch(entry);
}

/* Subscribe to outcome changes (first result and every retry). Returns an unsubscribe function. */
export function onCalendarChange(entry, fn) {
  if (!entry || typeof fn !== 'function') return () => {};
  entry.listeners.add(fn);
  return () => entry.listeners.delete(fn);
}

/* First calendar entity created by an integration ('holiday' or 'workday'), from the entity registry. */
export function findCalendar(hass, platform) {
  const reg = hass?.entities || {};
  return Object.keys(reg).filter(id => id.startsWith('calendar.') && reg[id]?.platform === platform && hass.states?.[id]).sort()[0] || null;
}

/* Forget everything (tests, and a fresh page context). */
export function clearCalendarCache() {
  for (const entry of cache.values()) if (entry.timer) clearTimeout(entry.timer);
  cache.clear();
}
