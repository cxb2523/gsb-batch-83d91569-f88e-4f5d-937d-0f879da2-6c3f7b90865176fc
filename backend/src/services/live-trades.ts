/**
 * Live trades for the coin on screen, from the TrenchyTools websocket (wss …/api/sol/data, `subscribeTokenTrade`).
 * One connection; subscriptions are swapped on it. Trades are kept in memory (200 per coin) and persisted to
 * backend/data/live-trades/<mint>.json so a page reload still shows them.
 *
 * Connection lifecycle:
 *   - an unexpected socket close is retried on a fixed delay, and the current coin is re-subscribed on the new socket;
 *   - a close caused by switching coins or by a changed API URL is intentional (`manualClose`) and never schedules a
 *     reconnect, and the old socket's listeners are detached so a stale socket can never touch the new state.
 *
 * Coin switching: the outgoing coin's trades are flushed to its own file first, then the in-memory trades and the
 * dedup signature set are replaced wholesale — nothing from the old coin (trades, signatures, injected markers)
 * survives into the new panel.
 */
import WebSocket from 'ws';
import fs from 'fs';
import path from 'path';
import * as vault from './vault';
import { trenchy } from './trenchy';
import { LIVE_TRADES_DIR } from '../paths';

/** Fixed retry delay after an unexpected disconnect. */
const RECONNECT_DELAY = 3000;
const MAX_TRADES = 200;

export interface FormattedTrade {
  signature: string;
  mint: string;
  type: string;
  trader: string;
  traderShort: string;
  solAmount: number;
  tokenAmount: number;
  marketCapSol: number | null;
  timestamp: number;
  isOurWallet: boolean;
  walletType: string | null;
  walletLabel: string | null;
  pool: string | null;
}

type TradeListener = (trade: FormattedTrade) => void;

/** Minimal shape of the `ws` client the tracker drives, so tests can inject a fake connection. */
export interface WebSocketLike {
  readonly readyState: number;
  on(event: 'open' | 'close' | 'error' | 'message', listener: (...args: any[]) => void): unknown;
  send(data: string): unknown;
  close(): unknown;
  /** Test hook: deliver a raw text frame as the server would. */
  emitFrame?(data: string): void;
  /** Test hook: simulate an unexpected server-side close. */
  simulateClose?(): void;
}
export type SocketFactory = (url: string) => WebSocketLike;

/** A trade this app just sent, for the panel: marked as ours with its wallet's slot and label. */
export function ownTrade(mint: string, type: 'buy' | 'sell', trader: string, solAmount: number, tokenAmount: number, walletType: string | null, walletLabel: string | null, signature: string): FormattedTrade {
  return { signature, mint, type, trader, traderShort: trader ? `${trader.slice(0, 4)}...${trader.slice(-4)}` : '???', solAmount, tokenAmount, marketCapSol: null, timestamp: Date.now(), isOurWallet: true, walletType, walletLabel, pool: null };
}

export interface TrackerOptions {
  /** Fixed delay between an unexpected close and the reconnect attempt. */
  reconnectDelayMs?: number;
  /** Where trade files are written; defaults to the global live-trades data directory. */
  dataDir?: string;
  /** Open a custom (fake) connection instead of a real websocket. */
  socketFactory?: SocketFactory;
}

class TradeTracker {
  private ws: WebSocketLike | null = null;
  private subscribedMint: string | null = null;
  private trades: FormattedTrade[] = [];
  private listeners = new Set<TradeListener>();
  private seenSigs = new Set<string>();
  private ourWallets = new Map<string, { type: string; label: string }>();
  /** Mint → wallets whose synthetic launch-buy row is still waiting for the wallet's first real buy. */
  private injectedWallets = new Map<string, Set<string>>();
  private persistTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private wsUrl: string | null = null;
  /** True only while WE are closing the socket (coin switch / URL change / shutdown): such closes never reconnect. */
  private manualClose = false;
  private readonly reconnectDelayMs: number;
  private readonly dataDir: string;
  private readonly createSocket: SocketFactory;

  constructor(opts: TrackerOptions = {}) {
    this.reconnectDelayMs = opts.reconnectDelayMs ?? RECONNECT_DELAY;
    this.dataDir = opts.dataDir ?? LIVE_TRADES_DIR;
    this.createSocket = opts.socketFactory ?? ((url: string) => new WebSocket(url) as unknown as WebSocketLike);
  }

