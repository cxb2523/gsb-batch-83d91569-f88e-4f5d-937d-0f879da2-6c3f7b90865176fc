// Map URL pagination and waitTillDone, against a local stub of the API. No API key or credits needed.
import {createServer, Server} from 'node:http';
import {AddressInfo} from 'node:net';
import {IncomingMessage, ServerResponse} from 'node:http';

import Olostep from '../src/index.js';

const KEY = 'olostep_test_key_abcdefghijklmnop1234';

type Handler = (req: IncomingMessage, res: ServerResponse, url: URL) => void;

let server: Server;
let baseUrl: string;
let handler: Handler;
let requests: {method?: string; path: string}[];

const reply = (res: ServerResponse, body: unknown, status = 200) => {
  res.writeHead(status, {'content-type': 'application/json'});
  res.end(JSON.stringify(body));
};

beforeAll(async () => {
  server = createServer((req, res) => {
    const url = new URL(req.url ?? '', 'http://localhost');
    requests.push({method: req.method, path: url.pathname + url.search});
    req.resume();
    req.on('end', () => handler(req, res, url));
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
});

afterAll(() => {
  server.closeAllConnections();
  server.close();
});

beforeEach(() => {
  requests = [];
  handler = (_req, res) => reply(res, {message: 'unexpected request'}, 500);
});

const client = () =>
  new Olostep({apiKey: KEY, apiBaseUrl: baseUrl, retry: {maxRetries: 0, initialDelayMs: 1}});

const collect = async (iterator: AsyncGenerator<string>): Promise<string[]> => {
  const urls: string[] = [];
  for await (const url of iterator) {
    urls.push(url);
  }
  return urls;
};

describe('client.maps.urls()', () => {
  test('paginates with a cursor, in order, without repeats', async () => {
    handler = (_req, res, url) => {
      expect(url.pathname).toBe('/v1/maps/map_1/urls');
      const cursor = url.searchParams.get('cursor');
      if (cursor === null) {
        // First page: `urls` field, `next_cursor` points at page two.
        reply(res, {urls: ['https://example.com/a', 'https://example.com/b'], next_cursor: 'page-2'});
      } else if (cursor === 'page-2') {
        // Second page: `items` field and a null `cursor` end the stream.
        reply(res, {items: ['https://example.com/c'], cursor: null});
      } else {
        reply(res, {message: `unexpected cursor ${cursor}`}, 500);
      }
    };

    const urls = await collect(client().maps.urls('map_1'));

    expect(urls).toEqual(['https://example.com/a', 'https://example.com/b', 'https://example.com/c']);
    expect(new Set(urls).size).toBe(urls.length);
    expect(requests).toHaveLength(2);
  });

  test('sends limit=50 by default and honours batchSize', async () => {
    const limits: (string | null)[] = [];
    handler = (_req, res, url) => {
      limits.push(url.searchParams.get('limit'));
      reply(res, {urls: [], next_cursor: null});
    };

    await collect(client().maps.urls('map_1'));
    await collect(client().maps.urls('map_1', {batchSize: 7}));
    await collect(client().maps.urls('map_1', {batch_size: 3}));

    expect(limits).toEqual(['50', '7', '3']);
  });

  test('stops when the cursor does not advance instead of repeating a page', async () => {
    handler = (_req, res, url) => {
      const cursor = url.searchParams.get('cursor');
      if (cursor === null) {
        reply(res, {urls: ['https://example.com/a'], next_cursor: 'same'});
      } else {
        // The server keeps returning the same cursor: the page must not be re-emitted.
        reply(res, {urls: ['https://example.com/b'], next_cursor: 'same'});
      }
    };

    const urls = await collect(client().maps.urls('map_1'));

    expect(urls).toEqual(['https://example.com/a', 'https://example.com/b']);
    expect(requests).toHaveLength(2);
  });

  test('an empty first page ends the stream immediately', async () => {
    handler = (_req, res) => reply(res, {urls: [], next_cursor: 'page-2'});

    const urls = await collect(client().maps.urls('map_1'));

    expect(urls).toEqual([]);
    expect(requests).toHaveLength(1);
  });
});

describe('Map handle urls()', () => {
  test('serves URLs inlined in the creation response without extra requests', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_1', urls: ['https://example.com/a', 'https://example.com/b']});
      } else {
        reply(res, {message: 'unexpected request'}, 500);
      }
    };

    const map = await client().maps.create('https://example.com');
    const urls = await collect(map.urls());

    expect(urls).toEqual(['https://example.com/a', 'https://example.com/b']);
    expect(requests).toHaveLength(1);
  });

  test('waits for completion, then paginates, when the creation response has no urls', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_2', urls_count: 2, has_more: false});
      } else if (url.pathname === '/v1/maps/map_2') {
        reply(res, {id: 'map_2', status: 'completed'});
      } else if (url.pathname === '/v1/maps/map_2/urls') {
        const cursor = url.searchParams.get('cursor');
        if (cursor === null) {
          reply(res, {urls: ['https://example.com/a'], next_cursor: 'page-2'});
        } else {
          reply(res, {urls: ['https://example.com/b'], next_cursor: null});
        }
      } else {
        reply(res, {message: 'unexpected request'}, 500);
      }
    };

    const map = await client().maps.create('https://example.com');
    const urls = await collect(map.urls());

    expect(urls).toEqual(['https://example.com/a', 'https://example.com/b']);
    // create + one status poll + two url pages
    expect(requests).toHaveLength(4);
    expect(requests[1]).toMatchObject({method: 'GET', path: '/v1/maps/map_2'});
  });

  test('waitForCompletion: false skips the status poll', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_3'});
      } else if (url.pathname === '/v1/maps/map_3/urls') {
        reply(res, {items: ['https://example.com/a'], cursor: null});
      } else {
        reply(res, {message: 'unexpected request'}, 500);
      }
    };

    const map = await client().maps.create('https://example.com');
    const urls = await collect(map.urls({waitForCompletion: false}));

    expect(urls).toEqual(['https://example.com/a']);
    expect(requests).toHaveLength(2);
    expect(requests.some((r) => r.path === '/v1/maps/map_3')).toBe(false);
  });

  test('an empty page ends the stream immediately', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_4'});
      } else {
        reply(res, {urls: []});
      }
    };

    const map = await client().maps.create('https://example.com');
    const urls = await collect(map.urls({waitForCompletion: false}));

    expect(urls).toEqual([]);
    expect(requests).toHaveLength(2);
  });
});

