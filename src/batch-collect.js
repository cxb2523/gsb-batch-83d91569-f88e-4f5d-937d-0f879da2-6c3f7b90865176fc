/**
 * batch-collect.js – Browser-side batch collection across every saved Proxy.
 *
 * A single batch reads all saved profiles (storage.loadProfiles) and pulls
 * GET /1/summary for each one through the existing, audited api.request
 * wrapper, so every request keeps the same guarantees:
 *
 *   - read-only (GET, no body) and same-origin checks,
 *   - the 8s timeout / abort handling inside api.request,
 *   - per-profile Authorization header built from that profile's token,
 *   - token-masked debug logging (api.request never logs credentials).
 *
 * Isolation rules implemented here:
 *   - Each profile is collected in its own try/catch. A timeout, HTTP error
 *     or invalid JSON for one profile never prevents the others from
 *     completing, and never rejects the whole batch.
 *   - A failed collection records a failure result but does NOT touch the
 *     profile's last *successful* summary, so stale data can never be
 *     presented as a fresh result.
 *   - Only one batch runs at a time. Re-triggering collection while a batch
 *     is in flight returns the same in-flight promise instead of stacking
 *     duplicate requests; within a batch every profile is requested once.
 *
 * The module is a factory so tests get an isolated collector with an
 * injected fetch-backed request function, in-memory profiles and a
 * deterministic clock. main.js uses the shared default singleton.
 */

import { request } from "./api.js";
import { loadProfiles } from "./storage.js";

/**
 * Turn any thrown api.request error into a short, human-readable Chinese
 * reason. Raw response bodies and parser internals are never surfaced —
 * api.request already strips those, and we only re-label its messages.
 *
 * @param {unknown} error
 * @returns {string}
 */
export function describeCollectionError(error) {
  if (!error || typeof error !== "object") {
    return "采集失败：未知错误";
  }
  if (error.name === "TimeoutError") {
    return "采集超时：Proxy 在规定时间内没有响应";
  }
  if (error.name === "AbortError" || error.name === "CancellationError") {
    return "采集请求已取消";
  }
  if (typeof error.status === "number") {
    return `Proxy 返回错误：HTTP ${error.status}`;
  }
  switch (error.message) {
    case "Invalid JSON response from Proxy API":
      return "Proxy 返回了无法解析的 JSON 数据";
    case "API configuration missing":
      return "该配置缺少有效的 API 地址";
    case "API request URL must stay on the configured proxy origin":
      return "该配置的 API 地址超出了允许的同源范围";
    case "Dashboard API client is read-only":
      return "只读客户端不允许该请求";
    default:
      break;
  }
  if (error instanceof TypeError) {
    // A fetch network failure (DNS, CORS, connection refused) arrives as a
    // TypeError; keep the browser's short message without any credentials.
    return `无法连接到 Proxy：${error.message || "网络请求失败"}`;
  }
  if (typeof error.message === "string" && error.message.length > 0) {
    return `采集失败：${error.message}`;
  }
  return "采集失败：未知错误";
}

/**
 * @typedef {object} CollectionResult
 * @property {string}  profileId   Profile this conclusion belongs to.
 * @property {string}  profileName Profile display name captured at collection time.
 * @property {boolean} ok          Whether /1/summary was fetched and parsed.
 * @property {number}  collectedAt Epoch ms when this attempt ran.
 * @property {object}  [summary]   Parsed summary, present only when ok === true.
 * @property {string}  [reason]    Readable failure reason, present only when ok === false.
 */

/**
 * @typedef {object} CollectionBatch
 * @property {number} startedAt
 * @property {number} finishedAt
 * @property {number} total
 * @property {number} succeeded
 * @property {number} failed
 * @property {CollectionResult[]} results One conclusion per profile, in profile order.
 */

/**
 * Create an isolated batch collector.
 *
 * @param {object} [deps]
 * @param {(path: string, options?: object, configOverride?: object) => Promise<object>} [deps.requestFn]
 *        Defaults to the audited api.request; tests inject a fetch-backed stub.
 * @param {() => Array<object>} [deps.getProfiles]
 *        Defaults to storage.loadProfiles; tests inject an in-memory list.
 * @param {() => number} [deps.now] Clock, injectable for deterministic tests.
 */
