/**
 * Local, dependency-free tests for the self-healing sensor pipeline.
 *
 * Run with:  node --test   (or npm test)
 *
 * No Home Assistant is involved: the mobile_app webhook is replaced by an
 * injectable fake request function whose behaviour is scripted per test.
 */

'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { SensorReporter, OUTCOME } = require('../src/sensor-reporter');

// Deterministic, controllable clock.
function makeClock(start = 1_000_000) {
  let t = start;
  return { now: () => t, tick: (ms = 60_000) => { t += ms; return t; } };
}

// The eight readings collectSensors() normally produces.
function sampleReadings() {
  return [
    { unique_id: 'display_screen', state: true, type: 'binary_sensor', name: 'Display Screen' },
    { unique_id: 'cpu_temperature', state: '52.3', type: 'sensor', name: 'CPU Temperature' },
    { unique_id: 'cpu_usage', state: '11.0', type: 'sensor', name: 'CPU Usage' },
    { unique_id: 'ram_usage', state: '34.5', type: 'sensor', name: 'RAM Usage' },
    { unique_id: 'ram_free_mb', state: '2048', type: 'sensor', name: 'RAM Free' },
    { unique_id: 'disk_usage', state: '61.2', type: 'sensor', name: 'Disk Usage' },
    { unique_id: 'system_uptime', state: '2d 3h', type: 'sensor', name: 'System Uptime' },
    { unique_id: 'ip_address', state: '192.168.1.10', type: 'sensor', name: 'IP Address' },
  ];
}

/**
 * Scriptable fake of HAClient.webhook(type, data).
 *
 * behaviour maps a webhook type to either a static response or a handler
 * (callIndex, data) => response | Error. Thrown Errors / null responses model
 * network delivery failures, exactly like the real client.
 */
function makeFakeWebhook(behaviour = {}) {
  const calls = [];
  const counts = {};
  const handler = async (type, data) => {
    counts[type] = (counts[type] || 0) + 1;
    const index = counts[type];
    calls.push({ type, data, index });
    const rule = behaviour[type];
    const result = typeof rule === 'function' ? rule(index, data) : rule;
    if (result instanceof Error) throw result;
    return result === undefined ? { status: 200, data: {} } : result;
  };
  handler.calls = calls;
  handler.counts = counts;
  handler.callsOf = (t) => calls.filter((c) => c.type === t);
  return handler;
}

function okResponse() { return { status: 200, data: {} }; }

function findOutcome(round, id) {
  const s = round.sensors.find((x) => x.unique_id === id);
  assert.ok(s, 'sensor ' + id + ' should appear in the round result');
  return s;
}

// ──────────────────────────────────────────────────────────────────────────
test('all sensors register once and push successfully; no duplicate registrations', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({
    register_sensor: okResponse(),
    update_sensor_states: okResponse(),
  });
  const reporter = new SensorReporter({
    webhookFn: webhook,
    isReady: () => true,
    now: clock.now,
  });

  const round1 = await reporter.reportRound(sampleReadings());

  assert.equal(round1.ready, true);
  assert.equal(round1.counts.success, 8);
  assert.equal(webhook.counts.register_sensor, 8, 'each sensor registered exactly once');
  assert.equal(webhook.counts.update_sensor_states, 1, 'one batch state push');

  // Second cycle: registrations must NOT repeat (prevents entity flapping).
  clock.tick();
  const round2 = await reporter.reportRound(sampleReadings());
  assert.equal(webhook.counts.register_sensor, 8, 'already-registered sensors are not re-registered');
  assert.equal(webhook.counts.update_sensor_states, 2);
  assert.equal(round2.counts.success, 8);

  for (const s of round2.sensors) {
    assert.equal(s.registered, true);
    assert.equal(s.registerAttempts, 1, s.unique_id + ' registered only once');
    assert.equal(s.consecutiveFailures, 0);
    assert.equal(s.lastOutcome, OUTCOME.SUCCESS);
    assert.equal(s.lastReason, null);
  }

  const status = reporter.getStatus();
  assert.equal(status.registeredIds.length, 8);
  assert.equal(status.round, 2);
});

