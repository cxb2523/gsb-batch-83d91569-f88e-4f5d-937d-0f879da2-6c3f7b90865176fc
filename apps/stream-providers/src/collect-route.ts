import { timingSafeEqual } from 'node:crypto';
import { z } from 'zod';
import {
  collectSearch,
  type CollectSearchOptions,
  type CollectSearchResult,
  type CollectSource,
} from './collect-search.ts';
import { createExtractorSources, type CollectSearchExtractors, type CollectSearchRuntime } from './collect-sources.ts';

/** Path served by the collective search endpoint. */
export const COLLECT_SEARCH_PATH = '/collect/search';

/** Default number of merged tracks when the caller omits `limit`. */
export const COLLECT_SEARCH_DEFAULT_LIMIT = 5;

/** Maximum caller-selectable `limit`. */
export const COLLECT_SEARCH_MAX_LIMIT = 25;

const requestSchema = z
  .object({
    query: z.string(),
    limit: z.number().int().min(1).max(COLLECT_SEARCH_MAX_LIMIT).optional(),
  })
  .strict();

/** Minimal host surface the endpoint needs; keeps the route testable without a real source host. */
export interface CollectSearchHost {
  runtime: CollectSearchRuntime;
  extractors: CollectSearchExtractors;
}

/** Options for {@link createCollectSearchHandler}. */
export interface CollectSearchHandlerOptions {
  /** Required bearer token; comparison is constant-time. */
  token: string;
  host: CollectSearchHost;
  /** Source list override, primarily for tests. Defaults to the host's loaded extractors. */
  sources?: readonly CollectSource[];
  /** Per-source deadline override. */
  timeoutMs?: number;
  /** Monotonic clock override. */
  now?: () => number;
  /** Search implementation override, primarily for tests. */
  collect?: (options: CollectSearchOptions) => Promise<CollectSearchResult>;
}

type BodyResult = { ok: true; query: string; limit: number } | { ok: false; code: 'invalid_body' | 'empty_query' };

/**
 * Build the `POST /collect/search` handler.
 *
 * Authentication runs before any validation or provider work, so unauthorized callers
 * never trigger outbound searches. Invalid bodies are rejected with 400 for the same
 * reason: no extractor is invoked until the request has been fully validated.
 */
export function createCollectSearchHandler(
  options: CollectSearchHandlerOptions,
): (request: Request) => Promise<Response> {
  const expected = Buffer.from(`Bearer ${options.token}`);
  const collect = options.collect ?? collectSearch;

  return async function handleCollectSearch(request: Request): Promise<Response> {
    // Authentication precedes method and body checks so unauthenticated callers always
    // receive 401 and can never distinguish valid from invalid request shapes.
    if (!isAuthorized(request, expected)) {
      return json({ error: { code: 'unauthorized' } }, 401);
    }

    if (request.method !== 'POST') {
      return json({ error: { code: 'method_not_allowed' } }, 405, { allow: 'POST' });
    }

    const body = await readBody(request);

    if (!body.ok) {
      return json({ error: { code: body.code } }, 400);
    }

    const sources = options.sources ?? createExtractorSources(options.host);

    try {
      const result = await collect({
        query: body.query,
        limit: body.limit,
        sources,
        ...(options.timeoutMs !== undefined ? { timeoutMs: options.timeoutMs } : {}),
        ...(options.now !== undefined ? { now: options.now } : {}),
      });

      return json(result, 200);
    } catch {
      return json({ error: { code: 'collect_failed' } }, 500);
    }
  };
}

async function readBody(request: Request): Promise<BodyResult> {
  let payload: unknown;

  try {
    payload = await request.json();
  } catch {
    return { ok: false, code: 'invalid_body' };
  }

  const parsed = requestSchema.safeParse(payload);
  if (!parsed.success) return { ok: false, code: 'invalid_body' };

  const query = parsed.data.query.trim();
  if (!query) return { ok: false, code: 'empty_query' };

  return {
    ok: true,
    query,
    limit: parsed.data.limit ?? COLLECT_SEARCH_DEFAULT_LIMIT,
  };
}

function isAuthorized(request: Request, expected: Buffer): boolean {
  const actual = Buffer.from(request.headers.get('authorization') ?? '');

  if (actual.length !== expected.length) return false;
  return timingSafeEqual(actual, expected);
}

function json(value: unknown, status: number, headers: Record<string, string> = {}): Response {
  return Response.json(value, {
    status,
    headers: { 'cache-control': 'no-store', ...headers },
  });
}
