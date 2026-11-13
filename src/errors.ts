/* eslint-disable max-classes-per-file */

export interface RequestMetadata {
  method: string;
  url: string;
  body?: unknown;
  query?: Record<string, unknown>;
}

export interface ResponseMetadata {
  status?: number;
  body?: unknown;
  headers?: Record<string, string | string[] | undefined>;
}

export interface ErrorDetails {
  request?: RequestMetadata;
  response?: ResponseMetadata;
  cause?: unknown;
  [key: string]: unknown;
}

const serialize = (value: unknown) => {
  try {
    if (typeof value === 'string') {
      return value;
    }
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

// Shows only the last 4 characters, so error messages and logs never carry a usable part of the key.
const maskApiKey = (apiKey?: string | null) => {
  if (!apiKey) {
    return '';
  }
  if (apiKey.length < 12) {
    return '[*****]';
  }
  return `[*****${apiKey.slice(-4)}]`;
};

export class OlostepBaseError extends Error {
  public readonly details?: ErrorDetails;

  constructor(message: string, details?: ErrorDetails) {
    super(message);
    this.name = new.target.name;
    this.details = details;
  }
}

export class OlostepAPIConnectionError extends OlostepBaseError {
  constructor(message = 'Olostep API connection error', details?: ErrorDetails) {
    super(message, details);
  }
}

export class OlostepServerError extends OlostepBaseError {}

export class OlostepServerTemporaryIssue extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('The Olostep API reported a temporary issue; retry later.', details);
  }
}

export class OlostepServerRequestUnprocessable extends OlostepServerError {
  constructor(details: ErrorDetails & {request: RequestMetadata; response: ResponseMetadata}) {
    const request = details.request;
    const response = details.response;
    const message = [
      `The Olostep API could not process ${request.method?.toUpperCase()} ${request.url}`,
      `Status: ${response.status ?? 'unknown'}`,
      `Request body:\n${serialize(request.body)}`,
      `Response body:\n${serialize(response.body)}`
    ].join('\n');
    super(message, details);
  }
}

export class OlostepServerParserNotFound extends OlostepServerRequestUnprocessable {}

export class OlostepServerBlacklistedDomain extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('The requested domain is blacklisted by Olostep.', details);
  }
}

export class OlostepServerFeatureApprovalRequired extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('This API feature requires explicit approval.', details);
  }
}

export class OlostepServerAuthFailed extends OlostepServerError {
  constructor(apiKey?: string | null, details?: ErrorDetails) {
    const masked = maskApiKey(apiKey);
    super(`The Olostep API rejected API key ${masked} as invalid.`, {
      ...details,
      maskedApiKey: masked
    });
  }
}

export class OlostepServerCreditsExhausted extends OlostepServerError {
  constructor(message?: string, details?: ErrorDetails) {
    super(message ?? 'Olostep credits exhausted. Upgrade your plan or wait for reset.', details);
  }
}

export class OlostepServerOutOfResources extends OlostepServerRequestUnprocessable {}

export class OlostepServerInvalidEndpointCalled extends OlostepServerError {
  constructor(request: RequestMetadata, response?: ResponseMetadata) {
    const message = [
      `Invalid Olostep endpoint requested: ${request.method?.toUpperCase()} ${request.url}`,
      response ? `Response body:\n${serialize(response.body)}` : undefined
    ]
      .filter(Boolean)
      .join('\n');
    super(message, {request, response});
  }
}

export class OlostepServerResourceNotFound extends OlostepServerError {
  constructor(response?: ResponseMetadata) {
    super('Requested Olostep resource was not found.', {response});
  }
}

export class OlostepServerNetworkBusy extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('Olostep network is busy; try again later.', details);
  }
}

export class OlostepServerNoResultInResponse extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('The Olostep API timed out before producing a result.', details);
  }
}

export class OlostepServerInternalNetworkIssue extends OlostepServerError {
  constructor(details?: ErrorDetails) {
    super('Transient network issue while communicating with Olostep.', details);
  }
}

export class OlostepServerUnknownIssue extends OlostepServerError {
  constructor(statusCode: number, response?: ResponseMetadata) {
    const message = [`Olostep API returned an unknown error (HTTP ${statusCode}).`];
    if (response?.body) {
      message.push(`Response:\n${serialize(response.body)}`);
    }
    super(message.join('\n'), {response: {...response, status: statusCode}});
  }
}

export class OlostepClientError extends OlostepBaseError {}

export class OlostepClientRequestValidationFailed extends OlostepClientError {
  constructor(errors: Array<Record<string, unknown>>) {
    const details = {validationErrors: errors};
    const message =
      errors
        .map((err) => {
          const loc = serialize(err.loc ?? err.path ?? 'unknown');
          const msg = err.msg ?? err.message ?? 'Invalid value';
          return `• ${loc}: ${msg}`;
        })
        .join('\n') || 'The request payload is invalid.';
    super(`Request validation failed:\n${message}`, details);
  }
}

export class OlostepClientResponseValidationFailed extends OlostepClientError {
  constructor(request: RequestMetadata, response: ResponseMetadata, errors: Array<Record<string, unknown>>) {
    const message = [
      `Response validation failed for ${request.method?.toUpperCase()} ${request.url}.`,
      `Status: ${response.status ?? 'unknown'}`,
      `Response body:\n${serialize(response.body)}`,
      `Validation errors:\n${serialize(errors)}`
    ].join('\n');
    super(message, {request, response, validationErrors: errors});
  }
}

export class OlostepClientNoAPIKey extends OlostepClientError {
  constructor() {
    super('Olostep API key is required but missing.');
  }
}

export class OlostepClientAsyncContext extends OlostepClientError {}

export class OlostepClientBetaFeatureAccessRequired extends OlostepClientError {
  constructor(details?: ErrorDetails) {
    super('Access to this beta feature has not been granted.', details);
  }
}

export class OlostepClientTimeout extends OlostepClientError {
  constructor(details?: ErrorDetails) {
    super('Client-side timeout while waiting for Olostep.', details);
  }
}