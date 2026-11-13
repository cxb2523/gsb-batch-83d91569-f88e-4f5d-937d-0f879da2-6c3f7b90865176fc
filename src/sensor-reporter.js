/**
 * SensorReporter — verifiable, self-healing mobile_app sensor pipeline.
 *
 * Every 60s cycle the main process collects sensor readings and hands them to
 * `reportRound()`. For each known sensor the reporter records an explicit
 * outcome:
 *
 *   - success        : registered (once) and state pushed OK
 *   - register_failed: register_sensor call failed (retried next cycles)
 *   - push_failed    : state push failed (retried next cycles)
 *   - not_collected  : no reading produced by collection this cycle
 *   - not_ready      : device has no webhookId yet, nothing can be reported
 *
 * Design guarantees:
 *   - A sensor that registered successfully is registered only ONCE. It is
 *     never re-registered (which would make the HA entity flap unavailable).
 *   - Failed registrations / pushes are retried on subsequent cycles until
 *     they succeed; consecutive failure counts are kept per sensor.
 *   - One sensor failing never interrupts the others: every sensor gets an
 *     outcome each cycle and failures are isolated.
 *   - The last round's per-sensor outcomes and failure reasons are readable
 *     via getStatus() (exposed over IPC to the settings panel).
 *
 * This module intentionally has no Electron / systeminformation dependencies
 * and takes its request function (`webhookFn`) by injection, so the whole
 * pipeline can be exercised with node:test without a real Home Assistant.
 */

'use strict';

// ── Per-sensor outcomes ──
const OUTCOME = Object.freeze({
  SUCCESS: 'success',
  REGISTER_FAILED: 'register_failed',
  PUSH_FAILED: 'push_failed',
  NOT_COLLECTED: 'not_collected',
  NOT_READY: 'not_ready',
});

// Stable catalog of every sensor the panel can report, in display order.
// Names/icons here are only used when a reading has not been collected yet
// (a real reading always carries its own registration payload).
const SENSOR_CATALOG = Object.freeze([
  { unique_id: 'display_screen', name: 'Display Screen' },
  { unique_id: 'cpu_temperature', name: 'CPU Temperature' },
  { unique_id: 'cpu_usage', name: 'CPU Usage' },
  { unique_id: 'ram_usage', name: 'RAM Usage' },
  { unique_id: 'ram_free_mb', name: 'RAM Free' },
  { unique_id: 'disk_usage', name: 'Disk Usage' },
  { unique_id: 'system_uptime', name: 'System Uptime' },
  { unique_id: 'ip_address', name: 'IP Address' },
]);

function defaultNow() { return Date.now(); }

class SensorReporter {
  /**
   * @param {object} opts
   * @param {(type: string, data: any) => Promise<object|null>} opts.webhookFn
   *   Injectable request function. Must resolve to a response shaped like
   *   { status, data } or null when the request could not be delivered.
   * @param {() => boolean} [opts.isReady]
   *   Returns false while the device has no webhookId (no reporting allowed).
   * @param {(msg: string) => void} [opts.logger]
   * @param {() => number} [opts.now]
   *   Injectable clock for deterministic timestamps in tests.
   */
  constructor({ webhookFn, isReady = () => true, logger = () => {}, now = defaultNow } = {}) {
    if (typeof webhookFn !== 'function') {
      throw new Error('SensorReporter requires a webhookFn request function');
    }
    this.webhookFn = webhookFn;
    this.isReady = isReady;
    this.log = logger;
    this.now = now;

    // unique_id -> full registration payload from the most recent reading.
    this.definitions = new Map();
    // unique_id -> per-sensor state bookkeeping.
    this.state = new Map();
    // unique_ids whose register_sensor call has succeeded at least once.
    this.registeredIds = new Set();

    this.round = 0;
    this.lastRound = null;

    // Location push (update_location) bookkeeping — separate from sensors.
    this.location = {
      lastOutcome: null,
      lastReason: null,
      consecutiveFailures: 0,
      lastAttemptAt: null,
      lastSuccessAt: null,
    };

    for (const def of SENSOR_CATALOG) this._ensureState(def.unique_id, def.name);
  }

