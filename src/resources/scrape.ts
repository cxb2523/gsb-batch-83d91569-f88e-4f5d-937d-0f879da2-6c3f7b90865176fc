import {OlostepTransport} from '../http/transport.js';
import {Action, Format, LinksOnPageOptions, ParserRef, ScrapeRequest, ScrapeStorageOptions, ScreenSize} from '../types.js';
import {OlostepResource} from './base.js';
import {ScrapeResult} from '../client_state/ScrapeResult.js';
import {normalizeToCamel} from '../casing.js';

export interface ScrapeResponse {
  id: string;
  available: string[];
  [key: string]: unknown;
}

const toArray = <T>(value?: T | T[]): T[] | undefined => {
  if (value === undefined) {
    return undefined;
  }
  return Array.isArray(value) ? value : [value];
};
const toParserPayload = (parser?: ParserRef | string, parserId?: string) => {
  const id = parserId ?? (typeof parser === 'string' ? parser : parser?.id);
  if (!id) {
    return undefined;
  }
  return {
    id,
    ...(typeof parser === 'object' && parser?.version ? {version: parser.version} : {})
  };
};
const toScreenSizePayload = (screen?: ScreenSize) => {
  if (!screen) {
    return undefined;
  }
  const {screenType, screenWidth, screenHeight} = screen;
  return {
    screen_type: screenType,
    screen_width: screenWidth,
    screen_height: screenHeight
  };
};
const toLinksOnPagePayload = (links?: LinksOnPageOptions) => {
  if (!links) {
    return undefined;
  }
  return {
    absolute_links: links.absoluteLinks,
    query_to_order_links_by: links.queryToOrderLinksBy,
    include_links: links.includeLinks,
    exclude_links: links.excludeLinks
  };
};
const toLLMExtractPayload = (llmExtract?: {schema?: Record<string, unknown> | string; prompt?: string}) => {
  if (!llmExtract) {
    return undefined;
  }
  return {
    schema: llmExtract.schema,
    prompt: llmExtract.prompt
  };
};
const normalizeScrapeInput = (input: string | ScrapeRequest): ScrapeRequest =>
  typeof input === 'string' ? {url: input} : input;
const toStoragePayload = (storage?: ScrapeStorageOptions) => {
  if (!storage) {
    return undefined;
  }
  return {expires_in: storage.expiresIn};
};

const buildScrapePayload = (input: ScrapeRequest) => ({
  url_to_scrape: input.url,
  formats: toArray(input.formats),
  country: input.country,
  wait_before_scraping: input.waitBeforeScraping,
  remove_css_selectors: input.removeCssSelectors,
  actions: toArray<Action>(input.actions),
  transformer: input.transformer,
  remove_images: input.removeImages,
  remove_class_names: input.removeClassNames,
  parser: toParserPayload(input.parser, input.parserId),
  llm_extract: toLLMExtractPayload(input.llmExtract),
  links_on_page: toLinksOnPagePayload(input.linksOnPage),
  screen_size: toScreenSizePayload(input.screenSize),
  storage: toStoragePayload(input.storage),
  metadata: input.metadata
});

export class ScrapeNamespace extends OlostepResource {
  constructor(transport: OlostepTransport) {
    super(transport);
  }

  async create(input: string | ScrapeRequest) {
    const payload = buildScrapePayload(normalizeToCamel(normalizeScrapeInput(input)));
    const {data} = await this.transport.request<ScrapeResponse>({
      method: 'POST',
      path: '/scrapes',
      body: payload
    });
    return new ScrapeResult(data as Record<string, unknown>);
  }

  async get(scrapeId: string) {
    const {data} = await this.transport.request({
      method: 'GET',
      path: `/scrapes/${scrapeId}`
    });
    return new ScrapeResult(data as Record<string, unknown>);
  }

  // Shorthand callable
  public async call(input: string | ScrapeRequest) {
    return this.create(input);
  }
}

