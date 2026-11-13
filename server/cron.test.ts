import { beforeEach, describe, expect, test } from 'bun:test';
import { Database } from 'bun:sqlite';
import { drizzle } from 'drizzle-orm/bun-sqlite';
import { sql } from 'drizzle-orm';
import { CronJobs, PUBLIC_NODE_TIMEOUT_MS, type PublicNodeConfig } from './cron';
import { HttpError, type HttpClient, type HttpConfig, type HttpResponse } from './http';
import * as schema from './schema';

type PostHandler = () => HttpResponse | Error;

class FakeHttpClient implements HttpClient {
  readonly calls: { url: string; body: unknown; config?: HttpConfig }[] = [];

  constructor(private readonly handlers: Map<string, PostHandler>) {}

  async get(): Promise<HttpResponse> {
    throw new Error('GET should not be used by public node probes');
  }

  async post(url: string, body?: unknown, config?: HttpConfig): Promise<HttpResponse> {
    this.calls.push({ url, body, config });
    const handler = this.handlers.get(url);
    const outcome = handler ? handler() : new Error(`No fake handler registered for ${url}`);
    if (outcome instanceof Error) throw outcome;
    return outcome;
  }
}

function createPublicNodesTable(sqlite: Database, includeDeprecated = true) {
  sqlite.run(`CREATE TABLE public_nodes (
    endpoint text,
    website text,
    websocket text,
    up integer,
    resp_time integer,
    version text,
    error text${includeDeprecated ? ',\n    deprecated integer' : ''}
  )`);
}

function createTestDatabase(includeDeprecated = true) {
  const sqlite = new Database(':memory:');
  createPublicNodesTable(sqlite, includeDeprecated);
  const database = drizzle(sqlite, { schema });
  return { sqlite, database };
}

async function rows(database: ReturnType<typeof createTestDatabase>['database']) {
  return database.select().from(schema.publicNodes);
}

const NODES: PublicNodeConfig[] = [
  { endpoint: 'https://ok.example/api', website: 'https://ok.example' },
  { endpoint: 'https://timeout.example/api' },
  { endpoint: 'https://bad-request.example/api' },
  { endpoint: 'https://unavailable.example/api', websocket: 'wss://unavailable.example/ws' },
  { endpoint: 'https://boom.example/api' },
];

function cronWithFakeHttp(handlers: Map<string, PostHandler>, database: ReturnType<typeof createTestDatabase>['database']) {
  const http = new FakeHttpClient(handlers);
  const cron = new CronJobs({ http, database });
  return { cron, http };
}

function defaultHandlers(): Map<string, PostHandler> {
  return new Map<string, PostHandler>([
    ['https://ok.example/api', () => ({ status: 200, data: { node_vendor: 'Nano Node v25.0' } })],
    [
      'https://timeout.example/api',
      () => new HttpError(`Request timed out after ${PUBLIC_NODE_TIMEOUT_MS}ms`, { code: 'ECONNABORTED' }),
    ],
    ['https://bad-request.example/api', () => new HttpError('Request failed with status code 400', {
      status: 400,
      data: { error: 'Bad Request' },
    })],
    ['https://unavailable.example/api', () => new HttpError('Request failed with status code 503', {
      status: 503,
      data: { error: 'Service Unavailable' },
    })],
    ['https://boom.example/api', () => new Error('Unexpected socket explosion')],
  ]);
}

