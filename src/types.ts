import {FlexibleInput} from './casing.js';

export type Primitive = string | number | boolean | null | undefined;

export enum Format {
  HTML = 'html',
  MARKDOWN = 'markdown',
  JSON = 'json',
  TEXT = 'text'
}

export enum Country {
  US = 'us',
  DE = 'de',
  FR = 'fr',
  GB = 'gb',
  SG = 'sg'
}

export interface ParserRef {
  id: string;
  version?: string;
}

interface ScreenSizeBase {
  screenType?: string;
  screenWidth?: number;
  screenHeight?: number;
}
export type ScreenSize = FlexibleInput<ScreenSizeBase>;

interface LLMExtractOptionsBase {
  schema?: Record<string, unknown> | string;
  prompt?: string;
}
export type LLMExtractOptions = FlexibleInput<LLMExtractOptionsBase>;

interface LinksOnPageOptionsBase {
  absoluteLinks?: boolean;
  queryToOrderLinksBy?: string;
  includeLinks?: string[];
  excludeLinks?: string[];
}
export type LinksOnPageOptions = FlexibleInput<LinksOnPageOptionsBase>;

export interface WaitAction {
  type: 'wait';
  milliseconds: number;
}

export interface FillInputAction {
  type: 'fill_input';
  selector: string;
  value: Primitive;
}

export interface ClickAction {
  type: 'click';
  selector?: string;
  text?: string;
  button?: 'left' | 'right' | 'middle';
}

export interface ScrollAction {
  type: 'scroll';
  distance?: number;
  selector?: string;
}

export type Action = WaitAction | FillInputAction | ClickAction | ScrollAction;

export type ScrapeStorageExpiresIn =
  | '7d'
  | '10d'
  | '30d'
  | '60d'
  | '90d'
  | '180d'
  | '365d'
  | 'never';

/**
 * Storage retention config for a scrape.
 * Controls how long Olostep keeps the scraped content on S3.
 * Defaults to `"7d"` when omitted.
 */
export interface ScrapeStorageOptions {
  /**
   * Retention duration. One of: `"7d"`, `"10d"`, `"30d"`, `"60d"`,
   * `"90d"`, `"180d"`, `"365d"`, `"never"`.
   */
  expiresIn: ScrapeStorageExpiresIn;
}

interface ScrapeRequestBase {
  url: string;
  formats?: Format | Format[] | string | string[];
  country?: Country | string;
  waitBeforeScraping?: number;
  removeCssSelectors?: string | string[];
  actions?: Action | Action[];
  transformer?: string;
  removeImages?: boolean;
  removeClassNames?: string[];
  parser?: ParserRef | string;
  parserId?: string;
  llmExtract?: LLMExtractOptions;
  linksOnPage?: LinksOnPageOptions;
  screenSize?: ScreenSize;
  /** Storage retention config. Omit to use the default (7 days). */
  storage?: ScrapeStorageOptions;
  metadata?: Record<string, Primitive>;
}
export type ScrapeRequest = FlexibleInput<ScrapeRequestBase>;

interface BatchItemBase {
  url: string;
  customId: string;
}
export type BatchItem = FlexibleInput<BatchItemBase>;

interface BatchRequestOptionsBase {
  country?: Country | string;
  parser?: ParserRef | string;
  parserId?: string;
  linksOnPage?: LinksOnPageOptions;
}
export type BatchRequestOptions = FlexibleInput<BatchRequestOptionsBase>;

interface CrawlRequestBase {
  url?: string;
  startUrl?: string;
  maxPages?: number;
  maxDepth?: number;
  includeUrls?: string | string[];
  excludeUrls?: string | string[];
  includeExternal?: boolean;
  includeSubdomain?: boolean;
  searchQuery?: string;
  topN?: number;
  webhookUrl?: string;
}
export type CrawlRequest = FlexibleInput<CrawlRequestBase>;

interface MapRequestBase {
  url: string;
  searchQuery?: string;
  topN?: number;
  includeSubdomain?: boolean;
  includeUrls?: string | string[];
  excludeUrls?: string | string[];
}
export type MapRequest = FlexibleInput<MapRequestBase>;

interface AnswerRequestBase {
  task: string;
  jsonFormat?: Record<string, unknown>;
}
export type AnswerRequest = FlexibleInput<AnswerRequestBase>;

interface SearchScrapeOptionsBase {
  formats?: Format | Format[] | string | string[];
  removeCssSelectors?: string;
  timeout?: number;
}
export type SearchScrapeOptions = FlexibleInput<SearchScrapeOptionsBase>;

interface SearchRequestBase {
  query: string;
  limit?: number;
  includeDomains?: string[];
  excludeDomains?: string[];
  scrapeOptions?: SearchScrapeOptions;
}
export type SearchRequest = FlexibleInput<SearchRequestBase>;

interface RetrieveRequestBase {
  retrieveId: string;
  formats?: Format | Format[];
}
export type RetrieveRequest = FlexibleInput<RetrieveRequestBase>;

export type RequestPayload =
  | ScrapeRequest
  | BatchItem[]
  | CrawlRequest
  | MapRequest
  | AnswerRequest
  | SearchRequest
  | RetrieveRequest;

interface ItemsIteratorOptionsBase {
  batchSize?: number;
  status?: string;
  cursor?: string;
  waitForCompletion?: boolean;
}
export type ItemsIteratorOptions = FlexibleInput<ItemsIteratorOptionsBase>;

interface PagesIteratorOptionsBase {
  batchSize?: number;
  cursor?: string;
  waitForCompletion?: boolean;
}
export type PagesIteratorOptions = FlexibleInput<PagesIteratorOptionsBase>;

interface WaitTillDoneOptionsBase {
  checkEveryNSecs?: number;
  timeoutSeconds?: number;
}
export type WaitTillDoneOptions = FlexibleInput<WaitTillDoneOptionsBase>;

export interface PaginatedIteratorConfig<T> {
  batchSize?: number;
  waitForCompletion?: boolean;
  fetchPage: (cursor?: string) => Promise<{ items: T[]; nextCursor?: string }>;
}

