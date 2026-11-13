import { Router, type Request, type Response } from 'express';
import { tracker as defaultTracker, type FormattedTrade, type TradeTracker } from '../services/live-trades';

/**
 * Server-sent events: the cached trades for a mint, then every new one from the API websocket.
 * A missing or too-short mint is rejected with 400 before any stream state is created. When the client (or the
 * process) closes the connection, every per-request resource — the trade listener, the heartbeat interval and the
 * initial-send timer — is released so detached clients cannot leak.
 *
 * The factory takes the tracker explicitly so the offline tests can bind it to an isolated instance; the default
 * router is bound to the process-wide singleton.
 */
export function createLiveTradesRouter(tracker: TradeTracker): Router {
  const router = Router();

  router.get('/', (req: Request, res: Response) => {
    const mint = String(req.query.mint || '');
    if (!mint || mint.length < 32) return res.status(400).json({ error: 'mint query param required' });

    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
    tracker.subscribe(mint);

    let closed = false;
    const cleanup = () => {
      if (closed) return;
      closed = true;
      clearInterval(keepalive);
      clearTimeout(initialTimer);
      tracker.removeListener(onTrade);
    };

    const initialTimer = setTimeout(() => {
      try { res.write(`data: ${JSON.stringify({ type: 'initial', trades: tracker.getTrades() })}\n\n`); } catch { /* closed */ }
    }, 500);
    initialTimer.unref?.();

    const onTrade = (trade: FormattedTrade) => { try { res.write(`data: ${JSON.stringify({ type: 'trade', trade })}\n\n`); } catch { /* closed */ } };
    tracker.addListener(onTrade);
    const keepalive = setInterval(() => { try { res.write(': ping\n\n'); } catch { /* closed */ } }, 15_000);
    keepalive.unref?.();

    req.on('close', cleanup);
    res.on('close', cleanup);
  });

  return router;
}

export default createLiveTradesRouter(defaultTracker);
