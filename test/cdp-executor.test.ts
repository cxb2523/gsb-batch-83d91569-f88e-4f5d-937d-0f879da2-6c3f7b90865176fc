/**
 * CdpExecutor (the Playwright fallback) driven against a headless Chromium it
 * launches itself, serving fixture pages from a loopback HTTP server (no
 * internet). Covers every Executor method plus the error mapping: unknown and
 * stale tab handles, a target with neither selector nor ref, missing upload
 * files, download size/source errors, eval exceptions, wait timeouts, the
 * DETACHED conversion when the browser goes away, and connect mode over CDP.
 *
 * Gated on Chromium being installed, like test/executor.test.ts.
 */

import { after, before, test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { chromium } from 'playwright';

import { CdpExecutor } from '../src/executor/cdp-executor';
import { ExecutorError } from '../src/executor/types';
import { sanitizeDownloadName } from '../shared/download';

let hasChromium = false;
try {
  hasChromium = existsSync(chromium.executablePath());
} catch {
  hasChromium = false;
}

const PAGES: Record<string, { type: string; body: string; headers?: Record<string, string> }> = {
  '/': {
    type: 'text/html',
    body: `<!doctype html><html><head><title>Home</title></head><body>
      <h1>Welcome home</h1>
      <div id="box"><p>Inner <b>bold</b></p></div>
      <input id="name" value="start">
      <textarea id="ta"></textarea>
      <select id="sel"><option value="pk">Pakistan</option><option value="de">Germany</option></select>
      <button id="btn" onclick="this.textContent='clicked ' + (event.button)">Press</button>
      <div id="hov" onmouseover="this.textContent='hovered'">hover me</div>
      <input id="file" type="file" multiple>
      <a id="dl" href="/file.txt" download="saved.txt">Download</a>
      <a id="redirect-dl" href="/redirect-file" download="redirect.txt">Redirect download</a>
      <canvas id="cv" width="200" height="200" style="border:1px solid"></canvas>
      <div style="height:3000px"></div><div id="bottom">Bottom</div>
      <script>
        window.keys = [];
        document.addEventListener('keydown', (e) => window.keys.push((e.shiftKey ? 'Shift+' : '') + e.key));
        window.strokes = 0;
        document.getElementById('cv').addEventListener('mousedown', () => window.strokes++);
        document.cookie = 'flavour=oat; path=/';
      </script>
    </body></html>`,
  },
  '/second': { type: 'text/html', body: '<!doctype html><title>Second</title><p>second page</p>' },
  '/late': {
    type: 'text/html',
    body: `<!doctype html><title>Late</title><div id="gone">bye</div><script>
      setTimeout(() => { document.body.insertAdjacentHTML('beforeend', '<p id="late">Arrived late</p>'); document.getElementById('gone').remove(); }, 80);
    </script>`,
  },
  '/file.txt': { type: 'text/plain', body: 'hello download', headers: { 'content-disposition': 'attachment; filename="saved.txt"' } },
};

/**
 * Download-response fixtures that need server-side behaviour the plain PAGES map
 * cannot express: an oversize body declared by Content-Length, a chunked body
 * that only exceeds the cap while streaming, and a body that breaks mid-read.
 * `cancelled` records each fixture whose server socket saw the client hang up,
 * so a test can prove the response body was really cancelled rather than just
 * dropped on the floor.
 */
const downloadFixtures = {
  /** A client-visible cancellation per fixture (declared / streamed). */
  cancelled: new Set<string>(),
};

let server: Server;
let base = '';
let requestLog: Array<{ host: string; path: string }> = [];

before(async () => {
  server = createServer((req, res) => {
    const path = (req.url ?? '/').split('?')[0];
    requestLog.push({ host: req.headers.host ?? '', path });
    if (path === '/redirect-file') {
      res.writeHead(302, { location: `http://localhost:${(server.address() as AddressInfo).port}/redirect-target` }).end();
      return;
    }
    if (path === '/redirect-permanent') {
      res.writeHead(301, { location: `http://localhost:${(server.address() as AddressInfo).port}/redirect-target` }).end();
      return;
    }
    if (path === '/redirect-target') {
      res.writeHead(200, { 'content-type': 'text/plain' }).end('must not be requested');
      return;
    }
    if (path === '/oversize-declared') {
      res.on('close', () => downloadFixtures.cancelled.add('declared'));
      res.writeHead(200, { 'content-type': 'application/octet-stream', 'content-length': String(60 * 1024 * 1024) });
      res.end('x');
      return;
    }
    if (path === '/oversize-streamed') {
      res.on('close', () => downloadFixtures.cancelled.add('streamed'));
      res.writeHead(200, { 'content-type': 'application/octet-stream' }); // chunked: no content-length
      const chunk = Buffer.alloc(1024 * 1024, 0x61);
      let sent = 0;
      const pump = (): void => {
        while (sent < 80 * 1024 * 1024) {
          sent += chunk.length;
          if (!res.write(chunk)) { res.once('drain', pump); return; }
        }
        res.end();
      };
      pump();
      return;
    }
    if (path === '/broken-body') {
      res.writeHead(200, { 'content-type': 'application/octet-stream' });
      res.write('partial');
      setTimeout(() => res.socket?.destroy(), 50);
      return;
    }
    if (path === '/not-modified') {
      // A 3xx that is NOT a redirect: no Location, nothing to follow.
      res.writeHead(304).end();
      return;
    }
    if (path === '/base-link') {
      const port = (server.address() as AddressInfo).port;
      res.writeHead(200, { 'content-type': 'text/html' }).end(`<head><base href="http://localhost:${port}/"></head><a id="base-dl" href="redirect-target">Download</a>`);
      return;
    }
    const page = PAGES[path];
    if (!page) {
      res.writeHead(404).end('nope');
      return;
    }
    res.writeHead(200, { 'content-type': page.type, ...(page.headers ?? {}) });
    res.end(page.body);
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
});
after(async () => {
  // Browsers keep connections alive; drop them so close() does not wait on them.
  server.closeAllConnections();
  await new Promise<void>((r) => server.close(() => r()));
});

function errCode(code: string): (err: unknown) => boolean {
  return (err: unknown) => {
    assert.ok(err instanceof ExecutorError, `expected ExecutorError, got ${String(err)}`);
    assert.equal(err.code, code);
    return true;
  };
}

/** Assert a failure carries the given code AND its checkable reason (and, optionally, details). */
function errReason(code: string, reason: string, details?: Record<string, unknown>): (err: unknown) => boolean {
  return (err: unknown) => {
    errCode(code)(err);
    assert.equal((err as ExecutorError).reason, reason, `expected reason ${reason}, got ${(err as ExecutorError).reason}`);
    for (const [key, value] of Object.entries(details ?? {})) {
      assert.equal((err as ExecutorError).details?.[key], value, `details.${key}`);
    }
    return true;
  };
}

test('CdpExecutor: launch, tabs, navigation and reads', { skip: !hasChromium }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'cmcp-cdpx-'));
  const ex = new CdpExecutor({ mode: 'launch', userDataDir: dir, headless: true, downloadDir: join(dir, 'dl') });
  try {
    assert.equal(ex.status().ready, false);
    assert.equal(await ex.ping(), false, 'not launched yet');
    await ex.ensureReady();
    assert.deepEqual(ex.status(), { ready: true, backend: 'cdp', activeTabId: null, extensionConnected: false, cdpAttached: true });
    assert.equal(await ex.ping(), true);
    assert.deepEqual(await ex.tabsList(), [], 'about:blank is not a content tab');

    const nav = await ex.navigate({ url: `${base}/` });
    assert.deepEqual(nav, { url: `${base}/`, title: 'Home', httpStatus: 200 });
    const tabs = await ex.tabsList();
    assert.equal(tabs.length, 1);
    assert.match(tabs[0].tabId, /^cdp:[0-9a-f-]+:\d+$/);
    assert.equal(tabs[0].active, true);
    assert.equal(tabs[0].title, 'Home');
    assert.equal((await ex.tabsList())[0].tabId, tabs[0].tabId, 'a page keeps its handle');

    const second = await ex.tabNew(`${base}/second`, { active: false });
    assert.equal(second.title, 'Second');
    assert.notEqual(second.tabId, tabs[0].tabId);
    const selected = await ex.tabSelect(second.tabId);
    assert.deepEqual(selected, { tabId: second.tabId, url: `${base}/second`, title: 'Second', active: true, index: 0 });
    assert.deepEqual(await ex.getText(undefined, { tabId: second.tabId }), { text: 'second page' });

    await ex.navigate({ url: `${base}/second`, tabId: tabs[0].tabId, waitUntil: 'domcontentloaded' });
    assert.equal((await ex.back(tabs[0].tabId)).title, 'Home');
    assert.equal((await ex.forward(tabs[0].tabId)).title, 'Second');
    assert.equal((await ex.reload({ tabId: tabs[0].tabId })).url, `${base}/second`);
    await ex.back(tabs[0].tabId);

    assert.deepEqual(await ex.tabClose(second.tabId), { closed: true, tabId: second.tabId });
    await assert.rejects(ex.tabSelect(second.tabId), errCode('TAB_NOT_FOUND'));
    await assert.rejects(ex.tabSelect('cdp:another-session:1'), errCode('STALE_TAB'));
    await assert.rejects(ex.getText(undefined, { tabId: 'x:1' }), errCode('TAB_NOT_FOUND'));

    const t = tabs[0].tabId;
    assert.match((await ex.getText(undefined, { tabId: t })).text, /Welcome home/);
    assert.deepEqual(await ex.getText({ selector: '#box b' }, { tabId: t }), { text: 'bold' });
    assert.deepEqual(await ex.getHtml({ selector: '#box' }, { tabId: t }), { html: '<p>Inner <b>bold</b></p>' });
    assert.deepEqual(await ex.getHtml({ selector: '#box' }, { tabId: t, outer: true }), { html: '<div id="box"><p>Inner <b>bold</b></p></div>' });
    assert.match((await ex.getHtml(undefined, { tabId: t })).html, /^<!DOCTYPE html><html><head><title>Home<\/title>/);

    const snap = await ex.snapshot({ tabId: t });
    const press = snap.nodes.find((n) => n.name === 'Press');
    assert.ok(press, 'snapshot found the button');
    assert.equal(press.role, 'button');
    const located = await ex.snapshot({ tabId: t, locator: { role: 'button', name: 'Press' } });
    assert.equal(located.nodes.length, 1);
    const landmarks = await ex.snapshot({ tabId: t, interactiveOnly: false, max: 500 });
    assert.ok(landmarks.nodes.some((n) => n.tag === 'h1'));
  } finally {
    await ex.dispose();
  }
  assert.equal(ex.status().ready, false, 'dispose drops the context');
});

