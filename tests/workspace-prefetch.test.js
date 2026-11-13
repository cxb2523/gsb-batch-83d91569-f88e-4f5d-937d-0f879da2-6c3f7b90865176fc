import test from 'node:test';
import assert from 'node:assert/strict';
import { prefetchWorkspaces, PREFETCH_STATUS } from '../src/utils/workspace-prefetch.js';
import { cachedWorkspace, clearOfflineDatabase } from '../src/utils/offline-cache.js';
import { workspaceStorage } from '../src/utils/workspace-storage.js';
import { offlineCacheKey } from '../src/utils/offline-cache.js';

function makeStorage({ failWrites = false } = {}) {
  const values = new Map();
  return {
    values,
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => {
      if (failWrites) throw new Error('localStorage quota exceeded');
      values.set(key, value);
    },
    removeItem: key => values.delete(key),
  };
}

const config = (name) => ({ categories: [{ category: 'Tools', categoryKey: 't', services: [
  { name, key: 'a', url: 'https://example.org' },
] }], searchEngines: [] });

// Local, self-contained IndexedDB fake. No real network or browser API is
// touched. `mode` selects:
//   working  - in-memory stores, get/put/getAll/delete + oncomplete
//   aborting - every readwrite transaction aborts (simulates quota pressure)
//   blocked  - open() always errors (simulates IndexedDB being unavailable)
function makeIndexedDB(mode = 'working') {
  const databases = new Map();
  return {
    open(name) {
      const request = {};
      queueMicrotask(() => {
        if (mode === 'blocked') {
          request.error = new Error('IndexedDB unavailable');
          request.onerror?.(new Event('error'));
          return;
        }
        let db = databases.get(name);
        const fresh = !db;
        if (!db) {
          const stores = new Map();
          db = {
            objectStoreNames: { contains: key => stores.has(key) },
            createObjectStore(key) { stores.set(key, new Map()); },
            close() {},
            transaction(key, txMode) {
              const values = stores.get(key);
              const tx = { pending: 0, completeScheduled: false, oncomplete: null, onerror: null, onabort: null };
              const scheduleComplete = () => {
                if (tx.pending || tx.completeScheduled) return;
                tx.completeScheduled = true;
                queueMicrotask(() => {
                  tx.completeScheduled = false;
                  if (tx.pending === 0) tx.oncomplete?.();
                });
              };
              const abort = () => {
                tx.error = new Error('Offline transaction aborted');
                tx.onabort?.(new Event('abort'));
                tx.onerror?.(new Event('error'));
              };
              const request = operation => {
                const req = {};
                tx.pending++;
                queueMicrotask(() => {
                  if (mode === 'aborting' && txMode === 'readwrite') {
                    tx.pending--;
                    abort();
                    return;
                  }
                  req.result = operation();
                  req.onsuccess?.();
                  tx.pending--;
                  scheduleComplete();
                });
                return req;
              };
              tx.objectStore = () => ({
                put: value => request(() => { values.set(value.key ?? value.user, structuredClone(value)); return value.key ?? value.user; }),
                get: key => request(() => structuredClone(values.get(key))),
                getAll: () => request(() => [...values.values()].map(x => structuredClone(x))),
                delete: key => request(() => values.delete(key)),
              });
              return tx;
            },
          };
          databases.set(name, db);
        }
        request.result = db;
        if (fresh) request.onupgradeneeded?.();
        request.onsuccess?.();
      });
      return request;
    },
    deleteDatabase(name) {
      const request = {};
      queueMicrotask(() => { databases.delete(name); request.onsuccess?.(); });
      return request;
    },
  };
}

function withGlobals({ indexedDB = null, localStorage: storage = makeStorage() } = {}, body) {
  const originalIDB = globalThis.indexedDB;
  const originalStorage = globalThis.localStorage;
  globalThis.indexedDB = indexedDB;
  globalThis.localStorage = storage;
  return (async () => {
    try {
      return await body(storage);
    } finally {
      try { if (globalThis.indexedDB) await clearOfflineDatabase(); } catch {}
      globalThis.indexedDB = originalIDB;
      globalThis.localStorage = originalStorage;
    }
  })();
}

