/**
 * Offline tests for the live-trade collection chain. No real network: a fake websocket is injected into a
 * TradeTracker, and the SSE route runs against an in-process express server.
 *
 * Run: node --import tsx --test test/live-trades.test.ts
 */
import { test, before, after, describe } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import express from 'express';
import type { AddressInfo } from 'node:net';
import { TradeTracker, ownTrade, type WebSocketLike } from '../src/services/live-trades';
import { createLiveTradesRouter } from '../src/routes/live-trades';

const OPEN = 1;

/** A controllable stand-in for the `ws` client: records outgoing frames and lets the test drive open/close/message. */
class FakeSocket implements WebSocketLike {
  readyState = 0;
  sent: Array<Record<string, unknown>> = [];
  closed = false;
  private listeners: Record<string, Set<(...args: any[]) => void>> = {};

  on(event: string, listener: (...args: any[]) => void): this {
    (this.listeners[event] ??= new Set()).add(listener);
    return this;
  }
  private emit(event: string, ...args: unknown[]) {
    this.listeners[event]?.forEach((l) => l(...args));
  }
  send(data: string) { this.sent.push(JSON.parse(data)); }
  close() { this.closed = true; this.readyState = 3; this.emit('close'); }
  removeAllListeners() { this.listeners = {}; }

  /** Test helpers (declared on WebSocketLike as optional). */
  open() { this.readyState = OPEN; this.emit('open'); }
  emitFrame(data: string) { this.emit('message', data); }
  simulateClose() { this.readyState = 3; this.emit('close'); }
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
/** 44-char base58-ish mint, long enough for the SSE route's length check. */
const mint = (id: string) => (id + '1'.repeat(44)).slice(0, 44);
const MINT_A = mint('AAAAAAAAAAAAAAAA');
const MINT_B = mint('BBBBBBBBBBBBBBBB');

function rawTrade(o: { sig: string; mint: string; trader: string; txType?: 'buy' | 'sell'; solAmount?: number; tokens?: number; timestamp?: number }) {
  return JSON.stringify({
    txType: o.txType ?? 'buy',
    signature: o.sig,
    mint: o.mint,
    traderPublicKey: o.trader,
    solAmount: o.solAmount ?? 1,
    buy: o.tokens ?? 100,
    timestamp: o.timestamp ?? 1_700_000_000_000,
  });
}

function makeTracker(dataDir: string) {
  const sockets: FakeSocket[] = [];
  const tracker = new TradeTracker({
    reconnectDelayMs: 25,
    dataDir,
    socketFactory: () => { const s = new FakeSocket(); sockets.push(s); return s; },
  });
  return { tracker, sockets };
}

let tmpRoot: string;
const savedEnv = { ...process.env };

before(() => {
  tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'live-trades-test-'));
  // Keep the (gitignored) vault/settings paths out of the repo; the trackers themselves write under tmpRoot.
  process.env.KEYS_DATA_DIR = path.join(tmpRoot, 'keys');
  process.env.TRENCHY_API_KEY = 'test-secret-key';
  process.env.TRENCHY_API_URL = 'https://api1.example.com';
});

after(() => {
  Object.assign(process.env, savedEnv);
  fs.rmSync(tmpRoot, { recursive: true, force: true });
});

describe('websocket reconnect lifecycle', () => {
  test('unexpected close reconnects on a fixed delay and re-subscribes the current mint', async () => {
    const dataDir = path.join(tmpRoot, 'reconnect');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      assert.ok(s1, 'a socket was opened on subscribe');
      s1.open();
      assert.deepEqual(s1.sent, [{ method: 'subscribeTokenTrade', keys: [MINT_A] }]);

      s1.simulateClose();
      assert.equal(sockets.length, 1, 'reconnect is delayed, not immediate');
      await sleep(45);
      assert.equal(sockets.length, 2, 'a fresh socket was opened after the fixed delay');
      const s2 = sockets[1];
      assert.notEqual(s2, s1);

      s2.open();
      assert.deepEqual(s2.sent, [{ method: 'subscribeTokenTrade', keys: [MINT_A] }], 'current mint re-subscribed on the new socket');

      // The old socket is fully detached: a late frame on it must never touch current state.
      s1.emitFrame(rawTrade({ sig: 'stale-sig', mint: MINT_A, trader: 'stale-wallet' }));
      assert.equal(tracker.getTrades().length, 0);
    } finally {
      tracker.dispose();
    }
  });

  test('a deliberate close from an API URL change schedules no extra reconnect', async () => {
    const dataDir = path.join(tmpRoot, 'url-change');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();

      process.env.TRENCHY_API_URL = 'https://api2.example.com';
      tracker.subscribe(MINT_A);
      const s2 = sockets[1];
      assert.ok(s1.closed, 'the old socket was closed intentionally');
      assert.ok(s2 && s2 !== s1, 'a socket for the new URL was opened directly');

      await sleep(60);
      assert.equal(sockets.length, 2, 'no reconnect was scheduled for the intentional close');
    } finally {
      process.env.TRENCHY_API_URL = 'https://api1.example.com';
      tracker.dispose();
    }
  });

  test('the API key is never written to logs', () => {
    const dataDir = path.join(tmpRoot, 'redact');
    const logs: string[] = [];
    const origLog = console.log;
    console.log = (...a: unknown[]) => logs.push(a.map(String).join(' '));
    const { tracker } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      assert.ok(logs.some((l) => l.includes('[feed] connecting')));
      assert.ok(!logs.some((l) => l.includes('test-secret-key')), 'connect log redacts the api-key query param');
    } finally {
      console.log = origLog;
      tracker.dispose();
    }
  });
});

