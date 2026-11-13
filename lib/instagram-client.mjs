// Zero-dependency JSON-RPC client for HasData's hosted Instagram MCP server,
// scoped to the profile lookup tool.
//
// Two transport quirks shape this file:
//   1. A streamable-HTTP body arrives as plain JSON OR as server-sent events,
//      so both shapes are parsed before anything is classified.
//   2. The MCP layer answers most failures with HTTP 200 and an isError result
//      instead of an HTTP status, so a failure has to be classified from the
//      body. The batch runner in ./batch-profiles.mjs branches on the error
//      types exported below.
//
// Global fetch (Node >= 18) is the only platform API used.

export const PROFILE_TOOL = 'hasdata_instagram_profile_getInstagramProfile';
export const DEFAULT_ENDPOINT = 'https://mcp.hasdata.com/mcp?apis=instagram';
export const DEFAULT_TIMEOUT_MS = 60_000;

export class InstagramApiError extends Error {
    constructor(message, options = {}) {
        super(message);
        this.name = 'InstagramApiError';
        this.httpStatus = options.httpStatus;
        this.code = options.code;
        // Only the concurrency-limit branch is retried; everything else fails
        // the handle immediately.
        this.retriable = options.retriable ?? false;
    }
}

// A handle that does not resolve. The upstream signals this with
// "HasData API error: 400 Bad Request" or requestMetadata.status === 'error'.
export class ProfileNotFoundError extends InstagramApiError {
    constructor(message, options = {}) {
        super(message, options);
        this.name = 'ProfileNotFoundError';
    }
}

// The plan's concurrency ceiling was hit: HTTP 429 or a body carrying
// concurrency_limit. Safe to retry after backing off.
export class ConcurrencyLimitError extends InstagramApiError {
    constructor(message, options = {}) {
        super(message, { ...options, retriable: true });
        this.name = 'ConcurrencyLimitError';
    }
}

// Collect every JSON-RPC message carried by a streamable-HTTP response. A plain
// JSON body is one message; an SSE stream can carry several, with progress
// notifications mixed in, so callers pick the message whose id matches.
export function parseRpcMessages(raw) {
    const trimmed = raw.trim();
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
        return [JSON.parse(trimmed)];
    }

    const messages = [];
    for (const event of trimmed.split(/\r?\n\r?\n+/)) {
        const data = event
            .split(/\r?\n/)
            .filter((line) => line.startsWith('data:'))
            .map((line) => line.slice(5).replace(/^ /, ''))
            .join('\n');
        if (!data || data === '[DONE]') continue;
        try {
            messages.push(JSON.parse(data));
        } catch {
            // Keep-alive comments and partial events are not RPC messages.
        }
    }
    return messages;
}

function looksLikeConcurrencyLimit(httpStatus, raw, rpcMessage) {
    if (httpStatus === 429) return true;
    const fragments = [
        raw,
        rpcMessage?.error?.message,
        rpcMessage?.error?.code && String(rpcMessage.error.code),
    ].filter(Boolean);
    return fragments.some((fragment) => /concurrency_limit/i.test(fragment) || /\b429\b/.test(fragment));
}

function looksLikeNotFound(httpStatus, raw, envelope) {
    if (httpStatus === 400) return true;
    if (envelope?.requestMetadata?.status === 'error') return true;
    return /400\s*Bad\s*Request/i.test(raw ?? '');
}

// A tools/call success wraps the payload in one text block holding
// { url, status, text, json }, with the scraped profile under .json.
function unwrapToolResult(rpcMessage) {
    const result = rpcMessage?.result;
    const text = result?.content?.[0]?.text;
    if (typeof text !== 'string' || !text) {
        throw new InstagramApiError('the tool response carried no text content block', {
            code: rpcMessage?.error?.code,
        });
    }

    let envelope;
    try {
        envelope = JSON.parse(text);
    } catch {
        envelope = null;
    }

    if (result.isError) {
        // Error envelopes sometimes come back as structured JSON (with
        // requestMetadata) and sometimes as a plain reason string.
        const reason = envelope?.text || envelope?.message || text;
        if (looksLikeNotFound(undefined, text, envelope)) {
            throw new ProfileNotFoundError(reason);
        }
        throw new InstagramApiError(reason);
    }

    if (!envelope?.json) {
        throw new InstagramApiError('the tool response carried no json payload');
    }
    return envelope;
}

