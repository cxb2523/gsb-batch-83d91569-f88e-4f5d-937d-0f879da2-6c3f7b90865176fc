// Process-wide budget shared by all web visitors. The collector is a separate process.
export function createUpstreamGuard(fetcher, { perMinute = 1200, concurrent = 32, now = Date.now } = {}) {
  let used = 0, until = 0, active = 0, pausedUntil = 0;
  return async (input, init) => {
    const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
    if (url.origin !== 'https://market.ft.tech' || url.pathname !== '/gateway/mcp') return fetcher(input, init);
    const time = now();
    if (time >= until) { used = 0; until = time + 60000; }
    if (time < pausedUntil || used >= perMinute || active >= concurrent) {
      const error = new Error('FtShare web request budget reached'); error.code = 'quota_exceeded'; throw error;
    }
    used++; active++;
    try {
      const response = await fetcher(input, init);
      if (response.status === 429) pausedUntil = now() + 60000;
      // Count the body download too; simply receiving headers does not finish a request.
      const body = await response.arrayBuffer();
      return new Response([204, 205, 304].includes(response.status) ? null : body, { status: response.status, statusText: response.statusText, headers: response.headers });
    } finally { active--; }
  };
}