export function createBatchCollector({
  requestFn = request,
  getProfiles = loadProfiles,
  now = () => Date.now(),
} = {}) {
  /** @type {Map<string, CollectionResult>} Latest attempt result per profile (success or failure). */
  const lastResults = new Map();
  /** @type {Map<string, {summary: object, collectedAt: number, profileName: string}>} Last success only. */
  const lastSuccess = new Map();
  /** @type {CollectionBatch | null} */
  let lastBatch = null;
  /** @type {Promise<CollectionBatch> | null} */
  let inFlight = null;

  /**
   * Collect one profile. Never rejects: every transport/parse failure is
   * converted into a failure result so Promise.all cannot be torn down by
   * a single bad proxy.
   *
   * @param {object} profile
   * @returns {Promise<CollectionResult>}
   */
  async function collectOne(profile) {
    const collectedAt = now();
    try {
      // Address this specific profile without changing the active profile in
      // storage. The third argument is an api.request config override, which
      // is still subject to its same-origin, read-only and timeout checks.
      const summary = await requestFn(
        "/1/summary",
        {},
        { apiUrl: profile.apiUrl, apiToken: profile.apiToken },
      );
      const result = {
        profileId: profile.id,
        profileName: profile.name,
        ok: true,
        collectedAt,
        summary,
      };
      // Success updates both the latest conclusion and the last-success store.
      lastSuccess.set(profile.id, {
        profileName: profile.name,
        summary,
        collectedAt,
      });
      lastResults.set(profile.id, result);
      return result;
    } catch (error) {
      const result = {
        profileId: profile.id,
        profileName: profile.name,
        ok: false,
        collectedAt,
        reason: describeCollectionError(error),
      };
      // Record the failure as the latest conclusion, but deliberately do NOT
      // touch lastSuccess: the previous good summary must remain available
      // and clearly labelled as an older successful collection.
      lastResults.set(profile.id, result);
      return result;
    }
  }

  /**
   * Run one batch over every saved profile. Concurrent across profiles,
   * isolated per profile. Reuses the in-flight batch when called again
   * before it settles, so duplicate triggers never stack requests.
   *
   * @returns {Promise<CollectionBatch>}
   */
  function collectAll() {
    if (inFlight) return inFlight;

    const startedAt = now();
    const batchPromise = (async () => {
      let targets = [];
      try {
        const profiles = getProfiles() || [];
        // Defensive de-duplication: storage normally guarantees unique IDs,
        // but a batch must never issue two concurrent requests for one ID.
        const seen = new Set();
        for (const profile of profiles) {
          if (!profile || typeof profile.id !== "string" || seen.has(profile.id)) {
            continue;
          }
          seen.add(profile.id);
          targets.push(profile);
        }
      } catch (error) {
        // Unreadable profile store: finish as an empty, failed-to-read batch
        // instead of throwing out of an event handler.
        const emptyBatch = {
          startedAt,
          finishedAt: now(),
          total: 0,
          succeeded: 0,
          failed: 0,
          results: [],
          readError: describeCollectionError(error),
        };
        lastBatch = emptyBatch;
        return emptyBatch;
      }

      // Every profile is settled independently; collectOne never rejects,
      // so one slow/dead proxy cannot drag down the others.
      const results = await Promise.all(targets.map(profile => collectOne(profile)));
      const succeeded = results.filter(result => result.ok).length;
      const batch = {
        startedAt,
        finishedAt: now(),
        total: results.length,
        succeeded,
        failed: results.length - succeeded,
        results,
      };
      lastBatch = batch;
      return batch;
    })();

    // Clear the in-flight slot regardless of outcome. collectOne swallows
    // per-profile errors, so this branch is mainly defensive.
    inFlight = batchPromise;
    batchPromise.finally(() => {
      if (inFlight === batchPromise) inFlight = null;
    });
    return batchPromise;
  }

  return {
    collectAll,
    /** @returns {CollectionBatch | null} */
    getLastBatch: () => lastBatch,
    /** @returns {CollectionResult | null} Latest attempt (success or failure) for a profile. */
    getLastResult: profileId => lastResults.get(profileId) ?? null,
    /** @returns {{summary: object, collectedAt: number, profileName: string} | null} Last successful collection only. */
    getLastSuccess: profileId => lastSuccess.get(profileId) ?? null,
    /** @returns {boolean} */
    isCollecting: () => inFlight !== null,
    /** Clear all retained conclusions. Intended for tests and logout. */
    reset() {
      lastResults.clear();
      lastSuccess.clear();
      lastBatch = null;
      inFlight = null;
    },
  };
}

/** Shared singleton used by the dashboard UI. */
export const batchCollector = createBatchCollector();