  private tradesFilePath(mint: string) { return path.join(this.dataDir, `${mint}.json`); }

  private loadPersisted(mint: string): FormattedTrade[] {
    const file = this.tradesFilePath(mint);
    if (!fs.existsSync(file)) return [];
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch { return []; }
  }

  private persist(mint: string, trades: FormattedTrade[]) {
    try {
      fs.mkdirSync(this.dataDir, { recursive: true });
      fs.writeFileSync(this.tradesFilePath(mint), JSON.stringify(trades.slice(0, MAX_TRADES)));
    } catch { /* best effort */ }
  }

  private refreshWallets() {
    this.ourWallets.clear();
    try {
      for (const w of vault.listWallets()) this.ourWallets.set(w.publicKey, { type: w.type, label: w.label });
    } catch { /* vault unreadable: trades show as not ours */ }
  }

  /**
   * Normalize a raw feed message into a panel trade. Does NOT touch the dedup set itself — callers own that, because
   * a duplicate that replaces a synthetic launch row must still be accepted on its own signature.
   */
  private formatTrade(raw: any): { trade: FormattedTrade; replacesInjected: boolean } | null {
    if (!raw.txType || raw.txType === 'create' || raw.txType === 'migrate') return null;
    const sig = raw.signature;
    if (!sig || this.seenSigs.has(sig)) return null;

    const trader = raw.traderPublicKey || '';
    const mint = raw.mint || '';
    let replacesInjected = false;
    if (raw.txType === 'buy') {
      const injectedSet = this.injectedWallets.get(mint);
      if (injectedSet?.has(trader)) {
        replacesInjected = true;
        injectedSet.delete(trader);
        if (injectedSet.size === 0) this.injectedWallets.delete(mint);
      }
    }
    // A wallet this app traded from is always "ours", even if the vault copy is momentarily unavailable.
    const walletInfo = this.ourWallets.get(trader);
    return {
      trade: {
        signature: sig, mint, type: raw.txType, trader,
        traderShort: trader ? `${trader.slice(0, 4)}...${trader.slice(-4)}` : '???',
        solAmount: raw.solAmount || raw.sol_amount || raw.amount || raw.sol || 0,
        tokenAmount: raw.txType === 'buy' ? (raw.buy || raw.tokenAmount || 0) : (raw.sell || raw.tokenAmount || 0),
        marketCapSol: raw.marketCapSol || null,
        timestamp: raw.timestamp || Date.now(),
        isOurWallet: !!walletInfo,
        walletType: walletInfo?.type || null,
        walletLabel: walletInfo?.label || null,
        pool: raw.pool || null,
      },
      replacesInjected,
    };
  }

  /**
   * A real trade matching a synthetic launch buy: replace the synthetic row in place, keeping the synthetic row's
   * wallet slot/label and its "ours" flag (the synthetic signature leaves the dedup set, the real one enters it).
   */
  private mergeInjected(trade: FormattedTrade): boolean {
    const idx = this.trades.findIndex(t => t.trader === trade.trader && t.mint === trade.mint && t.type === 'buy' && t.isOurWallet);
    if (idx === -1) return false;
    this.seenSigs.delete(this.trades[idx].signature);
    trade.isOurWallet = true;
    trade.walletType = this.trades[idx].walletType;
    trade.walletLabel = this.trades[idx].walletLabel;
    this.trades[idx] = trade;
    return true;
  }

  /** Detach every listener and drop a socket so a stale reconnecting socket can never mutate current state. */
  private teardownSocket(ws: WebSocketLike | null) {
    if (!ws) return;
    try { (ws as { removeAllListeners?: (e?: string) => void }).removeAllListeners?.(); } catch { /* no-op */ }
    if (ws === this.ws) this.ws = null;
  }

