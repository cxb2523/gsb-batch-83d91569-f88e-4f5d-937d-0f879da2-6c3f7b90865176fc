import { COLLECT_SEARCH_PATH, createCollectSearchHandler, type CollectSearchHost } from './collect-route.ts';

/** Runtime surface required to build the HTTP server. */
export interface ProviderServerHost extends CollectSearchHost {
  fetch(request: Request): Promise<Response>;
}

/** Options for {@link createProviderFetch}. */
export interface ProviderFetchOptions {
  /** Shared bearer token for the collection route and the host transport. */
  token: string;
  host: ProviderServerHost;
  /** Per-source deadline override, primarily for tests. */
  collectTimeoutMs?: number;
}

/**
 * Route incoming requests.
 *
 * `/health` and `/remedia/v1/media/` keep their existing behavior; `POST /collect/search`
 * is handled locally before the request is forwarded to the plugin host transport.
 */
export function createProviderFetch(
  options: ProviderFetchOptions,
): (request: Request, server: Bun.Server<unknown>) => Response | Promise<Response> {
  const handleCollect = createCollectSearchHandler({
    token: options.token,
    host: options.host,
    ...(options.collectTimeoutMs !== undefined ? { timeoutMs: options.collectTimeoutMs } : {}),
  });

  return (request, server) => {
    const pathname = new URL(request.url).pathname;

    if (pathname === '/health') {
      return Response.json({ status: 'ok' });
    }

    if (pathname === COLLECT_SEARCH_PATH) {
      return handleCollect(request);
    }

    if (pathname.startsWith('/remedia/v1/media/')) {
      server.timeout(request, 0);
    }

    return options.host.fetch(request);
  };
}
