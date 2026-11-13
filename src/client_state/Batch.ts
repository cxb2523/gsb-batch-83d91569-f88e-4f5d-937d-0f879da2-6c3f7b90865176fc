import {OlostepTransport} from '../http/transport.js';
import {ItemsIteratorOptions, WaitTillDoneOptions} from '../types.js';
import {normalizeToCamel} from '../casing.js';
import {BatchItem} from './BatchItem.js';

interface BatchHandleData extends Record<string, unknown> {
  id: string;
  total_urls?: number;
}

interface BatchItemsPage {
  items?: Array<{
    id: string;
    url: string;
    custom_id?: string;
    retrieve_id?: string;
    status: string;
    [key: string]: unknown;
  }>;
  cursor?: string | number | null;
  next_cursor?: string | number | null;
  has_more?: boolean;
}

export class Batch {
  public readonly id: string;
  public readonly total_urls: number;
  private readonly transport: OlostepTransport;
  [key: string]: unknown;

  constructor(transport: OlostepTransport, data: BatchHandleData) {
    this.transport = transport;
    this.id = data.id;
    this.total_urls = (data.total_urls as number | undefined) ?? 0;
    Object.assign(this, data);
  }

  async info(): Promise<unknown> {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/batches/${this.id}`
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
        completed_urls?: number;
        total_urls?: number;
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

  async *items(options?: ItemsIteratorOptions): AsyncGenerator<BatchItem> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const limit = opts?.batchSize ?? 50;
    let cursor: string | undefined = opts?.cursor;
    const waitForCompletion = opts?.waitForCompletion ?? true;

    // Wait for the batch to finish before paginating so we don't race the
    // server (matches the Python SDK behaviour). Callers can opt out with
    // { waitForCompletion: false }.
    if (waitForCompletion) {
      await this.waitTillDone();
    }

    while (true) {
      const {data} = await this.transport.request<BatchItemsPage>({
        method: 'GET',
        path: `/batches/${this.id}/items`,
        query: {
          limit,
          cursor,
          status: opts?.status
        }
      });

      const items = data?.items ?? [];
      if (!items.length) {
        break;
      }

      for (const item of items) {
        yield new BatchItem(this.transport, item);
      }

      const nextCursor = data?.next_cursor ?? data?.cursor;
      if (nextCursor === undefined || nextCursor === null) {
        break;
      }
      cursor = String(nextCursor);
    }
  }
}
