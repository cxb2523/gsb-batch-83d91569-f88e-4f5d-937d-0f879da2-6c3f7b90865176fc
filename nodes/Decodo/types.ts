import { TARGET } from './constants';

export enum ItemStatus {
  SUCCESS = 'success',
  FAILED = 'failed',
  SKIPPED = 'skipped',
}

export enum ItemErrorSource {
  API = 'api',
  VALIDATION = 'validation',
}

/** Field that carries the list of item indexes that failed in a run. */
export const RETRY_LIST_FIELD = 'retryList';

export type ScraperApiParams = {
  operation?: TARGET;
  url?: string;
  query?: string;
  video_id?: string;
  headless?: boolean;
  parse?: boolean;
  geo?: string;
  locale?: string;
  subtitle_origin?: 'auto_generated' | 'uploader_provided';
  language_code?: string;
  results_limit?: string | number;
  markdown?: boolean;
};