test('CdpExecutor: interaction, storage, eval, waits, cookies and screenshots', { skip: !hasChromium }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'cmcp-cdpx-'));
  const ex = new CdpExecutor({ mode: 'launch', userDataDir: dir, headless: true });
  try {
    await ex.navigate({ url: `${base}/` });
    const snap = await ex.snapshot();
    const press = snap.nodes.find((n) => n.name === 'Press');
    assert.ok(press);
    assert.deepEqual(await ex.click({ ref: press.ref }, { button: 'left', trusted: true }), { ok: true });
    assert.deepEqual(await ex.getText({ selector: '#btn' }), { text: 'clicked 0' });
    await assert.rejects(ex.click({} as never), errCode('SELECTOR_NOT_FOUND'));

    await ex.type({ selector: '#name' }, 'typed', { clear: true });
    assert.deepEqual(await ex.eval('document.getElementById("name").value'), { ok: true, value: 'typed', type: 'string' });
    await ex.type({ selector: '#ta' }, 'keys', { keyEvents: true, pressEnter: true });
    assert.equal((await ex.eval('document.getElementById("ta").value')).value, 'keys\n');
    await ex.fill({ selector: '#name' }, 'filled');
    assert.equal((await ex.eval('document.getElementById("name").value')).value, 'filled');

    await ex.selectOption({ selector: '#sel' }, ['de']);
    assert.equal((await ex.eval('document.getElementById("sel").value')).value, 'de');
    await ex.selectOption({ selector: '#sel' }, ['Pakistan']);
    assert.equal((await ex.eval('document.getElementById("sel").value')).value, 'pk', 'falls back to the visible label');

    await ex.press('a', { modifiers: ['Shift'] });
    await ex.press('Escape');
    const keys = (await ex.eval('window.keys')).value as string[];
    assert.ok(keys.includes('Shift+a') || keys.includes('Shift+A'), JSON.stringify(keys));
    assert.equal(keys[keys.length - 1], 'Escape', 'a bare key, no modifiers');

    await ex.hover({ selector: '#hov' });
    assert.deepEqual(await ex.getText({ selector: '#hov' }), { text: 'hovered' });

    await ex.scroll({ x: 0, y: 500 });
    assert.equal((await ex.eval('window.scrollY')).value, 500);
    await ex.scroll({ target: { selector: '#bottom' } });
    assert.ok(((await ex.eval('window.scrollY')).value as number) > 1000);
    await ex.scroll({ y: 0 });
    await ex.scroll({ deltaY: 120 });
    await ex.waitFor({ timeoutMs: 1 }); // nothing to wait on: matched immediately

    const drawn = await ex.draw([
      { points: [{ x: 20, y: 20 }, { x: 40, y: 40 }, { x: 60, y: 20 }] },
      { points: [{ x: 30, y: 30 }] },
    ] as never);
    assert.deepEqual(drawn, { ok: true, strokes: 2, points: 4 });

    assert.deepEqual(await ex.storage({ op: 'set', key: 'k', value: 'v' }), { ok: true });
    await ex.storage({ op: 'set', key: 'empty' });
    assert.deepEqual(await ex.storage({ op: 'get', key: 'k' }), { ok: true, value: 'v' });
    assert.deepEqual(await ex.storage({ op: 'get' }), { ok: true, entries: { k: 'v', empty: '' } });
    await ex.storage({ op: 'set', key: 's', value: '1', session: true });
    assert.deepEqual(await ex.storage({ op: 'get', session: true }), { ok: true, entries: { s: '1' } });
    await ex.storage({ op: 'remove', key: 'k' });
    assert.deepEqual(await ex.storage({ op: 'get' }), { ok: true, entries: { empty: '' } });
    await ex.storage({ op: 'clear' });
    assert.deepEqual(await ex.storage({ op: 'get' }), { ok: true, entries: {} });

    assert.deepEqual(await ex.eval('({ a: [1, 2] })'), { ok: true, value: { a: [1, 2] }, type: 'object' });
    const threw = await ex.eval('(() => { throw new Error("kaboom"); })()');
    assert.equal(threw.ok, false);
    assert.match(String(threw.error), /kaboom/);

    const cookies = await ex.getCookies();
    const flavour = cookies.cookies.find((c) => c.name === 'flavour');
    assert.ok(flavour);
    assert.equal(flavour.value, 'oat');
    assert.equal(flavour.expires, undefined, 'a session cookie has no expiry');
    assert.deepEqual((await ex.getCookies({ url: 'http://elsewhere.invalid/' })).cookies, []);

    const jpeg = await ex.screenshot({ format: 'jpeg', quality: 50 });
    assert.equal(jpeg.mimeType, 'image/jpeg');
    assert.equal(Buffer.from(jpeg.dataBase64, 'base64').subarray(0, 2).toString('hex'), 'ffd8');
    const el = await ex.screenshot({ format: 'png', target: { selector: '#btn' }, scale: 2 });
    assert.equal(el.mimeType, 'image/png');
    assert.equal(Buffer.from(el.dataBase64, 'base64').subarray(1, 4).toString(), 'PNG');
    assert.equal(el.truncated, false);
    assert.ok(el.width > 0 && el.height > 0, 'reports the viewport size');
    const full = await ex.screenshot({ fullPage: true, format: 'png' });
    assert.ok(full.dataBase64.length > 0);

    await ex.navigate({ url: `${base}/late` });
    const appeared = await ex.waitFor({ selector: '#late', timeoutMs: 3_000 });
    assert.equal(appeared.matched, true);
    assert.equal(typeof appeared.waitedMs, 'number');
    assert.equal((await ex.waitFor({ selector: '#gone', gone: true, timeoutMs: 3_000 })).matched, true);
    assert.equal((await ex.waitFor({ textContains: 'Arrived', timeoutMs: 3_000 })).matched, true);
    assert.equal((await ex.waitFor({ textContains: 'Never here', timeoutMs: 100 })).matched, false);
    assert.equal((await ex.waitFor({ selector: '#never', timeoutMs: 100 })).matched, false);
  } finally {
    await ex.dispose();
  }
});