  _ensureState(uniqueId, name) {
    if (!this.state.has(uniqueId)) {
      this.state.set(uniqueId, {
        unique_id: uniqueId,
        name: name || uniqueId,
        registered: false,
        lastOutcome: null,
        lastReason: null,
        consecutiveFailures: 0,
        registerAttempts: 0,
        pushAttempts: 0,
        lastAttemptAt: null,
        lastSuccessAt: null,
      });
    }
    return this.state.get(uniqueId);
  }

  /** Whether a sensor has a successful register_sensor behind it. */
  isRegistered(uniqueId) {
    return this.registeredIds.has(uniqueId);
  }

  /**
   * Run one full collect→register→push cycle.
   *
   * @param {Array<object>} sensors readings produced by collectSensors()
   * @returns {Promise<object>} the round summary (also stored as lastRound)
   */
  async reportRound(sensors) {
    const readings = Array.isArray(sensors) ? sensors : [];
    this.round += 1;
    const roundNo = this.round;
    const startedAt = this.now();

    const collectedIds = new Set();
    for (const sensor of readings) {
      if (!sensor || !sensor.unique_id) continue;
      collectedIds.add(sensor.unique_id);
      this.definitions.set(sensor.unique_id, sensor);
      const st = this._ensureState(sensor.unique_id, sensor.name);
      st.name = sensor.name || st.name;
    }

    // Every sensor we know about (catalog + anything seen at runtime).
    const allIds = [];
    for (const def of SENSOR_CATALOG) {
      if (!allIds.includes(def.unique_id)) allIds.push(def.unique_id);
    }
    for (const id of this.state.keys()) {
      if (!allIds.includes(id)) allIds.push(id);
    }

    // No webhookId yet: reporting is forbidden. Record an explicit, visible
    // "not ready" outcome for every sensor instead of silently skipping.
    if (!this.isReady()) {
      const results = allIds.map((id) => this._mark(id, OUTCOME.NOT_READY,
        'device not ready: webhookId missing (device registration pending)', startedAt, false));
      this.lastRound = this._buildRound(roundNo, startedAt, false,
        'webhookId missing — device registration has not completed', results);
      this.log('[Sensors] round ' + roundNo + ' not ready: no webhookId');
      return this.lastRound;
    }

    // ── Phase 1: register any sensor that is not registered yet ──
    // Per-sensor try/catch: one failure must never abort the remaining items.
    for (const sensor of readings) {
      if (!sensor || !sensor.unique_id) continue;
      const id = sensor.unique_id;
      if (this.registeredIds.has(id)) continue;

      const st = this._ensureState(id, sensor.name);
      st.registerAttempts += 1;
      st.lastAttemptAt = startedAt;
      const evalResult = await this._evalRegister(sensor);
      if (evalResult.ok) {
        this.registeredIds.add(id);
        st.registered = true;
      } else {
        this._mark(id, OUTCOME.REGISTER_FAILED, evalResult.reason, startedAt, true);
      }
    }

    // ── Phase 2: push states of the registered sensors in one batch ──
    const pushable = readings.filter((s) => s && s.unique_id && this.registeredIds.has(s.unique_id));
    const states = pushable.map((s) => ({ unique_id: s.unique_id, state: s.state, type: s.type }));
    let pushResponse = null;
    let pushError = null;
    if (states.length > 0) {
      try {
        pushResponse = await this.webhookFn('update_sensor_states', states);
      } catch (e) {
        pushError = e && e.message ? e.message : String(e);
      }
    }

    const itemErrors = this._extractItemErrors(pushResponse);

    for (const sensor of pushable) {
      const id = sensor.unique_id;
      const st = this._ensureState(id, sensor.name);
      st.pushAttempts += 1;
      st.lastAttemptAt = startedAt;

      if (pushError) {
        // Transport-level failure: nothing in the batch was delivered.
        this._mark(id, OUTCOME.PUSH_FAILED, 'update_sensor_states request failed: ' + pushError, startedAt, true);
        continue;
      }
      if (pushResponse && pushResponse.status >= 400) {
        this._mark(id, OUTCOME.PUSH_FAILED,
          'update_sensor_states HTTP ' + pushResponse.status + ': ' + this._summariseData(pushResponse.data),
          startedAt, true);
        continue;
      }
      const itemErr = itemErrors.get(id);
      if (itemErr) {
        // HA rejected this specific entity. If it says the sensor is unknown,
        // its registration was lost (e.g. HA restarted) — drop the cached
        // registration so the next cycle re-registers before re-pushing.
        if (this._needsReregister(itemErr)) {
          this.registeredIds.delete(id);
          st.registered = false;
        }
        this._mark(id, OUTCOME.PUSH_FAILED,
          'update_sensor_states rejected: ' + this._summariseData(itemErr), startedAt, true);
        continue;
      }
      this._mark(id, OUTCOME.SUCCESS, null, startedAt, false);
    }

    // Sensors whose registration failed this cycle already carry
    // REGISTER_FAILED; anything known but not collected gets NOT_COLLECTED.
    for (const id of allIds) {
      const st = this._ensureState(id);
      if (collectedIds.has(id)) continue;
      this._mark(id, OUTCOME.NOT_COLLECTED, 'no reading collected this cycle', startedAt, false);
    }

    const results = allIds.map((id) => this._publicState(this._ensureState(id)));
    this.lastRound = this._buildRound(roundNo, startedAt, true, null, results);

    const failed = results.filter((r) =>
      r.lastOutcome === OUTCOME.REGISTER_FAILED || r.lastOutcome === OUTCOME.PUSH_FAILED).length;
    this.log('[Sensors] round ' + roundNo + ': ' + results.length + ' tracked, ' +
      results.filter((r) => r.lastOutcome === OUTCOME.SUCCESS).length + ' ok, ' + failed + ' failed');

    return this.lastRound;
  }

