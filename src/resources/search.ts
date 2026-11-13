import {OlostepTransport} from '../http/transport.js';
import {SearchRequest, SearchScrapeOptions} from '../types.js';
import {OlostepResource} from './base.js';
import {SearchResult} from '../client_state/SearchResult.js';
import {normalizeToCamel} from '../casing.js';

const toArray = <T>(value?: T | T[]): T[] | undefined => {
  if (value === undefined) {
    return undefined;
  }
  return Array.isArray(value) ? value : [value];
};

const stripUndefined = <T extends Record<string, unknown>>(obj: T): Partial<T> => {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) {
      (out as Record<string, unknown>)[k] = v;
    }
  }
  return out;
};

const toScrapeOptionsPayload = (options?: SearchScrapeOptions) => {
  if (!options) {
    return undefined;
  }
  const payload = stripUndefined({
    formats: toArray(options.formats),
    remove_css_selectors: options.removeCssSelectors,
    timeout: options.timeout
  });
  return Object.keys(payload).length > 0 ? payload : undefined;
};

const normalizeSearchInput = (input: string | SearchRequest): SearchRequest =>
  typeof input === 'string' ? {query: input} : input;

const buildSearchPayload = (input: SearchRequest) =>
  stripUndefined({
    query: input.query,
    limit: input.limit,
    include_domains: input.includeDomains,
    exclude_domains: input.excludeDomains,
    scrape_options: toScrapeOptionsPayload(input.scrapeOptions)
  });

export class SearchNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  async create(input: string | SearchRequest) {
    const normalized = normalizeToCamel(normalizeSearchInput(input));
    const payload = buildSearchPayload(normalized);
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'POST',
      path: '/searches',
      body: payload
    });
    return new SearchResult(data);
  }

  async get(searchId: string) {
    const {data} = await this.transport.request<Record<string, unknown>>({
      method: 'GET',
      path: `/searches/${searchId}`
    });
    return new SearchResult(data);
  }

  // Shorthand callable
  public async call(input: string | SearchRequest) {
    return this.create(input);
  }
}