test('prefetches all authorized workspaces, uses no-store and user header', () => withGlobals({ indexedDB: makeIndexedDB() }, async () => {
  const calls = [], progress = [];
  const result = await prefetchWorkspaces({ user: 'alice', workspaces: [{ id: 'home' }, { id: 'work' }] }, {
    base: '/jump-key/',
    fetcher: async (url, options) => {
      calls.push([url, options]);
      return Response.json(config(url.includes('work') ? 'Work' : 'Home'));
    },
    onProgress: state => progress.push(state),
  });
  // Legacy fields stay compatible...
  assert.equal(result.available, 2);
  assert.equal(result.total, 2);
  assert.deepEqual(result.failures, []);
  // ...and every id now carries a checkable success conclusion.
  assert.deepEqual(result.results.map(r => r.status), [PREFETCH_STATUS.SUCCESS, PREFETCH_STATUS.SUCCESS]);
  assert.ok(result.results.every(r => r.storedIn === 'indexeddb'));
  assert.equal(calls.length, 2);
  assert.ok(calls.every(([, options]) => options.cache === 'no-store' && options.headers['X-JumpKey-User'] === 'alice'));
  assert.ok(calls.some(([url]) => url.includes('workspace=home')));
  assert.ok(calls.some(([url]) => url.includes('workspace=work')));
  const last = progress.at(-1);
  assert.equal(last.available, 2);
  assert.equal(last.total, 2);
  assert.deepEqual(last.failures, []);
  assert.deepEqual(last.results.map(r => r.status), [PREFETCH_STATUS.SUCCESS, PREFETCH_STATUS.SUCCESS]);
  // Results were filled in progressively, not only at the end.
  assert.ok(progress.length >= 3);
  assert.deepEqual(progress[0].results.map(r => r.status), [PREFETCH_STATUS.PENDING, PREFETCH_STATUS.PENDING]);
  assert.ok(progress.some(state => state.results.filter(r => r.status !== PREFETCH_STATUS.PENDING).length === 1));
  assert.ok(progress.every(state => state.results.length === 2));
  assert.equal((await cachedWorkspace('alice', 'work')).categories[0].services[0].name, 'Work');
  assert.notEqual(offlineCacheKey('alice', 'home'), offlineCacheKey('bob', 'home'));
}));

test('401, HTML login page and invalid JSON each get a distinct failure conclusion', () => withGlobals({ indexedDB: makeIndexedDB() }, async () => {
  const progress = [];
  const manifest = { user: 'alice', workspaces: [{ id: 'ok' }, { id: 'denied' }, { id: 'html' }, { id: 'invalid' }, { id: 'broken' }] };
  const result = await prefetchWorkspaces(manifest, {
    fetcher: async url => {
      if (url.includes('denied')) return new Response('unauthorized', { status: 401 });
      if (url.includes('html')) return new Response('<html>Login</html>', { status: 200, headers: { 'content-type': 'text/html; charset=utf-8' } });
      if (url.includes('invalid')) return Response.json({ invalid: true });
      if (url.includes('broken')) return new Response('not-json{', { status: 200, headers: { 'content-type': 'application/json' } });
      return Response.json(config('Okay'));
    },
    onProgress: state => progress.push(state),
  });
  assert.equal(result.available, 1);
  assert.deepEqual(new Set(result.failures), new Set(['denied', 'html', 'invalid', 'broken']));
  const byId = new Map(result.results.map(entry => [entry.id, entry]));
  assert.equal(byId.get('ok').status, PREFETCH_STATUS.SUCCESS);
  assert.equal(byId.get('denied').status, PREFETCH_STATUS.HTTP_ERROR);
  assert.equal(byId.get('denied').httpStatus, 401);
  assert.equal(byId.get('html').status, PREFETCH_STATUS.HTML_LOGIN);
  assert.equal(byId.get('html').httpStatus, 200);
  assert.equal(byId.get('invalid').status, PREFETCH_STATUS.INVALID_CONFIG);
  assert.equal(byId.get('broken').status, PREFETCH_STATUS.INVALID_CONFIG);
  // Failed payloads never reach the cache.
  for (const id of ['denied', 'html', 'invalid', 'broken']) {
    assert.equal(await cachedWorkspace('alice', id), null);
  }
  // The same conclusions travel with every progress tick and accumulate.
  const finalProgress = progress.at(-1);
  assert.deepEqual(finalProgress.results.map(r => r.status).sort(),
    result.results.map(r => r.status).sort());
  const firstFailureTick = progress.find(state => state.failures.length === 1);
  assert.ok(firstFailureTick, 'a failure is reported as soon as its item settles');
  assert.equal(firstFailureTick.results.filter(r => r.status === PREFETCH_STATUS.PENDING).length >= 1, true);
}));

test('storage failure is reported when both IndexedDB and localStorage writes fail', () => withGlobals(
  { indexedDB: makeIndexedDB('aborting'), localStorage: makeStorage({ failWrites: true }) },
  async storage => {
    const result = await prefetchWorkspaces(
      { user: 'alice', workspaces: [{ id: 'home' }] },
      { fetcher: async () => Response.json(config('Home')) },
    );
    assert.equal(result.available, 0);
    assert.deepEqual(result.failures, ['home']);
    assert.equal(result.results[0].status, PREFETCH_STATUS.STORAGE_ERROR);
    assert.equal(result.results[0].id, 'home');
    assert.equal(await cachedWorkspace('alice', 'home'), null);
    assert.equal(storage.values.size, 0);
  },
));

