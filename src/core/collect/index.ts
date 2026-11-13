export { collectFlights, DEFAULT_MAX_PAGES_PER_DAY, DEFAULT_PAGE_TIMEOUT_MS, type CollectDeps } from './collect.ts';
export { ApiFlightFetcher, type ApiFetcherOptions } from './fetcher-api.ts';
export { BrowserFlightFetcher, type BrowserFetcherOptions } from './fetcher-browser.ts';
export { selectFetcher, type SelectFetcherOptions } from './fetcher-select.ts';
export { renderCollectReport, describePage } from './report.ts';
export { expandDateRange, isValidIsoDate, addDays, monthStart, shiftMonth } from './range.ts';
export {
  parseFlightsPayload, normalizeItem, sortRecords, toRecord, pageFetchFromBody, PayloadError,
} from './parse.ts';
export type {
  CityRef, CollectOptions, CollectPath, CollectResult, DayStatus, DaySummary, FlightFetcher, FlightItem,
  FlightRecord, PageFetch, PageOutcome, PageResult,
} from './types.ts';
