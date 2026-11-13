/** Per-source outcome of a collective search. */
export type CollectSourceStatus = 'ok' | 'empty' | 'error' | 'timeout';

/** Aggregate outcome across every attempted source. */
export type CollectSearchStatus = 'ok' | 'partial' | 'failed';

/** One queryable provider. Sources are injected so tests never touch the network. */
export interface CollectSource {
  /** Stable provider name used in the response and as track provenance. */
  name: string;
  /** Run one provider search. Rejections and slow responses are contained per source. */
  search(input: CollectSearchInput): Promise<readonly unknown[]>;
}

/** Input passed to an individual provider search. */
export interface CollectSearchInput {
  /** Trimmed, non-empty search text. */
  query: string;
  /** Caller-requested result count. */
  limit: number;
  /** Aborted when this source exceeds its own timeout. */
  signal: AbortSignal;
}

/** Normalized track data returned by the collection endpoint. */
export interface CollectedTrack {
  id: string;
  title: string;
  author: string;
  duration: string;
  durationMs: number;
  url: string;
  thumbnail: string;
  live: boolean;
  /** Provider name that produced this track. */
  source: string;
}

/** Diagnostic details for one attempted source. */
export interface CollectSourceOutcome {
  name: string;
  status: CollectSourceStatus;
  /** Wall-clock time spent on this source, independent of the others. */
  durationMs: number;
  /** Tracks returned by the source before cross-source deduplication. */
  trackCount: number;
  /** Short failure description for `error` and `timeout` outcomes. */
  reason?: string;
}

/** Response payload of a collective search. */
export interface CollectSearchResult {
  query: string;
  limit: number;
  status: CollectSearchStatus;
  sourcesTried: number;
  sourcesFailed: number;
  /** One entry per source, in declaration order. */
  sources: CollectSourceOutcome[];
  /** Merged results in source order, deduplicated, capped at `limit`. */
  tracks: CollectedTrack[];
}

/** Options for {@link collectSearch}. */
export interface CollectSearchOptions {
  query: string;
  limit: number;
  sources: readonly CollectSource[];
  /** Per-source deadline; defaults to {@link DEFAULT_SOURCE_TIMEOUT_MS}. */
  timeoutMs?: number;
  /** Monotonic clock override, primarily for tests. */
  now?: () => number;
}

/** A source slower than this is reported as `timeout` without delaying the rest. */
export const DEFAULT_SOURCE_TIMEOUT_MS = 8_000;

const TIMED_OUT = Symbol('collect-search.timeout');

interface SourceRun {
  outcome: CollectSourceOutcome;
  tracks: CollectedTrack[];
}

/**
 * Search every source independently and merge the successful results.
 *
 * Sources run concurrently, each with its own timer and abort signal. A rejection, a
 * non-array response or a timeout only affects that source's entry; the remaining
 * sources still finish and contribute tracks.
 */
export async function collectSearch(options: CollectSearchOptions): Promise<CollectSearchResult> {
  const timeoutMs = options.timeoutMs ?? DEFAULT_SOURCE_TIMEOUT_MS;
  const now = options.now ?? (() => performance.now());

  const runs = await Promise.all(
    options.sources.map((source) => runSource(source, { query: options.query, limit: options.limit }, timeoutMs, now)),
  );

  const tracks: CollectedTrack[] = [];
  const seen = new Set<string>();

  merge: for (const run of runs) {
    for (const track of run.tracks) {
      if (tracks.length >= options.limit) break merge;

      const key = dedupeKey(track);
      if (seen.has(key)) continue;

      seen.add(key);
      tracks.push(track);
    }
  }

  const sources = runs.map((run) => run.outcome);
  const sourcesFailed = sources.filter((source) => source.status === 'error' || source.status === 'timeout').length;

  return {
    query: options.query,
    limit: options.limit,
    status: aggregateStatus(sources.length, sourcesFailed),
    sourcesTried: options.sources.length,
    sourcesFailed,
    sources,
    tracks,
  };
}

async function runSource(
  source: CollectSource,
  input: Pick<CollectSearchInput, 'query' | 'limit'>,
  timeoutMs: number,
  now: () => number,
): Promise<SourceRun> {
  const started = now();
  const controller = new AbortController();

  let timer: ReturnType<typeof setTimeout> | undefined;

  const timeout = new Promise<typeof TIMED_OUT>((resolve) => {
    timer = setTimeout(() => {
      controller.abort(new Error(`Search timed out after ${timeoutMs} ms`));
      resolve(TIMED_OUT);
    }, timeoutMs);
  });

  try {
    const value = await Promise.race([
      Promise.resolve().then(() =>
        source.search({ query: input.query, limit: input.limit, signal: controller.signal }),
      ),
      timeout,
    ]);

    const durationMs = elapsed(now, started);

    if (value === TIMED_OUT) {
      return timedOut(source.name, durationMs, timeoutMs);
    }

    const tracks = Array.isArray(value)
      ? value.map((track) => toCollectedTrack(track, source.name)).filter((track) => track !== null)
      : [];

    return {
      outcome: {
        name: source.name,
        status: tracks.length > 0 ? 'ok' : 'empty',
        durationMs,
        trackCount: tracks.length,
      },
      tracks,
    };
  } catch (error) {
    const durationMs = elapsed(now, started);

    // A source that honors the abort signal rejects instead of racing the timer.
    if (controller.signal.aborted) {
      return timedOut(source.name, durationMs, timeoutMs);
    }

    return {
      outcome: {
        name: source.name,
        status: 'error',
        durationMs,
        trackCount: 0,
        reason: describeError(error),
      },
      tracks: [],
    };
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}

function timedOut(name: string, durationMs: number, timeoutMs: number): SourceRun {
  return {
    outcome: {
      name,
      status: 'timeout',
      durationMs,
      trackCount: 0,
      reason: `Search timed out after ${timeoutMs} ms`,
    },
    tracks: [],
  };
}

function aggregateStatus(sourcesTried: number, sourcesFailed: number): CollectSearchStatus {
  if (sourcesTried === 0 || sourcesFailed === sourcesTried) return 'failed';
  return sourcesFailed > 0 ? 'partial' : 'ok';
}

function elapsed(now: () => number, started: number): number {
  return Math.max(0, Math.round(now() - started));
}

function toCollectedTrack(value: unknown, source: string): CollectedTrack | null {
  if (!value || typeof value !== 'object') return null;

  const record = value as Record<string, unknown>;
  const title = asText(record.title);
  const url = asText(record.url);

  if (!title && !url) return null;

  return {
    id: asText(record.id),
    title,
    author: asText(record.author),
    duration: asText(record.duration),
    durationMs: asDurationMs(record),
    url,
    thumbnail: asText(record.thumbnail),
    live: record.live === true,
    source,
  };
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asDurationMs(record: Record<string, unknown>): number {
  const value = record.durationMs ?? record.durationMS;
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.round(value) : 0;
}

function dedupeKey(track: CollectedTrack): string {
  const url = track.url.trim();
  if (url) return `url:${url}`;

  const title = track.title.trim().toLowerCase();
  const author = track.author.trim().toLowerCase();
  return `meta:${title}\u0000${author}`;
}

function describeError(error: unknown): string {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : 'Unknown source error';
  const compact = message.replace(/\s+/g, ' ').trim();

  if (!compact) return 'Unknown source error';
  return compact.length > 300 ? `${compact.slice(0, 297)}...` : compact;
}
