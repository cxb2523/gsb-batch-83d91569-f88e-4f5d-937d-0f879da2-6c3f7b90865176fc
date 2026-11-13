import {OlostepTransport} from '../http/transport.js';
import {MapRequest, PagesIteratorOptions, WaitTillDoneOptions} from '../types.js';
import {OlostepResource} from './base.js';
import {Map} from '../client_state/Map.js';
import {normalizeToCamel} from '../casing.js';

export interface MapResponse extends Record<string, unknown> {
  id: string;
  urlsCount: number;
  hasMore: boolean;
}

interface MapUrlsResponse {
  urls?: string[];
  items?: string[];
  cursor?: string | number | null;
  next_cursor?: string | number | null;
}

export class MapNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  private normalizePatterns(value?: string | string[]) {
    if (value === undefined) {
      return undefined;
    }
    return Array.isArray(value) ? value : [value];
  }

  async create(input: string | MapRequest) {
    const payload: MapRequest = typeof input === 'string' ? {url: input} : normalizeToCamel(input);
    const body = {
      url: payload.url,
      search_query: payload.searchQuery,
      top_n: payload.topN,
      include_subdomain: payload.includeSubdomain,
      include_urls: this.normalizePatterns(payload.includeUrls),
      exclude_urls: this.normalizePatterns(payload.excludeUrls)
    };
    const {data} = await this.transport.request<MapResponse>({
      method: 'POST',
      path: '/maps',
      body
    });
    return new Map(this.transport, data);
  }

  async info(mapId: string) {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/maps/${mapId}`
    });
    return data;
  }

  async waitTillDone(mapId: string, options?: WaitTillDoneOptions): Promise<void> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const checkEveryNSecs = opts?.checkEveryNSecs ?? 10;
    const timeoutSeconds = opts?.timeoutSeconds ?? 600;
    const startTime = Date.now();

    while (true) {
      const info = (await this.info(mapId)) as {status?: string};
      const waitElapsed = (Date.now() - startTime) / 1000;

      if (info.status === 'completed' || info.status === 'failed') {
        return;
      }

      if (waitElapsed >= timeoutSeconds) {
        throw new Error(
          `waitTillDone timed out after ${waitElapsed.toFixed(2)}s (timeout: ${timeoutSeconds}s)`
        );
      }

      await new Promise((resolve) => setTimeout(resolve, checkEveryNSecs * 1000));
    }
  }

  async *urls(mapId: string, options?: PagesIteratorOptions): AsyncGenerator<string> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const limit = opts?.batchSize ?? 50;
    let cursor: string | undefined = opts?.cursor;

    while (true) {
      const {data} = await this.transport.request<MapUrlsResponse>({
        method: 'GET',
        path: `/maps/${mapId}/urls`,
        query: {
          limit,
          cursor,
          wait_for_completion: opts?.waitForCompletion
        }
      });

      const items = data?.urls ?? data?.items ?? [];
      if (!items.length) {
        break;
      }

      for (const url of items) {
        yield url;
      }

      const nextCursor = data?.next_cursor ?? data?.cursor;
      if (!nextCursor) {
        break;
      }
      const next = String(nextCursor);
      if (next === cursor) {
        // The cursor did not advance: yielding again would repeat the same page.
        break;
      }
      cursor = next;
    }
  }

  // Shorthand callable
  public async call(...args: Parameters<MapNamespace['create']>) {
    return this.create(...args);
  }
}

