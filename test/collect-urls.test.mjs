import assert from 'node:assert/strict';
import { EventEmitter, once } from 'node:events';
import { createServer } from 'node:http';
import { test } from 'node:test';
import * as rusteerio from '../dist/index.mjs';

async function withServer(handler, run) {
  const server = createServer(handler);
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  try { return await run(`http://127.0.0.1:${server.address().port}`); }
  finally { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
}

function assertFailureShape(result) {
  assert.equal(result.ok, false);
  assert.equal(Object.hasOwn(result, 'error'), true);
  assert.equal(Object.hasOwn(result, 'document'), false);
  assert.equal(typeof result.error.name, 'string');
  assert.equal(typeof result.error.message, 'string');
  assert.equal(typeof result.error.code, 'string');
  assert.ok(result.error.name.length > 0);
  assert.ok(result.error.message.length > 0);
  assert.ok(result.error.code.length > 0);
}

test('collectURLs records success categories without aborting the batch', async () => {
  await withServer((request, response) => {
    if (request.url === '/ok') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end('<p>café</p>');
    } else if (request.url === '/missing') {
      response.writeHead(404, { 'content-type': 'text/html' }).end('<p>missing</p>');
    } else if (request.url === '/binary') {
      response.writeHead(200, { 'content-type': 'application/octet-stream' }).end('binary payload');
    } else if (request.url === '/large') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end(`<p>${'x'.repeat(4096)}</p>`);
    } else if (request.url === '/loop') {
      response.writeHead(302, { location: '/loop' }).end();
    } else {
      response.writeHead(500, { 'content-type': 'text/html' }).end('<p>unexpected</p>');
    }
  }, async base => {
    const urls = [
      `${base}/missing`,
      new URL(`${base}/ok`),
      `${base}/binary`,
      `${base}/large`,
      `${base}/loop`,
      `${base}/ok`,
    ];
    const results = await rusteerio.collectURLs(urls, { requestOptions: { maxResponseSize: 100 } });
    assert.equal(results.length, urls.length);
    assert.deepEqual(results.map(result => result.url), urls.map(String));

    const [missing, ok, binary, large, loop, okAgain] = results;
    assertFailureShape(missing);
    assert.equal(missing.error.name, 'ResponseError');
    assert.equal(missing.error.code, 'UND_ERR_RESPONSE');
    assert.equal(missing.error.statusCode, 404);

    assert.equal(ok.ok, true);
    assert.equal(Object.hasOwn(ok, 'error'), false);
    assert.equal(ok.document('p').text(), 'café');
    assert.equal(okAgain.document('p').text(), 'café');

    assertFailureShape(binary);
    assert.equal(binary.error.name, 'RangeError');
    assert.equal(binary.error.code, 'RangeError');
    assert.match(binary.error.message, /neither HTML nor XML/);

    assertFailureShape(large);
    assert.equal(large.error.code, 'UND_ERR_RES_EXCEEDED_MAX_SIZE');
    assert.equal(large.error.name, 'ResponseExceededMaxSizeError');

    assertFailureShape(loop);
    assert.match(loop.error.message, /max redirects reached/);
  });
});

test('collectURLs honors parser options, headers and redirect limits', async () => {
  const seen = [];
  await withServer((request, response) => {
    seen.push(request.headers['x-batch']);
    if (request.url === '/hop') return response.writeHead(302, { location: '/xml' }).end();
    if (request.url === '/xml') {
      response.writeHead(200, { 'content-type': 'application/xml; charset=utf-8' }).end('<?xml version="1.0"?><Root><Item>café</Item></Root>');
    } else if (request.url === '/html') {
      response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end('<p>already decoded</p>');
    } else response.writeHead(404, { 'content-type': 'text/html' }).end('<p>missing</p>');
  }, async base => {
    const results = await rusteerio.collectURLs([`${base}/hop`, `${base}/html`], {
      requestOptions: { headers: { 'x-batch': 'yes' }, maxRedirections: 1 },
      encoding: { userEncoding: 'utf-8' },
    });
    assert.ok(results.every(result => result.ok));
    assert.equal(results[0].document('Item').text(), 'café');
    assert.equal(results[1].document('p').text(), 'already decoded');
    assert.deepEqual(seen, ['yes', 'yes', 'yes']);
  });
});

