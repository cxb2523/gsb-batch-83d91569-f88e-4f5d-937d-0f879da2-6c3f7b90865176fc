import { strict as assert } from 'node:assert';
import test from 'node:test';
import handler, {
  ALLOWED_DOMAINS,
  FEED_OUTCOME,
  fetchFeedOutcome,
} from './rss-proxy.js';

const SAMPLE_RSS =
  '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Test</title><item><title>Hello</title></item></channel></rss>';

const ORIGINAL_FETCH = globalThis.fetch;

function restoreFetch() {
  globalThis.fetch = ORIGINAL_FETCH;
}

function makeProxyRequest(feedUrl) {
  const params = feedUrl === undefined ? '' : `?url=${encodeURIComponent(feedUrl)}`;
  return new Request(`https://chainscope.local/api/rss-proxy${params}`, {
    headers: { origin: 'http://localhost:5173' },
  });
}

function xmlResponse(body, status = 200, headers = {}) {
  return new Response(body, {
    status,
    headers: { 'content-type': 'application/xml', ...headers },
  });
}

function redirectResponse(location, status = 301) {
  return new Response(null, {
    status,
    headers: { location },
  });
}

/** A fetch stand-in that serves canned responses per URL and never hits the network. */
function createFetchStub(routes, { throwsFor = [] } = {}) {
  const calls = [];
  const stub = async (input, init) => {
    const target = String(input instanceof Request ? input.url : input);
    calls.push({ url: target, init });
    const thrower = throwsFor.find((entry) => entry.match(target));
    if (thrower) throw thrower.error;
    const route = routes[target] ?? routes['*'];
    if (!route) throw new Error(`unexpected fetch for ${target}`);
    return typeof route === 'function' ? route(target, init) : route;
  };
  stub.calls = calls;
  return stub;
}

test('success returns raw XML with unchanged cache headers and success status', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({ [feedUrl]: xmlResponse(SAMPLE_RSS) });

  try {
    const response = await handler(makeProxyRequest(feedUrl));
    assert.equal(response.status, 200);
    const body = await response.text();
    assert.equal(body, SAMPLE_RSS);
    assert.equal(response.headers.get('content-type'), 'application/xml');
    assert.equal(
      response.headers.get('cache-control'),
      'public, max-age=300, s-maxage=300, stale-while-revalidate=60',
    );
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.SUCCESS);
    assert.equal(Number(response.headers.get('x-feed-duration-ms')) >= 0, true);
    assert.equal(response.headers.get('access-control-allow-origin'), 'http://localhost:5173');
  } finally {
    restoreFetch();
  }
});

test('structured outcome reports requested url, category, status, redirect and duration', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({ [feedUrl]: xmlResponse(SAMPLE_RSS) });

  try {
    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.ok, true);
    assert.equal(outcome.category, FEED_OUTCOME.SUCCESS);
    assert.equal(outcome.feedUrl, feedUrl);
    assert.equal(outcome.url, feedUrl);
    assert.equal(outcome.status, 200);
    assert.equal(outcome.error, null);
    assert.equal(outcome.redirected, false);
    assert.equal(outcome.finalUrl, feedUrl);
    assert.deepEqual(outcome.redirectChain, []);
    assert.equal(typeof outcome.durationMs, 'number');
    assert.equal(outcome.durationMs >= 0, true);
    assert.equal(outcome.body, SAMPLE_RSS);
  } finally {
    restoreFetch();
  }
});

test('upstream 500 returns empty RSS, 200, and an upstream-error status header', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({ [feedUrl]: xmlResponse('boom', 500) });

  try {
    const response = await handler(makeProxyRequest(feedUrl));
    assert.equal(response.status, 200);
    const body = await response.text();
    assert.equal(body.includes('<rss version="2.0">'), true);
    assert.equal(body.includes('<item>'), false);
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.UPSTREAM_ERROR);
    assert.equal(response.headers.get('x-feed-upstream-status'), '500');
    assert.equal(
      response.headers.get('cache-control'),
      'public, max-age=120, s-maxage=120, stale-while-revalidate=60',
    );
  } finally {
    restoreFetch();
  }
});

test('structured outcome distinguishes upstream 404 from 500 while keeping the status code', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';

  for (const [status, body] of [[404, 'gone'], [503, 'unavailable']]) {
    globalThis.fetch = createFetchStub({ [feedUrl]: xmlResponse(body, status) });
    try {
      const outcome = await fetchFeedOutcome(feedUrl);
      assert.equal(outcome.ok, false);
      assert.equal(outcome.category, FEED_OUTCOME.UPSTREAM_ERROR);
      assert.equal(outcome.status, status);
      assert.equal(typeof outcome.error, 'string');
      assert.equal(outcome.body, null);
    } finally {
      restoreFetch();
    }
  }
});