test('blocked IndexedDB falls back to localStorage, and a blocked fallback is a storage failure', async t => {
  await t.test('localStorage fallback still counts as success', () => withGlobals(
    { indexedDB: makeIndexedDB('blocked') },
    async () => {
      const result = await prefetchWorkspaces(
        { user: 'alice', workspaces: [{ id: 'home' }] },
        { fetcher: async () => Response.json(config('Home')) },
      );
      assert.equal(result.available, 1);
      assert.deepEqual(result.failures, []);
      assert.equal(result.results[0].status, PREFETCH_STATUS.SUCCESS);
      assert.equal(result.results[0].storedIn, 'localstorage');
      assert.ok(JSON.parse(globalThis.localStorage.getItem(workspaceStorage('alice', 'home').configCache)));
    },
  ));
  await t.test('failing fallback is a storage failure, not a success', () => withGlobals(
    { indexedDB: makeIndexedDB('blocked'), localStorage: makeStorage({ failWrites: true }) },
    async () => {
      const result = await prefetchWorkspaces(
        { user: 'alice', workspaces: [{ id: 'home' }] },
        { fetcher: async () => Response.json(config('Home')) },
      );
      assert.equal(result.available, 0);
      assert.deepEqual(result.failures, ['home']);
      assert.equal(result.results[0].status, PREFETCH_STATUS.STORAGE_ERROR);
    },
  ));
});

test('a slower response initiated earlier never overwrites the newer cached config', () => withGlobals(
  { indexedDB: makeIndexedDB() },
  async () => {
    // Deferred fetcher lets the second run's request resolve before the first.
    let resolveOld;
    const oldFetch = new Promise(resolve => { resolveOld = resolve; });
    let run = 0;
    const fetcher = async () => {
      run += 1;
      if (run === 1) return oldFetch;
      return Response.json(config('NEW'));
    };
    const manifest = { user: 'alice', workspaces: [{ id: 'home' }] };

    const first = prefetchWorkspaces(manifest, { fetcher, concurrency: 1 });
    // Let the first run initiate its fetch before starting the second run.
    await Promise.resolve();
    await Promise.resolve();
    const second = prefetchWorkspaces(manifest, { fetcher, concurrency: 1 });
    await second;
    // The newer response is already cached...
    assert.equal((await cachedWorkspace('alice', 'home')).categories[0].services[0].name, 'NEW');
    // ...and the late, stale response must not overwrite it.
    resolveOld(Response.json(config('OLD')));
    await first;
    assert.equal((await cachedWorkspace('alice', 'home')).categories[0].services[0].name, 'NEW');
    assert.equal(run, 2, 'each run fetches the workspace once');

    const firstResults = await first;
    assert.equal(firstResults.results[0].status, PREFETCH_STATUS.SUCCESS);
    assert.equal(firstResults.results[0].superseded, true);
    assert.equal(firstResults.results[0].storedIn, null);
    const secondResults = await second;
    assert.equal(secondResults.results[0].status, PREFETCH_STATUS.SUCCESS);
    assert.equal(secondResults.results[0].storedIn, 'indexeddb');
  },
));

test('initiation-time guard also protects the localStorage fallback path', () => withGlobals(
  { indexedDB: makeIndexedDB('blocked') },
  async () => {
    let resolveOld;
    const oldFetch = new Promise(resolve => { resolveOld = resolve; });
    let run = 0;
    const fetcher = async () => {
      run += 1;
      if (run === 1) return oldFetch;
      return Response.json(config('NEW-LS'));
    };
    const manifest = { user: 'carol', workspaces: [{ id: 'home' }] };
    const first = prefetchWorkspaces(manifest, { fetcher, concurrency: 1 });
    await Promise.resolve();
    await Promise.resolve();
    const second = prefetchWorkspaces(manifest, { fetcher, concurrency: 1 });
    await second;
    resolveOld(Response.json(config('OLD-LS')));
    await first;
    const stored = JSON.parse(globalThis.localStorage.getItem(workspaceStorage('carol', 'home').configCache));
    assert.equal(stored.categories[0].services[0].name, 'NEW-LS');
  },
));

test('duplicate ids are fetched once and ids absent from the manifest are never requested', () => withGlobals(
  { indexedDB: makeIndexedDB() },
  async () => {
    let requests = 0;
    const requested = [];
    const result = await prefetchWorkspaces(
      { user: 'alice', workspaces: [{ id: 'home' }, { id: 'home' }, { id: 'work' }, { id: 'home' }] },
      {
        fetcher: async url => {
          requests++;
          requested.push(url);
          return Response.json(config('X'));
        },
      },
    );
    assert.equal(requests, 2);
    assert.equal(result.total, 2);
    assert.deepEqual(result.results.map(r => r.id), ['home', 'work']);
    assert.ok(result.results.every(r => r.status === PREFETCH_STATUS.SUCCESS));
  },
));

test('empty manifest requests nothing and keeps the legacy empty shape', async () => {
  let requests = 0;
  const result = await prefetchWorkspaces({ user: 'alice', workspaces: [] }, { fetcher: async () => { requests++; } });
  assert.equal(requests, 0);
  assert.deepEqual(
    { available: result.available, total: result.total, failures: result.failures },
    { available: 0, total: 0, failures: [] },
  );
  assert.deepEqual(result.results, []);
});
