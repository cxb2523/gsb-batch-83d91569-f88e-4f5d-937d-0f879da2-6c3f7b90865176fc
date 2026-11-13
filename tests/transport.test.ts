// Error handling, retries and the User-Agent, against a local stub of the API. No API key or credits needed.
import {createServer, Server} from 'node:http';
import {AddressInfo} from 'node:net';
import {readFileSync} from 'node:fs';

import Olostep from '../src/index.js';
import {SDK_VERSION} from '../src/config.js';
import {
  OlostepAPIConnectionError,
  OlostepServerAuthFailed,
  OlostepServerBlacklistedDomain,
  OlostepServerCreditsExhausted,
  OlostepServerInvalidEndpointCalled,
  OlostepServerResourceNotFound,
  OlostepServerTemporaryIssue
} from '../src/errors.js';

const KEY = 'olostep_test_key_abcdefghijklmnop1234';

type Reply = {status: number; body: unknown};
let server: Server;
let baseUrl: string;
let replies: Reply[];
let requests: {path: string; userAgent?: string}[];

beforeAll(async () => {
  server = createServer((req, res) => {
    requests.push({path: req.url ?? '', userAgent: req.headers['user-agent']});
    req.resume();
    req.on('end', () => {
      const reply = replies.length > 1 ? replies.shift()! : replies[0];
      res.writeHead(reply.status, {'content-type': 'application/json'});
      res.end(JSON.stringify(reply.body));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
});

afterAll(() => {
  server.closeAllConnections();
  server.close();
});

beforeEach(() => {
  replies = [];
  requests = [];
});

const client = (options: Record<string, unknown> = {}) =>
  new Olostep({apiKey: KEY, apiBaseUrl: baseUrl, retry: {maxRetries: 3, initialDelayMs: 1}, ...options});

// API errors stay wrapped in OlostepAPIConnectionError with the specific error in details.cause, as in 1.2.2,
// so existing catch blocks keep working.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const causeOf = (error: unknown): any => (error as OlostepAPIConnectionError).details?.cause;

describe('error handling', () => {
  test('an invalid key is reported as an auth failure, without leaking the key', async () => {
    replies = [{status: 401, body: {invalid_api_key: true, message: 'Your API key is invalid.'}}];
    const error = await client().scrapes.create({url: 'https://example.com'}).catch((err) => err);

    expect(error).toBeInstanceOf(OlostepAPIConnectionError);
    expect(causeOf(error)).toBeInstanceOf(OlostepServerAuthFailed);
    expect(error.message).toMatch(/^Olostep API request failed \(POST \/scrapes\): The Olostep API rejected API key/);
    expect(error.message).not.toMatch(/blacklisted|Failed to reach/i);
    expect(error.message).toContain('1234');
    expect(error.message).not.toContain('olostep_test_key');
    expect(JSON.stringify(causeOf(error).details)).not.toContain('olostep_test_key');
  });

  test('an invalid key in the newer error format is also an auth failure', async () => {
    replies = [{status: 401, body: {object: 'error', code: 'invalid_api_key', status: 401}}];
    const error = await client().batches.info('batch_1').catch((err) => err);

    expect(causeOf(error)).toBeInstanceOf(OlostepServerAuthFailed);
  });

  test('any other 401 is still reported as a blacklisted domain', async () => {
    replies = [{status: 401, body: {message: 'This domain is not allowed.'}}];
    const error = await client().scrapes.create({url: 'https://blocked.example'}).catch((err) => err);

    expect(causeOf(error)).toBeInstanceOf(OlostepServerBlacklistedDomain);
  });

  test('an unknown route is reported as an invalid endpoint, not a missing resource', async () => {
    replies = [{status: 404, body: {object: 'error', code: 'not_found', status: 404, title: 'route not found', metadata: {}}}];
    const error = await client().scrapes.create({url: 'https://example.com'}).catch((err) => err);

    expect(causeOf(error)).toBeInstanceOf(OlostepServerInvalidEndpointCalled);
    expect(requests).toHaveLength(1);
  });

  test('a missing batch is still a missing resource', async () => {
    replies = [{status: 404, body: {object: 'error', code: 'not_found', status: 404, title: 'batch not found', metadata: {resource: 'batch', id: 'batch_1'}}}];
    const error = await client().batches.info('batch_1').catch((err) => err);

    expect(causeOf(error)).toBeInstanceOf(OlostepServerResourceNotFound);
  });

  test('a missing resource is not retried', async () => {
    replies = [{status: 404, body: {error_code: 'not_found'}}];
    const started = Date.now();
    const error = await client({retry: {maxRetries: 3, initialDelayMs: 1000}})
      .batches.info('batch_missing')
      .catch((err) => err);

    expect(error).toBeInstanceOf(OlostepAPIConnectionError);
    expect(causeOf(error)).toBeInstanceOf(OlostepServerResourceNotFound);
    expect(requests).toHaveLength(1);
    expect(Date.now() - started).toBeLessThan(900);
  });

  test('temporary server errors are retried, then reported with the real reason', async () => {
    replies = [{status: 503, body: {message: 'busy'}}];
    const error = await client().scrapes.create({url: 'https://example.com'}).catch((err) => err);

    expect(error).toBeInstanceOf(OlostepAPIConnectionError);
    expect(causeOf(error)).toBeInstanceOf(OlostepServerTemporaryIssue);
    expect(requests).toHaveLength(4);
  });

  test('sporadic unprocessable (400) and rate-limit (429) responses are retried', async () => {
    replies = [
      {status: 400, body: {message: 'sporadic validation error'}},
      {status: 429, body: {message: 'slow down'}},
      {status: 200, body: {id: 'scrape_1', result: {markdown_content: 'ok'}}}
    ];
    const result = await client().scrapes.create({url: 'https://example.com'});

    expect(result.id).toBe('scrape_1');
    expect(requests).toHaveLength(3);
  });

  test('exhausted credits are not retried', async () => {
    replies = [{status: 402, body: {usage_limit_reached: true, message: 'You have consumed all available credits.'}}];
    const error = await client().scrapes.create({url: 'https://example.com'}).catch((err) => err);

    expect(causeOf(error)).toBeInstanceOf(OlostepServerCreditsExhausted);
    expect(error.message).toContain('consumed all available credits');
    expect(requests).toHaveLength(1);
  });

  test('a server error followed by success returns the result', async () => {
    replies = [
      {status: 502, body: {}},
      {status: 200, body: {id: 'scrape_1', result: {markdown_content: 'ok'}}}
    ];
    const result = await client().scrapes.create({url: 'https://example.com'});

    expect(result.id).toBe('scrape_1');
    expect(requests).toHaveLength(2);
  });

  test('an unreachable API is still reported as a connection error', async () => {
    const error = await client({apiBaseUrl: 'http://127.0.0.1:9/v1', retry: {maxRetries: 1, initialDelayMs: 1}})
      .scrapes.create({url: 'https://example.com'})
      .catch((err) => err);

    expect(error).toBeInstanceOf(OlostepAPIConnectionError);
    expect(error.message).toMatch(/^Failed to reach Olostep API/);
  });
});

describe('User-Agent', () => {
  test('carries the SDK version from its own package.json', async () => {
    const {version} = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    replies = [{status: 200, body: {id: 'scrape_1', result: {markdown_content: 'ok'}}}];
    await client().scrapes.create({url: 'https://example.com'});

    expect(SDK_VERSION).toBe(version);
    expect(requests[0].userAgent).toBe(`olostep-sdk/${version}`);
  });
});