test('CdpExecutor: downloads and uploads', { skip: !hasChromium }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'cmcp-cdpx-'));
  requestLog = [];
  const ex = new CdpExecutor({ mode: 'launch', userDataDir: dir, headless: true, policy: {
    allowDomains: ['127.0.0.1'], allowEval: false, allowDownloads: true, allowUploads: false,
    allowAllTabs: false, enableMutations: false, allowObservers: false,
  } });
  try {
    await ex.navigate({ url: `${base}/` });
    const byUrl = await ex.download({ url: `${base}/file.txt`, suggestedName: '../evil name.txt' });
    assert.equal(byUrl.backend, 'cdp');
    assert.equal(byUrl.bytes, 14);
    assert.match(String(byUrl.mimeType), /^text\/plain/);
    assert.ok(byUrl.path.startsWith(join(dir, 'downloads')), 'default download dir under the user data dir');
    assert.doesNotMatch(byUrl.path.slice(join(dir, 'downloads').length), /\.\./, 'the suggested name is sanitized');
    assert.equal(readFileSync(byUrl.path, 'utf8'), 'hello download');

    const byClick = await ex.download({ target: { selector: '#dl' }, suggestedName: 'clicked.txt' });
    assert.equal(byClick.suggestedName, 'saved.txt');
    assert.equal(byClick.bytes, 14);
    assert.equal(readFileSync(byClick.path, 'utf8'), 'hello download');

    // Redirect (URL and link): refused, attributed, and the target never contacted.
    await assert.rejects(
      ex.download({ url: `${base}/redirect-file` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_REDIRECT_REFUSED', { status: 302 }),
    );
    assert.ok(!requestLog.some((request) => request.host.startsWith('localhost:') && request.path === '/redirect-target'),
      'redirect target is not contacted');
    await assert.rejects(
      ex.download({ target: { selector: '#redirect-dl' } }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_REDIRECT_REFUSED', { status: 302 }),
    );
    assert.ok(!requestLog.some((request) => request.host.startsWith('localhost:') && request.path === '/redirect-target'),
      'link-triggered redirect target is not contacted');
    // Any redirect status is refused the same way (301 as well as 302).
    await assert.rejects(
      ex.download({ url: `${base}/redirect-permanent` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_REDIRECT_REFUSED', { status: 301 }),
    );
    assert.ok(!requestLog.some((request) => request.host.startsWith('localhost:') && request.path === '/redirect-target'),
      'a 301 destination is not contacted either');

    // Over the cap as declared by Content-Length, and as discovered while streaming:
    // both say DOWNLOAD_TOO_LARGE with the numbers, and both cancel the body.
    downloadFixtures.cancelled.clear();
    await assert.rejects(
      ex.download({ url: `${base}/oversize-declared` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_TOO_LARGE', { source: 'declared', declaredBytes: 60 * 1024 * 1024 }),
    );
    await assert.rejects(
      ex.download({ url: `${base}/oversize-streamed` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_TOO_LARGE', { source: 'streamed' }),
    );
    const cancelledBy = Date.now() + 2_000;
    while (downloadFixtures.cancelled.size < 2 && Date.now() < cancelledBy) await new Promise((r) => setTimeout(r, 50));
    assert.deepEqual([...downloadFixtures.cancelled].sort(), ['declared', 'streamed'], 'the server saw both response bodies cancelled');

    // A body that dies mid-read is a request failure, not a size or HTTP verdict.
    await assert.rejects(
      ex.download({ url: `${base}/broken-body` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_REQUEST_FAILED'),
    );

    // Policy veto keeps POLICY_DENIED but explains itself as a download-policy refusal.
    await ex.navigate({ url: `${base}/base-link` });
    await assert.rejects(ex.download({ target: { selector: '#base-dl' } }), errReason('POLICY_DENIED', 'DOWNLOAD_POLICY_DENIED'));
    assert.ok(!requestLog.some((request) => request.host.startsWith('localhost:') && request.path === '/redirect-target'),
      'link URL is resolved against its base element before policy evaluation');
    await ex.navigate({ url: `${base}/` });

    // A non-2xx answer is its own class: the status travels in the error.
    await assert.rejects(
      ex.download({ url: `${base}/nope` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_HTTP_STATUS', { status: 404 }),
    );
    // A 3xx that is not a redirect (304 Not Modified) is not mislabelled as one.
    await assert.rejects(
      ex.download({ url: `${base}/not-modified` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_HTTP_STATUS', { status: 304 }),
    );

    // Nothing listening at all is a transport failure, not an HTTP verdict.
    const deadPort = await new Promise<number>((r) => {
      const s = createServer();
      s.listen(0, '127.0.0.1', () => {
        const p = (s.address() as AddressInfo).port;
        s.close(() => r(p));
      });
    });
    await assert.rejects(
      ex.download({ url: `http://127.0.0.1:${deadPort}/gone` }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_REQUEST_FAILED'),
    );

    // The bytes arrived but could not be written (a directory already owns the
    // name): attributable to the save step, not to the request.
    mkdirSync(join(dir, 'downloads', sanitizeDownloadName('file.txt')));
    await assert.rejects(
      ex.download({ url: `${base}/file.txt`, suggestedName: 'file.txt' }),
      errReason('DOWNLOAD_FAILED', 'DOWNLOAD_SAVE_FAILED'),
    );

    // A missing url/target is a bad argument, distinguishable from a fetch failure.
    await assert.rejects(ex.download({}), errReason('DOWNLOAD_FAILED', 'DOWNLOAD_TARGET_INVALID'));

    const f1 = join(dir, 'up1.txt');
    const f2 = join(dir, 'up2.txt');
    writeFileSync(f1, 'one');
    writeFileSync(f2, 'two');
    assert.deepEqual(await ex.uploadFile({ selector: '#file' }, [f1, f2]), { ok: true });
    assert.deepEqual((await ex.eval('Array.from(document.getElementById("file").files).map((f) => f.name)')).value, ['up1.txt', 'up2.txt']);
    await assert.rejects(ex.uploadFile({ selector: '#file' }, [join(dir, 'missing.txt')]), (err: unknown) => {
      errCode('UPLOAD_FAILED')(err);
      assert.match((err as Error).message, /file not found: .*missing\.txt/);
      return true;
    });
    await assert.rejects(ex.uploadFile({ selector: '#btn' }, [f1]), (err: unknown) => {
      errCode('UPLOAD_FAILED')(err);
      assert.match((err as Error).message, /^could not set files on the input/);
      return true;
    });
    await assert.rejects(ex.uploadFile({} as never, [f1]), errCode('SELECTOR_NOT_FOUND'));
  } finally {
    await ex.dispose();
  }
});

/**
 * Top-level browser processes whose command line names `dir`. POSIX uses `ps`;
 * Windows has no `ps`, so it asks CIM (which also shows the command line). The
 * PowerShell that runs the query itself mentions `dir`, and its own child
 * processes carry `--type=`, so both are filtered out by name/arg.
 */
function browsersFor(dir: string): number[] {
  if (process.platform === 'win32') {
    const out = execFileSync(
      'powershell',
      [
        '-NoProfile',
        '-Command',
        `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains('${dir}') } | ForEach-Object { "$($_.Name)|$($_.ProcessId)|$($_.CommandLine)" }`,
      ],
      { encoding: 'utf8' },
    );
    return out
      .split('\n')
      .map((l) => l.trim())
      .filter((l) => /^chrome(-headless-shell)?\.exe\|/i.test(l) && !l.includes('--type='))
      .map((l) => Number.parseInt(l.split('|')[1], 10))
      .filter((n) => Number.isInteger(n));
  }
  const out = execFileSync('ps', ['-eo', 'pid=,command='], { encoding: 'utf8' });
  return out
    .split('\n')
    .filter((l) => l.includes(dir) && !l.includes('--type='))
    .map((l) => Number.parseInt(l.trim(), 10))
    .filter((n) => Number.isInteger(n));
}

/** Kill whatever a test left running for `dir`, so the test process can exit. */
function killBrowsersFor(dir: string): void {
  for (const pid of browsersFor(dir)) {
    try {
      process.kill(pid, 'SIGKILL');
    } catch {
      /* gone */
    }
  }
}

/** Close a page while an operation on it is in flight: the op must fail DETACHED. */
async function detachMidOperation(ex: CdpExecutor, expectedMode: 'connect' | 'launch'): Promise<ExecutorError> {
  const tab = await ex.tabNew(`${base}/second`);
  const pending = ex.waitFor({ tabId: tab.tabId, selector: '#never', timeoutMs: 10_000 });
  setTimeout(() => void ex.tabClose(tab.tabId).catch(() => undefined), 100);
  const err = await pending.then(
    () => assert.fail('the in-flight operation should have failed'),
    (e: unknown) => e,
  );
  errReason('DETACHED', expectedMode === 'connect' ? 'DETACHED_CONNECT' : 'DETACHED_LAUNCH', {
    mode: expectedMode,
    contextDropped: true,
  })(err);
  return err as ExecutorError;
}

test('CdpExecutor: a target closed mid-operation surfaces as DETACHED and the next call relaunches', { skip: !hasChromium }, async () => {
  const dir = mkdtempSync(join(tmpdir(), 'cmcp-cdpx-'));
  const ex = new CdpExecutor({ mode: 'launch', userDataDir: dir, headless: true });
  try {
    await ex.navigate({ url: `${base}/` });
    const [tab] = await ex.tabsList();
    await ex.tabClose(tab.tabId);
    await assert.rejects(ex.getText(undefined, { tabId: tab.tabId }), errCode('TAB_NOT_FOUND'), 'a closed handle is gone');

    const detachErr = await detachMidOperation(ex, 'launch');
    // The message itself names the mode and the dropped cache, so a caller reading
    // only the text can still tell what happened.
    assert.match(detachErr.message, /mode: launch/);
    assert.match(detachErr.message, /cached context dropped/);
    assert.equal(detachErr.details?.relaunchOnNextCall, true, 'launch mode: a fresh Chromium is started next call');
    assert.equal(ex.status().ready, false, 'the cached context was dropped');
    const nav = await ex.navigate({ url: `${base}/second` });
    assert.equal(nav.title, 'Second', 'the next call relaunched');
  } finally {
    await ex.dispose();
    killBrowsersFor(dir);
  }
});

test(
  'CdpExecutor: dropping a context after DETACHED does not orphan the Chromium it launched',
  {
    skip: !hasChromium,
  },
  async () => {
    const dir = mkdtempSync(join(tmpdir(), 'cmcp-cdpx-'));
    const ex = new CdpExecutor({ mode: 'launch', userDataDir: dir, headless: true });
    try {
      await ex.ensureReady();
      assert.equal(browsersFor(dir).length, 1);
      await detachMidOperation(ex, 'launch');
      await ex.navigate({ url: `${base}/second` });
      await new Promise((r) => setTimeout(r, 500));
      assert.equal(browsersFor(dir).length, 1, 'still exactly one launched Chromium after the relaunch');
      await ex.dispose();
      await new Promise((r) => setTimeout(r, 500));
      assert.deepEqual(browsersFor(dir), [], 'dispose leaves no Chromium behind');
    } finally {
      await ex.dispose();
      killBrowsersFor(dir);
    }
  },
);

test('CdpExecutor: connect mode attaches to a running Chrome and never closes it', { skip: !hasChromium }, async () => {
  const noEndpoint = new CdpExecutor({ mode: 'connect', userDataDir: mkdtempSync(join(tmpdir(), 'cmcp-cdpx-')) });
  await assert.rejects(noEndpoint.ensureReady(), (err: unknown) => {
    errCode('LAUNCH_FAILED')(err);
    assert.match((err as Error).message, /requires a cdpEndpoint/);
    return true;
  });

  const port = await new Promise<number>((r) => {
    const s = createServer();
    s.listen(0, '127.0.0.1', () => {
      const p = (s.address() as AddressInfo).port;
      s.close(() => r(p));
    });
  });
  const browser = await chromium.launch({ headless: true, args: [`--remote-debugging-port=${port}`] });
  try {
    const ex = new CdpExecutor({ mode: 'connect', cdpEndpoint: `http://127.0.0.1:${port}`, userDataDir: mkdtempSync(join(tmpdir(), 'cmcp-cdpx-')) });
    await ex.ensureReady();
    const tab = await ex.tabNew(`${base}/second`);
    assert.equal(tab.title, 'Second');

    // A page dying mid-operation in connect mode is still DETACHED, but says the
    // mode and that we only dropped the cache — we must never close their browser.
    const detachErr = await detachMidOperation(ex, 'connect');
    assert.match(detachErr.message, /mode: connect/);
    assert.equal(detachErr.details?.relaunchOnNextCall, false, 'connect mode: no browser of ours to close');
    assert.equal(browser.isConnected(), true, 'a mid-operation detach leaves the user\'s Chrome running');
    assert.equal(ex.status().ready, false, 'the cached context was dropped so the next call reconnects');
    assert.ok((await ex.tabsList()).some((t) => t.url === `${base}/second`), 'the next call reconnects to the same browser');

    await ex.dispose();
    assert.equal(browser.isConnected(), true, 'dispose in connect mode leaves the browser running');
    // A second executor reconnects to the same browser.
    const again = new CdpExecutor({ mode: 'connect', cdpEndpoint: `http://127.0.0.1:${port}`, userDataDir: mkdtempSync(join(tmpdir(), 'cmcp-cdpx-')) });
    assert.ok((await again.tabsList()).some((t) => t.url === `${base}/second`));
    await again.dispose();
  } finally {
    await browser.close();
  }
});
