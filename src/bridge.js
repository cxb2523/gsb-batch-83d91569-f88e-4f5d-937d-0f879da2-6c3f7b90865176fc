// A local stdio bridge for clients that cannot speak streamable HTTP. Every request is
// forwarded to the remote HasData endpoint, and the response -- plain JSON or a server-sent
// event stream -- is reduced to the one JSON-RPC message that carries our request id.

export const DEFAULT_ENDPOINT = "https://mcp.hasdata.com/mcp";

export class HasDataError extends Error {
  constructor(message, { status } = {}) {
    super(message);
    this.name = "HasDataError";
    if (status !== undefined) this.status = status;
  }
}

const preview = (text) => {
  const flat = String(text).replace(/\s+/g, " ").trim();
  return flat.length > 300 ? `${flat.slice(0, 300)}...` : flat;
};

// Streamable HTTP bodies come back as either one JSON document or a series of SSE events.
// Events are separated by blank lines; one event may spread its JSON over several data:
// lines, and notifications or keep-alives may sit in front of the answer we asked for.
function parseEventStream(body, id) {
  const messages = [];
  for (const event of body.split(/\r?\n\r?\n+/)) {
    const dataLines = event.split(/\r?\n/).filter((line) => line.startsWith("data:"));
    if (!dataLines.length) continue;
    const data = dataLines.map((line) => line.slice(5).replace(/^ /, "")).join("\n").trim();
    if (!data || data === "[DONE]") continue;
    try {
      const parsed = JSON.parse(data);
      // A JSON-RPC batch is an array; treat each element as a candidate message.
      if (Array.isArray(parsed)) messages.push(...parsed);
      else messages.push(parsed);
    } catch {
      // Keep-alive comments and truncated events are not JSON-RPC messages.
    }
  }

  if (!messages.length) {
    throw new HasDataError(
      `HasData returned an event stream with no parseable JSON-RPC message; body began: ${preview(body)}`
    );
  }

  const match = messages.find((message) => message && message.id === id);
  if (!match) {
    const seen = messages.map((message) => (message && "id" in message ? JSON.stringify(message.id) : "none")).join(", ");
    throw new HasDataError(
      `HasData returned no JSON-RPC message with id ${JSON.stringify(id)}; ids seen: ${seen}; body began: ${preview(body)}`
    );
  }
  return match;
}

// Parse a response body and return the JSON-RPC message whose id matches the request.
// Throws HasDataError when the body is unparseable or carries no message for that id.
export function parseRpcResponse(body, id) {
  const text = String(body).replace(/^\uFEFF/, "").trim();
  if (!text) throw new HasDataError("HasData returned an empty response body");

  if (text.startsWith("{") || text.startsWith("[")) {
    let parsed;
    try {
      parsed = JSON.parse(text);
    } catch (error) {
      throw new HasDataError(
        `HasData returned invalid JSON (${error.message}); body began: ${preview(text)}`
      );
    }
    const messages = Array.isArray(parsed) ? parsed : [parsed];
    const match = messages.find((message) => message && message.id === id);
    if (!match) {
      throw new HasDataError(
        `HasData returned no JSON-RPC message with id ${JSON.stringify(id)}; body began: ${preview(text)}`
      );
    }
    return match;
  }

  return parseEventStream(text, id);
}

// A matched message still has to be a usable answer: a JSON-RPC error or a missing result
// is a failure, not an empty success.
export function rpcResult(message) {
  if (message && message.error) {
    const error = message.error;
    const detail = error.message || JSON.stringify(error);
    const code = error.code !== undefined ? ` (code ${error.code})` : "";
    throw new HasDataError(`HasData returned a JSON-RPC error${code}: ${detail}`);
  }
  if (!message || !("result" in message)) {
    throw new HasDataError("HasData returned a JSON-RPC message without a result");
  }
  return message.result;
}

function httpError(response, body, hadApiKey) {
  const status = response.status;
  const statusText = response.statusText ? ` ${response.statusText}` : "";
  let message = `HasData responded with HTTP ${status}${statusText}`;
  const detail = preview(body);
  if (detail) message += `: ${detail}`;

  if (status === 401 || status === 403) {
    message += hadApiKey
      ? " (authentication failed: the server rejected HASDATA_API_KEY)"
      : " (authentication failed: HASDATA_API_KEY is not set, so the request was sent without credentials)";
  }
  return new HasDataError(message, { status });
}

// Forward one JSON-RPC request and return the matching JSON-RPC message. The endpoint,
// credentials and fetch implementation are injectable, and HASDATA_ENDPOINT can point the
// whole process at a test server, so tests can stay offline.
export async function forwardToHasData(
  request,
  {
    endpoint = process.env.HASDATA_ENDPOINT || DEFAULT_ENDPOINT,
    apiKey = process.env.HASDATA_API_KEY,
    fetchImpl = globalThis.fetch,
  } = {}
) {
  if (typeof fetchImpl !== "function") {
    throw new HasDataError("No fetch implementation is available to reach HasData");
  }

  const id = request.id ?? Math.floor(Math.random() * 1000);
  const payload = {
    jsonrpc: "2.0",
    id,
    method: request.method,
    params: request.params || {},
  };

  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
  };
  // Without a key the request is still forwarded; the server rejects it and the error
  // we surface says plainly that authentication is what failed.
  if (apiKey) headers["x-api-key"] = apiKey;

  let response;
  try {
    response = await fetchImpl(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });
  } catch (error) {
    throw new HasDataError(`Could not reach HasData at ${endpoint}: ${error.message}`);
  }

  const body = await response.text();
  if (!response.ok) throw httpError(response, body, Boolean(apiKey));

  return parseRpcResponse(body, id);
}

// tools/list degrades to an empty list with a reason on stderr; tools/call rethrows so the
// client sees a real failure instead of a silent undefined result.
export function createBridge(options = {}) {
  const { log = (...args) => console.error(...args), ...forwardOptions } = options;

  return {
    async listTools(request) {
      try {
        log("Fetching tools from HasData...");
        const message = await forwardToHasData(request, forwardOptions);
        return rpcResult(message);
      } catch (error) {
        log("Failed to fetch tools:", error.message);
        return { tools: [] };
      }
    },

    async callTool(request) {
      try {
        log(`Calling tool: ${request.params && request.params.name}`);
        const message = await forwardToHasData(request, forwardOptions);
        return rpcResult(message);
      } catch (error) {
        log("Tool execution failed:", error.message);
        throw error;
      }
    },
  };
}
