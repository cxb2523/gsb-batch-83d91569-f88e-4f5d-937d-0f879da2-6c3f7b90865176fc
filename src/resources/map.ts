import {OlostepTransport} from '../http/transport.js';
import {MapRequest} from '../types.js';
import {OlostepResource} from './base.js';
import {Map} from '../client_state/Map.js';
import {normalizeToCamel} from '../casing.js';

export interface MapResponse extends Record<string, unknown> {
  id: string;
  urlsCount: number;
  hasMore: boolean;
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

  // Streamer/iterator not yet implemented
  async *urls(mapId: string) {
    throw new Error('Streaming map URLs not implemented yet.');
  }

  // Shorthand callable
  public async call(...args: Parameters<MapNamespace['create']>) {
    return this.create(...args);
  }
}