describe('switching coins', () => {
  test('old coin is flushed to disk; memory and the dedup set only hold the new coin', async () => {
    const dataDir = path.join(tmpRoot, 'switch');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();
      s1.emitFrame(rawTrade({ sig: 'sig-A1', mint: MINT_A, trader: 'wallet-A' }));
      assert.equal(tracker.getTrades().length, 1);

      tracker.subscribe(MINT_B);
      // Same socket: old coin unsubscribed, new one subscribed on it.
      assert.deepEqual(s1.sent.slice(-2), [
        { method: 'unsubscribeTokenTrade', keys: [MINT_A] },
        { method: 'subscribeTokenTrade', keys: [MINT_B] },
      ]);
      assert.deepEqual(tracker.getTrades(), [], 'the new panel starts empty (no in-memory carry-over)');

      // The old coin's trades landed in its own file.
      const fileA = path.join(dataDir, `${MINT_A}.json`);
      const persistedA = JSON.parse(fs.readFileSync(fileA, 'utf8')) as Array<{ signature: string; mint: string }>;
      assert.equal(persistedA.length, 1);
      assert.equal(persistedA[0].signature, 'sig-A1');

      // The signature set was reset: the same signature is accepted again for the new coin.
      s1.emitFrame(rawTrade({ sig: 'sig-A1', mint: MINT_B, trader: 'wallet-B' }));
      const tradesB = tracker.getTrades();
      assert.equal(tradesB.length, 1);
      assert.equal(tradesB[0].mint, MINT_B);
      assert.equal(tradesB[0].signature, 'sig-A1');

      // Frames for the coin we left are ignored outright.
      s1.emitFrame(rawTrade({ sig: 'sig-A9', mint: MINT_A, trader: 'wallet-A' }));
      assert.equal(tracker.getTrades().length, 1);

      // An injection for the coin we left cannot pollute the current panel.
      tracker.injectTrade(ownTrade(MINT_A, 'buy', 'wallet-A', 1, 100, 'dev', 'Dev', 'sig-injected-old'));
      assert.equal(tracker.getTrades().length, 1);
    } finally {
      tracker.dispose();
    }
  });

  test('repeated identical signatures on the feed collapse to one row', () => {
    const dataDir = path.join(tmpRoot, 'dedup');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();
      s1.emitFrame(rawTrade({ sig: 'dup', mint: MINT_A, trader: 'w1' }));
      s1.emitFrame(rawTrade({ sig: 'dup', mint: MINT_A, trader: 'w1' }));
      s1.emitFrame(rawTrade({ sig: 'other', mint: MINT_A, trader: 'w2' }));
      const sigs = tracker.getTrades().map((t) => t.signature).sort();
      assert.deepEqual(sigs, ['dup', 'other']);
    } finally {
      tracker.dispose();
    }
  });

  test('re-subscribing to the same mint keeps live rows not yet flushed to disk', () => {
    const dataDir = path.join(tmpRoot, 'resubscribe');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();
      s1.emitFrame(rawTrade({ sig: 'live-only', mint: MINT_A, trader: 'w1' }));
      assert.equal(tracker.getTrades().length, 1);

      // A second SSE client subscribes to the same coin: no file flush happened yet, but the row must survive.
      tracker.subscribe(MINT_A);
      const rows = tracker.getTrades();
      assert.equal(rows.length, 1);
      assert.equal(rows[0].signature, 'live-only');

      // Dedup still works after the re-subscribe.
      s1.emitFrame(rawTrade({ sig: 'live-only', mint: MINT_A, trader: 'w1' }));
      assert.equal(tracker.getTrades().length, 1);
    } finally {
      tracker.dispose();
    }
  });
});

