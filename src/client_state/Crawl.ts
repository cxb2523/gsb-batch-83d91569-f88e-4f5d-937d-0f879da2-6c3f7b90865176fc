import {OlostepTransport} from '../http/transport.js';
import {PagesIteratorOptions, WaitTillDoneOptions} from '../types.js';
import {normalizeToCamel} from '../casing.js';
import {CrawlPage} from './CrawlPage.js';

interface CrawlHandleData extends Record<string, unknown> {
  id: string;
}

interface CrawlPagesResponse {
  pages?: Record<string, unknown>[];
  items?: Record<string, unknown>[];
  cursor?: string | number | null;
  next_cursor?: string | number | null;
}

export class Crawl {
  public readonly id: string;
  private readonly transport: OlostepTransport;
  [key: string]: unknown;

  constructor(transport: OlostepTransport, data: CrawlHandleData) {
    this.transport = transport;
    this.id = data.id;
    Object.assign(this, data);
  }

  async info(): Promise<unknown> {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/crawls/${this.id}`
    });
    return data;
  }

  async waitTillDone(options?: WaitTillDoneOptions): Promise<void> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const checkEveryNSecs = opts?.checkEveryNSecs ?? 10;
    const timeoutSeconds = opts?.timeoutSeconds ?? 600;
    const startTime = Date.now();

    while (true) {
      const info = (await this.info()) as {
        status: string;
        current_depth?: number;
        pages_count?: number;
      };

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

  async *pages(options?: PagesIteratorOptions): AsyncGenerator<CrawlPage> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const limit = opts?.batchSize ?? 50;
    let cursor: string | undefined = opts?.cursor;
    const waitForCompletion = opts?.waitForCompletion ?? true;

    // Wait for the crawl to finish before paginating so we don't race the
    // server (matches the Python SDK behaviour). Callers can opt out with
    // { waitForCompletion: false }.
    if (waitForCompletion) {
      await this.waitTillDone();
    }

    while (true) {
      const {data} = await this.transport.request<CrawlPagesResponse>({
        method: 'GET',
        path: `/crawls/${this.id}/pages`,
        query: {
          limit,
          cursor
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
}