  /**
   * Evaluate a single register_sensor call. Never throws.
   * @returns {{ok: boolean, reason: string|null}}
   */
  async _evalRegister(sensor) {
    let res = null;
    try {
      res = await this.webhookFn('register_sensor', sensor);
    } catch (e) {
      return { ok: false, reason: 'register_sensor request failed: ' + (e && e.message ? e.message : String(e)) };
    }
    if (res === null || res === undefined) {
      return { ok: false, reason: 'register_sensor request failed: no response (network error)' };
    }
    if (res.status < 200 || res.status >= 300) {
      return { ok: false, reason: 'register_sensor HTTP ' + res.status + ': ' + this._summariseData(res.data) };
    }
    // A 2xx carrying an explicit error payload is still a failure.
    const err = this._extractSingleError(res.data);
    if (err) return { ok: false, reason: 'register_sensor rejected: ' + this._summariseData(err) };
    return { ok: true, reason: null };
  }

  /**
   * Pull per-sensor errors out of an update_sensor_states response.
   * HA returns either { "<unique_id>": {success|error...}, ... } or an array
   * of per-sensor objects. Successful entries carry no error and are ignored.
   * @returns {Map<string, any>} unique_id -> error payload
   */
  _extractItemErrors(res) {
    const map = new Map();
    if (!res || res.data === undefined || res.data === null) return map;
    const data = res.data;
    if (Array.isArray(data)) {
      for (const item of data) {
        if (item && item.unique_id && this._isErrorPayload(item)) {
          map.set(item.unique_id, item);
        }
      }
    } else if (typeof data === 'object') {
      for (const [id, payload] of Object.entries(data)) {
        if (this._isErrorPayload(payload)) map.set(id, payload);
      }
    }
    return map;
  }

