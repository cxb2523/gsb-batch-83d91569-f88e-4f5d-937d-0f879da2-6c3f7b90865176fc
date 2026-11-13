import type { Dispatcher } from 'undici';
import type { Mock } from 'vitest';
import { describe, expect, test, vi, beforeEach } from 'vitest';
import { Transport } from '../src/core/transport';
import { ScrapeRouter } from '../src/api/scrape/router';
import { AmazonAPI } from '../src/api/scrape/amazon';
import { ScrapeResult } from '../src/models/result';
import { APIError, ValidationError } from '../src/utils/errors';
import { API_ENDPOINT } from '../src/utils/constants';
import type { SnapshotOperations } from '../src/types/datasets';

const mockRequest = vi.spyOn(Transport.prototype, 'request');

function makeTransport(): Transport {
    return new Transport({ apiKey: 'test_token_1234567890abcdef' });
}

function mockResponse(
    statusCode: number,
    body: unknown,
): Dispatcher.ResponseData {
    return {
        statusCode,
        headers: {},
        trailers: {},
        opaque: null,
        context: {},
        body: {
            text: () =>
                Promise.resolve(
                    typeof body === 'string' ? body : JSON.stringify(body),
                ),
        },
    } as unknown as Dispatcher.ResponseData;
}

type SnapshotScript =
    | { kind: 'success'; data: unknown }
    | { kind: 'timeout' } // never reaches a terminal status
    | { kind: 'fetchError'; error: Error } // ready status, fetch keeps failing
    | { kind: 'raceThenSuccess'; data: unknown }; // ready, 202 once, then data

interface ScriptedSnapshot {
    id: string;
    url: string;
    script: SnapshotScript;
    fetchCalls: number;
}

/**
 * Build a router whose trigger endpoint hands out scripted snapshots and
 * whose snapshot status/fetch endpoints play each script out. No real network
 * traffic is ever produced.
 */
function setupScriptedRouter(scripts: Record<string, SnapshotScript>) {
    const snapshots = new Map<string, ScriptedSnapshot>();
    let nextId = 0;

    mockRequest.mockImplementation(async (url, opts) => {
        const target = String(url);

        if (target === API_ENDPOINT.SCRAPE_ASYNC) {
            // Async triggers send a bare input array; sync mode wraps it in
            // { input }. Accept both shapes.
            const parsed = JSON.parse(
                (opts?.body as string | undefined) ?? '{}',
            ) as Array<{ url?: string }> | { input?: Array<{ url?: string }> };
            const records = Array.isArray(parsed) ? parsed : parsed.input;
            const itemUrl = records?.[0]?.url ?? '';
            const script = scripts[itemUrl];
            if (!script) {
                throw new APIError(
                    `no scripted snapshot for ${itemUrl}`,
                    500,
                );
            }
            const id = `snap_${++nextId}`;
            snapshots.set(id, {
                id,
                url: itemUrl,
                script,
                fetchCalls: 0,
            });
            return mockResponse(200, { snapshot_id: id });
        }

        if (target.includes('/snapshot/')) {
            const id = decodeURIComponent(
                target.split('/snapshot/')[1]!.split('?')[0]!,
            );
            const snap = snapshots.get(id)!;
            snap.fetchCalls += 1;

            switch (snap.script.kind) {
                case 'success':
                    return mockResponse(200, snap.script.data);
                case 'raceThenSuccess':
                    if (snap.fetchCalls === 1) {
                        // SnapshotAPI#fetch consumes the 202 body then throws
                        // DataNotReadyError, which toResult() must retry.
                        return mockResponse(202, 'not ready');
                    }
                    return mockResponse(200, snap.script.data);
                case 'fetchError':
                    throw snap.script.error;
                case 'timeout':
                    throw new Error('unreachable: timeout never fetches');
            }
        }

        if (target.includes('/progress/')) {
            const id = decodeURIComponent(
                target.split('/progress/')[1]!.split('?')[0]!,
            );
            const snap = snapshots.get(id)!;
            const status =
                snap.script.kind === 'timeout' ? 'running' : 'ready';
            return mockResponse(200, {
                snapshot_id: id,
                dataset_id: 'gd_l7q7dkf244hwjntr0',
                status,
            });
        }

        throw new APIError(`unexpected request to ${target}`, 500);
    });

    const router = new ScrapeRouter({ transport: makeTransport() });
    return { router, snapshots };
}

const URLS = {
    ok: 'https://www.amazon.com/dp/B000OK1',
    slow: 'https://www.amazon.com/dp/B000SLOW',
    broken: 'https://www.amazon.com/dp/B000FAIL',
    racy: 'https://www.amazon.com/dp/B000RACE',
} as const;

