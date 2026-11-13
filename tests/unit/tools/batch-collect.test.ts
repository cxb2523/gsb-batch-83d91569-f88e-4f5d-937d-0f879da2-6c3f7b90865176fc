/**
 * Unit tests for the batch collection tool's pure, browser-free surface:
 *  - {@link dedupeUrls} first-seen ordering and occurrence counts
 *  - {@link validateBatchParams} parameter taxonomy (INVALID_ARGUMENT raised
 *    before any browser work)
 *
 * The end-to-end Chromium behavior — real pages, timeouts, SSRF blocks,
 * continuation after failure — lives in
 * tests/integration/batch-collect.test.ts.
 */
import { describe, it, expect } from "vitest";
import {
  dedupeUrls,
  validateBatchParams,
  MAX_BATCH_URLS,
} from "../../../src/core/batch-collect.js";
import { CharlotteError, CharlotteErrorCode } from "../../../src/types/errors.js";

describe("dedupeUrls", () => {
  it("preserves first-seen order for distinct URLs", () => {
    const deduped = dedupeUrls(["https://a.test/", "https://b.test/", "https://c.test/"]);
    expect(deduped.map((entry) => entry.url)).toEqual([
      "https://a.test/",
      "https://b.test/",
      "https://c.test/",
    ]);
    expect(deduped.every((entry) => entry.occurrences === 1)).toBe(true);
  });

  it("collapses repeated URLs into one entry with the total occurrence count", () => {
    const deduped = dedupeUrls([
      "https://a.test/",
      "https://b.test/",
      "https://a.test/",
      "https://a.test/",
      "https://b.test/",
    ]);
    expect(deduped).toHaveLength(2);
    expect(deduped[0]).toEqual({ url: "https://a.test/", occurrences: 3 });
    expect(deduped[1]).toEqual({ url: "https://b.test/", occurrences: 2 });
  });

  it("handles an empty list", () => {
    expect(dedupeUrls([])).toEqual([]);
  });
});

describe("validateBatchParams", () => {
  it("defaults detail to summary when omitted", () => {
    expect(validateBatchParams(["https://a.test/"], undefined)).toBe("summary");
  });

  it.each(["minimal", "summary", "full"] as const)("accepts detail %s", (detail) => {
    expect(validateBatchParams(["https://a.test/"], detail)).toBe(detail);
  });

  it("rejects an empty urls array without touching browser-side state", () => {
    expect.assertions(2);
    try {
      validateBatchParams([], undefined);
    } catch (error) {
      expect(error).toBeInstanceOf(CharlotteError);
      expect((error as CharlotteError).code).toBe(CharlotteErrorCode.INVALID_ARGUMENT);
    }
  });

  it("rejects a non-array urls argument", () => {
    expect.assertions(1);
    try {
      validateBatchParams("https://a.test/", undefined);
    } catch (error) {
      expect((error as CharlotteError).code).toBe(CharlotteErrorCode.INVALID_ARGUMENT);
    }
  });

  it("rejects more than 50 URLs", () => {
    const tooMany = Array.from(
      { length: MAX_BATCH_URLS + 1 },
      (_, index) => `https://a.test/${index}`,
    );
    expect.assertions(1);
    try {
      validateBatchParams(tooMany, undefined);
    } catch (error) {
      expect((error as CharlotteError).code).toBe(CharlotteErrorCode.INVALID_ARGUMENT);
    }
  });

  it("accepts exactly 50 URLs", () => {
    const atLimit = Array.from({ length: MAX_BATCH_URLS }, (_, index) => `https://a.test/${index}`);
    expect(validateBatchParams(atLimit, undefined)).toBe("summary");
  });

  it("rejects non-string or blank URL entries", () => {
    expect.assertions(2);
    for (const bad of [
      ["https://a.test/", ""],
      ["https://a.test/", "   "],
    ]) {
      try {
        validateBatchParams(bad, undefined);
      } catch (error) {
        expect((error as CharlotteError).code).toBe(CharlotteErrorCode.INVALID_ARGUMENT);
      }
    }
  });

  it("rejects an illegal detail level", () => {
    expect.assertions(1);
    try {
      validateBatchParams(["https://a.test/"], "verbose");
    } catch (error) {
      expect((error as CharlotteError).code).toBe(CharlotteErrorCode.INVALID_ARGUMENT);
    }
  });
});
