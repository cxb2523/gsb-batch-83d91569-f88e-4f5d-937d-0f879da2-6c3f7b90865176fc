/* Drives the real card against the local hass stub: what the user sees when the calendar is
   readable, unreadable, empty, or recovers after a retry. */
import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { installDom, nodeText, nodeHidden } from './support/dom.mjs';
import { createHass, allDay, inDays } from './support/hass.mjs';
import { clearCalendarCache, configureCalendarFetch, resetCalendarFetch } from '../src/calendars.js';

installDom();
const { PoubelleCard } = await import('../src/poubelle-card.js');

const READ_ERROR = 'Calendar read failed, retrying soon';
const NO_EVENTS = 'Calendar available, no matching event';

const flush = () => new Promise(resolve => setImmediate(resolve));
const warn = card => nodeText(card, '.warn');
const warnShown = card => !nodeHidden(card, '.warn');
const status = card => nodeText(card, '.status');
const pill = card => nodeText(card, '.pill');

function setup({ events, startTime = null } = {}) {
  mock.timers.enable({ apis: ['Date', 'setTimeout'], now: new Date(2026, 10, 14, 9, 0).getTime() });
  configureCalendarFetch({ timeoutMs: 1000, retryDelays: [1000, 2000], now: () => Date.now() });
  clearCalendarCache();
  const hass = createHass({
    entity: 'calendar.bins',
    // the card must not fall back to the calendar entity's own next event: that made a failed
    // read look like a real (but wrong) pickup date
    startTime: startTime ?? `${inDays(2)} 07:00:00`,
    events: events ?? allDay([inDays(-6), inDays(9)]),
  });
  return hass;
}

function makeCard(hass, config = {}) {
  const card = new PoubelleCard();
  card.setConfig({ bin: 'yellow', entity: 'calendar.bins', hour: 6, ...config });
  card.hass = hass;
  return card;
}

function teardown() {
  clearCalendarCache();
  resetCalendarFetch();
  mock.timers.reset();
}

test('first read fails: failure hint, no "unknown date" fallback to the entity start_time', async () => {
  const hass = setup();
  try {
    hass.mode = 'error';
    const card = makeCard(hass);
    await flush();
    assert.equal(warnShown(card), true);
    assert.equal(warn(card), READ_ERROR);
    // never a pickup date guess from start_time, and not presented as "no collection planned"
    assert.equal(status(card), 'Unknown date');
    assert.equal(pill(card), '—');
    assert.notEqual(warn(card), NO_EVENTS);
  } finally { teardown(); }
});

test('calendar available but without matching events: a different, factual hint', async () => {
  const hass = setup({ events: allDay([inDays(-6), inDays(4)]) });
  try {
    const card = makeCard(hass, { calendar_filter: 'Glass' }); // nothing matches this title
    await flush();
    assert.equal(warnShown(card), true);
    assert.equal(warn(card), NO_EVENTS);
    assert.equal(status(card), 'Unknown date');
  } finally { teardown(); }
});

test('successful read: no hint, real dates from the calendar', async () => {
  const hass = setup();
  try {
    const card = makeCard(hass);
    await flush();
    assert.equal(warnShown(card), false);
    assert.match(status(card), /Pickup on/);
    assert.equal(card._cal.length, 2);
  } finally { teardown(); }
});

