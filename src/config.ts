import {createRequire} from 'node:module';

import {FlexibleInput, normalizeToCamel} from './casing.js';

interface RetryOptionsBase {
  maxRetries: number;
  initialDelayMs: number;
}
export type RetryOptions = FlexibleInput<RetryOptionsBase>;

interface OlostepClientOptionsBase {
  apiKey?: string;
  apiBaseUrl?: string;
  timeoutMs?: number;
  retry?: RetryOptions;
  validateRequests?: boolean;
  userAgent?: string;
  logPath?: string | null;
  logger?: Pick<Console, 'debug' | 'info' | 'warn' | 'error'>;
}
export type OlostepClientOptions = FlexibleInput<OlostepClientOptionsBase>;

// Read from the SDK's own package.json. npm_package_version belongs to whichever app is running.
// A bundler can move the file away from package.json, so a failed read must not break the import.
const readSdkVersion = (): string => {
  try {
    return createRequire(import.meta.url)('../package.json').version;
  } catch {
    return 'unknown';
  }
};
export const SDK_VERSION = readSdkVersion();

const envBaseUrl = process.env.OLOSTEP_BASE_API_URL;
export const DEFAULT_BASE_URL = envBaseUrl && envBaseUrl.trim().length > 0 ? envBaseUrl.trim() : 'https://api.olostep.com/v1';

const envTimeout = Number(process.env.OLOSTEP_API_TIMEOUT);
export const DEFAULT_TIMEOUT_MS = Number.isFinite(envTimeout) && envTimeout > 0 ? envTimeout * 1000 : 150_000;

export const DEFAULT_USER_AGENT =
  process.env.OLOSTEP_USER_AGENT ?? `olostep-sdk/${SDK_VERSION}`;

export const DEFAULT_LOG_PATH = process.env.OLOSTEP_IO_LOG_PATH ?? null;

export const DEFAULT_CLIENT_OPTIONS: Required<
  Pick<
    OlostepClientOptionsBase,
    'apiBaseUrl' | 'timeoutMs' | 'retry' | 'validateRequests' | 'userAgent' | 'logPath'
  >
> = {
  apiBaseUrl: DEFAULT_BASE_URL,
  timeoutMs: DEFAULT_TIMEOUT_MS,
  retry: {
    maxRetries: 3,
    initialDelayMs: 1000
  },
  validateRequests: true,
  userAgent: DEFAULT_USER_AGENT,
  logPath: DEFAULT_LOG_PATH
};

export const resolveClientOptions = (
  options: OlostepClientOptions = {}
): Required<Omit<OlostepClientOptionsBase, 'logger'>> & { logger?: OlostepClientOptionsBase['logger'] } => {
  const opts = normalizeToCamel(options) as OlostepClientOptionsBase;
  const apiKey = opts.apiKey ?? process.env.OLOSTEP_API_KEY;

  if (!apiKey) {
    throw new Error(
      'No API key provided. Set the OLOSTEP_API_KEY environment variable or pass apiKey to OlostepClient.'
    );
  }

  return {
    apiKey,
    apiBaseUrl: opts.apiBaseUrl ?? DEFAULT_CLIENT_OPTIONS.apiBaseUrl,
    timeoutMs: opts.timeoutMs ?? DEFAULT_CLIENT_OPTIONS.timeoutMs,
    retry: opts.retry ?? DEFAULT_CLIENT_OPTIONS.retry,
    validateRequests: opts.validateRequests ?? DEFAULT_CLIENT_OPTIONS.validateRequests,
    userAgent: opts.userAgent ?? DEFAULT_CLIENT_OPTIONS.userAgent,
    logPath: opts.logPath ?? DEFAULT_CLIENT_OPTIONS.logPath,
    logger: opts.logger
  };
};

