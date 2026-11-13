import Olostep, {OlostepClientOptions} from '../src/index.js';

const parseTimeoutMs = (value?: string) => {
  if (!value) {
    return undefined;
  }
  const timeoutSeconds = Number(value);
  return Number.isFinite(timeoutSeconds) && timeoutSeconds > 0 ? timeoutSeconds * 1000 : undefined;
};

export const createClient = (options?: OlostepClientOptions) => {
  const apiKey = process.env.OLOSTEP_API_KEY;

  if (!apiKey) {
    throw new Error('Set OLOSTEP_API_KEY before running the examples.');
  }

  const envOverrides: OlostepClientOptions = {
    apiBaseUrl: process.env.OLOSTEP_BASE_API_URL || undefined,
    timeoutMs: parseTimeoutMs(process.env.OLOSTEP_API_TIMEOUT)
  };

  return new Olostep({
    apiKey,
    ...envOverrides,
    ...options
  });
};

export const logJSON = (label: string, value: unknown) => {
  // eslint-disable-next-line no-console
  console.log(`\n=== ${label} ===\n${JSON.stringify(value, null, 2)}\n`);
};

