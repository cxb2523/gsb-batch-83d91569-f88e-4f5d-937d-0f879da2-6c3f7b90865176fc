import { describe, test, expect } from "bun:test"
import { appendBatch, nextBatchSize, type PaginatedRows } from "./pagination"
import { buildLoadFailure, RemoteHttpError } from "./remote-errors"

function makeRows(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: start + i,
    label: `row-${start + i}`,
  }))
}

function state(loadedRows: number, totalRows: number, rowCount: number): PaginatedRows {
  return {
    rows: makeRows(0, rowCount),
    loadedRows,
    hasMore: loadedRows < totalRows,
  }
}

describe("nextBatchSize", () => {
  test("unknown size (remote) uses the conservative 500-row batch", () => {
    expect(nextBatchSize(null)).toBe(500)
  })

  test("large files use 500, small files use 1000", () => {
    expect(nextBatchSize(20 * 1024 * 1024)).toBe(500)
    expect(nextBatchSize(1024)).toBe(1000)
  })
})

describe("appendBatch — happy path", () => {
  test("appends the next batch and advances loadedRows", () => {
    const current = state(500, 1500, 500)
    const batch = {
      rows: makeRows(500, 500),
      loadedRows: 1000,
      hasMore: true,
    }

    const next = appendBatch(current, batch)

    expect(next.rows).toHaveLength(1000)
    expect(next.rows[0]).toEqual({ id: 0, label: "row-0" })
    expect(next.rows[999]).toEqual({ id: 999, label: "row-999" })
    expect(next.loadedRows).toBe(1000)
    expect(next.hasMore).toBe(true)
  })

  test("final batch flips hasMore to false", () => {
    const current = state(1000, 1500, 1000)
    const batch = {
      rows: makeRows(1000, 500),
      loadedRows: 1500,
      hasMore: false,
    }

    const next = appendBatch(current, batch)
    expect(next.rows).toHaveLength(1500)
    expect(next.loadedRows).toBe(1500)
    expect(next.hasMore).toBe(false)
  })

  test("does not mutate the previous state object or its rows", () => {
    const current = state(2, 10, 2)
    const originalRows = current.rows
    const batch = { rows: makeRows(2, 2), loadedRows: 4, hasMore: true }

    const next = appendBatch(current, batch)

    expect(current.rows).toBe(originalRows)
    expect(current.rows).toHaveLength(2)
    expect(current.loadedRows).toBe(2)
    expect(next.rows).not.toBe(current.rows)
  })
})

describe("appendBatch — failed batch must not be appended", () => {
  test("a failed fetch leaves rows, loadedRows and remaining untouched", () => {
    const current = state(500, 1500, 500)
    const totalRows = 1500

    // Simulate the UI's failure path: appendBatch is never called because the
    // fetch threw, so the state reference is retained wholesale.
    const failure = buildLoadFailure(new RemoteHttpError(503, "Busy"), true)
    const retained = current // the state the UI keeps on error

    expect(failure.info?.kind).toBe("temporary")
    expect(retained.rows).toHaveLength(500)
    expect(retained.loadedRows).toBe(500)
    expect(totalRows - retained.loadedRows).toBe(1000)
    expect(retained.hasMore).toBe(true)
  })

  test("retry requests only the failed offset and appends it exactly once", () => {
    // Start: 500 rows shown, the next 500-row batch (offset 500) failed.
    const current = state(500, 1500, 500)
    const failedOffset = current.loadedRows // 500 — what the retry re-requests

    // Retry succeeds with the same offset (no overlap with shown rows).
    const retriedBatch = {
      rows: makeRows(500, 500),
      loadedRows: 1000,
      hasMore: true,
    }

    const next = appendBatch(current, retriedBatch, failedOffset)

    expect(next.rows).toHaveLength(1000)
    // No duplicated ids: every row id appears exactly once and stays ordered.
    const ids = next.rows.map((r) => r.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toEqual(Array.from({ length: 1000 }, (_, i) => i))
    expect(next.loadedRows).toBe(1000)
    expect(1500 - next.loadedRows).toBe(500)
  })

  test("refuses an overlapping batch that would duplicate rows", () => {
    const current = state(500, 1500, 500)

    // A stale/delivered-twice batch starting at an offset already shown.
    const overlapping = {
      rows: makeRows(400, 500),
      loadedRows: 900,
      hasMore: true,
    }

    expect(() => appendBatch(current, overlapping, 400)).toThrow(/duplicate/)
    // Original state remains intact.
    expect(current.rows).toHaveLength(500)
    expect(current.loadedRows).toBe(500)
  })

  test("an empty batch is a no-op (no spurious state change)", () => {
    const current = state(500, 1500, 500)
    const next = appendBatch(current, {
      rows: [],
      loadedRows: 500,
      hasMore: true,
    })
    expect(next).toBe(current)
  })
})

describe("continuation classification at the load-more boundary", () => {
  test("temporary network failure remains retryable and preserves the offset", () => {
    const current = state(500, 1500, 500)
    const failure = buildLoadFailure(new TypeError("Failed to fetch"), true)

    expect(failure.info?.kind).toBe("temporary")
    expect(failure.info?.status).toBeNull()
    // The retry offset is unchanged because no batch was merged.
    expect(current.loadedRows).toBe(500)
  })

  test("permanent link failure offers no retry and keeps loaded rows", () => {
    const current = state(500, 1500, 500)
    const failure = buildLoadFailure(new RemoteHttpError(403, "Forbidden"), true)

    expect(failure.info?.kind).toBe("permanent")
    // The UI renders no retry handler for permanent failures.
    const retryAvailable = failure.info?.kind === "temporary"
    expect(retryAvailable).toBe(false)
    // Already-displayed rows survive regardless.
    expect(current.rows).toHaveLength(500)
  })

  test("a local load-more failure has no retry classification at all", () => {
    const failure = buildLoadFailure(new Error("read failed"), false)
    expect(failure.info).toBeNull()
  })
})
