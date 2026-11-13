import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { WebScrapingApi } from "@decodo/sdk-ts";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CrawlFailedError } from "../../../src/crawl/errors/crawl-failed-error.js";
import { CrawlTimeoutError } from "../../../src/crawl/errors/crawl-timeout-error.js";
import { deliverCrawlPages } from "../../../src/crawl/services/deliver-crawl-pages.js";

const PAGES = [{ url: "https://example.com/", content: "home" }];
const NDJSON = `${JSON.stringify(PAGES[0])}\n`;

const DONE = {
  crawl_id: "abc",
  status: "done",
  completed: 1,
  discovered: 1,
  failed: 0,
  in_flight: 0,
};

describe("deliverCrawlPages", () => {
  let stdout: string[];
  let api: {
    getCrawlResults: ReturnType<typeof vi.fn>;
    getCrawlStatus: ReturnType<typeof vi.fn>;
  };

  beforeEach(() => {
    stdout = [];
    api = {
      getCrawlResults: vi.fn().mockResolvedValue(PAGES),
      getCrawlStatus: vi.fn(),
    };
    vi.spyOn(process.stdout, "write").mockImplementation((chunk) => {
      stdout.push(String(chunk));
      return true;
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  function asApi(): WebScrapingApi {
    return api as unknown as WebScrapingApi;
  }

  it("writes the pages once the crawl finishes", async () => {
    api.getCrawlStatus.mockResolvedValue(DONE);

    await deliverCrawlPages(asApi(), "abc", {});

    expect(stdout).toEqual([NDJSON]);
  });

  it("writes the completed pages before reporting a timeout", async () => {
    api.getCrawlStatus.mockResolvedValue({ ...DONE, status: "pending" });

    await expect(
      deliverCrawlPages(asApi(), "abc", { pollInterval: 1, timeout: 1 })
    ).rejects.toBeInstanceOf(CrawlTimeoutError);

    expect(api.getCrawlResults).toHaveBeenCalledWith("abc");
    expect(stdout).toEqual([NDJSON]);
  });

  it("writes the completed pages to the output file on timeout", async () => {
    api.getCrawlStatus.mockResolvedValue({ ...DONE, status: "pending" });
    const dir = mkdtempSync(join(tmpdir(), "decodo-crawl-"));
    const path = join(dir, "pages.ndjson");

    try {
      await expect(
        deliverCrawlPages(asApi(), "abc", {
          output: path,
          pollInterval: 1,
          timeout: 1,
        })
      ).rejects.toBeInstanceOf(CrawlTimeoutError);

      expect(readFileSync(path, "utf8")).toBe(NDJSON);
      expect(stdout).toEqual([]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("does not write pages when fetching the results fails on timeout", async () => {
    api.getCrawlStatus.mockResolvedValue({ ...DONE, status: "pending" });
    api.getCrawlResults.mockRejectedValue(new Error("Service unavailable"));

    await expect(
      deliverCrawlPages(asApi(), "abc", { pollInterval: 1, timeout: 1 })
    ).rejects.toThrow("Service unavailable");
    expect(stdout).toEqual([]);
  });

  it("writes the pages before a faulted crawl fails", async () => {
    api.getCrawlStatus.mockResolvedValue({ ...DONE, status: "faulted" });

    await expect(deliverCrawlPages(asApi(), "abc", {})).rejects.toBeInstanceOf(
      CrawlFailedError
    );
    expect(stdout).toEqual([NDJSON]);
  });

  it("forwards the results options", async () => {
    api.getCrawlStatus.mockResolvedValue(DONE);

    await deliverCrawlPages(asApi(), "abc", {}, { content: false });

    expect(api.getCrawlResults).toHaveBeenCalledWith("abc", { content: false });
  });
});