test('collectURLs enforces the concurrency cap and validates it before requesting', async () => {
  let active = 0;
  let peak = 0;
  let requested = 0;
  await withServer(async (_request, response) => {
    requested += 1;
    active += 1;
    peak = Math.max(peak, active);
    await new Promise(resolve => setTimeout(resolve, 20));
    active -= 1;
    response.writeHead(200, { 'content-type': 'text/html' }).end('<p>slow</p>');
  }, async base => {
    const urls = Array.from({ length: 9 }, (_, index) => `${base}/${index}`);
    const results = await rusteerio.collectURLs(urls, { concurrency: 3 });
    assert.equal(results.length, 9);
    assert.ok(results.every(result => result.ok));
    assert.ok(peak <= 3, `observed ${peak} concurrent requests with a cap of 3`);
    assert.ok(peak > 1, 'requests should overlap when concurrency allows it');

    peak = 0;
    const defaults = await rusteerio.collectURLs(urls);
    assert.equal(defaults.length, 9);
    assert.ok(defaults.every(result => result.ok));
    assert.ok(peak <= 4, `observed ${peak} concurrent requests with the default concurrency of 4`);

    const before = requested;
    for (const concurrency of [0, 65, 2.5, -1, 1.5, '2']) {
      await assert.rejects(rusteerio.collectURLs([`${base}/never`], { concurrency }), error => error instanceof RangeError && /1 to 64/.test(error.message));
    }
    assert.equal(requested, before);
  });
});

test('collectURLs marks started and unstarted addresses after an abort', async () => {
  let changed;
  const arrived = new Promise(resolve => { changed = resolve; });
  const requested = [];
  await withServer((request, response) => {
    requested.push(request.url);
    if (request.url === '/hold') { changed(); return; }
    response.writeHead(200, { 'content-type': 'text/html' }).end('<p>fast</p>');
  }, async base => {
    const controller = new AbortController();
    const pending = rusteerio.collectURLs(
      [`${base}/fast`, `${base}/hold`, `${base}/unreached`],
      { concurrency: 1, requestOptions: { signal: controller.signal } },
    );
    await arrived;
    controller.abort('batch stopped');
    const results = await pending;

    assert.equal(results.length, 3);
    assert.equal(results[0].ok, true);
    assert.equal(results[0].document('p').text(), 'fast');
    for (const result of results.slice(1)) {
      assertFailureShape(result);
      assert.equal(result.error.name, 'AbortError');
      assert.equal(result.error.code, 'AbortError');
      assert.equal(result.error.message, 'batch stopped');
    }
    // The address that had not started must not have issued a request.
    assert.deepEqual(requested, ['/fast', '/hold']);
  });
});

test('collectURLs reports an already-aborted signal without requesting', async () => {
  let requested = 0;
  await withServer((_request, response) => {
    requested += 1;
    response.writeHead(200, { 'content-type': 'text/html' }).end('<p>unexpected</p>');
  }, async base => {
    const controller = new AbortController();
    controller.abort();
    const results = await rusteerio.collectURLs([`${base}/a`, `${base}/b`], { requestOptions: { signal: controller.signal } });
    assert.equal(results.length, 2);
    for (const result of results) {
      assertFailureShape(result);
      assert.equal(result.error.name, 'AbortError');
      assert.equal(result.error.code, 'AbortError');
    }
    assert.equal(requested, 0);
  });
});

test('collectURLs accepts an EventEmitter signal and releases its listener', async () => {
  await withServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' });
    response.write('<p>');
  }, async base => {
    const signal = new EventEmitter();
    const pending = rusteerio.collectURLs([`${base}/hold`, `${base}/later`], { concurrency: 1, requestOptions: { signal } });
    signal.emit('abort');
    const results = await pending;
    assert.equal(results[0].ok, false);
    assert.equal(results[1].ok, false);
    for (const result of results) {
      assertFailureShape(result);
      assert.equal(result.error.name, 'AbortError');
    }
    assert.equal(signal.listenerCount('abort'), 0);

    await assert.rejects(rusteerio.collectURLs([base], { requestOptions: { signal: {} } }), { name: 'TypeError' });
    await assert.rejects(rusteerio.collectURLs([42]), { name: 'TypeError' });
    assert.deepEqual(await rusteerio.collectURLs([]), []);
    await assert.rejects(rusteerio.collectURLs('not an array'), { name: 'TypeError' });
  });
});
