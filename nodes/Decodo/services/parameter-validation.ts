import { QUERY_TARGETS, TARGET, URL_TARGETS } from '../constants';
import { ScraperApiParams } from '../types';

/**
 * Raised when the node can reject an item locally, before any request is sent.
 */
export class ParameterValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ParameterValidationError';
  }
}

const isBlank = (value: unknown): boolean =>
  value === undefined || value === null || (typeof value === 'string' && value.trim() === '');

const isSupportedTarget = (target: unknown): target is TARGET =>
  typeof target === 'string' && (Object.values(TARGET) as string[]).includes(target);

/**
 * Validates the parameters of a single input item without performing any network
 * request. Throws a {@link ParameterValidationError} describing the first problem.
 */
export const validateScrapingParameters = (params: ScraperApiParams): void => {
  const target = params.operation;

  if (isBlank(target)) {
    throw new ParameterValidationError(
      'The Target parameter is required. Select a scraping target before running the node.',
    );
  }

  if (isSupportedTarget(target)) {
    if (URL_TARGETS.includes(target) && isBlank(params.url)) {
      throw new ParameterValidationError(`The "${target}" target requires a non-empty URL.`);
    }

    if (QUERY_TARGETS.includes(target) && isBlank(params.query)) {
      throw new ParameterValidationError(`The "${target}" target requires a non-empty query.`);
    }

    if (target === TARGET.YOUTUBE_SUBTITLES && isBlank(params.video_id)) {
      throw new ParameterValidationError(`The "${target}" target requires a non-empty Video ID.`);
    }
  }

  if (!isBlank(params.results_limit)) {
    const rawLimit = params.results_limit;
    const limit = typeof rawLimit === 'number' ? rawLimit : Number(String(rawLimit).trim());

    if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
      throw new ParameterValidationError(
        `Results Amount must be an integer between 1 and 100; received "${String(rawLimit)}".`,
      );
    }
  }
};
