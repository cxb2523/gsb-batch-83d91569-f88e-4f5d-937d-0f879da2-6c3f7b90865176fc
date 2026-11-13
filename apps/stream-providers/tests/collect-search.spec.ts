import { describe, expect, it } from 'vitest';
import {
  collectSearch,
  DEFAULT_SOURCE_TIMEOUT_MS,
  type CollectSearchInput,
  type CollectSource,
  type CollectedTrack,
} from '../src/collect-search.ts';
import { createExtractorSources } from '../src/collect-sources.ts';
import { COLLECT_SEARCH_PATH, createCollectSearchHandler, type CollectSearchHost } from '../src/collect-route.ts';
import { createProviderFetch } from '../src/provider-server.ts';

const TOKEN = 'test-token-0123456789abcdef';
const AUTH = { authorization: `Bearer ${TOKEN}`, 'content-type': 'application/json' };

function track(title: string, url = `https://example.test/${encodeURIComponent(title)}`): CollectedTrack {
  return {
    id: url,
    title,
    author: 'Artist',
    duration: '03:00',
    durationMs: 180_000,
    url,
    thumbnail: '',
    live: false,
    source: 'unused',
  };
}

function source(name: string, search: CollectSource['search']): CollectSource {
  return { name, search };
}

function ok(name: string, titles: string[], artifact: { calls: string[] }): CollectSource {
  return source(name, async (_input) => {
    artifact.calls.push(name);
    return titles.map((title) => track(title));
  });
}

function failing(name: string, message: string, artifact: { calls: string[] }): CollectSource {
  return source(name, async () => {
    artifact.calls.push(name);
    throw new Error(message);
  });
}

function hanging(name: string, artifact: { calls: string[] }): CollectSource {
  return source(name, ({ signal }) => {
    artifact.calls.push(name);
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new Error('aborted by timeout')), { once: true });
    });
  });
}

function hostWithSearch(
  search: (query: string, options: { searchEngine: string }) => Promise<{ tracks: unknown[] }>,
  identifiers: string[] = ['com.discord-player.itsmaat.spotifyextractor'],
): CollectSearchHost {
  return {
    runtime: { search },
    extractors: { store: new Map(identifiers.map((id) => [id, {}])) },
  };
}

function post(body: unknown, headers: Record<string, string> = AUTH): Request {
  return new Request(`http://localhost${COLLECT_SEARCH_PATH}`, {
    method: 'POST',
    headers,
    body: typeof body === 'string' ? body : JSON.stringify(body),
  });
}

