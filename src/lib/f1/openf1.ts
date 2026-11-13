import { AsyncLocalStorage } from "node:async_hooks";
import { createHash } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";

// OpenF1 client: one throttled request queue per process and a disk cache under data/openf1.
// Finished sessions never change, so their responses are cached forever; calendar lists get a
// short TTL. When OpenF1 is unreachable or rate limited, a stale cached copy is served instead,
// which is what lets `npm run snapshot:f1` make the tools work offline.

export const OPENF1_BASE = "https://api.openf1.org/v1";
// OPENF1_CACHE_DIR overrides the cache root (tests use a temp dir); the layout is unchanged.
const CACHE_DIR = resolve(process.env.OPENF1_CACHE_DIR ?? resolve(process.cwd(), "data/openf1"));

// The free tier allows 3 requests per second and 30 per minute. A sliding window keeps us under
// both while still letting a single question's few requests go out in a burst.
const PER_SECOND = 3;
const PER_MINUTE = Number(process.env.OPENF1_PER_MINUTE ?? 28);
const sent: number[] = [];
let nextSlot = 0; // set after a 429 to pause the whole queue
let queue = Promise.resolve();
function takeSlot() {
  const turn = queue.then(async () => {
    for (;;) {
      const now = Date.now();
      while (sent.length && now - sent[0] > 60000) sent.shift();
      const lastSecond = sent.filter((t) => now - t < 1000).length;
      let wait = Math.max(0, nextSlot - now);
      if (sent.length >= PER_MINUTE) wait = Math.max(wait, sent[0] + 60000 - now + 50);
      if (lastSecond >= PER_SECOND) wait = Math.max(wait, sent[sent.length - PER_SECOND] + 1000 - now + 50);
      if (!wait) break;
      await new Promise((r) => setTimeout(r, wait));
    }
    sent.push(Date.now());
  });
  queue = turn.catch(() => {});
  return turn;
}

export type Params = Record<string, string | number | undefined>;

export function openf1Url(endpoint: string, params: Params = {}) {
  // OpenF1 filters look like `date>=...`, so the operator is part of the key.
  const query = Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => {
      const m = /^(.*?)(>=|<=|>|<)$/.exec(k);
      return m
        ? `${encodeURIComponent(m[1])}${m[2]}${encodeURIComponent(String(v))}`
        : `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`;
    })
    .join("&");
  return `${OPENF1_BASE}/${endpoint}${query ? `?${query}` : ""}`;
}

function endpointOf(url: string) {
  return new URL(url).pathname.split("/").pop() ?? "misc";
}

function cachePath(url: string) {
  const hash = createHash("sha1").update(url).digest("hex").slice(0, 16);
  return resolve(CACHE_DIR, endpointOf(url), `${hash}.json`);
}

type CacheEntry = { url: string; fetchedAt: number; final: boolean; data: unknown[] };

async function readCache(path: string): Promise<CacheEntry | null> {
  try {
    return JSON.parse(await readFile(path, "utf8")) as CacheEntry;
  } catch {
    return null;
  }
}

const inflight = new Map<string, Promise<unknown[]>>();
const memory = new Map<string, CacheEntry>();

// ── Fetch provenance ─────────────────────────────────────────────────────
// Every openf1() call reports how its data was obtained, so a tool result can say whether it
// came from a fresh cache, a live fetch, an empty answer, a stale fallback or a failure — the
// difference between "this session has no data" and "OpenF1 couldn't be reached just now".

export type FetchState = "cache" | "fetched" | "empty" | "stale" | "failed";

export interface FetchRecord {
  state: FetchState;
  url: string;
  endpoint: string;
  /** When the served data was originally fetched (absent for "failed"). */
  fetchedAt?: number;
  /** The served copy may be out of date (a stale fallback after a network failure). */
  stale?: boolean;
  /** Why the request failed (state "failed"). */
  reason?: string;
}

/** How a tool result's data was obtained, summarised from its FetchRecords. */
export interface SourceStatus {
  /** failed > stale > fetched > cache; "empty" when every request came back empty (a normal 404). */
  state: FetchState;
  /** Oldest served copy (ms epoch); for "stale", how old the fallback data is. */
  fetchedAt?: number;
  /** True when part of the result is a stale fallback that may be out of date. */
  stale?: boolean;
  /** Why fetching failed (state "failed"). */
  reason?: string;
  /** One entry per distinct request the tool made. */
  requests: FetchRecord[];
}

const fetchLog = new AsyncLocalStorage<FetchRecord[]>();

/** Run `fn` with every OpenF1 fetch it makes recorded into `log` (see summarizeFetches). */
export function withFetchLog<T>(log: FetchRecord[], fn: () => T): T {
  return fetchLog.run(log, fn);
}

function recordFetch(record: FetchRecord) {
  fetchLog.getStore()?.push(record);
}

