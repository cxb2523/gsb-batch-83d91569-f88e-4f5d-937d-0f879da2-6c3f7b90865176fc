import type { FlightFetcher } from './types.ts';
import type { PageSession } from '../cdp/page.ts';
import { BrowserFlightFetcher } from './fetcher-browser.ts';
import { ApiFlightFetcher } from './fetcher-api.ts';
import type { CityRef, CollectOptions, CollectPath } from './types.ts';

export interface SelectFetcherOptions {
  /** Browser page to drive when `path` is `browser`. */
  page?: PageSession;
  /** Called with human-readable actions from the browser path. */
  onAction?: (note: string) => void;
  fetchImpl?: typeof fetch;
}

/** Builds the fetcher a path/options pair calls for; throws when the browser path has no page to drive. */
export function selectFetcher(opts: CollectOptions, path: CollectPath, sel: SelectFetcherOptions = {}): FlightFetcher {
  if (path === 'api') return ApiFlightFetcher.forOptions(opts, sel.fetchImpl);
  if (!sel.page) throw new Error('path "browser" requires a PageSession');
  const city = (c: CityRef): CityRef => ({ code: c.code, name: c.name });
  return new BrowserFlightFetcher({ page: sel.page, baseUrl: opts.baseUrl, from: city(opts.from), to: city(opts.to), onAction: sel.onAction });
}
