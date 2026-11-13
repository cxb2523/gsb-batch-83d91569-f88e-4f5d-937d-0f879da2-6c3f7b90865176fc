/** Types for the repeatable flight-collection pipeline (fixtures/sites flights site). */

/** How records are obtained: the JSON API directly, or a browser page that triggers the same requests. */
export type CollectPath = 'api' | 'browser';

/**
 * A city the collector searches for. `code` is the IATA code the fixture API expects; `name` is what a person
 * types into the page autocomplete (required for the browser path, because suggestions match names, not codes).
 */
export interface CityRef {
  code: string;
  name?: string;
}

export interface CollectOptions {
  /** Origin of the fixture site, e.g. `http://localhost:1234/`. */
  baseUrl: string;
  from: CityRef;
  to: CityRef;
  /** Inclusive ISO dates (`YYYY-MM-DD`). The range is expanded one day at a time. */
  dateFrom: string;
  dateTo: string;
  /** Default `api`. The browser path needs a PageSession-backed fetcher (see BrowserFlightFetcher). */
  path?: CollectPath;
  /** Hard cap on pages requested per day; reaching it with the day's `total` uncovered truncates the day. */
  maxPagesPerDay?: number;
  /** Per-page deadline for both the HTTP request and the browser response. */
  pageTimeoutMs?: number;
  /** API sort mode (`best` by default; the browser path always uses the page's default sort). */
  sort?: string;
}

/** One flight, normalized the same way for both collection paths. */
export interface FlightRecord {
  date: string;
  price: number;
  airline: string;
  depart: string;
  arrive: string;
  stops: number;
  /** 1-based results page this record came from ("来源页"). */
  sourcePage: number;
}

/** A flight as the fixture API returns it (other fields are ignored). */
export interface FlightItem {
  price: number;
  airline: string;
  depart: string;
  arrive: string;
  stops: number;
}

/** How a single requested page ended. */
export type PageOutcome = 'success' | 'empty' | 'failed' | 'timeout' | 'page_limit';

export interface PageFetch {
  outcome: 'success' | 'empty' | 'failed' | 'timeout';
  httpStatus?: number;
  items?: FlightItem[];
  total?: number;
  error?: string;
}

/** Everything that happened to one page. `page_limit` marks the page that was NOT requested because of the cap. */
export interface PageResult {
  date: string;
  page: number;
  outcome: PageOutcome;
  /** False only for the synthetic `page_limit` marker. */
  requested: boolean;
  httpStatus: number | null;
  total: number | null;
  records: number;
  error: string | null;
}

export type DayStatus = 'complete' | 'truncated' | 'failed' | 'timeout' | 'incomplete';

/** Per-day accounting: how many pages were requested and how many records they yielded. */
export interface DaySummary {
  date: string;
  status: DayStatus;
  /** Pages actually requested for this day (failed pages included). */
  pages: number;
  records: number;
  /** The day's total from the fixture, when known. A failed later page leaves the earlier total in place. */
  total: number | null;
  error: string | null;
}

export interface CollectResult {
  from: string;
  to: string;
  dateFrom: string;
  dateTo: string;
  path: CollectPath;
  maxPagesPerDay: number;
  /** Day summaries in date order. */
  days: DaySummary[];
  /** Every page that was requested, in collection order, plus `page_limit` markers. */
  pages: PageResult[];
  /** Successful records sorted by date and then price (ascending, stable). */
  records: FlightRecord[];
  summary: {
    days: number;
    pagesRequested: number;
    records: number;
    outcomes: Record<PageOutcome, number>;
  };
  /** Set only when the collector itself hit an unexpected error; page failures live in `pages`/`days`. */
  error?: string;
}

/** A per-page data source. Implementations resolve every failure as a PageFetch instead of throwing. */
export interface FlightFetcher {
  readonly path: CollectPath;
  fetchPage(date: string, page: number, timeoutMs: number): Promise<PageFetch>;
  dispose?(): Promise<void>;
}
