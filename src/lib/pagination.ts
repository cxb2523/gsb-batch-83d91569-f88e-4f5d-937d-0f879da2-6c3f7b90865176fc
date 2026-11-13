// Pure continuation/pagination logic for batched Parquet row loading.
// Extracted from the UI so the "retry must not duplicate or drop rows"
// boundary can be unit-tested without rendering React or touching WASM.

export interface PaginatedRows {
  rows: Record<string, unknown>[]
  loadedRows: number
  hasMore: boolean
}

/**
 * Merge a successfully fetched batch into the rows already on screen.
 *
 * The batch starts at `expectedOffset`, which must equal the current
 * `loadedRows` — that invariant is what makes a retry safe: a failed batch is
 * never appended, so retrying re-requests the same offset and appends it once.
 * Appending an overlapping batch (e.g. a double-delivered retry) would
 * duplicate rows, so it is rejected rather than silently concatenated.
 */
export function appendBatch(
  current: PaginatedRows,
  batch: { rows: Record<string, unknown>[]; loadedRows: number; hasMore: boolean },
  expectedOffset: number = current.loadedRows
): PaginatedRows {
  if (batch.rows.length === 0) {
    // Nothing new arrived (e.g. an empty trailing read): keep state stable.
    return current
  }

  if (expectedOffset !== current.loadedRows) {
    throw new Error(
      `Batch offset ${expectedOffset} does not match loaded rows ${current.loadedRows}; refusing to append to avoid duplicate rows`
    )
  }

  return {
    rows: [...current.rows, ...batch.rows],
    loadedRows: batch.loadedRows,
    hasMore: batch.hasMore,
  }
}

/**
 * The next batch size, mirroring the size rule in the UI: large/unknown-size
 * sources page in chunks of 500, smaller local files in chunks of 1000.
 */
export function nextBatchSize(
  fileSize: number | null,
  largeThresholdBytes: number = 10 * 1024 * 1024
): number {
  return fileSize === null || fileSize > largeThresholdBytes ? 500 : 1000
}
