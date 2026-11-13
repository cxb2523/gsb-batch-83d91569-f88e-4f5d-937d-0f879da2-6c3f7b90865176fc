import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import {
  DuckDuckGoFallbackError,
  searchDuckDuckGoHtml,
  searchDuckDuckGoHtmlWithTrace,
  searchDuckDuckGoLiteHtml,
  type DuckDuckGoFallbackTrace,
} from '../../src/engines/duckduckgo-html.js';
import { resolveRequestProfile, currentProfileWindowKey } from '../../src/engines/request-profiles.js';

type FetchCall = { input: RequestInfo | URL; init?: RequestInit };

function mockFetch(handler: (call: FetchCall, index: number) => Response | Promise<Response>) {
  const calls: FetchCall[] = [];
  const originalFetch = global.fetch;
  global.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const call = { input, init };
    calls.push(call);
    return handler(call, calls.length - 1);
  }) as typeof fetch;
  return { calls, restore: () => { global.fetch = originalFetch; } };
}

const liteTableWithOrganicAndAd = `
  <table>
    <tr class="result-sponsored">
      <td><a class="result-link" href="https://ads.example/course">Sponsored Course</a></td>
    </tr>
    <tr class="result-sponsored">
      <td class="result-snippet">Sponsored snippet that must be dropped</td>
    </tr>
    <tr>
      <td><a class="result-link" href="javascript:alert(1)">JavaScript Link</a></td>
    </tr>
    <tr>
      <td><a class="result-link" href="https://duckduckgo.com/y.js?ad_domain=tracked">DDG internal link</a></td>
    </tr>
    <tr>
      <td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Flite&rut=abc">Lite Result</a></td>
    </tr>
    <tr>
      <td class="result-snippet">Lite <strong>snippet</strong></td>
    </tr>
    <tr>
      <td><a class="result-link" href="https://example.com/second">Second Result</a></td>
    </tr>
    <tr>
      <td class="result-snippet">Second paired snippet</td>
    </tr>
  </table>
`;

