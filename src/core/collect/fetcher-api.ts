import type { CollectOptions, FlightFetcher, PageFetch } from './types.ts';
import { pageFetchFromBody } from './parse.ts';

export interface ApiFetcherOptions {
  baseUrl: string;
  from: string;
  to: string;
  sort?: string;
  /** Injectable for tests; defaults to the global fetch. */
  fetchImpl?: typeof fetch;
}

/**
 * Collects pages by calling `/api/flights` directly. Every failure mode is turned into a PageFetch instead of
 * a rejection: a non-2xx status becomes `failed` with the status code, an aborted request becomes `timeout`,
 * and any other network/parse error becomes `failed` with the message.
 */
export class ApiFlightFetcher implements FlightFetcher {
  readonly path = 'api' as const;
  private readonly baseUrl: string;
  private readonly from: string;
  private readonly to: string;
  private readonly sort: string;
  private readonly fetchImpl: typeof fetch;

  constructor(opts: ApiFetcherOptions) {
    this.baseUrl = opts.baseUrl.replace(/\/+$/, '');
    this.from = opts.from;
    this.to = opts.to;
    this.sort = opts.sort ?? 'best';
    this.fetchImpl = opts.fetchImpl ?? ((...args) => globalThis.fetch(...args));
  }

  static forOptions(opts: CollectOptions, fetchImpl?: typeof fetch): ApiFlightFetcher {
    return new ApiFlightFetcher({ baseUrl: opts.baseUrl, from: opts.from.code, to: opts.to.code, sort: opts.sort, fetchImpl });
  }

  /** The URL requested for one page. */
  urlFor(date: string, page: number): string {
    const q = new URLSearchParams({ from: this.from, to: this.to, date, page: String(page), sort: this.sort });
    return `${this.baseUrl}/api/flights?${q.toString()}`;
  }

  async fetchPage(date: string, page: number, timeoutMs: number): Promise<PageFetch> {
    const url = this.urlFor(date, page);
    const ctrl = new AbortController();
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, timeoutMs);
    try {
      const res = await this.fetchImpl(url, { signal: ctrl.signal, headers: { accept: 'application/json' } });
      const body = await res.text();
      if (!res.ok) return { outcome: 'failed', httpStatus: res.status, error: `HTTP ${res.status}` };
      return pageFetchFromBody(body, res.status);
    } catch (e) {
      if (timedOut || (e instanceof Error && (e.name === 'AbortError' || /abort/i.test(e.message)))) {
        return { outcome: 'timeout', error: `no response within ${timeoutMs}ms` };
      }
      return { outcome: 'failed', error: e instanceof Error ? e.message : String(e) };
    } finally {
      clearTimeout(timer);
    }
  }
}
