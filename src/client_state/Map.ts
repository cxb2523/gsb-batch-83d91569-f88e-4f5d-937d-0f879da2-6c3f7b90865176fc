import {OlostepTransport} from '../http/transport.js';
import {PagesIteratorOptions, WaitTillDoneOptions} from '../types.js';
import {normalizeToCamel} from '../casing.js';

interface MapHandleData extends Record<string, unknown> {
  id: string;
  urls?: string[];
}

interface MapUrlsResponse {
  urls?: string[];
  items?: string[];
  cursor?: string | number | null;
  next_cursor?: string | number | null;
}

export class Map {
  public readonly id: string;
  private readonly transport: OlostepTransport;
  private readonly urlsList: string[];
  [key: string]: unknown;

  constructor(transport: OlostepTransport, data: MapHandleData) {
    this.transport = transport;
    this.id = data.id;
    this.urlsList = data.urls ?? [];

    // Assign all other fields except 'urls' to avoid conflict with urls() method
    const {urls, ...rest} = data;
    Object.assign(this, rest);
  }

  async info(): Promise<unknown> {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/maps/${this.id}`
    });
    return data;
  }

  async waitTillDone(options?: WaitTillDoneOptions): Promise<void> {
    const opts = options ? normalizeToCamel(options) : undefined;
    const checkEveryNSecs = opts?.checkEveryNSecs ?? 10;
    const timeoutSeconds = opts?.timeoutSeconds ?? 600;
    const startTime = Date.now();

    while (true) {
      const info = (await this.info()) as {status?: string};
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

  async *urls(options?: PagesIteratorOptions): AsyncGenerator<string> {
    const opts = options ? normalizeToCamel(options) : undefined;

    // URLs inlined in the creation response are served straight away.
    if (this.urlsList.length) {
      for (const url of this.urlsList) {
        yield url;
      }
      return;
    }

    // Otherwise fall back to paginating GET /maps/{id}/urls. Wait for the map
    // to finish generating first so we don't race it (matches the crawl
    // behaviour); callers can opt out with { waitForCompletion: false }.
    const waitForCompletion = opts?.waitForCompletion ?? true;
    if (waitForCompletion) {
      await this.waitTillDone();
    }

    const limit = opts?.batchSize ?? 50;
    let cursor: string | undefined = opts?.cursor;

    while (true) {
      const {data} = await this.transport.request<MapUrlsResponse>({
        method: 'GET',
        path: `/maps/${this.id}/urls`,
        query: {
          limit,
          cursor
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
}