// ──────────────────────────────────────────────────────────────────────────
test('registration failure is recorded, retried on later rounds and recovers; other sensors keep working', async () => {
  const clock = makeClock();
  // Per-sensor attempt counters so the failure schedule is independent of the
  // order in which the batch registration runs.
  const regAttempts = {};
  const webhook = makeFakeWebhook({
    // cpu_temperature registration fails on its first two attempts, then recovers.
    register_sensor: (index, data) => {
      if (data.unique_id === 'cpu_temperature') {
        regAttempts.cpu_temperature = (regAttempts.cpu_temperature || 0) + 1;
        return regAttempts.cpu_temperature <= 2
          ? { status: 500, data: { message: 'boom' } }
          : okResponse();
      }
      return okResponse();
    },
    update_sensor_states: okResponse(),
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  // Round 1: cpu_temperature registration fails; the other 7 succeed.
  const r1 = await reporter.reportRound(sampleReadings());
  const cpu1 = findOutcome(r1, 'cpu_temperature');
  assert.equal(cpu1.lastOutcome, OUTCOME.REGISTER_FAILED);
  assert.match(cpu1.lastReason, /register_sensor HTTP 500/);
  assert.equal(cpu1.consecutiveFailures, 1);
  assert.equal(cpu1.registered, false);
  assert.equal(r1.counts.register_failed, 1);
  assert.equal(r1.counts.success, 7, 'the failure does not block the other sensors');

  // cpu_temperature must not have been included in the batch push.
  const push1 = webhook.callsOf('update_sensor_states')[0].data;
  assert.equal(push1.some((s) => s.unique_id === 'cpu_temperature'), false);

  // Round 2: still failing — failure streak grows, registration retried.
  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  const cpu2 = findOutcome(r2, 'cpu_temperature');
  assert.equal(cpu2.lastOutcome, OUTCOME.REGISTER_FAILED);
  assert.equal(cpu2.consecutiveFailures, 2);
  assert.equal(cpu2.registerAttempts, 2);

  // Round 3: registration recovers, then the state push succeeds.
  clock.tick();
  const r3 = await reporter.reportRound(sampleReadings());
  const cpu3 = findOutcome(r3, 'cpu_temperature');
  assert.equal(cpu3.lastOutcome, OUTCOME.SUCCESS);
  assert.equal(cpu3.consecutiveFailures, 0, 'streak resets after recovery');
  assert.equal(cpu3.registerAttempts, 3);
  assert.equal(cpu3.pushAttempts, 1);
  assert.equal(cpu3.registered, true);
  assert.equal(r3.counts.success, 8);

  // Round 4: no further registration attempts for the recovered sensor.
  const regCallsForCpu = webhook.callsOf('register_sensor')
    .filter((c) => c.data.unique_id === 'cpu_temperature').length;
  assert.equal(regCallsForCpu, 3, 'retried until success, then never registered again');
  clock.tick();
  await reporter.reportRound(sampleReadings());
  assert.equal(
    webhook.callsOf('register_sensor').filter((c) => c.data.unique_id === 'cpu_temperature').length,
    3,
  );
});

// ──────────────────────────────────────────────────────────────────────────
test('network-style registration failure (null/throw) is retried and recovers', async () => {
  const clock = makeClock();
  let attempt = 0;
  const webhook = makeFakeWebhook({
    register_sensor: (index, data) => {
      if (data.unique_id === 'ip_address') {
        attempt += 1;
        if (attempt === 1) return null; // client returns null on delivery failure
        if (attempt === 2) return new Error('ECONNRESET');
        return okResponse();
      }
      return okResponse();
    },
    update_sensor_states: okResponse(),
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  const r1 = await reporter.reportRound(sampleReadings());
  assert.equal(findOutcome(r1, 'ip_address').lastOutcome, OUTCOME.REGISTER_FAILED);
  assert.match(findOutcome(r1, 'ip_address').lastReason, /no response/);

  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  assert.equal(findOutcome(r2, 'ip_address').consecutiveFailures, 2);
  assert.match(findOutcome(r2, 'ip_address').lastReason, /ECONNRESET/);

  clock.tick();
  const r3 = await reporter.reportRound(sampleReadings());
  assert.equal(findOutcome(r3, 'ip_address').lastOutcome, OUTCOME.SUCCESS);
  assert.equal(findOutcome(r3, 'ip_address').consecutiveFailures, 0);
});

// ──────────────────────────────────────────────────────────────────────────
test('state push failure is recorded per sensor, retried and recovers without re-registering', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({
    register_sensor: okResponse(),
    // First two batch pushes fail at transport level, third succeeds.
    update_sensor_states: (index) =>
      index <= 2 ? new Error('socket hang up') : okResponse(),
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  const r1 = await reporter.reportRound(sampleReadings());
  assert.equal(r1.counts.push_failed, 8);
  for (const s of r1.sensors) {
    assert.equal(s.lastOutcome, OUTCOME.PUSH_FAILED);
    assert.equal(s.consecutiveFailures, 1);
    assert.match(s.lastReason, /socket hang up/);
    assert.equal(s.registered, true, 'registration itself had succeeded');
  }
  assert.equal(webhook.counts.register_sensor, 8);

  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  assert.equal(r2.counts.push_failed, 8);
  assert.equal(webhook.counts.register_sensor, 8, 'push failures do NOT cause re-registration');
  for (const s of r2.sensors) assert.equal(s.consecutiveFailures, 2);

  clock.tick();
  const r3 = await reporter.reportRound(sampleReadings());
  assert.equal(r3.counts.success, 8);
  for (const s of r3.sensors) {
    assert.equal(s.consecutiveFailures, 0);
    assert.equal(s.registerAttempts, 1, 'still registered exactly once');
  }
  assert.equal(webhook.counts.register_sensor, 8);
});

// ──────────────────────────────────────────────────────────────────────────
test('per-item push error isolates the bad sensor and forces re-registration when entity is unknown', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({
    register_sensor: okResponse(),
    update_sensor_states: (index) => {
      if (index === 1) {
        // HA rejects just one entity (e.g. lost after an HA restart).
        return {
          status: 200,
          data: { disk_usage: { success: false, error: { code: 'not_found', message: 'Sensor not found' } } },
        };
      }
      return okResponse();
    },
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  const r1 = await reporter.reportRound(sampleReadings());
  assert.equal(findOutcome(r1, 'disk_usage').lastOutcome, OUTCOME.PUSH_FAILED);
  assert.equal(findOutcome(r1, 'disk_usage').consecutiveFailures, 1);
  assert.equal(r1.counts.push_failed, 1);
  assert.equal(r1.counts.success, 7, 'the other seven sensors still report success');

  // Next round: disk_usage is re-registered (once) and then pushed OK.
  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  const diskRegCalls = webhook.callsOf('register_sensor')
    .filter((c) => c.data.unique_id === 'disk_usage').length;
  assert.equal(diskRegCalls, 2, 'lost entity gets re-registered exactly once');
  assert.equal(findOutcome(r2, 'disk_usage').lastOutcome, OUTCOME.SUCCESS);
  assert.equal(findOutcome(r2, 'disk_usage').consecutiveFailures, 0);

  // And it is not registered again on the round after recovery.
  clock.tick();
  await reporter.reportRound(sampleReadings());
  assert.equal(
    webhook.callsOf('register_sensor').filter((c) => c.data.unique_id === 'disk_usage').length,
    2,
  );
});

// ──────────────────────────────────────────────────────────────────────────
test('without webhookId every sensor is marked not_ready and nothing is sent', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({});
  let ready = false;
  const reporter = new SensorReporter({ webhookFn: webhook, isReady: () => ready, now: clock.now });

  const r1 = await reporter.reportRound(sampleReadings());
  assert.equal(r1.ready, false);
  assert.match(r1.notReadyReason, /webhookId/);
  assert.equal(r1.counts.not_ready, 8);
  for (const s of r1.sensors) {
    assert.equal(s.lastOutcome, OUTCOME.NOT_READY);
    assert.equal(s.consecutiveFailures, 0, 'not-ready is not counted as a delivery failure');
  }
  assert.equal(webhook.calls.length, 0, 'no webhook traffic before webhookId exists');

  // Once the device registration completes and a webhookId exists, normal flow.
  ready = true;
  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  assert.equal(r2.ready, true);
  assert.equal(r2.counts.success, 8);
  assert.equal(webhook.counts.register_sensor, 8);
});

// ──────────────────────────────────────────────────────────────────────────
test('sensors missing from a round are marked not_collected without breaking the rest', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({
    register_sensor: okResponse(),
    update_sensor_states: okResponse(),
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  // First round: only three readings (e.g. thermal/network collection failed).
  const partial = sampleReadings().slice(0, 3);
  const r1 = await reporter.reportRound(partial);
  assert.equal(r1.counts.success, 3);
  assert.equal(r1.counts.not_collected, 5);
  // ram_usage is the 4th catalog item, so it is guaranteed absent here.
  assert.equal(findOutcome(r1, 'ram_usage').lastOutcome, OUTCOME.NOT_COLLECTED);
  assert.match(findOutcome(r1, 'ram_usage').lastReason, /no reading collected/);
  assert.equal(findOutcome(r1, 'display_screen').lastOutcome, OUTCOME.SUCCESS);

  // Next round everything is collected again and previously unseen ones register.
  clock.tick();
  const r2 = await reporter.reportRound(sampleReadings());
  assert.equal(r2.counts.success, 8);
  assert.equal(r2.counts.not_collected, 0);
  assert.equal(webhook.counts.register_sensor, 8);
});

// ──────────────────────────────────────────────────────────────────────────
test('location push outcomes and consecutive failures are tracked', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({});
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  reporter.recordLocationOutcome(null, 'ETIMEDOUT');
  assert.equal(reporter.getStatus().location.lastOutcome, 'push_failed');
  assert.equal(reporter.getStatus().location.consecutiveFailures, 1);
  assert.match(reporter.getStatus().location.lastReason, /ETIMEDOUT/);

  reporter.recordLocationOutcome({ status: 502, data: 'bad gateway' });
  assert.equal(reporter.getStatus().location.consecutiveFailures, 2);

  clock.tick();
  reporter.recordLocationOutcome({ status: 200, data: {} });
  const loc = reporter.getStatus().location;
  assert.equal(loc.lastOutcome, 'success');
  assert.equal(loc.consecutiveFailures, 0);
  assert.equal(loc.lastReason, null);
  assert.ok(loc.lastSuccessAt);
});

// ──────────────────────────────────────────────────────────────────────────
test('getStatus exposes the latest round with per-sensor reasons and attempt counts', async () => {
  const clock = makeClock();
  const webhook = makeFakeWebhook({
    register_sensor: (index, data) =>
      data.unique_id === 'ram_usage' ? { status: 401, data: 'unauthorized' } : okResponse(),
    update_sensor_states: okResponse(),
  });
  const reporter = new SensorReporter({ webhookFn: webhook, now: clock.now });

  await reporter.reportRound(sampleReadings());
  const status = reporter.getStatus();

  assert.equal(status.round, 1);
  assert.equal(status.ready, true);
  assert.ok(status.lastRound, 'last round snapshot is available');
  const ram = status.sensors.find((s) => s.unique_id === 'ram_usage');
  assert.equal(ram.lastOutcome, OUTCOME.REGISTER_FAILED);
  assert.match(ram.lastReason, /HTTP 401/);
  assert.equal(ram.consecutiveFailures, 1);
  assert.equal(ram.registerAttempts, 1);
  assert.equal(ram.pushAttempts, 0);

  const good = status.sensors.find((s) => s.unique_id === 'cpu_usage');
  assert.equal(good.lastOutcome, OUTCOME.SUCCESS);
  assert.equal(good.pushAttempts, 1);
});
