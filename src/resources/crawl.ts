import {OlostepTransport} from '../http/transport.js';
import {CrawlRequest, PagesIteratorOptions} from '../types.js';
import {OlostepResource} from './base.js';
import {CrawlPage} from '../client_state/CrawlPage.js';
import {Crawl} from '../client_state/Crawl.js';
import {normalizeToCamel} from '../casing.js';

export interface CrawlResponse {
  id: string;
  urls: number;
  [key: string]: unknown;
}

interface CrawlPagesResponse {
  pages?: Record<string, unknown>[];
  items?: Record<string, unknown>[];
  cursor?: string | number | null;
  next_cursor?: string | number | null;
}

export class CrawlNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  private normalizePatterns(value?: string | string[]) {
    if (value === undefined) {
      return undefined;
    }
    return Array.isArray(value) ? value : [value];
  }

  async create(input: string | CrawlRequest) {
    const payload: CrawlRequest = typeof input === 'string' ? {url: input} : normalizeToCamel(input);
    const body = {
      start_url: payload.startUrl ?? payload.url,
      max_pages: payload.maxPages,
      include_urls: this.normalizePatterns(payload.includeUrls),
      exclude_urls: this.normalizePatterns(payload.excludeUrls),
      max_depth: payload.maxDepth,
      include_external: payload.includeExternal,
      include_subdomain: payload.includeSubdomain,
      search_query: payload.searchQuery,
      top_n: payload.topN,
      webhook_url: payload.webhookUrl
    };
    const {data} = await this.transport.request<CrawlResponse>({
      method: 'POST',
      path: '/crawls',
      body
    });
    return new Crawl(this.transport, data);
  }

  async info(crawlId: string) {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/crawls/${crawlId}`
    });
    return data;
  }

  async waitTillDone(crawlId: string): Promise<void> {
    throw new Error('waitTillDone not implemented yet.');
  }

  async *pages(
    crawlId: string,
    options?: PagesIteratorOptions
  ): AsyncGenerator<CrawlPage> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const limit = opts?.batchSize ?? 50;
    let cursor: string | undefined = opts?.cursor;

    while (true) {
      const {data} = await this.transport.request<CrawlPagesResponse>({
        method: 'GET',
        path: `/crawls/${crawlId}/pages`,
        query: {
          limit,
          cursor,
          wait_for_completion: opts?.waitForCompletion
        }
      });

      const items = (data as CrawlPagesResponse)?.pages ?? (data as CrawlPagesResponse)?.items ?? [];
      if (!items.length) {
        break;
      }

      for (const page of items) {
        yield new CrawlPage(page);
      }

      const nextCursor = (data as CrawlPagesResponse)?.next_cursor ?? (data as CrawlPagesResponse)?.cursor;
      if (!nextCursor) {
        break;
      }
      cursor = String(nextCursor);
    }
  }

  // Shorthand callable
  public async call(...args: Parameters<CrawlNamespace['create']>) {
    return this.create(...args);
  }
}