describe('AmazonAPI.productsSettled', () => {
    beforeEach(() => {
        mockRequest.mockReset();
    });

    test('returns an independent result per URL with mixed outcomes', async () => {
        const { router } = setupScriptedRouter({
            [URLS.ok]: {
                kind: 'success',
                data: [{ title: 'Product OK', price: 12.34 }],
            },
            [URLS.slow]: { kind: 'timeout' },
            [URLS.broken]: {
                kind: 'fetchError',
                error: new APIError('snapshot download failed [HTTP500]', 500),
            },
        });

        const results = await router.amazon.productsSettled(
            [URLS.ok, URLS.slow, URLS.broken],
            { pollInterval: 5, pollTimeout: 80 },
        );

        expect(results).toHaveLength(3);
        expect(results.every((r) => r instanceof ScrapeResult)).toBe(true);
        // Input order is preserved.
        expect(results.map((r) => r.url)).toEqual([
            URLS.ok,
            URLS.slow,
            URLS.broken,
        ]);

        const [ok, slow, broken] = [
            results[0]!,
            results[1]!,
            results[2]!,
        ];

        // Success: data is retained.
        expect(ok.success).toBe(true);
        expect(ok.status).toBe('ready');
        expect(ok.data).toEqual([{ title: 'Product OK', price: 12.34 }]);
        expect(ok.error).toBeNull();
        expect(ok.snapshotId).toBeTruthy();
        expect(ok.platform).toBe('amazon');

        // Timeout is a timeout-class outcome, not a plain error.
        expect(slow.success).toBe(false);
        expect(slow.status).toBe('timeout');
        expect(slow.data).toBeNull();
        expect(slow.error).toBeTruthy();
        expect(slow.url).toBe(URLS.slow);

        // Fetch error is an error-class outcome with a visible reason.
        expect(broken.success).toBe(false);
        expect(broken.status).toBe('error');
        expect(broken.data).toBeNull();
        expect(broken.error).toContain('snapshot download failed');
        expect(broken.url).toBe(URLS.broken);

        // One snapshot was triggered per URL — no batch-wide abort.
        const triggerCalls = mockRequest.mock.calls.filter(
            ([url]) => String(url) === API_ENDPOINT.SCRAPE_ASYNC,
        );
        expect(triggerCalls).toHaveLength(3);
    });

    test('keeps retrying on the ready-but-not-ready race and still succeeds', async () => {
        const { router, snapshots } = setupScriptedRouter({
            [URLS.racy]: {
                kind: 'raceThenSuccess',
                data: [{ title: 'Racy Product' }],
            },
            [URLS.ok]: {
                kind: 'success',
                data: [{ title: 'Other Product' }],
            },
        });

        const results = await router.amazon.productsSettled(
            [URLS.racy, URLS.ok],
            { pollInterval: 5, pollTimeout: 2000 },
        );

        const racy = results.find((r) => r.url === URLS.racy)!;
        expect(racy.success).toBe(true);
        expect(racy.status).toBe('ready');
        expect(racy.data).toEqual([{ title: 'Racy Product' }]);

        // The first fetch hit the 202 race and was retried via toResult().
        const racySnap = [...snapshots.values()].find(
            (s) => s.url === URLS.racy,
        )!;
        expect(racySnap.fetchCalls).toBe(2);
    });

    test('a failed trigger for one URL does not affect the others', async () => {
        let nextId = 0;
        mockRequest.mockImplementation(async (url, opts) => {
            if (String(url) === API_ENDPOINT.SCRAPE_ASYNC) {
                const parsed = JSON.parse(
                    (opts?.body as string | undefined) ?? '{}',
                ) as
                    | Array<{ url?: string }>
                    | { input?: Array<{ url?: string }> };
                const records = Array.isArray(parsed)
                    ? parsed
                    : parsed.input;
                const itemUrl = records?.[0]?.url ?? '';
                if (itemUrl === URLS.broken) {
                    throw new APIError('trigger rejected [HTTP422]', 422);
                }
                return mockResponse(200, {
                    snapshot_id: `snap_ok_${++nextId}`,
                });
            }
            if (String(url).includes('/progress/')) {
                const id = String(url).split('/progress/')[1] ?? '';
                return mockResponse(200, {
                    snapshot_id: id,
                    dataset_id: 'gd_l7q7dkf244hwjntr0',
                    status: 'ready',
                });
            }
            return mockResponse(200, [{ title: 'Product OK' }]);
        });

        const router = new ScrapeRouter({ transport: makeTransport() });
        const results = await router.amazon.productsSettled(
            [URLS.broken, URLS.ok],
            { pollInterval: 5, pollTimeout: 2000 },
        );

        expect(results).toHaveLength(2);
        const [broken, ok] = [results[0]!, results[1]!];

        expect(broken.success).toBe(false);
        expect(broken.status).toBe('error');
        expect(broken.error).toContain('trigger rejected');
        expect(broken.url).toBe(URLS.broken);

        expect(ok.success).toBe(true);
        expect(ok.data).toEqual([{ title: 'Product OK' }]);
        expect(ok.url).toBe(URLS.ok);
    });

    test('applies one total timeout across the whole batch, not per URL', async () => {
        const { router } = setupScriptedRouter({
            [URLS.ok]: { kind: 'success', data: [{ title: 'Fast' }] },
            [URLS.slow]: { kind: 'timeout' },
        });

        const totalTimeout = 150;
        const start = Date.now();
        const results = await router.amazon.productsSettled(
            [URLS.ok, URLS.slow],
            { pollInterval: 5, pollTimeout: totalTimeout },
        );
        const elapsed = Date.now() - start;

        // Both URLs still get their own outcome.
        expect(results.map((r) => r.status)).toEqual(['ready', 'timeout']);

        // The slow URL draws from the shared batch deadline: it must finish
        // well inside two per-URL budgets (which would take >= ~300ms).
        expect(elapsed).toBeLessThan(totalTimeout * 2);
    });

    test('is reachable as client.scrape.amazon.productsSettled', () => {
        const router = new ScrapeRouter({ transport: makeTransport() });
        expect(typeof router.amazon.productsSettled).toBe('function');
    });

    test.each([
        ['not an array', 'nope' as unknown],
        ['an empty array', []],
        ['a non-string element', [URLS.ok, 42 as unknown]],
        ['a null element', [URLS.ok, null as unknown]],
        ['an object element', [{ url: URLS.ok } as unknown]],
    ])(
        'throws ValidationError before any network request when input is %s',
        async (_label, badInput) => {
            mockRequest.mockClear();
            const router = new ScrapeRouter({ transport: makeTransport() });

            await expect(
                router.amazon.productsSettled(badInput as string[], {
                    pollInterval: 5,
                }),
            ).rejects.toBeInstanceOf(ValidationError);

            expect(mockRequest).not.toHaveBeenCalled();
        },
    );

    test('mixed outcomes via injected fake SnapshotOperations', async () => {
        // Exercise the SnapshotOperations seam that ScrapeJob.toResult()
        // depends on directly: triggers are faked on the transport while
        // status/fetch are scripted per snapshot id, with no HTTP involved.
        const statusBySnapshot = new Map<string, string>();
        const fetchImplBySnapshot = new Map<
            string,
            (call: number) => unknown
        >();
        let nextId = 0;

        mockRequest.mockImplementation(async (url, opts) => {
            if (String(url) !== API_ENDPOINT.SCRAPE_ASYNC) {
                throw new APIError('unexpected non-trigger request', 500);
            }
            const parsed = JSON.parse(
                (opts?.body as string | undefined) ?? '{}',
            ) as Array<{ url?: string }>;
            const itemUrl = parsed[0]?.url ?? '';
            const id = `snap_${++nextId}`;

            if (itemUrl === URLS.ok) {
                statusBySnapshot.set(id, 'ready');
                fetchImplBySnapshot.set(id, () => [{ title: 'From Fake' }]);
            } else if (itemUrl === URLS.slow) {
                statusBySnapshot.set(id, 'running'); // never ready -> timeout
                fetchImplBySnapshot.set(id, () => {
                    throw new Error('should never be fetched');
                });
            } else {
                statusBySnapshot.set(id, 'ready');
                fetchImplBySnapshot.set(id, () => {
                    throw new APIError('fetch exploded [HTTP502]', 502);
                });
            }
            return mockResponse(200, { snapshot_id: id });
        });

        const fakeOps: SnapshotOperations = {
            getStatus: vi.fn(async (snapshotId: string) => ({
                snapshot_id: snapshotId,
                dataset_id: 'gd_l7q7dkf244hwjntr0',
                status: statusBySnapshot.get(snapshotId) ?? 'running',
            })),
            fetch: vi.fn(async (snapshotId: string) => {
                const impl = fetchImplBySnapshot.get(snapshotId)!;
                const calls = (fakeOps.fetch as Mock).mock.calls.filter(
                    ([id]) => id === snapshotId,
                ).length;
                return impl(calls);
            }),
            download: vi.fn(),
            cancel: vi.fn(),
        };

        const api = new AmazonAPI({
            transport: makeTransport(),
            snapshotOps: fakeOps,
        });

        const results = await api.productsSettled(
            [URLS.ok, URLS.slow, URLS.broken],
            { pollInterval: 5, pollTimeout: 60 },
        );

        expect(results.map((r) => r.status)).toEqual([
            'ready',
            'timeout',
            'error',
        ]);
        expect(results[0]!.data).toEqual([{ title: 'From Fake' }]);
        expect(results[1]!.error).toBeTruthy();
        expect(results[2]!.error).toContain('fetch exploded');
        // Every snapshot was driven through the injected fake operations.
        expect(fakeOps.getStatus).toHaveBeenCalled();
    });
});