describe('waitTillDone', () => {
  test('client.maps.waitTillDone polls until the map completes', async () => {
    let polls = 0;
    handler = (_req, res) => {
      polls += 1;
      reply(res, {id: 'map_5', status: polls < 3 ? 'in_progress' : 'completed'});
    };

    await expect(
      client().maps.waitTillDone('map_5', {checkEveryNSecs: 0.01, timeoutSeconds: 30})
    ).resolves.toBeUndefined();
    expect(polls).toBe(3);
  });

  test('Map.waitTillDone returns on a failed map too', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_6'});
      } else {
        reply(res, {id: 'map_6', status: 'failed'});
      }
    };

    const map = await client().maps.create('https://example.com');
    await expect(
      map.waitTillDone({check_every_n_secs: 0.01, timeout_seconds: 30})
    ).resolves.toBeUndefined();
  });

  test('throws with the elapsed time when the map never finishes', async () => {
    handler = (_req, res) => reply(res, {id: 'map_7', status: 'in_progress'});

    const error = await client()
      .maps.waitTillDone('map_7', {checkEveryNSecs: 0.01, timeoutSeconds: 0.05})
      .catch((err) => err);

    expect(error).toBeInstanceOf(Error);
    expect(error.message).toMatch(/^waitTillDone timed out after \d+\.\d{2}s \(timeout: 0\.05s\)$/);
    expect(requests.length).toBeGreaterThan(1);
  });

  test('Map.waitTillDone times out the same way', async () => {
    handler = (_req, res, url) => {
      if (url.pathname === '/v1/maps') {
        reply(res, {id: 'map_8'});
      } else {
        reply(res, {id: 'map_8', status: 'in_progress'});
      }
    };

    const map = await client().maps.create('https://example.com');
    await expect(
      map.waitTillDone({checkEveryNSecs: 0.01, timeoutSeconds: 0.05})
    ).rejects.toThrow(/^waitTillDone timed out after .* \(timeout: 0\.05s\)$/);
  });
});
