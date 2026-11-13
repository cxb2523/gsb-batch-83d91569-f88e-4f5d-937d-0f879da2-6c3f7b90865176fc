// Classification of remote Parquet load failures. Kept free of WASM/React
// imports so the rules can be exercised directly under `bun test`.
//
// Two recoverability classes are surfaced to the user:
//   - "permanent": the link itself is unusable (expired presigned URL, missing
//     permission, object gone). Retrying the same URL cannot help — the user
//     must obtain a fresh link.
//   - "temporary": the request never got a definitive answer (server 5xx,
//     dropped connection, timeout, DNS hiccup). The same URL may work on retry.

export type RemoteErrorKind = "permanent" | "temporary"

export interface RemoteErrorInfo {
  kind: RemoteErrorKind
  /** HTTP status code when the server answered; null for opaque network errors. */
  status: number | null
  /** User-facing explanation of why the load failed. */
  message: string
  /** Short hint about what the user can do next. */
  hint: string
  /** Whether the failure looks like a browser CORS block. */
  isCors: boolean
}

// Statuses that mean the URL/credentials are no good. 401 (unauthenticated),
// 403 (forbidden — the typical "presigned URL expired or signature wrong"
// response) and 404 (object deleted / wrong key) never recover on their own.
const PERMANENT_STATUSES = new Set([401, 402, 403, 404, 410])

// Error raised when a remote server answers with an unusable HTTP status.
// Carrying `status` lets the UI distinguish an expired/forbidden link from a
// transient server failure without parsing the message text. Defined here
// (rather than in the WASM-bound parquet module) so classification tests stay
// free of parquet-wasm imports.
export class RemoteHttpError extends Error {
  readonly status: number

  constructor(status: number, statusText: string) {
    super(`The server returned ${status} ${statusText} for this URL.`)
    this.name = "RemoteHttpError"
    this.status = status
  }
}

// Opaque network-level failures, keyed by the messages Chrome, Firefox and
// Safari use. The browser hides whether it was CORS, DNS or a dropped
// connection, so all of these are treated as potentially transient.
const NETWORK_ERROR_PATTERN =
  /failed to fetch|networkerror|load failed|network request failed|cors|cross-origin|timed out|timeout|aborted|socket|dns|connection/i

function errorMessageOf(err: unknown): string {
  if (err instanceof Error) return err.message
  if (typeof err === "string") return err
  try {
    return String(err)
  } catch {
    return "Unknown error"
  }
}

/**
 * Classify any error thrown while opening or paging through a remote Parquet
 * file. Network-level failures (no HTTP answer) are always treated as
 * temporary: an expired presigned URL normally answers with 403, whereas an
 * opaque "Failed to fetch" more often means a dropped connection or a server
 * that is temporarily unreachable.
 */
export function classifyRemoteError(err: unknown): RemoteErrorInfo {
  const rawMessage = errorMessageOf(err)
  const status = extractStatus(err, rawMessage)
  const isCors = NETWORK_ERROR_PATTERN.test(rawMessage)

  if (status !== null) {
    if (PERMANENT_STATUSES.has(status)) {
      return {
        kind: "permanent",
        status,
        isCors: false,
        message: `The server refused this link with HTTP ${status}. The link may have expired, you may not have permission to access this file, or the file no longer exists.`,
        hint: "Retrying won't help — please obtain a fresh link to the file and open it again.",
      }
    }
    if (status >= 500) {
      return {
        kind: "temporary",
        status,
        isCors: false,
        message: `The server is temporarily unavailable (HTTP ${status}). The file and link are fine, but the server couldn't fulfill the request right now.`,
        hint: "Wait a moment and try again.",
      }
    }
    // Other 4xx (e.g. 416, 429): surface the status but don't promise that a
    // blind retry will fix a malformed request — treat as permanent unless
    // it's explicitly retryable. 429 (rate limited) is temporary.
    if (status === 429) {
      return {
        kind: "temporary",
        status,
        isCors: false,
        message: `The server rate-limited this request (HTTP ${status}).`,
        hint: "Wait a moment and try again.",
      }
    }
    return {
      kind: "permanent",
      status,
      isCors: false,
      message: `The server rejected this request with HTTP ${status}.`,
      hint: "Please check the link and obtain a fresh one if needed.",
    }
  }

  // No HTTP status: the request never completed (network drop, timeout, CORS
  // preflight failure, DNS error). All of these can clear on their own.
  return {
    kind: "temporary",
    status: null,
    isCors,
    message: isCors
      ? "The request failed before the server could answer — this can be a network interruption, a timeout, or the server blocking cross-origin (CORS) requests."
      : "The network request failed before the server could answer — your connection may have dropped or the server may be temporarily unreachable.",
    hint: "Check your connection and try again. If it keeps failing, the file's server may be blocking this app (CORS).",
  }
}

/**
 * Pull an HTTP status code off a thrown error. parquet-wasm/fetch errors carry
 * a `status` field; plain Error messages may embed one ("returned 503 ...").
 */
export function extractStatus(err: unknown, rawMessage?: string): number | null {
  if (typeof err === "object" && err !== null) {
    const candidate = (err as { status?: unknown; statusCode?: unknown }).status
      ?? (err as { statusCode?: unknown }).statusCode
    if (typeof candidate === "number" && Number.isFinite(candidate)) {
      return candidate
    }
  }
  const message = rawMessage ?? errorMessageOf(err)
  const match = message.match(/\b([1-5]\d{2})\b/)
  return match ? Number(match[1]) : null
}

export function isPermanentRemoteError(err: unknown): boolean {
  return classifyRemoteError(err).kind === "permanent"
}

export function isTemporaryRemoteError(err: unknown): boolean {
  return classifyRemoteError(err).kind === "temporary"
}

export interface LoadFailure {
  message: string
  /**
   * Classification for remote sources; null for local files. A null info is
   * the UI's signal that no retry entry should be rendered.
   */
  info: RemoteErrorInfo | null
}

/**
 * Build the error state shown by a load/load-more failure card. Local files
 * are never classified: their failures can't be retried over the network, so
 * `info` comes back null and the card renders without a retry button.
 */
export function buildLoadFailure(err: unknown, isRemote: boolean): LoadFailure {
  const message =
    err instanceof Error ? err.message : "Failed to read parquet file"
  return {
    message,
    info: isRemote ? classifyRemoteError(err) : null,
  }
}
