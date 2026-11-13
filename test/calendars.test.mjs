import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { createHass, allDay, inDays, response } from './support/hass.mjs';
import { calendarEntry, refreshCalendar, onCalendarChange, clearCalendarCache, configureCalendarFetch, resetCalendarFetch,
  CAL_OK, CAL_ERROR, CAL_TIMEOUT, CAL_INVALID } from '../src/calendars.js';

/* ---- local hass stub: callWS succeeds / throws / hangs / returns no `response` ---- */

const fixedNow = () => Date.now(); // the mocked clock
const setClock = d => { mock.timers.setTime(d.getTime()); };
const advance = ms => { mock.timers.tick(ms); };
const flush = () => new Promise(resolve => setImmediate(resolve)); // let async hops settle (timers stay mocked)

function setup({ timeoutMs = 1000, retryDelays = [1000, 2000, 4000, 90000] } = {}) {
  mock.timers.enable({ apis: ['Date', 'setTimeout'], now: new Date(2026, 10, 14, 9, 0).getTime() });
  configureCalendarFetch({ timeoutMs, retryDelays, now: fixedNow });
  clearCalendarCache();
  return createHass({ entity: 'calendar.bins', events: allDay([inDays(-7), inDays(3)]) });
}

function teardown() {
  clearCalendarCache();
  resetCalendarFetch();
  mock.timers.reset();
}

/* Outcomes recorded on the entry, and what listeners were told. */
const outcomes = entry => ({ outcome: entry.outcome, everOk: entry.everOk, hasData: entry.data !== null, attempts: entry.attempts });

test('success is recorded and shared: one callWS per entity and day', async () => {
  const hass = setup();
  try {
    const seen = [];
    const first = calendarEntry(hass, 'calendar.bins', 'events');
    onCalendarChange(first, e => seen.push(e.outcome));
    const second = calendarEntry(hass, 'calendar.bins', 'events'); // second card, same page
    assert.equal(first, second);
    await flush();
    assert.equal(first.outcome, CAL_OK);
    assert.equal(first.everOk, true);
    // 'events' entries keep the raw events (the card filters by title itself)
    assert.deepEqual(first.data.map(ev => ev.start.date), [inDays(-7), inDays(3)]);
    assert.equal(hass.calls.length, 1);
    assert.equal(seen.at(-1), CAL_OK);
    // later calls during the same day are served from the cache
    calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(hass.calls.length, 1);
  } finally { teardown(); }
});

test('service error: recorded as error, no data, retried at a growing interval', async () => {
  const hass = setup();
  try {
    hass.mode = 'error';
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.deepEqual(outcomes(entry), { outcome: CAL_ERROR, everOk: false, hasData: false, attempts: 1 });
    // the retry is not immediate: still one call after less than the first delay
    advance(999);
    await flush();
    assert.equal(hass.calls.length, 1);

    advance(1); // first retry (1 s), still failing
    await flush();
    assert.equal(hass.calls.length, 2);
    assert.equal(entry.attempts, 2);
    assert.equal(entry.outcome, CAL_ERROR);

    hass.mode = 'ok'; // the second retry (after 2 s) succeeds
    advance(2000);
    await flush();
    assert.equal(hass.calls.length, 3);
    assert.equal(entry.outcome, CAL_OK);
    assert.equal(entry.everOk, true);
    assert.equal(entry.attempts, 0);
    assert.deepEqual(entry.data.map(ev => ev.start.date), [inDays(-7), inDays(3)]);
  } finally { teardown(); }
});

test('timeout: a hanging callWS is recorded as timeout, never as a silent null', async () => {
  const hass = setup({ timeoutMs: 1000, retryDelays: [5000] });
  try {
    hass.mode = 'timeout';
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    advance(999);
    await flush();
    assert.equal(entry.outcome, null, 'still waiting before the deadline');
    advance(1);
    await flush();
    assert.equal(entry.outcome, CAL_TIMEOUT);
    assert.equal(entry.everOk, false);
    assert.equal(entry.data, null);
    advance(5000);
    await flush();
    assert.equal(hass.calls.length, 2); // retried
    assert.equal(entry.outcome, CAL_TIMEOUT);
  } finally { teardown(); }
});

test('an explicit abort / TimeoutError from callWS is a timeout, anything else an error', async () => {
  const hass = setup();
  try {
    hass.mode = 'abort';
    const e1 = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(e1.outcome, CAL_TIMEOUT);
  } finally { teardown(); }
});