describe('collectSearch', () => {
  it('merges successful sources in order and deduplicates tracks', async () => {
    const calls: string[] = [];
    const shared = track('Shared', 'https://example.test/shared');

    const result = await collectSearch({
      query: 'daft punk',
      limit: 5,
      sources: [
        source('alpha', async () => {
          calls.push('alpha');
          return [shared, track('Alpha One')];
        }),
        failing('beta', 'catalog exploded', { calls }),
        source('gamma', async () => {
          calls.push('gamma');
          return [shared, track('Gamma One')];
        }),
      ],
    });

    expect(calls).toEqual(['alpha', 'beta', 'gamma']);
    expect(result.status).toBe('partial');
    expect(result.sourcesTried).toBe(3);
    expect(result.sourcesFailed).toBe(1);
    expect(result.sources.map((entry) => entry.name)).toEqual(['alpha', 'beta', 'gamma']);
    expect(result.sources[0]).toMatchObject({ status: 'ok', trackCount: 2 });
    expect(result.sources[1]).toMatchObject({ status: 'error', trackCount: 0, reason: 'catalog exploded' });
    expect(result.sources[2]).toMatchObject({ status: 'ok' });
    expect(result.tracks.map((entry) => entry.title)).toEqual(['Shared', 'Alpha One', 'Gamma One']);
    expect(result.tracks[0]?.source).toBe('alpha');
  });

  it('reports empty and caps merged tracks at the requested limit', async () => {
    const calls: string[] = [];
    const result = await collectSearch({
      query: 'query',
      limit: 2,
      sources: [
        source('one', async () => {
          calls.push('one');
          return [track('A'), track('B'), track('C')];
        }),
        source('two', async () => {
          calls.push('two');
          return [track('D')];
        }),
        source('three', async () => {
          calls.push('three');
          return [];
        }),
      ],
    });

    expect(result.status).toBe('ok');
    expect(result.sourcesFailed).toBe(0);
    expect(result.sources.map((entry) => entry.status)).toEqual(['ok', 'ok', 'empty']);
    expect(result.tracks).toHaveLength(2);
    expect(result.tracks.map((entry) => entry.title)).toEqual(['A', 'B']);
  });

  it('marks every timed-out source without waiting for the others', async () => {
    const calls: string[] = [];
    const result = await collectSearch({
      query: 'slow',
      limit: 5,
      timeoutMs: 20,
      sources: [hanging('first', { calls }), hanging('second', { calls }), ok('third', ['Fast'], { calls })],
    });

    expect(calls.sort()).toEqual(['first', 'second', 'third']);
    expect(result.status).toBe('partial');
    expect(result.sourcesFailed).toBe(2);
    expect(result.sources[0]).toMatchObject({ status: 'timeout', trackCount: 0 });
    expect(result.sources[0]?.reason).toContain('20 ms');
    expect(result.sources[1]).toMatchObject({ status: 'timeout' });
    expect(result.sources[2]).toMatchObject({ status: 'ok', trackCount: 1 });
    expect(result.tracks.map((entry) => entry.title)).toEqual(['Fast']);
  });

  it('reports failed when every source fails', async () => {
    const calls: string[] = [];
    const sockets = ['a', 'b', 'c', 'd'];

    const result = await collectSearch({
      query: 'nothing',
      limit: 5,
      timeoutMs: 20,
      sources: [
        failing('a', 'boom a', { calls }),
        hanging('b', { calls }),
        source('c', async () => {
          calls.push('c');
          return Promise.reject(new Error('boom c'));
        }),
        hanging('d', { calls }),
      ],
    });

    expect(calls.sort()).toEqual(sockets);
    expect(result.status).toBe('failed');
    expect(result.sourcesTried).toBe(4);
    expect(result.sourcesFailed).toBe(4);
    expect(result.sources.map((entry) => entry.status)).toEqual(['error', 'timeout', 'error', 'timeout']);
    expect(result.tracks).toEqual([]);
  });

  it('measures each source against its own start time', async () => {
    // Both sources start before either resolves, so the clock is read in this order:
    // first start, second start, first end, second end.
    const ticks = [10, 35, 100, 175];
    let index = 0;

    const result = await collectSearch({
      query: 'timed',
      limit: 5,
      now: () => ticks[Math.min(index++, ticks.length - 1)] ?? 0,
      sources: [
        source('first', async () => [track('One')]),
        source('second', async () => {
          throw new Error('nope');
        }),
      ],
    });

    expect(result.sources[0]?.durationMs).toBe(100 - 10);
    expect(result.sources[1]?.durationMs).toBe(175 - 35);
  });

  it('never reports negative elapsed time', async () => {
    const ticks = [500, 500, 400, 300];
    let index = 0;

    const result = await collectSearch({
      query: 'backwards',
      limit: 5,
      now: () => ticks[Math.min(index++, ticks.length - 1)] ?? 0,
      sources: [source('first', async () => []), source('second', async () => [track('One')])],
    });

    expect(result.sources.map((entry) => entry.durationMs)).toEqual([0, 0]);
  });

  it('defaults to an eight-second source deadline', () => {
    expect(DEFAULT_SOURCE_TIMEOUT_MS).toBe(8_000);
  });

  it('treats non-array results and unusable tracks as empty', async () => {
    const result = await collectSearch({
      query: 'weird',
      limit: 5,
      sources: [
        source('odd', async () => ({ nope: true }) as never),
        source('junk', async () => [null, 42, { unrelated: true }] as never),
      ],
    });

    expect(result.status).toBe('ok');
    expect(result.sources.map((entry) => entry.status)).toEqual(['empty', 'empty']);
    expect(result.tracks).toEqual([]);
  });

  it('passes the trimmed query, limit and a signal to each source', async () => {
    const received: CollectSearchInput[] = [];

    await collectSearch({
      query: 'search me',
      limit: 3,
      sources: [
        source('probe', async (input) => {
          received.push(input);
          return [];
        }),
      ],
    });

    expect(received[0]?.query).toBe('search me');
    expect(received[0]?.limit).toBe(3);
    expect(received[0]?.signal).toBeInstanceOf(AbortSignal);
  });
});

