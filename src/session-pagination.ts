import { randomBytes } from 'node:crypto';
import { z } from 'zod';
import { TwitterError } from './errors.js';

const rawPage = z.object({
  tweets: z.array(z.object({ id: z.string().regex(/^[1-9]\d{0,19}$/) }).passthrough()).max(200),
  cursor: z.string().min(1).max(4096).nullable(),
  source: z.literal('twscrape'),
  fetchedAt: z.string(),
  twscrapeVersion: z.string(),
  partial: z.boolean().optional(),
  user: z.record(z.unknown()).optional(),
});
type State = {
  binding: string;
  cursor: string | null;
  started: boolean;
  pending: Record<string, unknown>[];
  seen: Set<string>;
  cursors: Set<string>;
  meta: Record<string, unknown>;
  expiresAt: number;
  stopped: boolean;
  partial: boolean;
};

const TTL_MS = 15 * 60 * 1000;
// One call reads a bounded number of raw upstream pages and one browsing sequence
// stops at a bounded number of unique posts; neither budget is a completeness claim.
const MAX_PAGE_REQUESTS = 8;
const MAX_UNIQUE_POSTS = 5000;
const MAX_CHECKPOINTS = 32;
const MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024;

// Canonical JSON keeps binding stable across object key order and omitted undefined values.
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, item]) => item !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(',')}}`;
  }
  return JSON.stringify(value) ?? 'null';
}

function invalidCursor(message: string): TwitterError {
  return new TwitterError('INVALID_CURSOR', message);
}

// Tokens refer to bounded, process-local snapshots, never cookies or raw X responses.
export function createSessionPager(
  fetchPage: (
    operation: string,
    params: Record<string, unknown>,
    timeoutMs: number,
  ) => Promise<Record<string, unknown>>,
  timeoutMs: number,
  now = Date.now,
) {
  const states = new Map<string, { state: State; bytes: number }>();
  let bytes = 0;
  const remove = (token: string) => {
    bytes -= states.get(token)?.bytes || 0;
    states.delete(token);
  };
  return {
    clear() {
      states.clear();
      bytes = 0;
    },
    async read(operation: string, params: Record<string, unknown>) {
      for (const [token, item] of states) if (item.state.expiresAt <= now()) remove(token);
      const { nextToken, maxResults, ...filters } = params;
      // maxResults is page size, not a query condition, so continuation may change it.
      const binding = canonical({ operation, inputs: filters });
      const entry = typeof nextToken === 'string' ? states.get(nextToken) : undefined;
      // Reject before touching the upstream worker: a foreign, expired or unknown
      // checkpoint must never trigger a request with the caller's other inputs.
      if (nextToken && !entry)
        throw invalidCursor(
          'Session cursor is unknown or expired: it may be older than 15 minutes, evicted from the checkpoint cache, or issued by a previous server process. Omit nextToken and repeat the original inputs.',
        );
      if (nextToken && entry!.state.binding !== binding)
        throw invalidCursor(
          'Session cursor belongs to different inputs. Use the same operation, query, sort, username and filters, or omit nextToken and start the query again.',
        );
      const old = entry?.state;
      const state: State = old
        ? {
            binding: old.binding,
            cursor: old.cursor,
            started: old.started,
            pending: [...old.pending],
            seen: new Set(old.seen),
            cursors: new Set(old.cursors),
            meta: { ...old.meta },
            expiresAt: old.expiresAt,
            stopped: old.stopped,
            partial: old.partial,
          }
        : {
            binding,
            cursor: null,
            started: false,
            pending: [],
            seen: new Set(),
            cursors: new Set(),
            meta: {},
            expiresAt: now() + TTL_MS,
            stopped: false,
            partial: false,
          };
      const tweets: Record<string, unknown>[] = [];
      const limit = Number(maxResults);
      const deadline = now() + timeoutMs;
      let requests = 0;
      // A per-call budget stop describes this response only; it must not poison the
      // stored sequence, whose next call may still drain the remaining pages.
      let budgetStopped = false;
      while (tweets.length < limit && state.seen.size < MAX_UNIQUE_POSTS) {
        if (state.pending.length) {
          const tweet = state.pending.shift()!;
          const id = String(tweet.id);
          if (!state.seen.has(id)) {
            state.seen.add(id);
            tweets.push(tweet);
          }
          continue;
        }
        // Repeated upstream cursors (or the sequence cap) end pagination permanently.
        if (state.stopped) break;
        if (state.started && !state.cursor) break;
        if (requests >= MAX_PAGE_REQUESTS || now() >= deadline) {
          // Already-fetched items stay returned; the checkpoint remains usable.
          budgetStopped = true;
          break;
        }
        // Any thrown upstream failure leaves the stored snapshot untouched, so the
        // caller's existing nextToken can be retried without losing or duplicating items.
        const data = rawPage.safeParse(
          await fetchPage(
            operation + 'Page',
            {
              ...filters,
              ...(state.cursor ? { cursor: state.cursor } : {}),
              ...(state.meta.user ? { user: state.meta.user } : {}),
            },
            Math.max(1, deadline - now()),
          ),
        );
        if (!data.success)
          throw new TwitterError('UPSTREAM_FORMAT', 'Session page returned an unsupported shape.');
        requests++;
        const page = data.data;
        state.started = true;
        state.partial ||= Boolean(page.partial);
        // Keep the profile resolved on the first page; later pages may omit it.
        const profile = state.meta.user ?? page.user;
        state.meta = {
          source: page.source,
          fetchedAt: page.fetchedAt,
          twscrapeVersion: page.twscrapeVersion,
          ...(profile ? { user: profile } : {}),
        };
        state.pending = page.tweets;
        if (page.cursor && state.cursors.has(page.cursor)) {
          state.cursor = null;
          state.partial = true;
          state.stopped = true;
        } else {
          state.cursor = page.cursor;
          if (page.cursor) state.cursors.add(page.cursor);
        }
      }
      // A session is a bounded browsing sequence, never an unbounded archive job.
      if (state.seen.size >= MAX_UNIQUE_POSTS) {
        state.pending = [];
        state.cursor = null;
        state.stopped = true;
        state.partial = true;
      }
      // A stopped upstream cursor can still leave buffered pages to drain.
      const hasMore = state.pending.length > 0 || state.cursor !== null;
      let token: string | null = null;
      if (hasMore) {
        const size = Buffer.byteLength(
          JSON.stringify({ ...state, seen: [...state.seen], cursors: [...state.cursors] }),
        );
        if (size > MAX_CHECKPOINT_BYTES)
          throw new TwitterError(
            'UPSTREAM_FORMAT',
            'Session page exceeds the continuation memory budget.',
          );
        while (states.size >= MAX_CHECKPOINTS || bytes + size > MAX_CHECKPOINT_BYTES)
          remove(states.keys().next().value!);
        token = 'session.' + randomBytes(24).toString('base64url');
        states.set(token, { state, bytes: size });
        bytes += size;
      }
      if (operation === 'getUserTweets')
        tweets.sort((a, b) => String(b.publishedAt).localeCompare(String(a.publishedAt)));
      return {
        ...state.meta,
        ...(operation === 'searchTweets'
          ? { query: params.query, sortOrder: params.sortOrder }
          : {}),
        tweets,
        resultCount: tweets.length,
        nextToken: token,
        hasMore,
        cursorExpiresAt: token ? new Date(state.expiresAt).toISOString() : null,
        partial: state.partial || budgetStopped,
        limitReached: tweets.length === limit,
        coverage: 'bounded',
        ...(state.stopped ? { paginationStopped: true } : {}),
      };
    },
  };
}
