import { TimeoutError } from "@decodo/sdk-ts";
import { describe, expect, it } from "vitest";
import { CrawlTimeoutError } from "../../../src/crawl/errors/crawl-timeout-error.js";

describe("CrawlTimeoutError", () => {
  it("names the crawl, the waited seconds and the cancel command", () => {
    const err = new CrawlTimeoutError("abc", 30);

    expect(err).toBeInstanceOf(TimeoutError);
    expect(err.name).toBe("TimeoutError");
    expect(err.crawlId).toBe("abc");
    expect(err.waitedSeconds).toBe(30);
    expect(err.message).toBe(
      "Crawl abc did not finish within 30s. It is still running; run `decodo crawl cancel abc` to stop it."
    );
  });
});