describe('createExtractorSources', () => {
  it('maps known extractor identifiers to provider names and preserves registration order', async () => {
    const identifiers = [
      'com.retrouser955.discord-player.discord-player-youtubei',
      'com.discord-player.itsmaat.spotifyextractor',
      'com.discord-player.applemusicextractor',
      'com.discord-player.soundcloudextractor',
    ];
    const seen: Array<{ engine: string; query: string; limit: number }> = [];

    const sources = createExtractorSources({
      runtime: {
        search: async (query, options) => {
          seen.push({ engine: options.searchEngine, query, limit: options.limit });
          return { tracks: [] };
        },
      },
      extractors: { store: new Map(identifiers.map((id) => [id, {}])) },
    });

    expect(sources.map((entry) => entry.name)).toEqual(['youtube', 'spotify', 'apple-music', 'soundcloud']);

    await Promise.all(
      sources.map((entry) => entry.search({ query: 'q', limit: 4, signal: new AbortController().signal })),
    );

    expect(seen.map((entry) => entry.engine)).toEqual(identifiers);
    expect(seen.every((entry) => entry.query === 'q' && entry.limit === 4)).toBe(true);
  });
});

describe('POST /collect/search validation and auth', () => {
  function handler(overrides: Partial<Parameters<typeof createCollectSearchHandler>[0]> = {}) {
    return createCollectSearchHandler({
      token: TOKEN,
      host: hostWithSearch(async () => ({ tracks: [] })),
      ...overrides,
    });
  }

  it('rejects requests without the bearer token before any source runs', async () => {
    let called = false;
    const handle = handler({
      sources: [
        source('only', async () => {
          called = true;
          return [];
        }),
      ],
    });

    const missing = await handle(post({ query: 'test' }, { 'content-type': 'application/json' }));
    expect(missing.status).toBe(401);
    expect(await missing.json()).toEqual({ error: { code: 'unauthorized' } });

    const wrong = await handle(post({ query: 'test' }, { authorization: 'Bearer wrong-token-value' }));
    expect(wrong.status).toBe(401);

    // Authentication wins over method and body checks.
    const wrongMethod = await handle(
      new Request(`http://localhost${COLLECT_SEARCH_PATH}`, {
        method: 'GET',
        headers: { authorization: 'Bearer nope' },
      }),
    );
    expect(wrongMethod.status).toBe(401);
    expect(called).toBe(false);
  });

  it('rejects non-POST methods for authenticated callers', async () => {
    const response = await handler()(
      new Request(`http://localhost${COLLECT_SEARCH_PATH}`, {
        method: 'GET',
        headers: { authorization: `Bearer ${TOKEN}` },
      }),
    );

    expect(response.status).toBe(405);
    expect(response.headers.get('allow')).toBe('POST');
  });

  it('rejects an empty query with 400 and does not search', async () => {
    let called = false;
    const handle = handler({
      sources: [
        source('only', async () => {
          called = true;
          return [];
        }),
      ],
    });

    for (const body of [{ query: '' }, { query: '   ' }, { query: '\n\t ' }]) {
      const response = await handle(post(body));
      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ error: { code: 'empty_query' } });
    }

    for (const body of [{ query: 42 }, { query: null }, {}]) {
      const response = await handle(post(body));
      expect(response.status).toBe(400);
      expect(await response.json()).toEqual({ error: { code: 'invalid_body' } });
    }

    expect(called).toBe(false);
  });

  it('rejects out-of-range and non-integer limits without searching', async () => {
    let called = false;
    const handle = handler({
      sources: [
        source('only', async () => {
          called = true;
          return [];
        }),
      ],
    });

    for (const limit of [0, -1, 26, 1.5, '5']) {
      const response = await handle(post({ query: 'test', limit }));
      expect(response.status).toBe(400);
    }

    expect(called).toBe(false);
  });

  it('rejects malformed JSON and unknown fields', async () => {
    const handle = handler();

    expect((await handle(post('{not json'))).status).toBe(400);
    expect((await handle(post({ query: 'test', extra: true }))).status).toBe(400);
  });

  it('defaults limit to five and accepts the boundaries', async () => {
    const seen: number[] = [];
    const handle = handler({
      sources: [
        source('only', async (input) => {
          seen.push(input.limit);
          return [];
        }),
      ],
    });

    const response = await handle(post({ query: 'test' }));
    const body = (await response.json()) as { limit: number };

    expect(response.status).toBe(200);
    expect(body.limit).toBe(5);

    expect((await handle(post({ query: 'test', limit: 1 }))).status).toBe(200);
    expect((await handle(post({ query: 'test', limit: 25 }))).status).toBe(200);
    expect(seen).toEqual([5, 1, 25]);
  });

  it('returns per-source detail with a duplicate-free merged track list', async () => {
    const handle = handler({
      sources: [
        source('first', async () => [track('Same'), track('First Only')]),
        source('second', async () => [track('Same'), track('Second Only')]),
      ],
    });

    const response = await handle(post({ query: ' mix ', limit: 3 }));
    const body = (await response.json()) as Record<string, unknown>;

    expect(response.status).toBe(200);
    expect(body.query).toBe('mix');
    expect(body.status).toBe('ok');
    expect(body.sourcesTried).toBe(2);
    expect(body.sourcesFailed).toBe(0);
    expect((body.tracks as CollectedTrack[]).map((entry) => entry.title)).toEqual([
      'Same',
      'First Only',
      'Second Only',
    ]);
  });

  it('uses the injected host runtime for the default sources', async () => {
    const engines: string[] = [];
    const handle = createCollectSearchHandler({
      token: TOKEN,
      host: hostWithSearch(async (_query, options) => {
        engines.push(options.searchEngine);
        return { tracks: [] };
      }),
    });

    const response = await handle(post({ query: 'test' }));

    expect(response.status).toBe(200);
    expect(engines).toEqual(['com.discord-player.itsmaat.spotifyextractor']);
  });

  it('reports failed with no sources when the host has no extractors loaded', async () => {
    const handle = handler({ host: hostWithSearch(async () => ({ tracks: [] }), []) });

    const response = await handle(post({ query: 'test' }));
    const body = (await response.json()) as Record<string, unknown>;

    expect(response.status).toBe(200);
    expect(body).toMatchObject({ status: 'failed', sourcesTried: 0, sourcesFailed: 0, sources: [], tracks: [] });
  });
});