describe('CronJobs.checkPublicNodes', () => {
  test('records a clear conclusion for success, timeout, 4xx, 5xx and unexpected errors', async () => {
    const { database } = createTestDatabase();
    const { cron, http } = cronWithFakeHttp(defaultHandlers(), database);

    const statuses = await cron.checkPublicNodes(NODES);

    // Every endpoint is probed exactly once with the version action and the 2500ms timeout.
    expect(http.calls).toHaveLength(NODES.length);
    for (const call of http.calls) {
      expect(call.body).toEqual({ action: 'version' });
      expect(call.config?.timeout).toBe(PUBLIC_NODE_TIMEOUT_MS);
      expect(PUBLIC_NODE_TIMEOUT_MS).toBe(2500);
    }

    const byEndpoint = new Map(statuses.map((status) => [status.endpoint, status]));
    const stored = await rows(database);
    expect(stored).toHaveLength(NODES.length);
    const storedByEndpoint = new Map(stored.map((row) => [row.endpoint, row]));

    // Successful probe: up, vendor version, no error.
    const ok = byEndpoint.get('https://ok.example/api')!;
    expect(ok.up).toBe(1);
    expect(ok.version).toBe('Nano Node v25.0');
    expect(ok.error).toBeNull();
    expect(ok.website).toBe('https://ok.example');
    expect(storedByEndpoint.get(ok.endpoint)!.version).toBe('Nano Node v25.0');

    // Timeout: down, no version, error mentions Timeout.
    const timedOut = byEndpoint.get('https://timeout.example/api')!;
    expect(timedOut.up).toBe(0);
    expect(timedOut.version).toBeNull();
    expect(JSON.parse(timedOut.error!).error).toContain('Timeout');

    // 4xx: node reachable, up but no version and the status code is recorded.
    const badRequest = byEndpoint.get('https://bad-request.example/api')!;
    expect(badRequest.up).toBe(1);
    expect(badRequest.version).toBeNull();
    expect(JSON.parse(badRequest.error!).error).toContain('400');

    // 5xx: down with the status code recorded.
    const unavailable = byEndpoint.get('https://unavailable.example/api')!;
    expect(unavailable.up).toBe(0);
    expect(unavailable.version).toBeNull();
    expect(JSON.parse(unavailable.error!).error).toContain('503');
    expect(unavailable.websocket).toBe('wss://unavailable.example/ws');

    // Unexpected exception: captured as a failed endpoint instead of breaking the batch.
    const crashed = byEndpoint.get('https://boom.example/api')!;
    expect(crashed.up).toBe(0);
    expect(crashed.version).toBeNull();
    expect(JSON.parse(crashed.error!).error).toContain('Unexpected socket explosion');

    // respTime is always a non-negative integer number of milliseconds.
    for (const status of statuses) {
      expect(Number.isInteger(status.respTime)).toBe(true);
      expect(status.respTime).toBeGreaterThanOrEqual(0);
    }
  });

  test('is idempotent: two runs leave one row per unique endpoint, including duplicate config entries', async () => {
    const { database } = createTestDatabase();
    const { cron } = cronWithFakeHttp(defaultHandlers(), database);
    const nodesWithDuplicates: PublicNodeConfig[] = [
      ...NODES,
      { ...NODES[0] }, // same endpoint repeated in the configuration
      { endpoint: NODES[1].endpoint, website: 'https://different-website.example' },
    ];

    await cron.checkPublicNodes(nodesWithDuplicates);
    await cron.checkPublicNodes(nodesWithDuplicates);

    const stored = await rows(database);
    const uniqueEndpoints = new Set(nodesWithDuplicates.map((node) => node.endpoint));
    expect(stored).toHaveLength(uniqueEndpoints.size);
    expect(stored).toHaveLength(NODES.length);

    const endpoints = stored.map((row) => row.endpoint);
    expect(new Set(endpoints).size).toBe(endpoints.length);
    expect([...new Set(endpoints)].sort()).toEqual([...uniqueEndpoints].sort());
  });

  test('wipes and replaces the whole table inside one transaction with no partial writes', async () => {
    const { sqlite, database } = createTestDatabase();
    const { cron } = cronWithFakeHttp(defaultHandlers(), database);

    await cron.checkPublicNodes(NODES);
    expect(await rows(database)).toHaveLength(NODES.length);

    // A trigger raises on every INSERT inside the next transaction. The DELETE and the
    // failed INSERT share one transaction, so rollback must keep the previous snapshot
    // intact (no delete-without-insert, no partial rows).
    sqlite.run(`CREATE TRIGGER fail_insert BEFORE INSERT ON public_nodes
      BEGIN SELECT RAISE(ABORT, 'forced insert failure'); END`);
    const sabotagedCron = new CronJobs({
      http: new FakeHttpClient(defaultHandlers()),
      database,
    });

    await expect(sabotagedCron.checkPublicNodes(NODES)).rejects.toThrow('forced insert failure');

    sqlite.run('DROP TRIGGER fail_insert');
    const survivors = await database.select().from(schema.publicNodes);
    expect(survivors).toHaveLength(NODES.length);
    expect(survivors.map((row) => row.endpoint).sort()).toEqual(
      NODES.map((node) => node.endpoint).sort()
    );
  });
});