describe('injected trades vs the real feed', () => {
  test('real copy of an injected signature upgrades the row in place to our wallet, no duplicate', () => {
    const dataDir = path.join(tmpRoot, 'inject-upgrade');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();

      // Feed arrives first: an ordinary (not-yet-ours) row.
      s1.emitFrame(rawTrade({ sig: 'sig-1', mint: MINT_A, trader: 'our-wallet' }));
      assert.equal(tracker.getTrades()[0].isOurWallet, false);

      // Then the app learns it sent that exact transaction.
      tracker.injectTrade(ownTrade(MINT_A, 'buy', 'our-wallet', 2, 200, 'dev', 'Dev wallet', 'sig-1'));
      const rows = tracker.getTrades();
      assert.equal(rows.length, 1, 'no duplicate row is added');
      assert.equal(rows[0].isOurWallet, true);
      assert.equal(rows[0].walletType, 'dev');
      assert.equal(rows[0].walletLabel, 'Dev wallet');
      assert.equal(rows[0].signature, 'sig-1');

      // Reverse order: injection first, then the feed's copy of the same signature stays one row.
      tracker.injectTrade(ownTrade(MINT_A, 'sell', 'our-wallet', 1, 50, 'dev', 'Dev wallet', 'sig-2'));
      s1.emitFrame(rawTrade({ sig: 'sig-2', mint: MINT_A, trader: 'our-wallet', txType: 'sell' }));
      assert.equal(tracker.getTrades().length, 2);
      assert.ok(tracker.getTrades().some((t) => t.signature === 'sig-2' && t.isOurWallet));
    } finally {
      tracker.dispose();
    }
  });

  test("the synthetic launch-buy row is replaced by the wallet's first real buy", () => {
    const dataDir = path.join(tmpRoot, 'launch-replace');
    const { tracker, sockets } = makeTracker(dataDir);
    try {
      tracker.subscribe(MINT_A);
      const s1 = sockets[0];
      s1.open();

      const devWallet = 'dev-wallet-pubkey';
      tracker.injectLaunchBuys(MINT_A, [
        ownTrade(MINT_A, 'buy', devWallet, 3, 300, 'dev', 'Dev', 'launch:run-1:dev'),
      ]);
      assert.equal(tracker.getTrades()[0].signature, 'launch:run-1:dev');

      // The real buy from the same wallet replaces the synthetic row, keeping wallet slot/label.
      s1.emitFrame(rawTrade({ sig: 'real-buy-1', mint: MINT_A, trader: devWallet, solAmount: 3, tokens: 300 }));
      const rows = tracker.getTrades();
      assert.equal(rows.length, 1);
      assert.equal(rows[0].signature, 'real-buy-1');
      assert.equal(rows[0].isOurWallet, true);
      assert.equal(rows[0].walletType, 'dev');
      assert.equal(rows[0].walletLabel, 'Dev');

      // A second real buy by the same wallet is a normal new row (the injected marker was consumed).
      s1.emitFrame(rawTrade({ sig: 'real-buy-2', mint: MINT_A, trader: devWallet }));
      const sigs = tracker.getTrades().map((t) => t.signature).sort();
      assert.deepEqual(sigs, ['real-buy-1', 'real-buy-2']);

      // The synthetic signature is gone from the dedup set and the real ones are tracked.
      s1.emitFrame(rawTrade({ sig: 'real-buy-1', mint: MINT_A, trader: devWallet }));
      assert.equal(tracker.getTrades().length, 2);
    } finally {
      tracker.dispose();
    }
  });
});

describe('SSE route', () => {
  let server: http.Server;
  let baseUrl: string;
  let sseTracker: TradeTracker;

  before(async () => {
    // The router is bound to an isolated tracker (its own tmp data dir, no real websocket), so the process-wide
    // singleton and the repo's data directory are never touched by these tests.
    sseTracker = new TradeTracker({
      reconnectDelayMs: 25,
      dataDir: path.join(tmpRoot, 'sse'),
      socketFactory: () => new FakeSocket(),
    });
    const app = express();
    app.use('/api/live-trades', createLiveTradesRouter(sseTracker));
    server = app.listen(0);
    await new Promise<void>((r) => server.once('listening', () => r()));
    baseUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
  });
  after(async () => {
    sseTracker.dispose();
    await new Promise<void>((r) => server.close(() => r()));
  });

  test('rejects a missing or too-short mint with 400', async () => {
    for (const q of ['', '?mint=short']) {
      const res = await fetch(`${baseUrl}/api/live-trades${q}`);
      assert.equal(res.status, 400);
      await res.body?.cancel();
    }
  });

  test('streams the initial snapshot and removes its listener when the client disconnects', async () => {
    const coin = mint('SSE-COIN-');
    const baseline = sseTracker.listenerCount();

    const chunks: Buffer[] = [];
    const req = http.get(`${baseUrl}/api/live-trades?mint=${coin}`, (res) => {
      assert.equal(res.statusCode, 200);
      assert.match(String(res.headers['content-type']), /text\/event-stream/);
      res.on('data', (c: Buffer) => chunks.push(c));
    });

    // Once subscribed, an injected trade is part of the initial snapshot.
    await sleep(80);
    sseTracker.injectTrade(ownTrade(coin, 'buy', 'w', 1, 100, 'manual', 'Manual', 'sse-sig'));

    await sleep(600);
    req.destroy();
    await sleep(80);

    const body = Buffer.concat(chunks).toString();
    assert.match(body, /"type":"initial"/);
    assert.match(body, /sse-sig/);
    assert.equal(sseTracker.listenerCount(), baseline, 'the trade listener was removed on disconnect');
  });
});