/** Collapse a tool's fetch records into the `source` status attached to its result. */
export function summarizeFetches(fetches: FetchRecord[]): SourceStatus {
  // A URL shared by concurrent callers can record once per caller; keep one entry per state+url.
  const seen = new Set<string>();
  const requests = fetches.filter((r) => {
    const key = `${r.state} ${r.url}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const times = requests.map((r) => r.fetchedAt).filter((t): t is number => t !== undefined);
  const fetchedAt = times.length ? Math.min(...times) : undefined;
  const failed = requests.find((r) => r.state === "failed");
  if (failed) return { state: "failed", reason: failed.reason, fetchedAt, requests };
  const stale = requests.filter((r) => r.state === "stale");
  if (stale.length) {
    const staleTimes = stale.map((r) => r.fetchedAt).filter((t): t is number => t !== undefined);
    return { state: "stale", stale: true, fetchedAt: staleTimes.length ? Math.min(...staleTimes) : undefined, requests };
  }
  // "Empty" only when nothing served any data: an empty endpoint next to served rows is normal.
  if (requests.length && requests.every((r) => r.state === "empty")) return { state: "empty", fetchedAt, requests };
  if (requests.some((r) => r.state === "fetched")) return { state: "fetched", fetchedAt, requests };
  return { state: "cache", fetchedAt, requests };
}

export interface FetchOptions {
  /** The data can no longer change (a finished session). Cached forever. */
  final?: boolean;
  /** Seconds a non-final cached copy stays fresh (default 10 minutes). */
  ttl?: number;
  signal?: AbortSignal;
  /** Serve only from cache; never hit the network. */
  offline?: boolean;
}

export class OpenF1Error extends Error {}

/** GET an OpenF1 endpoint. A 404 "No results found" is an empty list, not an error. */
export async function openf1<T = Record<string, unknown>>(
  endpoint: string,
  params: Params = {},
  options: FetchOptions = {},
): Promise<T[]> {
  const url = openf1Url(endpoint, params);
  const path = cachePath(url);
  const ttlMs = (options.ttl ?? 600) * 1000;
  const cached = memory.get(url) ?? (await readCache(path));
  if (cached) memory.set(url, cached);
  const fresh =
    cached && (cached.final || options.offline || Date.now() - cached.fetchedAt < ttlMs);
  if (fresh && cached) {
    recordFetch({ state: "cache", url, endpoint, fetchedAt: cached.fetchedAt });
    return cached.data as T[];
  }
  if (options.offline) {
    recordFetch({ state: "failed", url, endpoint, reason: `Not in the local snapshot: ${url}` });
    throw new OpenF1Error(`Not in the local snapshot: ${url}`);
  }

  // Concurrent callers of the same URL share one network request; the request itself records
  // the outcome, so it is logged exactly once no matter how many callers await it.
  const pending = inflight.get(url);
  if (pending) return pending as Promise<T[]>;
  const request = (async () => {
    try {
      const data = await fetchWithRetry(url, options.signal);
      const entry: CacheEntry = { url, fetchedAt: Date.now(), final: !!options.final, data };
      memory.set(url, entry);
      // Hosts with a read-only filesystem (e.g. Vercel) keep the in-memory copy only.
      try {
        await mkdir(dirname(path), { recursive: true });
        const tmp = `${path}.${process.pid}.tmp`;
        await writeFile(tmp, JSON.stringify(entry));
        await rename(tmp, path);
      } catch {}
      // A 404 or an empty array is a normal "no data", not a failure.
      recordFetch({ state: data.length ? "fetched" : "empty", url, endpoint, fetchedAt: entry.fetchedAt });
      return data;
    } catch (error) {
      if (cached) {
        // Stale beats nothing — but say so: this copy may be out of date.
        recordFetch({ state: "stale", url, endpoint, fetchedAt: cached.fetchedAt, stale: true });
        return cached.data;
      }
      recordFetch({ state: "failed", url, endpoint, reason: error instanceof Error ? error.message : String(error) });
      throw error;
    } finally {
      inflight.delete(url);
    }
  })();
  inflight.set(url, request);
  return request as Promise<T[]>;
}

async function fetchWithRetry(url: string, signal?: AbortSignal): Promise<unknown[]> {
  // OPENF1_BACKOFF_MS shortens the retry pause in tests; production keeps 4s, doubling per retry.
  let backoff = Math.max(50, Number(process.env.OPENF1_BACKOFF_MS ?? 4000));
  for (let attempt = 0; ; attempt++) {
    await takeSlot();
    signal?.throwIfAborted();
    let response: Response;
    try {
      response = await fetch(url, {
        signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(45000)]) : AbortSignal.timeout(45000),
        headers: { accept: "application/json" },
      });
    } catch (error) {
      if (attempt >= 2 || signal?.aborted) throw new OpenF1Error(`OpenF1 unreachable: ${String(error)}`);
      await new Promise((r) => setTimeout(r, backoff));
      backoff *= 2;
      continue;
    }
    if (response.status === 404) return [];
    if (response.status === 429 || response.status >= 500) {
      if (attempt >= 4) throw new OpenF1Error(`OpenF1 HTTP ${response.status}. Try again shortly.`);
      const retryAfter = Number(response.headers.get("retry-after"));
      // Push the whole queue back, so other requests wait too.
      const pause = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : backoff;
      nextSlot = Math.max(nextSlot, Date.now() + pause);
      backoff *= 2;
      continue;
    }
    if (!response.ok) throw new OpenF1Error(`OpenF1 HTTP ${response.status} for ${url}`);
    const body = (await response.json()) as unknown;
    if (!Array.isArray(body)) return [];
    return body;
  }
}