test('timeout is classified as timeout, not as a generic error', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  const abortError = new Error('The operation was aborted.');
  abortError.name = 'AbortError';

  // Honour the abort signal so the helper's own timeout path is exercised.
  globalThis.fetch = async (_input, init = {}) =>
    new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(abortError));
    });

  try {
    // A short explicit timeout keeps the test fast.
    const response = await handler(makeProxyRequest(feedUrl), { timeoutMs: 25 });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.TIMEOUT);
  } finally {
    restoreFetch();
  }
});

test('fetchFeedOutcome honours an explicit timeout and reports timeout category', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  const abortError = new Error('The operation was aborted.');
  abortError.name = 'AbortError';

  globalThis.fetch = async (_input, init = {}) =>
    new Promise((_resolve, reject) => {
      init.signal?.addEventListener('abort', () => reject(abortError));
    });

  try {
    const outcome = await fetchFeedOutcome(feedUrl, { timeoutMs: 25 });
    assert.equal(outcome.ok, false);
    assert.equal(outcome.category, FEED_OUTCOME.TIMEOUT);
    assert.equal(outcome.feedUrl, feedUrl);
    assert.equal(outcome.status, null);
    assert.equal(typeof outcome.error, 'string');
    assert.equal(outcome.durationMs >= 20, true);
  } finally {
    restoreFetch();
  }
});

test('network failure is classified separately from timeout', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';

  globalThis.fetch = async () => {
    throw new TypeError('fetch failed');
  };

  try {
    const response = await handler(makeProxyRequest(feedUrl));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.NETWORK_ERROR);

    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.NETWORK_ERROR);
    assert.equal(outcome.status, null);
    assert.equal(outcome.error, 'fetch failed');
  } finally {
    restoreFetch();
  }
});

test('redirect outside the allowlist is reported as redirect-not-allowed', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({
    [feedUrl]: redirectResponse('https://untrusted.example.com/feed.xml'),
  });

  try {
    const response = await handler(makeProxyRequest(feedUrl));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.REDIRECT_NOT_ALLOWED);
    assert.equal(response.headers.get('x-feed-upstream-status'), '301');
    assert.equal(response.headers.get('x-feed-final-url'), 'https://untrusted.example.com/feed.xml');

    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.REDIRECT_NOT_ALLOWED);
    assert.equal(outcome.redirected, true);
    assert.equal(outcome.status, 301);
    assert.equal(outcome.finalUrl, 'https://untrusted.example.com/feed.xml');
    assert.deepEqual(outcome.redirectChain, ['https://untrusted.example.com/feed.xml']);
  } finally {
    restoreFetch();
  }
});

test('allowed redirect is followed, recorded, and fetched once more', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  const redirectUrl = 'https://feeds.capi24.com/news/rss.xml';
  const stub = createFetchStub({
    [feedUrl]: redirectResponse(redirectUrl, 302),
    [redirectUrl]: xmlResponse(SAMPLE_RSS),
  });
  globalThis.fetch = stub;

  try {
    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.SUCCESS);
    assert.equal(outcome.redirected, true);
    assert.equal(outcome.finalUrl, redirectUrl);
    assert.deepEqual(outcome.redirectChain, [redirectUrl]);
    assert.equal(outcome.status, 200);
    assert.equal(stub.calls.length, 2);
    assert.equal(stub.calls[1].init.redirect, 'manual');
  } finally {
    restoreFetch();
  }
});

test('redirect target with a non-http protocol is rejected', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({
    [feedUrl]: redirectResponse('file:///etc/passwd'),
  });

  try {
    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.REDIRECT_NOT_ALLOWED);
    assert.equal(outcome.redirected, true);
  } finally {
    restoreFetch();
  }
});

test('domain not in the allowlist is rejected with 403 and its own category', async () => {
  let fetchCalled = false;
  globalThis.fetch = async () => {
    fetchCalled = true;
    return xmlResponse(SAMPLE_RSS);
  };

  try {
    const response = await handler(makeProxyRequest('https://evil.example.com/feed.xml'));
    assert.equal(response.status, 403);
    assert.equal(fetchCalled, false);
    const body = await response.json();
    assert.equal(body.error, 'Domain not allowed');

    const outcome = await fetchFeedOutcome('https://evil.example.com/feed.xml');
    assert.equal(outcome.category, FEED_OUTCOME.DOMAIN_NOT_ALLOWED);
    assert.equal(outcome.ok, false);
    assert.equal(outcome.status, null);
    assert.equal(typeof outcome.error, 'string');
  } finally {
    restoreFetch();
  }
});

