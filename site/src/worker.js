// getcheapapi.com: static assets, plus Rybbit analytics proxied through /stats/ (wrangler.jsonc sends only those
// paths here). RYBBIT_UPSTREAM is a secret so the shared collector never shows up in this public repo or the pages.
const STATS = '/stats';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!url.pathname.startsWith(`${STATS}/`)) return env.ASSETS.fetch(request);
    if (!env.RYBBIT_UPSTREAM) return new Response(null, { status: 404 });
    if (request.method === 'OPTIONS') return new Response(null, { status: 204 });
    if (request.method !== 'GET' && request.method !== 'POST') return new Response(null, { status: 405 });

    const headers = new Headers();
    for (const name of ['content-type', 'user-agent', 'accept-language', 'origin', 'referer']) {
      const value = request.headers.get(name);
      if (value) headers.set(name, value);
    }
    // Rybbit geolocates by visitor IP (the site has First-Party Proxy on); cookies are not forwarded.
    const ip = request.headers.get('cf-connecting-ip');
    if (ip) headers.set('x-forwarded-for', ip);

    const target = `${env.RYBBIT_UPSTREAM.replace(/\/$/, '')}${url.pathname.slice(STATS.length)}${url.search}`;
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === 'POST' ? await request.arrayBuffer() : undefined,
    });
    const out = new Headers();
    for (const name of ['content-type', 'cache-control']) {
      const value = response.headers.get(name);
      if (value) out.set(name, value);
    }
    return new Response(response.body, { status: response.status, headers: out });
  },
};