describe('DuckDuckGo HTML → Lite fallback audit trace', () => {
  let originalFetch: typeof fetch;

  beforeEach(() => {
    originalFetch = global.fetch;
  });

  afterEach(() => {
    global.fetch = originalFetch;
  });

  it('reports primary http_202, a results outcome and the returned count after a successful Lite fallback', async () => {
    const liteHtml = `
      <table>
        <tr>
          <td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Flite&rut=abc">Lite Result</a></td>
        </tr>
        <tr>
          <td class="result-snippet">Lite snippet</td>
        </tr>
        <tr>
          <td><a class="result-link" href="https://example.com/second">Second Result</a></td>
        </tr>
        <tr>
          <td class="result-snippet">Second paired snippet</td>
        </tr>
      </table>
    `;
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response(liteHtml, { status: 200 }),
    );

    try {
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      });

      expect(outcome.results).toHaveLength(2);
      expect(outcome.fallbackTrace).toEqual({
        primaryChannelStatus: 'http_202',
        fallbackChannel: 'lite',
        fallbackOutcome: 'results',
        count: 2,
        sponsoredDropped: 0,
        unsafeLinkDropped: 0,
      } satisfies DuckDuckGoFallbackTrace);
      expect(Object.isFrozen(outcome.fallbackTrace)).toBe(true);
      expect(harness.calls.map(call => String(call.input))).toEqual([
        'https://html.duckduckgo.com/html/',
        'https://lite.duckduckgo.com/lite/',
      ]);
    } finally {
      harness.restore();
    }
  });

  it('reports an empty outcome (not a challenge) when Lite answers with no usable results', async () => {
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response('<html><body>No results here</body></html>', { status: 200 }),
    );

    try {
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      });

      expect(outcome.results).toEqual([]);
      expect(outcome.fallbackTrace).toMatchObject({
        primaryChannelStatus: 'http_202',
        fallbackChannel: 'lite',
        fallbackOutcome: 'empty',
        count: 0,
      });
    } finally {
      harness.restore();
    }
  });

  it('distinguishes a Lite #challenge-form page from an empty result page in soft mode', async () => {
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response(
            "<html><form class='gate' id = 'challenge-form'></form></html>",
            { status: 200 },
          ),
    );

    try {
      // Soft mode must not throw, but the trace still names the challenge.
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10);
      expect(outcome.results).toEqual([]);
      expect(outcome.fallbackTrace).toMatchObject({
        primaryChannelStatus: 'http_202',
        fallbackOutcome: 'challenge',
        count: 0,
      });

      // Hard mode turns the same page into the layered fallback error.
      harness.calls.length = 0;
      await expect(
        searchDuckDuckGoHtmlWithTrace('test query', 10, { throwOnError: true }),
      ).rejects.toMatchObject({
        name: 'DuckDuckGoFallbackError',
        failureType: 'bot_challenge',
        retryable: false,
        cooldownMs: 3_600_000,
        fallbackTrace: expect.objectContaining({
          primaryChannelStatus: 'http_202',
          fallbackOutcome: 'failed',
          count: 0,
        }),
      });
    } finally {
      harness.restore();
    }
  });

  it('accounts for discarded sponsored rows and non-http(s)/DDG-internal links in the trace', async () => {
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response(liteTableWithOrganicAndAd, { status: 200 }),
    );

    try {
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      });

      expect(outcome.results.map(result => result.title)).toEqual([
        'Lite Result',
        'Second Result',
      ]);
      // One sponsored title row (its snippet row is dropped with it), one
      // javascript: link and one duckduckgo.com internal link.
      expect(outcome.fallbackTrace).toMatchObject({
        fallbackOutcome: 'results',
        count: 2,
        sponsoredDropped: 1,
        unsafeLinkDropped: 2,
      });
      expect(outcome.results.every(result => result.engines?.join() === 'duckduckgo')).toBe(true);
    } finally {
      harness.restore();
    }
  });

  it('pairs each Lite snippet with its own title row so dropped ads cannot shift snippets', async () => {
    const liteHtml = `
      <table>
        <tr class="result-sponsored">
          <td><a class="result-link" href="https://ads.example/course">Sponsored Course</a></td>
        </tr>
        <tr class="result-sponsored">
          <td class="result-snippet">Sponsored snippet</td>
        </tr>
        <tr>
          <td><a class="result-link" href="https://example.com/organic">Organic Result</a></td>
        </tr>
        <tr>
          <td class="result-snippet">Organic paired snippet</td>
        </tr>
      </table>
    `;
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response(liteHtml, { status: 200 }),
    );

    try {
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      });

      expect(outcome.results).toEqual([
        expect.objectContaining({
          title: 'Organic Result',
          snippet: 'Organic paired snippet',
          url: 'https://example.com/organic',
        }),
      ]);
      expect(outcome.fallbackTrace).toMatchObject({
        sponsoredDropped: 1,
        unsafeLinkDropped: 0,
        count: 1,
      });
    } finally {
      harness.restore();
    }
  });

  it('uses one query-derived browser identity for both the HTML and Lite requests', async () => {
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response('<html><body>No results</body></html>', { status: 200 }),
    );

    try {
      await searchDuckDuckGoHtmlWithTrace('shared identity query', 10);

      expect(harness.calls).toHaveLength(2);
      const [htmlHeaders, liteHeaders] = harness.calls.map(
        call => new Headers(call.init?.headers),
      );
      const expectedProfile = resolveRequestProfile(
        'shared identity query',
        currentProfileWindowKey(),
      );
      expect(htmlHeaders.get('user-agent')).toBe(expectedProfile.userAgent);
      expect(liteHeaders.get('user-agent')).toBe(expectedProfile.userAgent);
      expect(liteHeaders.get('user-agent')).toBe(htmlHeaders.get('user-agent'));
      expect(liteHeaders.get('sec-ch-ua')).toBe(htmlHeaders.get('sec-ch-ua'));
    } finally {
      harness.restore();
    }
  });

  it('attaches no fallback trace when the HTML channel answers normally', async () => {
    const harness = mockFetch(() => new Response(
      '<html><body>No results here</body></html>',
      { status: 200 },
    ));

    try {
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10);
      expect(outcome.fallbackTrace).toBeUndefined();
      expect(harness.calls).toHaveLength(1);
    } finally {
      harness.restore();
    }
  });

  it('carries the failed Lite reason on DuckDuckGoFallbackError with the full trace', async () => {
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response('Service Unavailable', { status: 503 }),
    );

    try {
      const error = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      }).then(
        () => { throw new Error('expected rejection'); },
        reason => reason,
      );

      expect(error).toBeInstanceOf(DuckDuckGoFallbackError);
      const fallbackError = error as DuckDuckGoFallbackError;
      expect(fallbackError.message).toBe(
        'DuckDuckGo fallback failed: HTML HTTP 202 rate limit; Lite: DuckDuckGo Lite HTTP 503',
      );
      expect(fallbackError.failureType).toBe('bot_challenge');
      expect(fallbackError.retryable).toBe(false);
      expect(fallbackError.cooldownMs).toBe(3_600_000);
      expect(fallbackError.fallbackTrace).toEqual({
        primaryChannelStatus: 'http_202',
        fallbackChannel: 'lite',
        fallbackOutcome: 'failed',
        count: 0,
        sponsoredDropped: 0,
        unsafeLinkDropped: 0,
      });
    } finally {
      harness.restore();
    }
  });

  it('returns an empty soft-mode answer without throwing when Lite cannot be reached', async () => {
    const harness = mockFetch((_call, index) => {
      if (index === 0) return new Response('', { status: 202 });
      throw new Error('Lite network error');
    });

    try {
      // Layered semantics: without throwOnError the failure stays swallowed in
      // an empty answer; the structured evidence lives on the hard-mode error.
      const outcome = await searchDuckDuckGoHtmlWithTrace('test query', 10);
      expect(outcome.results).toEqual([]);
      expect(harness.calls).toHaveLength(2);

      harness.calls.length = 0;
      const error = await searchDuckDuckGoHtmlWithTrace('test query', 10, {
        throwOnError: true,
      }).then(
        () => { throw new Error('expected rejection'); },
        reason => reason,
      );
      expect(error).toBeInstanceOf(DuckDuckGoFallbackError);
      expect((error as DuckDuckGoFallbackError).fallbackTrace).toMatchObject({
        primaryChannelStatus: 'http_202',
        fallbackOutcome: 'failed',
        count: 0,
      });
      expect(harness.calls).toHaveLength(2);
    } finally {
      harness.restore();
    }
  });

  it('never starts the Lite request when the caller cancels after HTML 202', async () => {
    const controller = new AbortController();
    const harness = mockFetch(() => {
      controller.abort(new DOMException('cancelled', 'AbortError'));
      return new Response('', { status: 202 });
    });

    try {
      await expect(
        searchDuckDuckGoHtmlWithTrace('test query', 10, {
          signal: controller.signal,
          throwOnError: true,
        }),
      ).rejects.toMatchObject({ name: 'AbortError' });
      expect(harness.calls).toHaveLength(1);
      expect(String(harness.calls[0].input)).toBe('https://html.duckduckgo.com/html/');
    } finally {
      harness.restore();
    }
  });

  it('keeps the array-returning API backward compatible: no trace property leaks onto results', async () => {
    const liteHtml = `
      <table>
        <tr>
          <td><a class="result-link" href="https://example.com/only">Only Result</a></td>
        </tr>
        <tr>
          <td class="result-snippet">Only snippet</td>
        </tr>
      </table>
    `;
    const harness = mockFetch((_call, index) =>
      index === 0
        ? new Response('', { status: 202 })
        : new Response(liteHtml, { status: 200 }),
    );

    try {
      const results = await searchDuckDuckGoHtml('test query', 10, {
        throwOnError: true,
      });
      expect(Array.isArray(results)).toBe(true);
      expect(results).toHaveLength(1);
      expect((results as Record<string, unknown>).fallbackTrace).toBeUndefined();
    } finally {
      harness.restore();
    }
  });

  it('exposes the same Lite filtering through the standalone Lite entry point', async () => {
    const harness = mockFetch(() => new Response(liteTableWithOrganicAndAd, { status: 200 }));

    try {
      const results = await searchDuckDuckGoLiteHtml('test query', 10, {
        throwOnError: true,
      });
      expect(results.map(result => result.title)).toEqual([
        'Lite Result',
        'Second Result',
      ]);
      expect(harness.calls).toHaveLength(1);
      expect(String(harness.calls[0].input)).toBe('https://lite.duckduckgo.com/lite/');
    } finally {
      harness.restore();
    }
  });
});