export function createProfileClient(options = {}) {
    const apiKey = options.apiKey ?? process.env.HASDATA_API_KEY;
    if (!apiKey) {
        throw new Error(
            'HASDATA_API_KEY is not set. Create a free key at https://app.hasdata.com and set HASDATA_API_KEY.'
        );
    }
    const endpoint = options.endpoint ?? DEFAULT_ENDPOINT;
    const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    // Injected by tests; production uses the global fetch.
    const fetchImpl = options.fetch ?? fetch;
    let nextId = 1;

    return {
        endpoint,

        // One profile lookup, one upstream attempt. Retry policy lives in the
        // batch runner so a single-handle caller is never made to wait on it.
        async getProfile(handle) {
            const id = nextId++;
            let res;
            try {
                res = await fetchImpl(endpoint, {
                    method: 'POST',
                    headers: {
                        'x-api-key': apiKey,
                        'Content-Type': 'application/json',
                        Accept: 'application/json, text/event-stream',
                    },
                    body: JSON.stringify({
                        jsonrpc: '2.0',
                        id,
                        method: 'tools/call',
                        params: { name: PROFILE_TOOL, arguments: { handle } },
                    }),
                    signal: AbortSignal.timeout(timeoutMs),
                });
            } catch (err) {
                // Network failure, DNS loss, timeout: the request never produced
                // a classifiable response, so it is a generic call failure.
                throw new InstagramApiError(`request for ${handle} failed before a response: ${err.message}`, {
                    code: err.name,
                });
            }

            const raw = await res.text();

            // HTTP-level rejections: the gateway can answer 429 itself before
            // the MCP layer ever builds a result.
            if (res.status === 429) {
                throw new ConcurrencyLimitError(`429 concurrency_limit for ${handle}`, { httpStatus: 429 });
            }
            if (res.status === 400) {
                throw new ProfileNotFoundError(`400 Bad Request for ${handle}`, { httpStatus: 400 });
            }
            if (!res.ok) {
                throw new InstagramApiError(`HasData answered HTTP ${res.status} for ${handle}: ${raw.slice(0, 200)}`, {
                    httpStatus: res.status,
                });
            }

            let messages;
            try {
                messages = parseRpcMessages(raw);
            } catch (err) {
                throw new InstagramApiError(`unparseable response for ${handle}: ${err.message}`);
            }
            const rpcMessage = messages.find((message) => message.id === id) ?? messages[0];
            if (!rpcMessage) {
                throw new InstagramApiError(`no JSON-RPC message in the response for ${handle}`);
            }

            // Protocol-level error object (e.g. MCP -32602 input validation).
            if (rpcMessage.error) {
                const message = rpcMessage.error.message || `JSON-RPC error ${rpcMessage.error.code}`;
                if (looksLikeConcurrencyLimit(res.status, raw, rpcMessage)) {
                    throw new ConcurrencyLimitError(message, { code: rpcMessage.error.code });
                }
                if (looksLikeNotFound(res.status, raw, null)) {
                    throw new ProfileNotFoundError(message, { code: rpcMessage.error.code });
                }
                throw new InstagramApiError(message, { code: rpcMessage.error.code });
            }

            if (looksLikeConcurrencyLimit(res.status, raw, rpcMessage)) {
                throw new ConcurrencyLimitError(`concurrency_limit reported for ${handle}`, { httpStatus: res.status });
            }

            const envelope = unwrapToolResult(rpcMessage);
            if (looksLikeNotFound(res.status, raw, envelope)) {
                throw new ProfileNotFoundError(envelope.text || `requestMetadata.status=error for ${handle}`, {
                    httpStatus: res.status,
                });
            }
            return envelope.json;
        },
    };
}
