import { describe, test, expect } from "bun:test"
import {
  classifyRemoteError,
  extractStatus,
  isPermanentRemoteError,
  isTemporaryRemoteError,
  buildLoadFailure,
  RemoteHttpError,
} from "./remote-errors"

describe("classifyRemoteError — link invalid / no permission (permanent)", () => {
  test("403 is permanent and explains an expired/forbidden link", () => {
    const info = classifyRemoteError(new RemoteHttpError(403, "Forbidden"))
    expect(info.kind).toBe("permanent")
    expect(info.status).toBe(403)
    expect(info.isCors).toBe(false)
    expect(info.message.toLowerCase()).toContain("expired")
    expect(info.hint).toContain("fresh link")
  })

  test("401 is permanent (unauthenticated)", () => {
    const info = classifyRemoteError(new RemoteHttpError(401, "Unauthorized"))
    expect(info.kind).toBe("permanent")
    expect(info.status).toBe(401)
    expect(isPermanentRemoteError(new RemoteHttpError(401, "Unauthorized"))).toBe(true)
  })

  test("404 is permanent (object gone)", () => {
    const info = classifyRemoteError(new RemoteHttpError(404, "Not Found"))
    expect(info.kind).toBe("permanent")
    expect(info.status).toBe(404)
  })

  test("410 Gone is permanent", () => {
    const info = classifyRemoteError(
      new Error("The server returned 410 Gone for this URL.")
    )
    expect(info.kind).toBe("permanent")
    expect(info.status).toBe(410)
  })

  test("permanent errors never expose a retry classification", () => {
    expect(isTemporaryRemoteError(new RemoteHttpError(403, "Forbidden"))).toBe(false)
  })
})

describe("classifyRemoteError — temporary failures (retryable)", () => {
  test("503 is temporary", () => {
    const info = classifyRemoteError(new RemoteHttpError(503, "Service Unavailable"))
    expect(info.kind).toBe("temporary")
    expect(info.status).toBe(503)
    expect(info.isCors).toBe(false)
    expect(info.message).toContain("503")
    expect(info.hint.toLowerCase()).toContain("try again")
  })

  test("500 and 502/504 are temporary", () => {
    for (const status of [500, 502, 504]) {
      const info = classifyRemoteError(
        new Error(`The server returned ${status} error for this URL.`)
      )
      expect(info.kind).toBe("temporary")
      expect(info.status).toBe(status)
    }
  })

  test("429 rate limiting is temporary", () => {
    const info = classifyRemoteError(new RemoteHttpError(429, "Too Many Requests"))
    expect(info.kind).toBe("temporary")
    expect(info.status).toBe(429)
  })

  test("opaque Chrome network error (Failed to fetch) is temporary", () => {
    const info = classifyRemoteError(new TypeError("Failed to fetch"))
    expect(info.kind).toBe("temporary")
    expect(info.status).toBeNull()
    expect(info.isCors).toBe(true)
  })

  test("Firefox network error is temporary", () => {
    const info = classifyRemoteError(
      new TypeError("NetworkError when attempting to fetch resource.")
    )
    expect(info.kind).toBe("temporary")
    expect(info.status).toBeNull()
  })

  test("Safari load failure is temporary", () => {
    const info = classifyRemoteError(new TypeError("Load failed"))
    expect(info.kind).toBe("temporary")
    expect(info.status).toBeNull()
  })

  test("timeout messages are treated as temporary", () => {
    const info = classifyRemoteError(new Error("The operation timed out"))
    expect(info.kind).toBe("temporary")
    expect(info.status).toBeNull()
  })

  test("string errors from WASM are handled without throwing", () => {
    const info = classifyRemoteError("Failed to fetch")
    expect(info.kind).toBe("temporary")
  })
})

describe("extractStatus", () => {
  test("reads a numeric status field", () => {
    expect(extractStatus(new RemoteHttpError(503, "Service Unavailable"))).toBe(503)
  })

  test("reads statusCode as a fallback", () => {
    expect(extractStatus({ statusCode: 404 })).toBe(404)
  })

  test("parses a status embedded in a message", () => {
    expect(
      extractStatus(new Error("The server returned 403 Forbidden for this URL."))
    ).toBe(403)
  })

  test("returns null when no status is present", () => {
    expect(extractStatus(new TypeError("Failed to fetch"))).toBeNull()
    expect(extractStatus(new Error("Invalid Parquet magic bytes"))).toBeNull()
  })

  test("ignores non-numeric status fields", () => {
    expect(extractStatus({ status: "oops" })).toBeNull()
  })
})

describe("buildLoadFailure — local vs remote gating", () => {
  test("remote 403 gets a permanent classification", () => {
    const failure = buildLoadFailure(new RemoteHttpError(403, "Forbidden"), true)
    expect(failure.info).not.toBeNull()
    expect(failure.info?.kind).toBe("permanent")
    expect(failure.info?.status).toBe(403)
  })

  test("remote 503 gets a temporary (retryable) classification", () => {
    const failure = buildLoadFailure(new RemoteHttpError(503, "Busy"), true)
    expect(failure.info?.kind).toBe("temporary")
  })

  test("remote network error gets a temporary classification", () => {
    const failure = buildLoadFailure(new TypeError("Failed to fetch"), true)
    expect(failure.info?.kind).toBe("temporary")
    expect(failure.info?.isCors).toBe(true)
  })

  test("a local file error is never classified and carries no retry info", () => {
    const failure = buildLoadFailure(
      new Error("Invalid Parquet magic bytes: not a parquet file"),
      false
    )
    expect(failure.info).toBeNull()
    expect(failure.message).toContain("Invalid Parquet magic bytes")
  })

  test("local-file network-style messages still get no retry info", () => {
    // Even if a File read surfaces a generic message, local sources must not
    // render a remote-retry entry.
    const failure = buildLoadFailure(new TypeError("Failed to fetch"), false)
    expect(failure.info).toBeNull()
  })

  test("non-Error values produce a fallback message", () => {
    const failure = buildLoadFailure("boom", true)
    // A thrown string isn't an Error instance: the UI uses a stable fallback
    // message, but still classifies the remote failure.
    expect(failure.message).toBe("Failed to read parquet file")
    expect(failure.info).not.toBeNull()

    const localFailure = buildLoadFailure(undefined, false)
    expect(localFailure.info).toBeNull()
    expect(localFailure.message).toBe("Failed to read parquet file")
  })
})