describe('createProviderFetch', () => {
  function server() {
    const timeouts: Request[] = [];
    return {
      timeouts,
      server: {
        timeout: (request: Request) => {
          timeouts.push(request);
        },
      } as unknown as Bun.Server<unknown>,
    };
  }

  it('keeps health, media timeout and host forwarding behavior', async () => {
    const forwarded: string[] = [];
    const { server: bunServer, timeouts } = server();

    const fetch = createProviderFetch({
      token: TOKEN,
      host: {
        runtime: { search: async () => ({ tracks: [] }) },
        extractors: { store: new Map() },
        fetch: async (request) => {
          forwarded.push(new URL(request.url).pathname);
          return new Response('host', { status: 202 });
        },
      },
    });

    const health = await fetch(new Request('http://localhost/health'), bunServer);
    expect(health.status).toBe(200);
    expect(await health.json()).toEqual({ status: 'ok' });

    const media = new Request('http://localhost/remedia/v1/media/token');
    await fetch(media, bunServer);
    expect(timeouts).toEqual([media]);

    const other = new Request('http://localhost/.well-known/remedia');
    const response = await fetch(other, bunServer);
    expect(response.status).toBe(202);
    expect(forwarded).toEqual(['/remedia/v1/media/token', '/.well-known/remedia']);
  });

  it('serves collective search without forwarding to the host', async () => {
    let forwarded = 0;
    const { server: bunServer } = server();

    const fetch = createProviderFetch({
      token: TOKEN,
      collectTimeoutMs: 20,
      host: {
        runtime: { search: async () => ({ tracks: [] }) },
        extractors: { store: new Map() },
        fetch: async () => {
          forwarded += 1;
          return new Response('host');
        },
      },
    });

    const response = await fetch(post({ query: 'x' }), bunServer);
    expect(response.status).toBe(200);
    expect(forwarded).toBe(0);

    const unauthorized = await fetch(post({ query: 'x' }, {}), bunServer);
    expect(unauthorized.status).toBe(401);
  });
});