  _isErrorPayload(payload) {
    if (!payload || typeof payload !== 'object') return false;
    if (payload.success === false) return true;
    return payload.error !== undefined || payload.errmsg !== undefined ||
      (payload.status !== undefined && String(payload.status).toLowerCase() !== 'success');
  }

  _extractSingleError(data) {
    if (!data || typeof data !== 'object') return null;
    return this._isErrorPayload(data) ? data : null;
  }

  /**
   * Whether a push error means the entity must be re-registered
   * (mobile_app "sensor not found / needs registration" style responses).
   */
  _needsReregister(payload) {
    const text = this._summariseData(payload).toLowerCase();
    return text.includes('not found') || text.includes('unknown') ||
      text.includes('not registered') || text.includes('register');
  }

  _summariseData(data) {
    if (data === undefined || data === null) return 'no body';
    if (typeof data === 'string') return data;
    try { return JSON.stringify(data); } catch (_) { return String(data); }
  }

  /**
   * Apply an outcome to a sensor, maintaining the consecutive-failure streak.
   * NOT_COLLECTED / NOT_READY are delivery-neutral and do not touch the streak.
   */
  _mark(uniqueId, outcome, reason, at, isFailure) {
    const st = this._ensureState(uniqueId);
    st.lastOutcome = outcome;
    st.lastReason = reason || null;
    if (isFailure) {
      st.consecutiveFailures += 1;
    } else if (outcome === OUTCOME.SUCCESS) {
      st.consecutiveFailures = 0;
      st.lastSuccessAt = at;
    }
    return this._publicState(st);
  }

  _publicState(st) {
    return {
      unique_id: st.unique_id,
      name: st.name,
      registered: st.registered,
      lastOutcome: st.lastOutcome,
      lastReason: st.lastReason,
      consecutiveFailures: st.consecutiveFailures,
      registerAttempts: st.registerAttempts,
      pushAttempts: st.pushAttempts,
      lastAttemptAt: st.lastAttemptAt,
      lastSuccessAt: st.lastSuccessAt,
    };
  }

  _buildRound(roundNo, startedAt, ready, notReadyReason, results) {
    const counts = {
      success: 0,
      register_failed: 0,
      push_failed: 0,
      not_collected: 0,
      not_ready: 0,
    };
    for (const r of results) {
      if (counts[r.lastOutcome] !== undefined) counts[r.lastOutcome] += 1;
    }
    return {
      round: roundNo,
      at: startedAt,
      ready,
      notReadyReason: notReadyReason || null,
      counts,
      sensors: results,
      location: { ...this.location },
    };
  }

  /**
   * Record the outcome of the ~5-minute update_location push so the status
   * interface can report it alongside the sensor outcomes.
   */
  recordLocationOutcome(response, error) {
    this.location.lastAttemptAt = this.now();
    const failed = !!error ||
      !response || response.status === undefined || response.status < 200 || response.status >= 300;
    if (failed) {
      this.location.lastOutcome = 'push_failed';
      this.location.lastReason = error ?
        'update_location request failed: ' + error :
        'update_location HTTP ' + (response ? response.status : 'n/a') +
          ': ' + this._summariseData(response ? response.data : null);
      this.location.consecutiveFailures += 1;
    } else {
      this.location.lastOutcome = 'success';
      this.location.lastReason = null;
      this.location.consecutiveFailures = 0;
      this.location.lastSuccessAt = this.location.lastAttemptAt;
    }
    return { ...this.location };
  }

  /** Full status snapshot for the settings panel / status IPC. */
  getStatus() {
    return {
      round: this.round,
      ready: this.isReady(),
      lastRound: this.lastRound,
      registeredIds: Array.from(this.registeredIds),
      sensors: SENSOR_CATALOG.map((def) => this._publicState(this._ensureState(def.unique_id, def.name))),
      location: { ...this.location },
    };
  }
}

module.exports = { SensorReporter, OUTCOME, SENSOR_CATALOG };