test('success then failure: keeps the known pickup date and shows the hint', async () => {
  const hass = setup();
  try {
    const card = makeCard(hass);
    await flush();
    const before = status(card);
    const beforeCal = card._cal.map(d => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`);
    const beforeN = card._compute().n;
    assert.equal(warnShown(card), false);

    // next day: the per-day cache is stale, the read fails
    mock.timers.setTime(new Date(2026, 10, 15, 9, 0).getTime());
    hass.mode = 'error';
    card.hass = hass; // a fresh hass push, as Home Assistant does regularly
    await flush();

    assert.equal(warnShown(card), true);
    assert.equal(warn(card), READ_ERROR);
    // the last successful events are still used: the pickup date did not vanish
    assert.equal(status(card), before);
    assert.deepEqual(card._cal.map(d => `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()}`), [beforeCal[0], beforeCal[1]]);
    assert.equal(card._compute().n, beforeN - 1, 'computed from the retained events, one day later');
  } finally { teardown(); }
});

test('retry succeeds: the hint disappears and the normal display returns', async () => {
  const hass = setup();
  try {
    hass.mode = 'timeout';
    const card = makeCard(hass);
    mock.timers.tick(1000); // our own deadline
    await flush();
    assert.equal(warn(card), READ_ERROR);

    hass.mode = 'ok';
    hass.events = allDay([inDays(-2), inDays(5)]);
    mock.timers.tick(1000); // first retry delay
    await flush();

    assert.equal(warnShown(card), false, 'hint cleared after a successful retry');
    assert.match(status(card), /^Pickup on /); // normal display (weekday or date)
    assert.equal(card._cal.length, 2);
    assert.equal(card._calEntry.outcome, 'ok');
    assert.equal(card._calEntry.everOk, true);
    assert.equal(card._calEntry.attempts, 0);
  } finally { teardown(); }
});

test('retry still failing: the error hint stays and the previous dates keep being used', async () => {
  const hass = setup();
  try {
    const card = makeCard(hass);
    await flush();
    const known = status(card);
    mock.timers.setTime(new Date(2026, 10, 15, 9, 0).getTime());
    hass.mode = 'invalid';
    card.hass = hass;
    await flush();
    assert.equal(warn(card), READ_ERROR);
    mock.timers.tick(1000); // a retry attempt, still malformed
    await flush();
    assert.equal(warn(card), READ_ERROR);
    assert.equal(status(card), known);
  } finally { teardown(); }
});

test('two cards, same calendar, same day: one callWS between them', async () => {
  const hass = setup();
  try {
    const a = makeCard(hass, { bin: 'yellow' });
    const b = makeCard(hass, { bin: 'green' });
    await flush();
    assert.equal(hass.calls.length, 1);
    assert.match(status(a), /Pickup on/);
    assert.match(status(b), /Pickup on/);
    // later hass pushes on the same day do not re-read either
    a.hass = hass; b.hass = hass;
    await flush();
    assert.equal(hass.calls.length, 1);
  } finally { teardown(); }
});

test('two cards, same calendar, next day: one new callWS, shared', async () => {
  const hass = setup();
  try {
    const a = makeCard(hass, { bin: 'yellow' });
    const b = makeCard(hass, { bin: 'green' });
    await flush();
    assert.equal(hass.calls.length, 1);
    mock.timers.setTime(new Date(2026, 10, 15, 8, 0).getTime());
    a.hass = hass; b.hass = hass;
    await flush();
    assert.equal(hass.calls.length, 2, 'the new day invalidates the cache, once for both cards');
  } finally { teardown(); }
});

test('calendar without callWS support falls back to the entity state', async () => {
  const hass = setup();
  try {
    delete hass.callWS;
    const card = makeCard(hass);
    await flush();
    assert.equal(card._cal, null);
    assert.equal(warnShown(card), false); // no calendar fetch involved: no hint
    assert.match(status(card), /Pickup on/); // from attributes.start_time
  } finally { teardown(); }
});

test('sensor entity: no calendar fetch, no calendar hint, date from the sensor state', async () => {
  const hass = setup();
  try {
    hass.states['sensor.bins'] = { entity_id: 'sensor.bins', state: '3', attributes: {} };
    const card = new PoubelleCard();
    card.setConfig({ bin: 'grey', entity: 'sensor.bins', interval: 7 });
    card.hass = hass;
    await flush();
    card.hass = hass;
    await flush();
    assert.equal(hass.calls.length, 0, 'sensors are never read through calendar.get_events');
    assert.equal(warnShown(card), false);
    assert.equal(pill(card), 'In 3 d');
  } finally { teardown(); }
});

test('schedule card: an unreadable Holiday calendar shows the same read-error hint, cleared on retry', async () => {
  const hass = setup();
  try {
    hass.states['calendar.holiday'] = { entity_id: 'calendar.holiday', state: 'off', attributes: {} };
    hass.mode = 'error';
    const card = new PoubelleCard();
    card.setConfig({ bin: 'grey', days: [2], holidays: 'next_day', holiday_calendar: 'calendar.holiday' });
    card.hass = hass;
    await flush();
    assert.equal(warnShown(card), true);
    assert.equal(warn(card), READ_ERROR);

    hass.mode = 'ok';
    hass.events = allDay([inDays(1)]);
    mock.timers.tick(1000); // first retry
    await flush();
    assert.equal(warnShown(card), false);
  } finally { teardown(); }
});