test('non-http protocol is rejected with 400 before any fetch', async () => {
  let fetchCalled = false;
  globalThis.fetch = async () => {
    fetchCalled = true;
    return xmlResponse(SAMPLE_RSS);
  };

  try {
    const response = await handler(makeProxyRequest('file:///etc/passwd'));
    assert.equal(response.status, 400);
    assert.equal(fetchCalled, false);
    const body = await response.json();
    assert.equal(body.error, 'Invalid protocol');

    const outcome = await fetchFeedOutcome('ftp://feeds.bbci.co.uk/news/rss.xml');
    assert.equal(outcome.category, FEED_OUTCOME.INVALID_PROTOCOL);
    assert.equal(fetchCalled, false);
  } finally {
    restoreFetch();
  }
});

test('missing url still returns 400 and CORS preflight is untouched', async () => {
  globalThis.fetch = async () => {
    throw new Error('fetch should not be called');
  };

  try {
    const missing = await handler(makeProxyRequest(undefined));
    assert.equal(missing.status, 400);

    const preflight = await handler(
      new Request('https://chainscope.local/api/rss-proxy', {
        method: 'OPTIONS',
        headers: { origin: 'http://localhost:5173' },
      }),
    );
    assert.equal(preflight.status, 204);
    assert.equal(preflight.headers.get('access-control-allow-origin'), 'http://localhost:5173');
    assert.equal(preflight.headers.get('access-control-allow-methods'), 'GET, OPTIONS');
  } finally {
    restoreFetch();
  }
});

test('unparseable url degrades to an empty feed with its own category', async () => {
  globalThis.fetch = async () => {
    throw new Error('fetch should not be called');
  };

  try {
    const response = await handler(makeProxyRequest('not a url'));
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('x-feed-status'), FEED_OUTCOME.INVALID_URL);

    const outcome = await fetchFeedOutcome('not a url');
    assert.equal(outcome.category, FEED_OUTCOME.INVALID_URL);
    assert.equal(outcome.status, null);
    assert.equal(outcome.feedUrl, 'not a url');
  } finally {
    restoreFetch();
  }
});

test('redirect without a location is reported as an upstream error', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  globalThis.fetch = createFetchStub({
    [feedUrl]: new Response(null, { status: 302 }),
  });

  try {
    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.UPSTREAM_ERROR);
    assert.equal(outcome.status, 302);
    assert.equal(outcome.redirected, false);
  } finally {
    restoreFetch();
  }
});

test('a redirect loop stops instead of fetching forever', async () => {
  const feedUrl = 'https://feeds.bbci.co.uk/news/rss.xml';
  const stub = createFetchStub({
    [feedUrl]: redirectResponse(feedUrl, 302),
  });
  globalThis.fetch = stub;

  try {
    const outcome = await fetchFeedOutcome(feedUrl);
    assert.equal(outcome.category, FEED_OUTCOME.NETWORK_ERROR);
    assert.equal(outcome.redirected, true);
    // initial request + MAX_REDIRECTS hops
    assert.equal(stub.calls.length, 6);
  } finally {
    restoreFetch();
  }
});

test('success and every failure category are distinct values', () => {
  const categories = Object.values(FEED_OUTCOME);
  assert.equal(new Set(categories).size, categories.length);
  assert.equal(categories.includes(FEED_OUTCOME.SUCCESS), true);
  assert.equal(categories.includes(FEED_OUTCOME.DOMAIN_NOT_ALLOWED), true);
  assert.equal(categories.includes(FEED_OUTCOME.INVALID_PROTOCOL), true);
  assert.equal(categories.includes(FEED_OUTCOME.REDIRECT_NOT_ALLOWED), true);
  assert.equal(categories.includes(FEED_OUTCOME.UPSTREAM_ERROR), true);
  assert.equal(categories.includes(FEED_OUTCOME.TIMEOUT), true);
  assert.equal(categories.includes(FEED_OUTCOME.NETWORK_ERROR), true);
});

test('allowlist still contains its documented security entries', () => {
  for (const domain of ['feeds.bbci.co.uk', 'news.google.com', 'cryptopotato.com']) {
    assert.equal(ALLOWED_DOMAINS.includes(domain), true, `missing ${domain}`);
  }
});