test('malformed response (no response field) is recorded as invalid', async () => {
  const hass = setup();
  try {
    hass.mode = 'invalid';
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(entry.outcome, CAL_INVALID);
    assert.equal(entry.everOk, false);
  } finally { teardown(); }
});

test('a failure after a success keeps the last successful data and the caller can still compute', async () => {
  const hass = setup();
  try {
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(entry.outcome, CAL_OK);
    const good = entry.data;
    // next day: the cached copy expires, the read fails
    setClock(new Date(2026, 10, 15, 9, 0));
    hass.mode = 'error';
    const again = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(again.outcome, CAL_ERROR);
    assert.equal(again.everOk, true, 'had succeeded before');
    assert.equal(again.data, good, 'previous weeks stay available');
  } finally { teardown(); }
});

test('the day changes: new fetch, same entity; a second card does not double-call', async () => {
  const hass = setup();
  try {
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(hass.calls.length, 1);
    setClock(new Date(2026, 10, 15, 0, 30)); // just after midnight
    calendarEntry(hass, 'calendar.bins', 'events');
    calendarEntry(hass, 'calendar.bins', 'events'); // second card, same entity
    assert.equal(hass.calls.length, 2, 'one call for the new day, shared by both cards');
    await flush();
    assert.equal(entry.outcome, CAL_OK);
  } finally { teardown(); }
});

test('a response arriving after our own timeout is ignored, not applied over fresher data', async () => {
  const hass = setup({ timeoutMs: 1000, retryDelays: [500] });
  try {
    let release;
    const stale = new Promise(resolve => { release = resolve; });
    let call = 0;
    hass.callWS = msg => {
      hass.calls.push(msg);
      return ++call === 1 ? stale : Promise.resolve(response(msg.target.entity_id, allDay([inDays(2)])));
    };
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    advance(1000); // first call times out
    await flush();
    assert.equal(entry.outcome, CAL_TIMEOUT);

    advance(500); // retry succeeds
    await flush();
    assert.equal(entry.outcome, CAL_OK);
    const good = entry.data;

    release(response('calendar.bins', allDay([inDays(30)]))); // the stale response finally lands
    await flush();
    assert.equal(entry.outcome, CAL_OK);
    assert.equal(entry.data, good, 'stale payload discarded');
  } finally { teardown(); }
});

test('a different entity has its own cache entry', async () => {
  const hass = setup();
  try {
    calendarEntry(hass, 'calendar.bins', 'events');
    calendarEntry(hass, 'calendar.other', 'events');
    await flush();
    assert.equal(hass.calls.length, 2);
  } finally { teardown(); }
});

test('an entity state change refreshes a stale success, at most every 30 minutes', async () => {
  const hass = setup();
  try {
    const entry = calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(hass.calls.length, 1);

    refreshCalendar(entry); // just read: not worth a new request
    await flush();
    assert.equal(hass.calls.length, 1);

    advance(30 * 60000);   // a new push after the minimum interval: read again
    refreshCalendar(entry);
    assert.equal(hass.calls.length, 2);
    await flush();

    // a broken calendar follows its own retry schedule, not every state change
    hass.mode = 'error';
    setClock(new Date(2026, 10, 15, 9, 0)); // next day: read fails
    calendarEntry(hass, 'calendar.bins', 'events');
    await flush();
    assert.equal(entry.outcome, CAL_ERROR);
    const calls = hass.calls.length;
    refreshCalendar(entry);
    refreshCalendar(entry);
    await flush();
    assert.equal(hass.calls.length, calls, 'no extra calls while a retry is pending');
  } finally { teardown(); }
});

test('Holiday / Workday calendars (kind days) use their own range and cache', async () => {
  const hass = setup();
  try {
    hass.events = allDay([inDays(0), inDays(1)]);
    const entry = calendarEntry(hass, 'calendar.holiday', 'days');
    await flush();
    assert.equal(entry.outcome, CAL_OK);
    assert.ok(entry.data.has(inDays(0)) && entry.data.has(inDays(1)));
    const span = (msg => {
      const s = new Date(msg.service_data.start_date_time), e = new Date(msg.service_data.end_date_time);
      return Math.round((e - s) / 86400000);
    })(hass.calls[0]);
    assert.ok(span > 780, `about a year either side, got ${span} days`);
  } finally { teardown(); }
});
