import type {
  RequestTrace,
  RequestTraceEntry,
  RedirectTraceEntry,
  RetryTraceEntry,
} from '../../types';
import type { Response } from '../response';
import { normalizeMethod } from '../../native/index';

/** Error codes produced by the redirect policy itself rather than a transport attempt. */
const REDIRECT_POLICY_ERROR_CODES = new Set([
  'ERR_REDIRECT',
  'ERR_TOO_MANY_REDIRECTS',
  'ERR_REDIRECT_LOOP',
]);

/** Accumulates trace entries in the order in which the pipeline observes them. */
export class RequestTraceCollector {
  readonly #entries: RequestTraceEntry[] = [];

  /** Records a followed redirect hop. */
  recordRedirect(params: {
    url: string;
    method: string;
    status: number;
    location: string;
    toUrl: string;
  }): void {
    const entry: RedirectTraceEntry = {
      sequence: this.#entries.length + 1,
      stage: 'redirect',
      url: params.url,
      method: normalizeMethod(params.method),
      status: params.status,
      location: params.location,
      toUrl: params.toUrl,
      reason: `Redirected with status ${params.status} to ${params.toUrl}`,
    };

    this.#entries.push(entry);
  }

  /** Records an attempt whose outcome leads to another attempt or terminates the request. */
  recordRetry(params: {
    attempt: number;
    url: string;
    method: string;
    reason: string;
    response?: Response;
    error?: { name?: string; code?: string };
  }): void {
    const entry: RetryTraceEntry = {
      sequence: this.#entries.length + 1,
      stage: 'retry',
      attempt: params.attempt,
      url: params.url,
      method: normalizeMethod(params.method),
      reason: params.reason,
    };

    if (params.response) {
      entry.status = params.response.status;
    }

    if (params.error) {
      if (params.error.name) {
        entry.errorName = params.error.name;
      }

      if (params.error.code) {
        entry.errorCode = params.error.code;
      }
    }

    this.#entries.push(entry);
  }

  /** Returns a detached snapshot of the entries collected so far. */
  snapshot(): RequestTrace {
    return this.#entries.map((entry) => ({ ...entry })) as RequestTrace;
  }
}

/** Builds the reason string for an entry that gives way to another retry attempt. */
export function retryTriggerReason(params: {
  attempt: number;
  response?: Response;
  error?: { name?: string; code?: string };
}): string {
  if (params.response) {
    return `Retry triggered by response status ${params.response.status} on attempt ${params.attempt}`;
  }

  const errorName = params.error?.name ?? 'Error';
  const errorCode = params.error?.code ? ` (${params.error.code})` : '';

  return `Retry triggered by ${errorName}${errorCode} on attempt ${params.attempt}`;
}

/** Builds the reason string for the entry describing the final failed attempt. */
export function retryExhaustedReason(params: {
  attempt: number;
  response?: Response;
  error?: { name?: string; code?: string };
}): string {
  if (params.response) {
    return `Retry attempts exhausted: final response status ${params.response.status} on attempt ${params.attempt}`;
  }

  const errorName = params.error?.name ?? 'Error';
  const errorCode = params.error?.code ? ` (${params.error.code})` : '';

  return `Retry attempts exhausted: final ${errorName}${errorCode} on attempt ${params.attempt}`;
}

/**
 * Redirect-policy failures (`manual` interception is a return, not an error; this covers
 * `redirect: 'error'`, `maxRedirects` and redirect loops) are themselves the boundary and
 * must not gain a fabricated retry entry — the trace only contains what already happened.
 */
export function isRedirectPolicyError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'code' in error &&
    typeof (error as { code?: unknown }).code === 'string' &&
    REDIRECT_POLICY_ERROR_CODES.has((error as { code: string }).code)
  );
}

/** Attaches a trace snapshot to an error so callers can read it alongside the failure. */
export function attachTraceToError(error: unknown, trace: RequestTrace): void {
  if (typeof error === 'object' && error !== null) {
    (error as { wreq?: { trace?: RequestTrace } }).wreq = { trace };
  }
}

/** Reads a trace previously attached to an error object. */
export function readTraceFromError(error: unknown): RequestTrace | undefined {
  if (typeof error !== 'object' || error === null || !('wreq' in error)) {
    return undefined;
  }

  const wreq = (error as { wreq?: { trace?: RequestTrace } }).wreq;

  return wreq?.trace;
}
