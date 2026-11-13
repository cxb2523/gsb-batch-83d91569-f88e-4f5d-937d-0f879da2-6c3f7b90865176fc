import { isIP } from 'node:net';

export function positiveOption(env, name, fallback) {
  const value = env[name] === undefined || env[name] === '' ? fallback : Number(env[name]);
  if (!Number.isInteger(value) || value < 1 || value > 100000) throw new Error(name + ' must be an integer between 1 and 100000');
  return value;
}
const normalized = ip => ip?.startsWith('::ffff:') ? ip.slice(7) : ip || 'unknown';
export function clientAddress(request, trustLoopback = false) {
  const peer = normalized(request.socket.remoteAddress);
  // Trust exactly one address, and only when the immediate peer is our local proxy.
  const forwarded = request.headers['x-forwarded-for'];
  return trustLoopback && ['127.0.0.1', '::1'].includes(peer) && typeof forwarded === 'string' && isIP(forwarded.trim())
    ? normalized(forwarded.trim()) : peer;
}
export function createRequestGuard({ perMinute = 180, concurrent = 32, maxClients = 10000, now = Date.now } = {}) {
  const clients = new Map(); let active = 0, lastPrune = 0;
  return {
    enter(ip) {
      const time = now();
      if (time - lastPrune >= 60000) { for (const [key, value] of clients) if (value.until <= time) clients.delete(key); lastPrune = time; }
      if (active >= concurrent) return null;
      let client = clients.get(ip);
      if (!client || client.until <= time) {
        if (!client && clients.size >= maxClients) return null;
        client = { count: 0, until: time + 60000 }; clients.set(ip, client);
      }
      if (client.count >= perMinute) return null;
      client.count++; active++;
      let done = false;
      return () => { if (!done) { active--; done = true; } };
    }
  };
}