  private clearReconnectTimer() {
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null; }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      // Still following a coin and no live connection: open a fresh socket; its 'open' re-subscribes.
      if (this.subscribedMint && !this.ws) this.connect();
    }, this.reconnectDelayMs);
    this.reconnectTimer.unref?.();
  }

  /** Open the websocket. An existing socket is closed and discarded first; only unexpected closes reconnect. */
  private connect() {
    if (!this.wsUrl) { console.warn('[feed] no TrenchyTools API key: live trades off'); return; }
    if (this.ws) {
      this.manualClose = true;
      try { this.ws.close(); } catch { /* closing */ }
      this.teardownSocket(this.ws);
    }
    console.log('[feed] connecting to', this.wsUrl.replace(/api-key=[^&]+/, 'api-key=…'));
    const ws = this.createSocket(this.wsUrl);
    this.ws = ws;
    this.manualClose = false;

    ws.on('open', () => {
      if (ws !== this.ws) return;   // a stale socket from an earlier connection
      console.log('[feed] connected');
      if (this.subscribedMint) this.sendSubscribe(this.subscribedMint);
    });

    ws.on('message', (data: unknown) => {
      if (ws !== this.ws) return;
      try {
        const text = typeof data === 'string' ? data : Buffer.isBuffer(data) ? data.toString() : String(data);
        const msg = JSON.parse(text);
        if (!msg.txType) return;
        const result = this.formatTrade(msg);
        if (!result || result.trade.mint !== this.subscribedMint) return;
        const { trade, replacesInjected } = result;
        this.seenSigs.add(trade.signature);
        if (replacesInjected) {
          if (!this.mergeInjected(trade)) this.trades.unshift(trade);
        } else {
          this.trades.unshift(trade);
        }
        if (this.trades.length > MAX_TRADES) this.trades.length = MAX_TRADES;
        for (const cb of this.listeners) cb(trade);
      } catch { /* not a trade */ }
    });

    ws.on('close', () => {
      const stale = ws !== this.ws;
      console.log('[feed] disconnected');
      if (!stale) this.teardownSocket(ws);
      // Intentional closes (coin switch, API URL change, shutdown) must not trigger an extra reconnect.
      if (!stale && !this.manualClose) this.scheduleReconnect();
    });
    ws.on('error', (err: { message?: string }) => {
      if (ws !== this.ws) return;
      console.error('[feed] websocket error:', err?.message ?? err);
    });
  }

  private sendSubscribe(mint: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ method: 'subscribeTokenTrade', keys: [mint] }));
      console.log(`[feed] subscribed to ${mint.slice(0, 8)}...`);
    }
  }

  private sendUnsubscribe(mint: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ method: 'unsubscribeTokenTrade', keys: [mint] }));
  }

  private startPersistTimer() {
    this.stopPersistTimer();
    this.persistTimer = setInterval(() => {
      if (this.subscribedMint && this.trades.length > 0) this.persist(this.subscribedMint, this.trades);
    }, 10_000);
    this.persistTimer.unref?.();
  }

  private stopPersistTimer() {
    if (this.persistTimer) { clearInterval(this.persistTimer); this.persistTimer = null; }
  }

  /**
   * Follow one coin. The outgoing coin's trades are flushed to its own file first, then the in-memory trades and the
   * dedup signature set are replaced wholesale, so no record (or signature) of the old coin reaches the new panel.
   * A changed API URL deliberately closes the old socket without scheduling a reconnect.
   */
  subscribe(mint: string) {
    const api = trenchy();
    const url = api.configured ? api.wsUrl() : null;
    if (url !== this.wsUrl) {
      this.wsUrl = url;
      this.clearReconnectTimer();
      if (this.ws) {
        this.manualClose = true;
        try { this.ws.close(); } catch { /* closing */ }
        this.teardownSocket(this.ws);
      }
    }
    this.refreshWallets();
    const switching = !!this.subscribedMint && this.subscribedMint !== mint;
    if (switching) {
      if (this.trades.length > 0) this.persist(this.subscribedMint!, this.trades);
      this.injectedWallets.delete(this.subscribedMint!);
      this.sendUnsubscribe(this.subscribedMint!);
    }
    this.subscribedMint = mint;

    // Fresh panel for a new coin: only its persisted history, never the previous coin's memory or dedup set.
    // A re-subscribe to the SAME coin (another SSE client) keeps the live in-memory rows and merges history in,
    // so feed trades not yet flushed by the persist timer are not lost.
    const persisted = this.loadPersisted(mint).filter(t => t.mint === mint);
    if (switching) {
      const sigs = new Set<string>();
      const merged: FormattedTrade[] = [];
      for (const t of persisted) {
        if (sigs.has(t.signature)) continue;
        merged.push(t);
        sigs.add(t.signature);
      }
      merged.sort((a, b) => b.timestamp - a.timestamp);
      this.trades = merged.slice(0, MAX_TRADES);
      this.seenSigs = new Set(this.trades.map(t => t.signature));
    } else {
      const sigs = new Set(this.trades.map(t => t.signature));
      for (const t of persisted) {
        if (sigs.has(t.signature)) continue;
        this.trades.push(t);
        sigs.add(t.signature);
      }
      this.trades.sort((a, b) => b.timestamp - a.timestamp);
      if (this.trades.length > MAX_TRADES) this.trades.length = MAX_TRADES;
      this.seenSigs = new Set(this.trades.map(t => t.signature));
    }
    this.startPersistTimer();

    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) this.connect();
    else this.sendSubscribe(mint);
  }

  addListener(cb: TradeListener) { this.listeners.add(cb); }
  removeListener(cb: TradeListener) { this.listeners.delete(cb); }
  /** Test/observability hook: how many SSE streams are currently attached. */
  listenerCount(): number { return this.listeners.size; }
  getTrades(): FormattedTrade[] { return [...this.trades]; }

  /**
   * A trade this app sent (manual buy/sell, auto-sell): shown at once. If the feed later pushes the same signature it
   * is deduped — when the existing row was not yet marked ours it is upgraded in place to "our wallet", keeping the
   * injected wallet type and label instead of adding a duplicate row.
   */
  injectTrade(trade: FormattedTrade) {
    if (trade.isOurWallet && trade.trader) this.ourWallets.set(trade.trader, { type: trade.walletType ?? 'manual', label: trade.walletLabel ?? '' });
    // Injections for a coin we are no longer following must not pollute the current panel.
    if (this.subscribedMint !== trade.mint) return;
    if (this.seenSigs.has(trade.signature)) {
      const ex = this.trades.find(t => t.signature === trade.signature);
      if (ex && !ex.isOurWallet && trade.isOurWallet) {
        ex.isOurWallet = true;
        ex.walletType = trade.walletType;
        ex.walletLabel = trade.walletLabel;
        for (const cb of this.listeners) cb(ex);
        this.persist(trade.mint, this.trades);
      }
      return;
    }
    this.seenSigs.add(trade.signature);
    this.trades.unshift(trade);
    if (this.trades.length > MAX_TRADES) this.trades.length = MAX_TRADES;
    for (const cb of this.listeners) cb(trade);
    this.persist(trade.mint, this.trades);
  }

  /**
   * The launch buys (dev + bundle) with synthetic signatures, so the panel shows them even when the feed misses a
   * Jito bundle. The first real buy by the same wallet replaces its synthetic row (see mergeInjected).
   */
  injectLaunchBuys(mint: string, trades: FormattedTrade[]) {
    this.refreshWallets();
    if (this.subscribedMint !== mint) return;
    if (!this.injectedWallets.has(mint)) this.injectedWallets.set(mint, new Set());
    const injectedSet = this.injectedWallets.get(mint)!;
    for (const t of trades) {
      if (t.mint !== mint || this.seenSigs.has(t.signature)) continue;
      const existingIdx = this.trades.findIndex(ex => ex.trader === t.trader && ex.mint === mint && ex.type === 'buy');
      if (existingIdx !== -1) {
        this.trades[existingIdx].walletType = t.walletType;
        this.trades[existingIdx].walletLabel = t.walletLabel;
        this.trades[existingIdx].isOurWallet = true;
        continue;
      }
      injectedSet.add(t.trader);
      this.seenSigs.add(t.signature);
      this.trades.unshift(t);
      if (this.trades.length > MAX_TRADES) this.trades.length = MAX_TRADES;
      for (const cb of this.listeners) cb(t);
    }
    this.persist(mint, this.trades);
  }

  /** Shutdown/teardown: stop timers and close the socket without scheduling a reconnect. */
  dispose() {
    this.stopPersistTimer();
    this.clearReconnectTimer();
    if (this.ws) {
      this.manualClose = true;
      try { this.ws.close(); } catch { /* closing */ }
      this.teardownSocket(this.ws);
    }
  }
}

/** Process-wide tracker used by the HTTP routes. Tests construct their own isolated instances instead. */
export const tracker = new TradeTracker();
export { TradeTracker };
